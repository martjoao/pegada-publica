"""Tests for TseDownloader — the streaming binary download client."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from common.http_client import TseDownloader


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_response(status: int = 200, content: bytes = b"data", content_length: int = None):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {}
    if content_length is not None:
        resp.headers["Content-Length"] = str(content_length)
    resp.iter_content = MagicMock(return_value=iter([content]))
    if status >= 400:
        http_err = requests.HTTPError(response=resp)
        resp.raise_for_status = MagicMock(side_effect=http_err)
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _make_session(*responses):
    """Session whose .get() returns responses in order."""
    session = MagicMock()
    session.get = MagicMock(side_effect=list(responses))
    return session


# ── tests ────────────────────────────────────────────────────────────────────

def test_download_writes_file(tmp_path):
    session = _make_session(_make_response(content=b"zip bytes"))
    dl = TseDownloader(session=session)
    dest = tmp_path / "out.zip"
    dl.download("http://example.com/file.zip", dest)
    assert dest.read_bytes() == b"zip bytes"


def test_download_atomic_rename(tmp_path):
    """Destination file must not exist mid-write; temp file cleaned up after."""
    session = _make_session(_make_response(content=b"data"))
    dl = TseDownloader(session=session)
    dest = tmp_path / "out.zip"
    dl.download("http://example.com/file.zip", dest)
    assert dest.exists()
    assert not (tmp_path / "out.zip.tmp").exists()


def test_download_creates_parent_dirs(tmp_path):
    session = _make_session(_make_response(content=b"data"))
    dl = TseDownloader(session=session)
    dest = tmp_path / "a" / "b" / "out.zip"
    dl.download("http://example.com/file.zip", dest)
    assert dest.read_bytes() == b"data"


def test_download_retries_on_503(tmp_path):
    err_resp = _make_response(status=503)
    ok_resp = _make_response(content=b"ok")
    session = _make_session(err_resp, ok_resp)
    dl = TseDownloader(session=session, backoff_base=0)
    dest = tmp_path / "out.zip"
    dl.download("http://example.com/file.zip", dest)
    assert dest.read_bytes() == b"ok"
    assert session.get.call_count == 2


def test_download_retries_on_connection_error(tmp_path):
    session = MagicMock()
    ok_resp = _make_response(content=b"ok")
    session.get = MagicMock(
        side_effect=[requests.ConnectionError("network down"), ok_resp]
    )
    dl = TseDownloader(session=session, backoff_base=0)
    dest = tmp_path / "out.zip"
    dl.download("http://example.com/file.zip", dest)
    assert dest.read_bytes() == b"ok"


def test_download_raises_immediately_on_404(tmp_path):
    session = _make_session(_make_response(status=404))
    dl = TseDownloader(session=session, max_retries=3, backoff_base=0)
    with pytest.raises(requests.HTTPError):
        dl.download("http://example.com/file.zip", tmp_path / "out.zip")
    assert session.get.call_count == 1  # no retry


def test_download_raises_on_content_length_mismatch(tmp_path):
    # Server says 100 bytes, sends 5
    session = _make_session(_make_response(content=b"short", content_length=100))
    dl = TseDownloader(session=session, max_retries=0)
    dest = tmp_path / "out.zip"
    with pytest.raises(ValueError, match="Content-length mismatch"):
        dl.download("http://example.com/file.zip", dest)
    assert not dest.exists()
    assert not (tmp_path / "out.zip.tmp").exists()


def test_download_exhausts_retries_and_raises(tmp_path):
    session = MagicMock()
    session.get = MagicMock(side_effect=requests.ConnectionError("always down"))
    dl = TseDownloader(session=session, max_retries=2, backoff_base=0)
    with pytest.raises(requests.ConnectionError):
        dl.download("http://example.com/file.zip", tmp_path / "out.zip")
    assert session.get.call_count == 3  # initial + 2 retries
