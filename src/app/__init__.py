import logging
import os
from flask import Flask

from app.config import Config
from app.services.channel_manager import channel_manager
from app.services.refresh_scheduler import playlist_refresh_scheduler
from app.services.source_manager import SourceRegistryError, source_manager

def create_app():
    app = Flask(__name__, static_url_path='')
    
    # Configure logging
    log_file = os.path.join(Config.DATA_DIR, 'app.log')
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file)
        ]
    )
    app.logger.setLevel(logging.INFO)

    # Upgrade the persistent source registry before serving requests. Migration
    # is idempotent and never overwrites corrupt or future schemas.
    try:
        source_manager.get_sources()
    except SourceRegistryError as exc:
        app.logger.error("Source registry unavailable; cached channels remain usable: %s", exc)

    # Initial update
    # But useful to have *some* data.
    try:
        if not path_exists_check(Config.JSON_FILE):
             app.logger.info("Performing initial channel update...")
             channel_manager.update_channels()
    except Exception as e:
         app.logger.error(f"Failed initial channel update: {e}")

    from app.routes import main_bp
    app.register_blueprint(main_bp)

    # Independent from WebUI traffic; cross-process locking prevents duplicate
    # refreshes if Gunicorn is later configured with multiple workers.
    playlist_refresh_scheduler.start()

    return app

def path_exists_check(path):
    return os.path.exists(path)
