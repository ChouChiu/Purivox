from __future__ import annotations

import hashlib
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from features.neural_separation import catalog
from features.neural_separation.catalog import ModelEntry
from features.neural_separation.model_store import ensure_model, find_model
from shared.processing import CancellationToken, ProcessingCancelled

MODEL_NAME = "test_model.onnx"
PAYLOAD = b"purivox-test-model" * 4096
ENTRY = ModelEntry(
    "test_model",
    "Test Model",
    MODEL_NAME,
    len(PAYLOAD),
    hashlib.sha256(PAYLOAD).hexdigest(),
    "mdl_mdxnet_1",
)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not self.path.endswith(MODEL_NAME):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        # Written in slices so the transfer reports progress more than once.
        for start in range(0, len(PAYLOAD), 4096):
            self.wfile.write(PAYLOAD[start : start + 4096])

    def log_message(self, *_args):
        pass


@pytest.fixture(autouse=True)
def local_model_host(monkeypatch):
    """Serve the catalogue from localhost so no test reaches the real release host."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(catalog, "MODEL_BASE_URL", f"http://127.0.0.1:{httpd.server_address[1]}/")
    yield
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def test_a_verified_download_lands_at_the_destination(tmp_path: Path):
    events = []
    path = ensure_model(ENTRY, tmp_path, CancellationToken(), events.append)
    assert path == tmp_path / MODEL_NAME
    assert path.read_bytes() == PAYLOAD
    assert events, "the download must report progress"
    assert all(15 <= event.value <= 24 for event in events)


def test_an_existing_model_is_not_downloaded_again(tmp_path: Path):
    (tmp_path / MODEL_NAME).write_bytes(b"already here")
    path = ensure_model(ENTRY, tmp_path, CancellationToken(), lambda _event: None)
    assert path.read_bytes() == b"already here"


def test_a_checksum_mismatch_leaves_no_model_behind(tmp_path: Path):
    entry = replace(ENTRY, sha256="0" * 64)
    with pytest.raises(RuntimeError):
        ensure_model(entry, tmp_path, CancellationToken(), lambda _event: None)
    assert find_model(entry, tmp_path) is None
    assert not list(tmp_path.iterdir()), "a rejected download must not leave partial files"


def test_a_size_mismatch_leaves_no_model_behind(tmp_path: Path):
    entry = replace(ENTRY, size=len(PAYLOAD) + 1)
    with pytest.raises(RuntimeError):
        ensure_model(entry, tmp_path, CancellationToken(), lambda _event: None)
    assert not list(tmp_path.iterdir())


def test_an_http_error_is_reported_as_a_runtime_error(tmp_path: Path):
    entry = replace(ENTRY, filename="missing.onnx")
    with pytest.raises(RuntimeError):
        ensure_model(entry, tmp_path, CancellationToken(), lambda _event: None)
    assert not list(tmp_path.iterdir())


def test_cancellation_aborts_the_transfer(tmp_path: Path):
    token = CancellationToken()
    token.cancel()
    with pytest.raises(ProcessingCancelled):
        ensure_model(ENTRY, tmp_path, token, lambda _event: None)
    assert not list(tmp_path.iterdir())
