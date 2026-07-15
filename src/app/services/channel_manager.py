import hashlib
import os
import json
import re
import time
import fcntl
import tempfile
import threading
import requests
import logging
from app.config import Config

logger = logging.getLogger(__name__)

class ChannelManager:
    def __init__(self):
        self.last_update = self._cache_mtime()
        self._update_lock = threading.Lock()
        self._process_lock_file = os.path.join(Config.DATA_DIR, 'channels.refresh.lock')
        if not os.path.exists(Config.DATA_DIR):
            os.makedirs(Config.DATA_DIR)

    def update_channels(self):
        """Downloads and processes the M3U list from ALL sources with deduplication."""
        return self._run_update(force=True)

    def update_channels_if_due(self, max_age):
        """Refresh once per max_age across threads and Gunicorn workers."""
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
            with open(self._process_lock_file, 'a+') as process_lock:
                fcntl.flock(process_lock.fileno(), fcntl.LOCK_EX)
                if not force and not self.is_update_due(max_age):
                    return None
                return self._update_channels_locked()

    def _update_channels_locked(self):
        from app.services.source_manager import source_manager

        logger.info("Updating channels list from all sources...")
        
        sources = source_manager.get_sources()
        previous_channels = self._load_global_channels()
        os.makedirs(Config.SOURCE_CACHE_DIR, exist_ok=True)
        self._migrate_global_cache(sources, previous_channels)

        source_snapshots = []
        successful_sources = 0
        cached_sources = 0
        
        requests.packages.urllib3.disable_warnings()

        for src in sources:
            url = src['url']
            cached_channels = self._load_source_cache(url)
            try:
                logger.info(f"Fetching source: {url}")
                response = requests.get(url, timeout=30, verify=False)
                response.raise_for_status()
                content = response.text
                if "#EXTM3U" not in content.upper():
                    raise ValueError("response is not an M3U playlist")

                source_channels = []
                self._parse_m3u_content(
                    content,
                    url,
                    source_channels,
                    set(),
                    ["#EXTM3U"],
                )
                if cached_channels and not source_channels:
                    raise ValueError("empty playlist would replace a non-empty source cache")

                self._save_source_cache(url, source_channels)
                source_snapshots.append(source_channels)
                successful_sources += 1
            except Exception as e:
                logger.error(f"Failed to download list from {url}: {e}")
                fallback = cached_channels or self._legacy_channels_for_source(previous_channels, url)
                source_snapshots.append(fallback)
                if fallback:
                    cached_sources += 1
                    logger.warning(
                        "Using cached source: %s | Channels: %s",
                        url,
                        len(fallback),
                    )

        all_channels = self._merge_source_snapshots(source_snapshots)

        if sources and successful_sources == 0:
            if not os.path.exists(Config.JSON_FILE) and all_channels:
                return self._save_global_outputs(all_channels, successful_sources, cached_sources, len(sources))
            logger.error(
                "Channel refresh aborted: all sources failed; preserving current global cache."
            )
            return False

        return self._save_global_outputs(
            all_channels,
            successful_sources,
            cached_sources,
            len(sources),
        )

    def _save_global_outputs(self, channels, successful_sources, cached_sources, source_count):
        try:
            self._atomic_write(Config.JSON_FILE, json.dumps(channels, indent=2))
            self._atomic_write(Config.M3U_FILE, self._render_m3u(channels))

            self.last_update = time.time()
            logger.info(
                "Update complete. Total: %s channels | Fresh sources: %s/%s | "
                "Cached fallbacks: %s",
                len(channels),
                successful_sources,
                source_count,
                cached_sources,
            )
            return True
        except Exception as e:
            logger.error(f"Error saving output files: {e}")
            return False

    def _source_cache_path(self, source_url):
        digest = hashlib.sha256(source_url.encode('utf-8')).hexdigest()
        return os.path.join(Config.SOURCE_CACHE_DIR, f"{digest}.json")

    def _save_source_cache(self, source_url, channels):
        payload = {
            "schema_version": 1,
            "source_url": source_url,
            "updated_at": time.time(),
            "channels": channels,
        }
        self._atomic_write(
            self._source_cache_path(source_url),
            json.dumps(payload, indent=2),
        )

    def _load_source_cache(self, source_url):
        try:
            with open(self._source_cache_path(source_url), 'r') as handle:
                payload = json.load(handle)
            channels = payload.get("channels")
            if (
                payload.get("source_url") != source_url
                or not isinstance(channels, list)
                or not all(isinstance(channel, dict) for channel in channels)
            ):
                raise ValueError("invalid source cache payload")
            return channels
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            if not isinstance(exc, FileNotFoundError):
                logger.warning("Ignoring invalid source cache for %s: %s", source_url, exc)
            return []

    def _load_global_channels(self):
        try:
            with open(Config.JSON_FILE, 'r') as handle:
                channels = json.load(handle)
            return channels if isinstance(channels, list) else []
        except (OSError, ValueError):
            return []

    def _legacy_channels_for_source(self, channels, source_url):
        return [channel for channel in channels if channel.get("source") == source_url]

    def _migrate_global_cache(self, sources, previous_channels):
        if not previous_channels:
            return
        for source in sources:
            url = source['url']
            if os.path.exists(self._source_cache_path(url)):
                continue
            legacy_channels = self._legacy_channels_for_source(previous_channels, url)
            if legacy_channels:
                self._save_source_cache(url, legacy_channels)
                logger.info(
                    "Migrated global cache for source: %s | Channels: %s",
                    url,
                    len(legacy_channels),
                )

    def _merge_source_snapshots(self, snapshots):
        channels = []
        seen_ids = set()
        for snapshot in snapshots:
            for original in snapshot:
                ace_id = original.get("id")
                if not ace_id or ace_id in seen_ids:
                    continue
                seen_ids.add(ace_id)
                channel = dict(original)
                channel["url"] = (
                    f"http://{Config.ACEXY_IP}:{Config.ACEXY_PORT}/ace/getstream?id={ace_id}"
                )
                channels.append(channel)
        return channels

    def _render_m3u(self, channels):
        lines = ["#EXTM3U"]
        for channel in channels:
            name = str(channel.get("name") or "Unknown").replace('\n', ' ')
            logo = str(channel.get("logo") or "").replace('"', '')
            group = str(channel.get("group") or "General").replace('"', '')
            lines.append(f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group}",{name}')
            lines.append(channel["url"])
        return "\n".join(lines)

    def _atomic_write(self, destination, content):
        directory = os.path.dirname(destination)
        fd, temporary = tempfile.mkstemp(prefix='.ace-hls-', dir=directory, text=True)
        try:
            with os.fdopen(fd, 'w') as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _parse_m3u_content(self, content, source_url, channels_list, seen_ids, m3u_lines):
        lines = content.splitlines()
        info_line = ""
        
        # Stats for this source
        stats = {"added": 0, "duplicates": 0, "total_found": 0}
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if line.startswith("#EXTINF:"):
                info_line = line
                continue
            
            if info_line:
                ace_id = None
                # Regex to extract AceStream ID
                match_ace = re.search(r'acestream://([a-f0-9]{40})', line)
                match_http = re.search(r'id=([a-f0-9]{40})', line)

                if match_ace:
                    ace_id = match_ace.group(1)
                elif match_http:
                    ace_id = match_http.group(1)

                if ace_id:
                    stats["total_found"] += 1
                    # Deduplication check
                    if ace_id in seen_ids:
                        # Skip duplicate
                        stats["duplicates"] += 1
                        info_line = ""
                        continue
                        
                    seen_ids.add(ace_id)
                    stats["added"] += 1

                    # Parse Meta (Name, Logo)
                    name = info_line.split(',')[-1].strip().replace(" [ACESTREAM]", "")
                    logo_match = re.search(r'tvg-logo="([^"]+)"', info_line)
                    logo = logo_match.group(1) if logo_match else ""
                    group_match = re.search(r'group-title="([^"]+)"', info_line)
                    group = group_match.group(1) if group_match else "General"

                    # Generate new stream URL
                    stream_url = f"http://{Config.ACEXY_IP}:{Config.ACEXY_PORT}/ace/getstream?id={ace_id}"
                    
                    # Add to JSON list
                    channels_list.append({
                        "id": ace_id,
                        "name": name,
                        "logo": logo,
                        "group": group,
                        "url": stream_url,
                        "source": source_url # Track origin for debugging
                    })

                    # Add to M3U
                    m3u_lines.append(info_line.replace(" [ACESTREAM]", ""))
                    m3u_lines.append(stream_url)

                info_line = "" # Reset for next
        
        logger.info(f"Source Processed: {source_url} | Found: {stats['total_found']} | Added: {stats['added']} | Duplicates: {stats['duplicates']}")

# Global Instance
channel_manager = ChannelManager()
