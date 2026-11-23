# 0001. Local ONNX embeddings with bge-small, on Python 3.14

Status: Accepted (2026-11-22).

## Context
Passages and questions are turned into vectors by a local embedding model (settled during
planning: no embedding API, no cost, nothing leaves the cluster for retrieval). Platform ADR 0025
gives the indexing Job 384Mi and the app 384Mi, and rules out PyTorch.

Checked on 2026-11-22:

- **ONNX Runtime** 1.32.0 (released 2026-11-13) publishes wheels for Python 3.11 to 3.14 only,
  arm64 included. There is no Python 3.15 build and no nightly on PyPI. The repo was scaffolded on
  Python 3.15 to match the link shortener.
- **fastembed** (the usual ONNX wrapper) pulls in pillow, loguru, requests, mmh3 and a Rust
  stemmer, and downloads models from Hugging Face at runtime.
- **Model fit** against the real corpus (285 passages, median 141 words): `all-MiniLM-L6-v2`
  reads 256 tokens and would truncate 97 passages (34%); `bge-small-en-v1.5` reads 512 tokens and
  would truncate 2 (1%). Both give 384-dimensional vectors.

## Decision
- **Python 3.14** for this repository (CI, `pyproject.toml`, the image in issue #7). Move to 3.15
  when ONNX Runtime publishes cp315 Linux arm64 wheels; Dependabot or a periodic check of PyPI
  shows when.
  Since #59, Dependabot (`.github/dependabot.yml`) proposes the `python:3.15-slim` base; that
  PR's image build fails at `pip install` until onnxruntime ships a cp315 wheel.
- **`BAAI/bge-small-en-v1.5`** (MIT licence), fp32 ONNX, 384 dimensions, pinned to a Hugging Face
  revision and checked by sha256. Questions get the model's retrieval prefix; passages are embedded
  as their heading path followed by their text, truncated at 512 tokens.
- **`onnxruntime`, `tokenizers` and `numpy` directly**, not fastembed: CLS pooling and
  normalisation are a few lines of our own code, and the dependency tree stays small.
- **The model file is never downloaded at runtime.** Local development and CI fetch it once with
  `python -m app.embed.download` (pinned revision, sha256 checked); the image bakes it in (#7).
- **Memory is measured, not assumed.** A full indexing run of the real corpus (285 passages) in a
  container limited to 384Mi, reading the container's own peak (`memory.peak`), x86 Docker on the
  developer laptop, 2026-11-22:

  | Batching | Peak |
  |---|---|
  | 4 texts per batch, padded to the longest | OOM-killed at 384Mi (435 MiB without a limit) |
  | same, ONNX Runtime memory pattern off | 453 MiB, no help |
  | same, `MALLOC_ARENA_MAX=2` | 410 MiB |
  | fixed lengths 128/256/512, sorted by length | 379 MiB |
  | **fixed lengths plus a token budget (4 x 128, 2 x 256, 1 x 512)** | **247 MiB** (227 with `MALLOC_ARENA_MAX=2`) |

  Padding to the longest text gives ONNX Runtime a new input shape almost every batch and memory
  creeps up; a few fixed shapes and one long text at a time keep it flat. The token-budget batching
  is what the code does. `MALLOC_ARENA_MAX=2` is optional headroom for the manifests (demo #195).
  The int8 fallback was not needed, so the full-precision model stays.

## Consequences
- The assistant runs one Python minor version behind the link shortener. They are separate images,
  so nothing else is affected, but the version has to be moved on purpose later.
- Changing the model changes every vector. The index records the model and revision it was built
  with, and a different model forces a full re-index.
- Two passages (tables kept whole by the splitter) are embedded from their first 512 tokens only.
- The measurement ran on x86; the node is arm64. Platform issue demo #196 measures the real pod.
- The ONNX Runtime wheel contains a telemetry provider. It starts at `import onnxruntime` and, when
  the home directory is not writable (as in the pod), prints "Failed to persist telemetry device
  ID". Measured with `strace` on x86 (a control `connect()` was caught; none from the library):
  loading the model and embedding a text open no network connection, with a writable or an
  unwritable home. This was not measured on arm64, and a few seconds is not proof for all time.
  So the code calls `disable_telemetry_events()` before the first session (it cannot silence the
  import-time warning), CI embeds with `--network none`, and the M3 NetworkPolicy (egress to the
  provider only) is what actually enforces "nothing else leaves the pod".
- Loading the model alone takes about 200 MiB, so an index run where nothing changed still peaks
  near 225 MiB. The app pod (one question at a time) peaked at 207 MiB in the same setup.

## At scale
A shared embedding service (one model server per cluster, batching across callers, GPU when the
corpus is large) instead of a model loaded in every pod, and a larger model chosen by retrieval
evals rather than by memory.
