import json
import os
import time
import logging
from threading import Lock
from app.config import Config

logger = logging.getLogger(__name__)

class StatsManager:
    def __init__(self):
        self._file = os.path.join(Config.DATA_DIR, 'stats.json')
        self._lock = Lock()
        self._stats = self._load_stats()

    def _load_stats(self):
        if not os.path.exists(self._file):
            return {}
        try:
            with open(self._file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load stats: {e}")
            return {}

    def _save_stats(self):
        try:
            with open(self._file, 'w') as f:
                json.dump(self._stats, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save stats: {e}")

    def update_channel_success(self, ace_id, tech_info=None):
        """
        Updates the success stats for a channel.
        :param ace_id: The AceStream ID
        :param tech_info: Optional dictionary with technical metadata (res, fps, codecs)
        """
        with self._lock:
            now = int(time.time())
            
            if ace_id not in self._stats:
                self._stats[ace_id] = {
                    "first_seen": now,
                    "success_count": 0
                }
            
            entry = self._stats[ace_id]
            entry["last_ok"] = now
            entry["success_count"] += 1
            
            if tech_info:
                entry["tech_info"] = tech_info
                
            self._save_stats()
            # logger.info(f"Updated stats for {ace_id}: Count={entry['success_count']}")

    def update_user_feedback(self, ace_id, vote):
        """
        Updates user feedback (like/dislike)
        :param ace_id: The AceStream ID
        :param vote: 'like' or 'dislike'
        """
        with self._lock:
            now = int(time.time())
            if ace_id not in self._stats:
                self._stats[ace_id] = {
                    "first_seen": now,
                    "success_count": 0
                }
            
            entry = self._stats[ace_id]
            
            # Initialize feedback counters if missing
            if "diff_votes" not in entry:
                entry["diff_votes"] = 0 # Net score (likes - dislikes)
            if "vote_count" not in entry:
                entry["vote_count"] = 0 # Total interactions

            if vote == 'like':
                entry["diff_votes"] += 1
            elif vote == 'dislike':
                entry["diff_votes"] -= 1
            
            entry["vote_count"] += 1
            entry["last_vote"] = now
            
            self._save_stats()

    def get_stats(self, ace_id=None):
        if ace_id:
            return self._stats.get(ace_id)
        return self._stats

# Global instance
stats_manager = StatsManager()
