import json
import os
import logging
from app.config import Config

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
                "acexy_public_endpoint": Config.ACEXY_PUBLIC_ENDPOINT or "",
                "acexy_public_token": Config.ACEXY_PUBLIC_TOKEN or ""
            }
            self.save(defaults)
            logger.info(f"Created settings.json with defaults: {defaults}")

    def get_all(self):
        try:
            with open(self.settings_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading settings: {e}")
            return {}

    def get(self, key, default=None):
        data = self.get_all()
        return data.get(key, default)

    def save(self, new_settings):
        """Updates settings.json. Merges with existing."""
        current = self.get_all()
        current.update(new_settings)
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(current, f, indent=4)
            return True
        except Exception as e:
            logger.error(f"Error saving settings: {e}")
            return False

settings_manager = SettingsManager()
