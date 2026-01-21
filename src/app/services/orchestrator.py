import os
import requests
import logging

logger = logging.getLogger(__name__)

class OrchestratorService:
    def __init__(self):
        self.ip = os.getenv('ACEXY_IP', 'acestream')
        self.port = os.getenv('ACEXY_PORT', '8000')
        self.token = os.getenv('ACEXY_API_TOKEN', 'defaultpassword')
        self.base_url = f"http://{self.ip}:{self.port}"

    def is_enabled(self):
        from app.services.settings_manager import settings_manager
        return settings_manager.get("orchestrator_enabled", True)

    def get_status(self):
        if not self.is_enabled():
            return {"error": "Orchestrator integration is disabled in settings"}
        
        url = f"{self.base_url}/engines"
        headers = {
            'Authorization': f'Bearer {self.token}',
            'User-Agent': 'AceHLS-Viewer/2.0',
            'DNT': '1'
        }
        
        try:
            # Short timeout as this should be local/fast
            response = requests.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            logger.error("Orchestrator request timed out")
            return {"error": "Timeout connecting to Orchestrator"}
    def get_streams(self):
        if not self.is_enabled():
            return []

        url = f"{self.base_url}/streams?status=started"
        headers = {
            'Authorization': f'Bearer {self.token}',
            'User-Agent': 'AceHLS-Viewer/2.0',
            'DNT': '1'
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Orchestrator streams error: {e}")
            return {"error": str(e)}
