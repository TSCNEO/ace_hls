import json
import os
import logging
from app.config import Config

logger = logging.getLogger(__name__)

class SourceManager:
    def __init__(self):
        self._ensure_sources_file()

    def _ensure_sources_file(self):
        """Ensures the sources file exists, migrating URL_ORIGEN if needed."""
        if not os.path.exists(Config.SOURCES_FILE):
            initial_sources = []
            # Migration: Use existing env var as default source
            default_url = Config.URL_ORIGEN
            if default_url:
                logger.info(f"Initializing sources with default URL_ORIGEN: {default_url}")
                initial_sources.append({"url": default_url, "added_at": 0})
            
            self._save_sources(initial_sources)

    def _save_sources(self, sources):
        try:
            with open(Config.SOURCES_FILE, 'w') as f:
                json.dump(sources, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save sources: {e}")

    def get_sources(self):
        """Returns list of source dicts."""
        try:
            if not os.path.exists(Config.SOURCES_FILE):
                return []
            with open(Config.SOURCES_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load sources: {e}")
            return []

    def add_source(self, url):
        """Adds a new source URL. Returns True if added, False if duplicate."""
        sources = self.get_sources()
        # Check for duplicates
        if any(s['url'] == url for s in sources):
            return False
            
        import time
        sources.append({"url": url, "added_at": time.time()})
        self._save_sources(sources)
        return True

    def delete_source(self, url):
        """Removes a source URL."""
        sources = self.get_sources()
        initial_len = len(sources)
        sources = [s for s in sources if s['url'] != url]
        
        if len(sources) < initial_len:
            self._save_sources(sources)
            return True
        return False

source_manager = SourceManager()
