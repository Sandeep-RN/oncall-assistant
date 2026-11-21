import hashlib

import pytest

from app.corpus.fetch import FetchError
from app.embed.download import download
from tests.corpus.helpers import FakeGet

CONTENT = b"pretend model bytes"
GOOD = {"model.onnx": ("onnx/model.onnx", hashlib.sha256(CONTENT).hexdigest())}


def test_downloads_checks_the_hash_and_is_idempotent(tmp_path):
    get = FakeGet({"onnx/model.onnx": CONTENT})
    assert download(tmp_path, get=get, files=GOOD) == ["model.onnx"]
    assert (tmp_path / "model.onnx").read_bytes() == CONTENT
    assert download(tmp_path, get=get, files=GOOD) == []  # already present: nothing fetched
    assert len(get.calls) == 1


def test_a_wrong_hash_is_refused_and_leaves_no_file(tmp_path):
    get = FakeGet({"onnx/model.onnx": b"tampered"})
    with pytest.raises(FetchError, match="does not match"):
        download(tmp_path, get=get, files=GOOD)
    assert list(tmp_path.iterdir()) == []


def test_a_corrupt_existing_file_is_replaced(tmp_path):
    (tmp_path / "model.onnx").write_bytes(b"half a download")
    assert download(tmp_path, get=FakeGet({"onnx/model.onnx": CONTENT}), files=GOOD) == [
        "model.onnx"
    ]
    assert (tmp_path / "model.onnx").read_bytes() == CONTENT
