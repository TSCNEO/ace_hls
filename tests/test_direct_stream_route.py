import json
from unittest.mock import patch, MagicMock
import requests
from app import create_app


def test_direct_stream_success():
    app = create_app()
    client = app.test_client()

    fake_upstream = MagicMock()
    fake_upstream.status_code = 200
    fake_upstream.iter_content.return_value = [b"G\x47fake_mpegts_chunk_1", b"G\x47fake_mpegts_chunk_2"]

    with patch("app.routes.requests.get", return_value=fake_upstream) as mock_get:
        resp = client.get("/api/stream/direct/test_ace_id_123")

        assert resp.status_code == 200
        assert resp.mimetype == "video/mp2t"
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"
        assert "no-cache" in resp.headers.get("Cache-Control", "")
        assert resp.headers.get("X-Accel-Buffering") == "no"
        assert resp.data == b"G\x47fake_mpegts_chunk_1G\x47fake_mpegts_chunk_2"

        # Verify call to upstream with id
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert "id=test_ace_id_123" in args[0]
        assert kwargs.get("stream") is True

        # Verify upstream was closed
        fake_upstream.close.assert_called()


def test_direct_stream_identifier_type_infohash():
    app = create_app()
    client = app.test_client()

    fake_upstream = MagicMock()
    fake_upstream.status_code = 200
    fake_upstream.iter_content.return_value = [b"chunk_data"]

    with patch("app.routes.requests.get", return_value=fake_upstream) as mock_get:
        resp = client.get("/api/stream/direct/aabbccdd11223344?identifier_type=infohash")

        assert resp.status_code == 200
        assert resp.data == b"chunk_data"

        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert "infohash=aabbccdd11223344" in args[0]
        fake_upstream.close.assert_called()


def test_direct_stream_upstream_connection_failure():
    app = create_app()
    client = app.test_client()

    with patch("app.routes.requests.get", side_effect=requests.ConnectionError("Connection refused")):
        resp = client.get("/api/stream/direct/test_ace_id_123")

        assert resp.status_code == 502
        data = json.loads(resp.data)
        assert data.get("error") == "upstream_error"
        assert "Connection refused" in data.get("message", "")


def test_direct_stream_upstream_http_error():
    app = create_app()
    client = app.test_client()

    fake_upstream = MagicMock()
    fake_upstream.status_code = 500
    fake_upstream.raise_for_status.side_effect = requests.HTTPError("500 Server Error")

    with patch("app.routes.requests.get", return_value=fake_upstream):
        resp = client.get("/api/stream/direct/test_ace_id_123")

        assert resp.status_code == 502
        data = json.loads(resp.data)
        assert data.get("error") == "upstream_error"
        assert "500 Server Error" in data.get("message", "")
