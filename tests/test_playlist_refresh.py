import json
import os
import time
from unittest.mock import Mock, patch

import requests

from app.config import Config
from app.services.channel_manager import ChannelManager
from app.services.refresh_scheduler import PlaylistRefreshScheduler
from app.services.source_manager import source_manager


def configure_paths(tmp_path):
    return patch.multiple(
        Config,
        DATA_DIR=str(tmp_path),
        JSON_FILE=str(tmp_path / "channels.json"),
        SOURCE_CACHE_DIR=str(tmp_path / "source_cache"),
        M3U_FILE=str(tmp_path / "ace_hls.m3u"),
        SOURCES_FILE=str(tmp_path / "sources.json"),
    )


def test_due_refresh_updates_cache_without_web_request(tmp_path):
    m3u = """#EXTM3U
#EXTINF:-1 group-title="Sports",Example
acestream://0123456789abcdef0123456789abcdef01234567
"""
    response = Mock(text=m3u)
    response.raise_for_status.return_value = None

    with configure_paths(tmp_path):
        manager = ChannelManager()
        with patch.object(source_manager, "get_sources", return_value=[{"url": "https://source/list.m3u"}]):
            with patch("app.services.channel_manager.requests.get", return_value=response):
                assert manager.update_channels_if_due(900) is True

        channels = json.loads((tmp_path / "channels.json").read_text())

    assert channels[0]["name"] == "Example"
    assert channels[0]["group"] == "Sports"
    assert channels[0]["id"] == "0123456789abcdef0123456789abcdef01234567"


def test_fresh_cache_skips_network_refresh(tmp_path):
    with configure_paths(tmp_path):
        (tmp_path / "channels.json").write_text("[]")
        manager = ChannelManager()
        with patch("app.services.channel_manager.requests.get") as request_get:
            assert manager.update_channels_if_due(900) is None

    request_get.assert_not_called()


def test_all_source_failures_preserve_previous_cache(tmp_path):
    previous = '[{"id":"existing"}]'
    with configure_paths(tmp_path):
        (tmp_path / "channels.json").write_text(previous)
        old = time.time() - 3600
        os.utime(tmp_path / "channels.json", (old, old))
        manager = ChannelManager()
        with patch.object(source_manager, "get_sources", return_value=[{"url": "https://broken/list.m3u"}]):
            with patch(
                "app.services.channel_manager.requests.get",
                side_effect=requests.ConnectionError("offline"),
            ):
                assert manager.update_channels_if_due(900) is False

        current = (tmp_path / "channels.json").read_text()

    assert current == previous


def test_scheduler_runs_due_check_with_configured_interval():
    manager = Mock(last_update=0)
    manager.update_channels_if_due.return_value = True
    manager.last_update = 1234
    scheduler = PlaylistRefreshScheduler(manager=manager, interval=900)

    assert scheduler.run_once() is True

    manager.update_channels_if_due.assert_called_once_with(900)
    assert scheduler.last_success == 1234
    assert scheduler.last_result == "updated"


def test_scheduler_waits_only_until_existing_cache_is_due():
    manager = Mock(last_update=0)
    manager._cache_mtime.return_value = time.time() - 840
    scheduler = PlaylistRefreshScheduler(manager=manager, interval=900)

    remaining = scheduler._seconds_until_due()

    assert 59 <= remaining <= 60


def test_partial_failure_uses_last_valid_cache_for_failed_source(tmp_path):
    source_a = "https://source/a.m3u"
    source_b = "https://source/b.m3u"
    first_a = json_response(m3u_channel("A old", "a" * 40))
    first_b = json_response(m3u_channel("B cached", "b" * 40))
    updated_a = json_response(m3u_channel("A new", "c" * 40))

    with configure_paths(tmp_path):
        manager = ChannelManager()
        sources = [{"url": source_a}, {"url": source_b}]
        with patch.object(source_manager, "get_sources", return_value=sources):
            with patch(
                "app.services.channel_manager.requests.get",
                side_effect=[first_a, first_b],
            ):
                assert manager.update_channels() is True
            with patch(
                "app.services.channel_manager.requests.get",
                side_effect=[updated_a, requests.ConnectionError("offline")],
            ):
                assert manager.update_channels() is True

        channels = json.loads((tmp_path / "channels.json").read_text())
        playlist = (tmp_path / "ace_hls.m3u").read_text()
        source_cache_files = list((tmp_path / "source_cache").glob("*.json"))

    assert [(channel["name"], channel["source"]) for channel in channels] == [
        ("A new", source_a),
        ("B cached", source_b),
    ]
    assert "A new" in playlist
    assert "B cached" in playlist
    assert len(source_cache_files) == 2


def test_invalid_success_response_does_not_replace_source_cache(tmp_path):
    source = "https://source/unstable.m3u"
    valid = json_response(m3u_channel("Stable", "d" * 40))
    invalid = json_response("upstream temporarily unavailable")

    with configure_paths(tmp_path):
        manager = ChannelManager()
        with patch.object(source_manager, "get_sources", return_value=[{"url": source}]):
            with patch("app.services.channel_manager.requests.get", return_value=valid):
                assert manager.update_channels() is True
            previous = (tmp_path / "channels.json").read_text()
            with patch("app.services.channel_manager.requests.get", return_value=invalid):
                assert manager.update_channels() is False

        current = (tmp_path / "channels.json").read_text()

    assert current == previous


def test_existing_global_cache_is_migrated_before_failed_refresh(tmp_path):
    source = "https://source/legacy.m3u"
    legacy_channel = {
        "id": "e" * 40,
        "name": "Legacy",
        "logo": "",
        "group": "General",
        "url": "http://old/stream",
        "source": source,
    }

    with configure_paths(tmp_path):
        (tmp_path / "channels.json").write_text(json.dumps([legacy_channel]))
        manager = ChannelManager()
        with patch.object(source_manager, "get_sources", return_value=[{"url": source}]):
            with patch(
                "app.services.channel_manager.requests.get",
                side_effect=requests.ConnectionError("offline"),
            ):
                assert manager.update_channels() is False

        caches = list((tmp_path / "source_cache").glob("*.json"))
        cached_payload = json.loads(caches[0].read_text())

    assert cached_payload["source_url"] == source
    assert cached_payload["channels"] == [legacy_channel]


def test_failed_scheduler_uses_bounded_retry_delay():
    manager = Mock(last_update=0)
    manager._cache_mtime.return_value = time.time() - 3600
    scheduler = PlaylistRefreshScheduler(manager=manager, interval=900)
    scheduler.last_result = "failed"

    assert scheduler._seconds_until_due() == 60


def json_response(content):
    response = Mock(text=content)
    response.raise_for_status.return_value = None
    return response


def m3u_channel(name, ace_id):
    return f'''#EXTM3U
#EXTINF:-1 group-title="Test",{name}
acestream://{ace_id}
'''
