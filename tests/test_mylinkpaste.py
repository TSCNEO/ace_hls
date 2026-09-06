import base64
import gzip
import json
from unittest.mock import MagicMock

import pytest

from app.services.source_validator import (
    SourceValidationError,
    SourceValidator,
    decode_dns_payload,
    detect_source_kind,
    normalize_source_url,
    parse_mylinkpaste,
)


def _make_txt_payload(data: list | dict, compress: bool = True) -> str:
    raw = json.dumps(data).encode("utf-8")
    if compress:
        raw = gzip.compress(raw)
    b64 = base64.b64encode(raw).decode("ascii")
    # Return formatted as DNS TXT quoted string
    return f'"{b64}"'


def test_normalize_mylinkpaste_urls():
    mock_id1 = "a1b2c3d4e5f6789012345678"
    mock_id2 = "fedcba098765432112345678"
    mock_id3 = "wW9eSampleRefIdentifierStringMock1234567890XYZ"
    assert normalize_source_url(mock_id1) == f"mylinkpaste://{mock_id1}"
    assert normalize_source_url(f"mylinkpaste://{mock_id2}") == f"mylinkpaste://{mock_id2}"
    assert normalize_source_url(mock_id3) == f"mylinkpaste://{mock_id3}"
    assert normalize_source_url(f"https://{mock_id1}.elcano.top") == f"mylinkpaste://{mock_id1}"
    assert normalize_source_url("http://example.com/playlist.m3u") == "http://example.com/playlist.m3u"

    assert detect_source_kind(f"mylinkpaste://{mock_id1}") == "mylinkpaste"
    assert detect_source_kind("https://example.com/playlist.m3u") == "m3u"
    assert detect_source_kind("https://api.acestream.me/all") == "acestream_api"

    with pytest.raises(SourceValidationError):
        normalize_source_url("")

    with pytest.raises(SourceValidationError):
        normalize_source_url("short")

    with pytest.raises(SourceValidationError):
        normalize_source_url("invalid / with spaces")


def test_decode_dns_payload_gzip_and_plain():
    data = [{"name": "Canal 1", "url": "acestream://" + "a" * 40}]
    
    # GZIP compressed
    txt_gzip = _make_txt_payload(data, compress=True)
    decoded_gzip = decode_dns_payload(txt_gzip)
    assert decoded_gzip == data

    # Plain uncompressed
    txt_plain = _make_txt_payload(data, compress=False)
    decoded_plain = decode_dns_payload(txt_plain)
    assert decoded_plain == data


def test_decode_dns_payload_fragmented_strings():
    data = [{"name": "Test", "url": "acestream://" + "1" * 40}]
    raw_b64 = base64.b64encode(json.dumps(data).encode("utf-8")).decode("ascii")
    
    # Split into 2 chunks
    mid = len(raw_b64) // 2
    fragmented_txt = f'"{raw_b64[:mid]}""{raw_b64[mid:]}"'
    assert decode_dns_payload(fragmented_txt) == data


def test_parse_mylinkpaste_recursive_and_circular_protection():
    # Mock DoH responses for ref_root -> ref_cat -> ref_channels
    ref_root = "root_ref_1234567890"
    ref_cat = "cat_ref_1234567890"
    ref_tdt = "tdt_ref_1234567890"

    mock_db = {
        ref_root: [
            {"name": "Actualizado hoy", "url": ""},
            {"name": "Deportes", "type": "category", "ref": ref_cat},
            {"name": "TDT", "type": "category", "ref": ref_tdt},
        ],
        ref_cat: [
            {
                "name": "Fútbol",
                "subLinks": [
                    {"name": "Partidazo HD", "url": "acestream://" + "b" * 40},
                ],
            },
            # Circular reference back to root
            {"name": "Volver", "type": "category", "ref": ref_root},
        ],
        ref_tdt: [
            {
                "name": "General",
                "subLinks": [
                    {"name": "La 1 HD", "url": "acestream://" + "c" * 40},
                ],
            },
        ],
    }

    def fake_get(url, params=None, **kwargs):
        name = (params or {}).get("name", "")
        ref = name.split(".")[0]
        resp = MagicMock()
        resp.status_code = 200
        if ref in mock_db:
            resp.json.return_value = {
                "Answer": [{"type": 16, "data": _make_txt_payload(mock_db[ref])}]
            }
        else:
            resp.json.return_value = {"Answer": []}
        return resp

    session = MagicMock()
    session.get.side_effect = fake_get

    channels = parse_mylinkpaste(
        ref_root,
        source_url=f"mylinkpaste://{ref_root}",
        source_name="MylinkPaste",
        session=session,
    )

    assert len(channels) == 2
    assert channels[0]["name"] == "Partidazo HD"
    assert channels[0]["id"] == "b" * 40
    assert channels[0]["group"] == "Fútbol"

    assert channels[1]["name"] == "La 1 HD"
    assert channels[1]["id"] == "c" * 40
    assert channels[1]["group"] == "General"


def test_validator_with_mylinkpaste():
    ref = "test_valid_ref_123456"
    mock_data = [
        {
            "name": "Canales Directos",
            "subLinks": [
                {"name": "Canal Uno", "url": "acestream://" + "f" * 40},
            ],
        }
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "Answer": [{"type": 16, "data": _make_txt_payload(mock_data)}]
    }

    session = MagicMock()
    session.get.return_value = mock_resp

    validator = SourceValidator(session=session)
    result = validator.validate(f"mylinkpaste://{ref}", "Mi MylinkPaste")

    assert result.valid is True
    assert result.kind == "mylinkpaste"
    assert result.channel_count == 1
    assert result.channels[0]["name"] == "Canal Uno"
    assert result.channels[0]["id"] == "f" * 40
    assert result.channels[0]["group"] == "Canales Directos"
