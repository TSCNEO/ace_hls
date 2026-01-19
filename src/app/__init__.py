import logging
import os
from flask import Flask

from app.config import Config
from app.services.channel_manager import channel_manager

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

    # Scheduler removed as per user request (Lazy loading preferred)
    
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

    return app

def path_exists_check(path):
    import os
    return os.path.exists(path)
