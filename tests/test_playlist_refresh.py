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
