import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import Config
from app.services.channel_manager import ChannelManager
from app.services.custom_channel_manager import (
    CustomChannelManager,
    DuplicateCustomChannel,
)
from app.services.source_manager import SourceManager, SourceRegistryError, UnsupportedSourceSchema
from app.services.source_validator import (
    SourceValidator,
    extract_stream_reference,
    parse_acestream_api,
    parse_m3u,
)


def configure_paths(tmp_path):
    return patch.multiple(
        Config,
        DATA_DIR=str(tmp_path),
        SOURCES_FILE=str(tmp_path / "sources.json"),
        SOURCE_CACHE_DIR=str(tmp_path / "source_cache"),
        CUSTOM_CHANNELS_FILE=str(tmp_path / "custom_channels.json"),
        JSON_FILE=str(tmp_path / "channels.json"),
        M3U_FILE=str(tmp_path / "ace_hls.m3u"),
        URL_ORIGEN="",
    )


def test_legacy_sources_migrate_once_with_backup_and_stable_ids(tmp_path):
    legacy = [
        {"url": "https://one.example/list.m3u", "added_at": 10},
        {"url": "https://one.example/other.m3u", "added_at": 20},
    ]
    (tmp_path / "sources.json").write_text(json.dumps(legacy))
    manager = SourceManager()

    with configure_paths(tmp_path):
        first = manager.get_sources()
        second = manager.get_sources()

    assert first == second
    assert first[0]["id"].startswith("src-")
    assert [item["name"] for item in first] == ["one.example", "one.example 2"]
    assert first[0]["created_at"] == 10
    assert json.loads((tmp_path / "sources.v1.backup.json").read_text()) == legacy
    assert json.loads((tmp_path / "sources.json").read_text())["schema_version"] == 2


def test_future_or_corrupt_source_schema_is_never_overwritten(tmp_path):
    manager = SourceManager()
    future = '{"schema_version":99,"sources":[]}'
    (tmp_path / "sources.json").write_text(future)
    with configure_paths(tmp_path):
        with pytest.raises(UnsupportedSourceSchema):
            manager.get_sources()
    assert (tmp_path / "sources.json").read_text() == future

    corrupt = "{broken"
    (tmp_path / "sources.json").write_text(corrupt)
    with configure_paths(tmp_path):
        with pytest.raises(SourceRegistryError):
            manager.get_sources()
    assert (tmp_path / "sources.json").read_text() == corrupt


@pytest.mark.parametrize(
    ("raw", "stream_id", "identifier_type"),
    [
        ("A" * 40, "a" * 40, "id"),
        (f"acestream://{'b' * 40}", "b" * 40, "id"),
        (f"INFOHASH://{'C' * 40}", "c" * 40, "infohash"),
        (f"https://host/stream?content_id={'d' * 40}", "d" * 40, "id"),
        (f"https://host/stream?INFOHASH={'e' * 40}", "e" * 40, "infohash"),
    ],
)
def test_stream_reference_formats(raw, stream_id, identifier_type):
    reference = extract_stream_reference(raw)
    assert reference.stream_id == stream_id
    assert reference.identifier_type == identifier_type


def test_m3u_parser_preserves_metadata_and_rejects_bare_torrent():
    body = f'''\ufeff#EXTM3U
#EXTINF:-1 tvg-id="sport.one" tvg-logo="https://logo" group-title="Sports",One
https://host/play?infohash={'a' * 40}
'''
    channel = parse_m3u(body, "https://source/list.m3u", "Source")[0]
    assert channel == {
        "id": "a" * 40,
        "identifier_type": "infohash",
        "name": "One",
        "logo": "https://logo",
        "group": "Sports",
        "tvg_id": "sport.one",
        "source": "https://source/list.m3u",
    }

    with pytest.raises(ValueError, match="AceXY"):
        parse_m3u("#EXTM3U\n#EXTINF:-1,File\nhttps://host/file.torrent\n", "https://source", "Source")


def test_acestream_api_parser_reads_nested_items_and_deduplicates():
    payload = json.dumps({
        "result": {
            "items": [
                {"name": "API channel", "infohash": "a" * 40, "category": "API"},
                {"name": "Duplicate", "infohash": "a" * 40},
            ]
        }
    })
    channels = parse_acestream_api(payload, "https://api.acestream.me/search?q=x", "Search")
    assert len(channels) == 1
    assert channels[0]["identifier_type"] == "infohash"
    assert channels[0]["group"] == "API"


class FakeResponse:
    def __init__(self, chunks):
        self._chunks = chunks
        self.encoding = "utf-8"
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, _size):
        yield from self._chunks

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def get(self, _url, **kwargs):
        self.kwargs = kwargs
        return self.response


def test_validator_enforces_limit_and_network_defaults():
    response = FakeResponse([b"#EXTM3U\n", b"x" * 50])
    session = FakeSession(response)
    with patch.multiple(Config, SOURCE_MAX_BYTES=20, SOURCE_CONNECT_TIMEOUT=8, SOURCE_READ_TIMEOUT=30, SOURCE_TLS_VERIFY=False):
        result = SourceValidator(session).validate("https://source/list.m3u", "Source")
    assert result.error_code == "response_too_large"
    assert session.kwargs["timeout"] == (8, 30)
    assert session.kwargs["verify"] is False
    assert response.closed


def test_custom_channel_crud_and_manual_precedence(tmp_path):
    manager = CustomChannelManager()
    with configure_paths(tmp_path):
        created = manager.create({
            "name": "Manual",
            "stream_id": f"infohash://{'a' * 40}",
            "group": "Mine",
            "logo": "https://logo",
            "tvg_id": "manual.one",
        })
        with pytest.raises(DuplicateCustomChannel):
            manager.create({"name": "Duplicate", "stream_id": f"infohash://{'a' * 40}"})
        updated = manager.update(created["id"], {"name": "Updated"})
        manual = manager.normalized_channels()[0]
        remote = dict(manual, name="Remote", source_id="remote")
        merged = ChannelManager._merge_source_snapshots([[manual], [remote]])
        deleted = manager.delete(created["id"])

    assert updated["name"] == "Updated"
    assert updated["group"] == "Mine"
    assert merged[0]["name"] == "Updated"
    assert len(merged) == 1
    assert deleted["id"] == created["id"]


def test_webui_does_not_interpolate_remote_metadata_as_html():
    script = Path(__file__).parents[1] / "src/app/static/script.js"
    javascript = script.read_text(encoding="utf-8")

    assert "innerHTML = `" not in javascript
    assert "innerHTML = html" not in javascript
    assert "insertAdjacentHTML" not in javascript
    assert "element('strong', '', String(engine.container_name" in javascript
    assert "element('div', 'channel-name'" in javascript
