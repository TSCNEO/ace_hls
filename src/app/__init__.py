import logging
from flask import Flask

from app.config import Config
from app.services.channel_manager import channel_manager

def create_app():
    app = Flask(__name__, static_url_path='')
    
    # Configure logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    app.logger.setLevel(logging.INFO)

    # Scheduler removed as per user request (Lazy loading preferred)
    
    # Initial update on startup (optional, can be removed if we want pure lazy loading)
    # But useful to have *some* data.
    try:
        if not path_exists_check(Config.JSON_FILE):
             app.logger.info("Performing initial channel update...")
             channel_manager.update_channels()
    except:
        pass

    from app.routes import main_bp
    app.register_blueprint(main_bp)

    return app

def path_exists_check(path):
    import os
    return os.path.exists(path)
