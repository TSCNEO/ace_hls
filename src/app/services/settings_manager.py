import json
import os
import logging
from app.config import Config
from app.services.storage import atomic_write_json
from app.utils import normalize_public_endpoint

logger = logging.getLogger(__name__)

class SettingsManager:
    def __init__(self):
        self.settings_file = os.path.join(Config.DATA_DIR, 'settings.json')
        self.ensure_file_exists()

    def ensure_file_exists(self):
        """Creates settings.json with defaults from Env Vars if missing."""
        if not os.path.exists(self.settings_file):
            defaults = {
                "transcode_720p_bitrate": Config.TRANSCODE_720P_BITRATE,
                "transcode_480p_bitrate": Config.TRANSCODE_480P_BITRATE,
                "transcode_compat_crf": Config.TRANSCODE_COMPAT_CRF,
                "stream_public_endpoint": Config.STREAM_PUBLIC_ENDPOINT or "",
                "stream_public_token": Config.ACEXY_PUBLIC_TOKEN or "",
                "transcode_video_codec": "h264", # h264, hevc
                "transcode_audio_bitrate": "128k",
                "transcode_preset": "veryfast", # ultrafast, superfast, veryfast, faster, fast, medium...
                "transcode_deinterlace": False,
                "orchestrator_enabled": False
            }
            self.save(defaults)
            logger.info("Created settings.json with application defaults")
        else:
            self._migrate_legacy_keys()

    @staticmethod
    def _normalize(data):
        normalized = dict(data)
        legacy_mappings = {
            "acexy_public_endpoint": "stream_public_endpoint",
            "acexy_public_token": "stream_public_token",
        }
        for legacy, current in legacy_mappings.items():
            if current not in normalized and legacy in normalized:
                normalized[current] = normalized[legacy]
            normalized.pop(legacy, None)
        if "stream_public_endpoint" in normalized:
            normalized["stream_public_endpoint"] = normalize_public_endpoint(
                normalized["stream_public_endpoint"]
            )
        return normalized

    def _migrate_legacy_keys(self):
        try:
            with open(self.settings_file, "r", encoding="utf-8") as handle:
                current = json.load(handle)
            migrated = self._normalize(current)
            if migrated != current:
                atomic_write_json(self.settings_file, migrated)
                logger.info("Migrated legacy streaming settings")
        except (OSError, ValueError, TypeError) as exc:
            logger.error("Error migrating settings: %s", exc)

    def get_all(self):
        try:
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                return self._normalize(json.load(f))
        except Exception as e:
            logger.error(f"Error reading settings: {e}")
            return {}

    def get(self, key, default=None):
        data = self.get_all()
        return data.get(key, default)

    def save(self, new_settings):
        """Updates settings.json. Merges with existing."""
        current = self.get_all()
        current.update(self._normalize(new_settings))
        try:
            atomic_write_json(self.settings_file, current)
            return True
        except Exception as e:
            logger.error(f"Error saving settings: {e}")
            return False

settings_manager = SettingsManager()
