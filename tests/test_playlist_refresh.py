import json
import os
import time
from unittest.mock import Mock, patch

from app.config import Config
from app.services.channel_manager import ChannelManager
from app.services.refresh_scheduler import PlaylistRefreshScheduler
from app.services.source_manager import source_manager
from app.services.source_validator import ValidationResult


def configure_paths(tmp_path):
    return patch.multiple(
        Config,
        DATA_DIR=str(tmp_path),
        JSON_FILE=str(tmp_path / "channels.json"),
        SOURCE_CACHE_DIR=str(tmp_path / "source_cache"),
        M3U_FILE=str(tmp_path / "ace_hls.m3u"),
        SOURCES_FILE=str(tmp_path / "sources.json"),
        CUSTOM_CHANNELS_FILE=str(tmp_path / "custom_channels.json"),
    )


def source(url, suffix="1"):
    return {
        "id": f"src-{suffix}",
        "name": f"Source {suffix}",
        "url": url,
        "enabled": True,
    }


def valid_result(url, name, stream_id, identifier_type="id"):
    return ValidationResult(
        True,
        "valid",
        "m3u",
        url,
        [{
            "id": stream_id,
            "identifier_type": identifier_type,
            "name": name,
            "logo": "",
            "group": "Sports",
            "tvg_id": "",
            "source": url,
        }],
    )


def failed_result(url):
    return ValidationResult(
        False,
        "unreachable",
        "m3u",
        url,
        error_code="source_unreachable",
        error="offline",
    )


def refresh_context(sources, results):
    return (
        patch.object(source_manager, "get_sources", return_value=sources),
        patch.object(source_manager, "record_refresh"),
        patch("app.services.channel_manager.source_validator.validate", side_effect=results),
        patch("app.services.channel_manager.custom_channel_manager.normalized_channels", return_value=[]),
    )


def test_due_refresh_updates_cache_without_web_request(tmp_path):
    configured_source = source("https://source/list.m3u")
    result = valid_result(configured_source["url"], "Example", "0123456789abcdef0123456789abcdef01234567")
    with configure_paths(tmp_path):
        manager = ChannelManager()
        contexts = refresh_context([configured_source], [result])
        with contexts[0], contexts[1], contexts[2], contexts[3]:
            assert manager.update_channels_if_due(900) is True
        channels = json.loads((tmp_path / "channels.json").read_text())

    assert channels[0]["name"] == "Example"
    assert channels[0]["source_id"] == "src-1"


def test_fresh_cache_skips_network_refresh(tmp_path):
    with configure_paths(tmp_path):
        (tmp_path / "channels.json").write_text("[]")
        manager = ChannelManager()
        with patch("app.services.channel_manager.source_validator.validate") as validate:
            assert manager.update_channels_if_due(900) is None
    validate.assert_not_called()


def test_all_source_failures_preserve_previous_cache(tmp_path):
    configured_source = source("https://broken/list.m3u")
    previous = '[{"id":"existing"}]'
    with configure_paths(tmp_path):
        (tmp_path / "channels.json").write_text(previous)
        old = time.time() - 3600
        os.utime(tmp_path / "channels.json", (old, old))
        manager = ChannelManager()
        contexts = refresh_context([configured_source], [failed_result(configured_source["url"])])
        with contexts[0], contexts[1], contexts[2], contexts[3]:
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


def test_scheduler_waits_only_until_existing_cache_is_due():
    manager = Mock(last_update=0)
    manager._cache_mtime.return_value = time.time() - 840
    scheduler = PlaylistRefreshScheduler(manager=manager, interval=900)
    assert 59 <= scheduler._seconds_until_due() <= 60


def test_partial_failure_uses_last_valid_cache_for_failed_source(tmp_path):
    source_a = source("https://source/a.m3u", "a")
    source_b = source("https://source/b.m3u", "b")
    first = [
        valid_result(source_a["url"], "A old", "a" * 40),
        valid_result(source_b["url"], "B cached", "b" * 40),
    ]
    second = [valid_result(source_a["url"], "A new", "c" * 40), failed_result(source_b["url"])]

    with configure_paths(tmp_path):
        manager = ChannelManager()
        contexts = refresh_context([source_a, source_b], first + second)
        with contexts[0], contexts[1], contexts[2], contexts[3]:
            assert manager.update_channels() is True
            assert manager.update_channels() is True
        channels = json.loads((tmp_path / "channels.json").read_text())
        caches = list((tmp_path / "source_cache").glob("*.json"))

    assert [(item["name"], item["source_id"]) for item in channels] == [
        ("A new", "src-a"),
        ("B cached", "src-b"),
    ]
    assert len(caches) == 2


def test_invalid_response_does_not_replace_source_cache(tmp_path):
    configured_source = source("https://source/unstable.m3u")
    with configure_paths(tmp_path):
        manager = ChannelManager()
        contexts = refresh_context(
            [configured_source],
            [valid_result(configured_source["url"], "Stable", "d" * 40), failed_result(configured_source["url"])],
        )
        with contexts[0], contexts[1], contexts[2], contexts[3]:
            assert manager.update_channels() is True
            previous = (tmp_path / "channels.json").read_text()
            assert manager.update_channels() is False
        current = (tmp_path / "channels.json").read_text()
    assert current == previous


def test_existing_global_cache_migrates_to_source_id_cache(tmp_path):
    configured_source = source("https://source/legacy.m3u")
    legacy_channel = {
        "id": "e" * 40,
        "name": "Legacy",
        "logo": "",
        "group": "General",
        "url": "http://old/stream",
        "source": configured_source["url"],
    }
    with configure_paths(tmp_path):
        (tmp_path / "channels.json").write_text(json.dumps([legacy_channel]))
        manager = ChannelManager()
        contexts = refresh_context([configured_source], [failed_result(configured_source["url"])])
        with contexts[0], contexts[1], contexts[2], contexts[3]:
            assert manager.update_channels() is False
        cache = json.loads((tmp_path / "source_cache" / "src-1.json").read_text())
    assert cache["source_id"] == "src-1"
    assert cache["channels"][0]["source_id"] == "src-1"


def test_failed_scheduler_uses_bounded_retry_delay():
    manager = Mock(last_update=0)
    manager._cache_mtime.return_value = time.time() - 3600
    scheduler = PlaylistRefreshScheduler(manager=manager, interval=900)
    scheduler.last_result = "failed"
    assert scheduler._seconds_until_due() == 60
