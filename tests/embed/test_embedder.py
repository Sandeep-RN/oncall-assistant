"""The real model (downloaded by python -m app.embed.download; CI caches it)."""

import numpy as np
import pytest

from app.embed.model import DEFAULT_DIR, DIMENSIONS, FILES, OnnxEmbedder


@pytest.fixture(scope="module")
def embedder():
    if not all((DEFAULT_DIR / n).is_file() for n in FILES):
        pytest.skip("model not downloaded (python -m app.embed.download)")
    return OnnxEmbedder()


def test_vectors_have_the_right_shape_and_unit_length(embedder):
    v = embedder.embed_passages(["one passage", "another passage"])
    assert v.shape == (2, DIMENSIONS) and v.dtype == np.float32
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)


def test_a_question_is_closer_to_the_passage_that_answers_it(embedder):
    passages = [
        "Restore the sealing keys before ArgoCD syncs anything, or no SealedSecret decrypts.",
        "The link shortener returns a 302 redirect for a known short code.",
    ]
    p = embedder.embed_passages(passages)
    q = embedder.embed_query("What must happen before ArgoCD syncs after a rebuild?")
    scores = p @ q
    assert scores[0] > scores[1]


def test_batching_does_not_change_the_vectors(embedder):
    texts = ["short", "a somewhat longer passage about backups and restores", "third"]
    together = embedder.embed_passages(texts)
    alone = np.stack([embedder.embed_passages([t])[0] for t in texts])
    assert np.allclose(together, alone, atol=1e-4)


def test_mixed_lengths_across_buckets_come_back_in_input_order(embedder):
    texts = ["word " * 300, "tiny", "word " * 150, "short text", "word " * 700]
    together = embedder.embed_passages(texts)
    alone = np.stack([embedder.embed_passages([t])[0] for t in texts])
    assert np.allclose(together, alone, atol=1e-4)


def test_text_longer_than_the_model_reads_is_truncated_not_an_error(embedder):
    v = embedder.embed_passages(["word " * 2000])
    assert v.shape == (1, DIMENSIONS)


def test_missing_model_files_give_a_clear_message(tmp_path):
    with pytest.raises(FileNotFoundError, match="app.embed.download"):
        OnnxEmbedder(tmp_path)
