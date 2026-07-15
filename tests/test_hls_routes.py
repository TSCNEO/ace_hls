import os
import tempfile
from unittest.mock import Mock, patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ace-hls-tests-"))

from flask import Flask

from app import routes


class FakeResponse:
    def __init__(self, content_type, chunks, status_error=None):
        self.headers = {"content-type": content_type}
        self._chunks = chunks
        self._status_error = status_error
        self.closed = False

    def raise_for_status(self):
        if self._status_error:
            raise self._status_error

    def iter_content(self, _chunk_size):
        yield from self._chunks

    def close(self):
        self.closed = True


def test_probe_classifies_continuous_mpegts_stream():
    response = FakeResponse("video/mp2t", [b"\x47" + b"x" * 4095])

    with patch.object(routes.requests, "get", return_value=response):
        assert routes._probe_upstream_media("channel-id") == "stream"

    assert response.closed


def test_probe_classifies_hls_manifest_with_media():
    response = FakeResponse(
        "application/vnd.apple.mpegurl",
        [b"#EXTM3U\n#EXTINF:4,\nsegment.ts?seq=1\n"],
    )

    with patch.object(routes.requests, "get", return_value=response):
        assert routes._probe_upstream_media("channel-id") == "hls"

    assert response.closed


def test_original_mpegts_uses_ffmpeg_instead_of_manifest_proxy():
    app = Flask(__name__)
    expected = {
        "status": "ok",
        "url": "/hls/channel-id/index.m3u8",
        "attempts": 1,
    }

    with app.test_request_context("/api/hls/start/channel-id?profile=original"):
        with patch.object(routes, "_probe_upstream_media", return_value="stream"):
            with patch.object(routes, "_start_hls_with_retries", return_value=expected) as start:
                response = routes.start_hls("channel-id")

    assert response.get_json() == expected
    start.assert_called_once_with(
        "channel-id",
        "original",
        force=False,
        upstream_ready=True,
    )


def test_proxy_rejects_continuous_stream_after_first_chunk():
    def chunks():
        yield b"\x47" + b"x" * 4095
        raise AssertionError("continuous stream must not be read beyond the first chunk")

    response = FakeResponse("video/mp2t", chunks())

    with patch.object(routes.requests, "get", return_value=response):
        result = routes.proxy_upstream_manifest("channel-id")

    assert result == ("AceXY returned a continuous stream instead of an HLS manifest", 502)
    assert response.closed


def test_proxy_rewrites_real_hls_manifest():
    app = Flask(__name__)
    response = FakeResponse(
        "application/vnd.apple.mpegurl",
        [b"#EXTM3U\n#EXTINF:4,\nhttp://acexy/ace/hls/segment.ts?stream=id&seq=7\n"],
    )

    with app.test_request_context("/proxy/hls/channel-id/index.m3u8"):
        with patch.object(routes.requests, "get", return_value=response):
            result = routes.proxy_upstream_manifest("channel-id")

    assert result.status_code == 200
    assert b"/proxy/hls/channel-id/segment.ts?seq=7" in result.get_data()
    assert response.closed


def test_manifest_wait_refreshes_stream_activity():
    process = Mock()
    process.poll.return_value = None

    with patch.object(routes, "_manifest_has_segment", side_effect=[False, True]):
        with patch.object(routes.time, "sleep"):
            with patch.dict(routes.hls_manager.processes, {"stream-id": process}, clear=True):
                with patch.object(routes.hls_manager, "update_activity") as update_activity:
                    assert routes._wait_for_ready_manifest("stream-id", timeout=1)

    assert update_activity.call_count == 2
