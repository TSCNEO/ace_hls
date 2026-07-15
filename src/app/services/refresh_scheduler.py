import logging
import threading
import time

from app.config import Config
from app.services.channel_manager import channel_manager


logger = logging.getLogger(__name__)


class PlaylistRefreshScheduler:
    def __init__(self, manager=channel_manager, interval=None):
        self.manager = manager
        self.interval = interval or Config.PLAYLIST_REFRESH_INTERVAL
        self._stop_event = threading.Event()
        self._start_lock = threading.Lock()
        self._thread = None
        self.last_attempt = None
        self.last_success = manager.last_update or None
        self.last_result = "not_started"

    def start(self):
        with self._start_lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="playlist-refresh",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self):
        self._stop_event.set()

    def run_once(self):
        self.last_attempt = time.time()
        try:
            result = self.manager.update_channels_if_due(self.interval)
            if result is True:
                self.last_success = self.manager.last_update
                self.last_result = "updated"
            elif result is None:
                self.last_result = "skipped_fresh_cache"
            else:
                self.last_result = "failed"
            return result
        except Exception:
            self.last_result = "failed"
            logger.exception("Scheduled playlist refresh failed")
            return False

    def status(self):
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "interval_seconds": self.interval,
            "last_attempt": self.last_attempt,
            "last_success": self.last_success,
            "last_result": self.last_result,
        }

    def _run(self):
        logger.info("Playlist refresh scheduler started (interval=%ss)", self.interval)
        while not self._stop_event.is_set():
            self.run_once()
            if self._stop_event.wait(self._seconds_until_due()):
                break

    def _seconds_until_due(self):
        cache_mtime = self.manager._cache_mtime()
        if not cache_mtime:
            return min(60, self.interval)
        remaining = self.interval - (time.time() - cache_mtime)
        return max(1, remaining)


playlist_refresh_scheduler = PlaylistRefreshScheduler()
