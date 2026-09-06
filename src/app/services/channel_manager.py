from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import threading
import time
from copy import deepcopy

from app.config import Config
from app.services.custom_channel_manager import custom_channel_manager
from app.services.source_validator import ValidationResult, source_validator
from app.services.storage import atomic_write_json, atomic_write_text
from app.utils import format_url_host


logger = logging.getLogger(__name__)


def _safe_m3u_value(value, *, strip_quotes=False) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    return text.replace('"', "'") if strip_quotes else text


class ChannelManager:
    def __init__(self):
        self.last_update = self._cache_mtime()
        self._update_lock = threading.Lock()

    @property
    def _process_lock_file(self) -> str:
        return os.path.join(Config.DATA_DIR, "channels.refresh.lock")

    def update_channels(self):
        return self._run_update(force=True)

    def update_channels_if_due(self, max_age):
        return self._run_update(force=False, max_age=max_age)

    def is_update_due(self, max_age):
        cache_mtime = self._cache_mtime()
        return not cache_mtime or (time.time() - cache_mtime) >= max_age

    def _cache_mtime(self):
        try:
            return os.path.getmtime(Config.JSON_FILE)
        except OSError:
            return 0

    def _run_update(self, force, max_age=None):
        os.makedirs(Config.DATA_DIR, exist_ok=True)
        with self._update_lock:
            with open(self._process_lock_file, "a+", encoding="utf-8") as process_lock:
                fcntl.flock(process_lock.fileno(), fcntl.LOCK_EX)
                if not force and not self.is_update_due(max_age):
                    return None
                return self._update_channels_locked()

    def _update_channels_locked(self):
        from app.services.source_manager import source_manager
        from concurrent.futures import ThreadPoolExecutor, as_completed

        sources = source_manager.get_sources()
        enabled_sources = [source for source in sources if source.get("enabled", True)]
        custom_channels = custom_channel_manager.normalized_channels()

        if not enabled_sources:
            channels = self._merge_source_snapshots([custom_channels])
            return self._save_global_outputs(channels, 0, 0, 0)

        def _fetch_source(src):
            cached_channels, cached_hash = self._load_source_cache_entry(src)
            val = source_validator.validate(src["url"], src.get("name", ""), cached_hash=cached_hash)
            return src, cached_channels, cached_hash, val

        workers = min(Config.SOURCE_REFRESH_WORKERS, len(enabled_sources))
        results = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="src-refresh") as executor:
            future_to_src = {executor.submit(_fetch_source, src): src for src in enabled_sources}
            for future in as_completed(future_to_src):
                try:
                    results.append(future.result())
                except Exception as exc:
                    src = future_to_src[future]
                    logger.error("Unexpected error refreshing source %s: %s", src.get("url"), exc)
                    cached_channels, cached_hash = self._load_source_cache_entry(src)
                    val = source_validator.ValidationResult(
                        False, "invalid", "unknown", src.get("url", ""), error=str(exc)
                    )
                    results.append((src, cached_channels, cached_hash, val))

        # Preserve source order as in sources.json
        src_order = {src["id"]: i for i, src in enumerate(enabled_sources)}
        results.sort(key=lambda r: src_order.get(r[0]["id"], 999))

        snapshots: list[list[dict]] = [custom_channels]
        successful_sources = 0
        cached_sources = 0

        for source, cached_channels, cached_hash, validation in results:
            if validation.valid:
                if validation.not_modified:
                    # Content verified unchanged: reuse cached channels immediately
                    snapshots.append(cached_channels)
                    successful_sources += 1
                    source_manager.record_refresh(source["id"], validation=validation, success=True)
                    continue

                channels = self._with_source_identity(validation.channels, source)
                if cached_channels and not channels:
                    validation.valid = False
                    validation.status = "invalid"
                    validation.error = "Una respuesta vacía no puede reemplazar una caché no vacía."
                else:
                    self.save_source_snapshot(source, channels, content_hash=validation.content_hash)
                    snapshots.append(channels)
                    successful_sources += 1
                    source_manager.record_refresh(source["id"], validation=validation, success=True)
                    continue

            snapshots.append(cached_channels)
            if cached_channels:
                cached_sources += 1
            source_manager.record_refresh(
                source["id"],
                validation=validation,
                using_cache=bool(cached_channels),
                error=validation.error,
            )
            logger.warning("Source refresh failed for %s: %s", source["url"], validation.error)

        channels = self._merge_source_snapshots(snapshots)
        if enabled_sources and successful_sources == 0 and os.path.exists(Config.JSON_FILE):
            logger.error("All enabled sources failed; preserving the current global cache.")
            return False
        return self._save_global_outputs(
            channels,
            successful_sources,
            cached_sources,
            len(enabled_sources),
        )

    @staticmethod
    def _with_source_identity(channels: list[dict], source: dict) -> list[dict]:
        normalized = []
        for original in channels:
            channel = deepcopy(original)
            channel["source"] = source["url"]
            channel["source_id"] = source["id"]
            normalized.append(channel)
        return normalized

    def _save_global_outputs(self, channels, successful_sources=0, cached_sources=0, source_count=0):
        try:
            atomic_write_json(Config.JSON_FILE, channels)
            atomic_write_text(Config.M3U_FILE, self._render_direct_m3u(channels))
            self.last_update = time.time()
            logger.info(
                "Channel update complete: total=%s fresh=%s/%s cached=%s",
                len(channels),
                successful_sources,
                source_count,
                cached_sources,
            )
            return True
        except Exception as exc:
            logger.error("Error saving channel outputs: %s", exc)
            return False

    def _source_cache_path(self, source: dict) -> str:
        return os.path.join(Config.SOURCE_CACHE_DIR, f"{source['id']}.json")

    def _legacy_source_cache_path(self, source_url: str) -> str:
        digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
        return os.path.join(Config.SOURCE_CACHE_DIR, f"{digest}.json")

    def _migrate_source_cache(self, source: dict) -> None:
        current = self._source_cache_path(source)
        legacy = self._legacy_source_cache_path(source["url"])
        if os.path.exists(current) or not os.path.exists(legacy):
            return
        try:
            with open(legacy, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            channels = self._with_source_identity(payload.get("channels", []), source)
            self.save_source_snapshot(source, channels)
            logger.info("Migrated source cache %s to %s.", legacy, current)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not migrate source cache for %s: %s", source["url"], exc)

    def save_source_snapshot(self, source: dict, channels: list[dict], content_hash: str | None = None) -> None:
        os.makedirs(Config.SOURCE_CACHE_DIR, exist_ok=True)
        normalized = self._with_source_identity(channels, source)
        atomic_write_json(
            self._source_cache_path(source),
            {
                "schema_version": 2,
                "source_id": source["id"],
                "source_url": source["url"],
                "updated_at": time.time(),
                "content_hash": content_hash,
                "channels": normalized,
            },
        )

    def delete_source_snapshot(self, source: dict) -> None:
        for path in (self._source_cache_path(source), self._legacy_source_cache_path(source["url"])):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def _load_source_cache_entry(self, source: dict) -> tuple[list[dict], str | None]:
        self._migrate_source_cache(source)
        try:
            with open(self._source_cache_path(source), "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            channels = payload.get("channels")
            content_hash = payload.get("content_hash")
            if (
                payload.get("source_id") != source["id"]
                or not isinstance(channels, list)
                or not all(isinstance(channel, dict) for channel in channels)
            ):
                raise ValueError("invalid source cache payload")
            return self._with_source_identity(channels, source), content_hash
        except FileNotFoundError:
            legacy = self._legacy_channels_for_source(self._load_global_channels(), source)
            if legacy:
                self.save_source_snapshot(source, legacy)
            return legacy, None
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Ignoring invalid cache for %s: %s", source["url"], exc)
            return [], None

    def _load_source_cache(self, source: dict) -> list[dict]:
        channels, _ = self._load_source_cache_entry(source)
        return channels

    def _load_global_channels(self) -> list[dict]:
        try:
            with open(Config.JSON_FILE, "r", encoding="utf-8") as handle:
                channels = json.load(handle)
            return channels if isinstance(channels, list) else []
        except (OSError, ValueError):
            return []

    @staticmethod
    def _legacy_channels_for_source(channels: list[dict], source: dict) -> list[dict]:
        matched = [
            channel for channel in channels
            if channel.get("source_id") == source["id"] or channel.get("source") == source["url"]
        ]
        return ChannelManager._with_source_identity(matched, source)

    def rebuild_from_cache(self) -> bool:
        from app.services.source_manager import source_manager

        snapshots = [custom_channel_manager.normalized_channels()]
        for source in source_manager.get_sources():
            if source.get("enabled", True):
                snapshots.append(self._load_source_cache(source))
        return self._save_global_outputs(self._merge_source_snapshots(snapshots))

    def accept_validated_source(self, source: dict, validation) -> bool:
        if validation.valid:
            self.save_source_snapshot(source, validation.channels)
        return self.rebuild_from_cache()

    @staticmethod
    def _merge_source_snapshots(snapshots: list[list[dict]]) -> list[dict]:
        channels = []
        seen: set[tuple[str, str]] = set()
        for snapshot in snapshots:
            for original in snapshot:
                stream_id = original.get("id")
                identifier_type = original.get("identifier_type", "id")
                identity = (identifier_type, stream_id)
                if not stream_id or identity in seen:
                    continue
                seen.add(identity)
                channel = deepcopy(original)
                channel["identifier_type"] = identifier_type
                query_key = "infohash" if identifier_type == "infohash" else "id"
                channel["url"] = (
                    f"http://{format_url_host(Config.STREAM_PROXY_HOST)}:{Config.STREAM_PROXY_PORT}"
                    f"/ace/getstream?{query_key}={stream_id}"
                )
                channels.append(channel)
        return channels

    @staticmethod
    def _render_direct_m3u(channels: list[dict]) -> str:
        lines = ["#EXTM3U"]
        for channel in channels:
            name = _safe_m3u_value(channel.get("name") or "Unknown")
            logo = _safe_m3u_value(channel.get("logo"), strip_quotes=True)
            group = _safe_m3u_value(channel.get("group") or "General", strip_quotes=True)
            tvg_id = _safe_m3u_value(channel.get("tvg_id") or channel.get("id"), strip_quotes=True)
            lines.append(
                f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{logo}" group-title="{group}",{name}'
            )
            lines.append(channel["url"])
        return "\n".join(lines)


channel_manager = ChannelManager()
