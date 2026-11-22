"""The embedding model: which files, from where, and how to turn text into vectors (ADR 0001).

bge-small-en-v1.5 is a BERT-style encoder. Its sentence vector is the hidden state of the first
token ([CLS]), L2-normalised, so cosine similarity is a plain dot product.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np

MODEL_ID = "BAAI/bge-small-en-v1.5"
REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
DIMENSIONS = 384
MAX_TOKENS = 512
# bge's own instruction for retrieval queries; passages get no prefix.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
DEFAULT_DIR = Path("models") / "bge-small-en-v1.5"

# file name -> (path in the Hugging Face repo, sha256). A different file is refused.
FILES: dict[str, tuple[str, str]] = {
    "model.onnx": (
        "onnx/model.onnx",
        "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35",
    ),
    "tokenizer.json": (
        "tokenizer.json",
        "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
    ),
}


def model_key() -> str:
    """What the index records; a different key forces a full re-index."""
    return f"{MODEL_ID}@{REVISION}/{DIMENSIONS}"


class Embedder(Protocol):
    def embed_passages(self, texts: Sequence[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


# Memory, measured on the full corpus in a 384Mi container (ADR 0001): padding every batch to the
# longest text gives ONNX Runtime a new input shape almost every batch, and memory crept up to an
# OOM kill. Padding to one of three fixed lengths, with a token budget per batch (4 x 128,
# 2 x 256 or 1 x 512 tokens) and texts sorted by length, peaked at 278 MiB.
BUCKETS = (128, 256, MAX_TOKENS)
TOKEN_BUDGET = 512


class OnnxEmbedder:
    """Loads the model once and embeds in token-budgeted batches (ADR 0025 memory budget)."""

    def __init__(self, model_dir: Path = DEFAULT_DIR, *, threads: int = 1):
        # Imported here so modules that only need the Protocol stay light.
        import onnxruntime as ort
        from tokenizers import Tokenizer

        missing = [n for n in FILES if not (model_dir / n).is_file()]
        if missing:
            raise FileNotFoundError(
                f"model files missing in {model_dir}: {missing}; run python -m app.embed.download"
            )
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=MAX_TOKENS)
        # Padding is done below with numpy, never by mutating the tokenizer per batch, so one
        # embedder can serve concurrent requests in the app.
        self.tokenizer.no_padding()
        self.pad_id = self.tokenizer.token_to_id("[PAD]") or 0
        # The wheel contains a telemetry provider (ADR 0001, issue #15). Opt out before the
        # session exists. It cannot silence the "Failed to persist telemetry device ID" warning:
        # that is printed by `import onnxruntime` itself, before any of our code runs.
        ort.disable_telemetry_events()
        opts = ort.SessionOptions()
        # One thread: the pod has a CPU limit, and more threads only add contention.
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        # The arena keeps freed blocks for reuse, so the peak never comes back down. Without it
        # memory returns to the system after each batch: a little slower, much smaller.
        opts.enable_cpu_mem_arena = False
        self.session = ort.InferenceSession(
            str(model_dir / "model.onnx"), opts, providers=["CPUExecutionProvider"]
        )
        self.input_names = {i.name for i in self.session.get_inputs()}

    def _run(self, encodings: list, length: int) -> np.ndarray:
        """Embed encodings padded to exactly `length` tokens; returns unit vectors."""
        n = len(encodings)
        ids = np.full((n, length), self.pad_id, dtype=np.int64)
        mask = np.zeros((n, length), dtype=np.int64)
        for row, enc in enumerate(encodings):
            ids[row, : len(enc.ids)] = enc.ids
            mask[row, : len(enc.ids)] = 1
        feed = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
        feed = {k: v for k, v in feed.items() if k in self.input_names}
        cls = self.session.run(None, feed)[0][:, 0, :]  # hidden state of [CLS], (n, 384)
        return cls / np.linalg.norm(cls, axis=1, keepdims=True)

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        encodings = self.tokenizer.encode_batch(list(texts))
        lengths = [len(e.ids) for e in encodings]
        order = sorted(range(len(texts)), key=lengths.__getitem__)
        out = np.empty((len(texts), DIMENSIONS), dtype=np.float32)
        i = 0
        while i < len(order):
            bucket = next(b for b in BUCKETS if lengths[order[i]] <= b)
            group = [j for j in order[i : i + TOKEN_BUDGET // bucket] if lengths[j] <= bucket]
            out[group] = self._run([encodings[j] for j in group], bucket)
            i += len(group)
        return out

    def embed_passages(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([QUERY_PREFIX + text])[0]
