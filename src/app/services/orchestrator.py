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

    def get_status(self):
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
