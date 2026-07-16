import logging

import requests

from app.config import Config


logger = logging.getLogger(__name__)


class OrchestratorService:
    def __init__(self, session=None):
        self.base_url = Config.ORCHESTRATOR_URL
        self.api_prefix = Config.ORCHESTRATOR_API_PREFIX
        self.token = Config.ORCHESTRATOR_API_TOKEN
        self.timeout = Config.ORCHESTRATOR_TIMEOUT
        self.session = session or requests.Session()

    def is_enabled(self):
        from app.services.settings_manager import settings_manager

        if Config.STREAM_BACKEND_CONFIGURED:
            return Config.STREAM_BACKEND == "orchestrator"
        return settings_manager.get("orchestrator_enabled", False)

    def connection_info(self, request_host=None):
        result = {
            "enabled": self.is_enabled(),
            "backend": Config.STREAM_BACKEND,
            "deployment": Config.ORCHESTRATOR_MODE,
            "base_url": self.base_url,
            "orchestrator_host": Config.ORCHESTRATOR_HOST,
            "orchestrator_port": int(Config.ORCHESTRATOR_PORT),
            "stream_proxy_host": Config.STREAM_PROXY_HOST,
            "stream_proxy_port": int(Config.STREAM_PROXY_PORT),
            "stream_public_port": Config.STREAM_PUBLIC_PORT,
            "api_prefix": self.api_prefix,
            "authenticated": bool(self.token),
            "managed_by_environment": Config.STREAM_BACKEND_CONFIGURED,
        }
        if request_host:
            from app.utils import get_stream_public_base

            public_base = get_stream_public_base(request_host)
            result["public_endpoint"] = public_base
            if Config.STREAM_BACKEND == "orchestrator":
                result["panel_url"] = f"{public_base}/panel"
        return result

    def get_engines(self):
        if not self.is_enabled():
            return self._disabled_error()
        return self._get_json("/engines", expected_type=list)

    def get_status(self):
        """Backward-compatible alias used by the existing AceHLS frontend."""
        return self.get_engines()

    def get_streams(self):
        if not self.is_enabled():
            return []
        return self._get_json(
            "/streams",
            params={"status": "started"},
            expected_type=list,
        )

    def get_overview(self):
        if not self.is_enabled():
            return self._disabled_error()
        return self._get_json("/orchestrator/status", expected_type=dict)

    def get_dashboard_metrics(self, window_seconds=900):
        if not self.is_enabled():
            return self._disabled_error()
        window_seconds = max(60, min(int(window_seconds), 604800))
        return self._get_json(
            "/metrics/dashboard",
            params={"window_seconds": window_seconds},
            expected_type=dict,
        )

    def _endpoint(self, path):
        return f"{self.base_url}{self.api_prefix}{path}"

    def _headers(self):
        headers = {
            "Accept": "application/json",
            "User-Agent": "AceHLS-Viewer/2.6",
            "DNT": "1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get_json(self, path, params=None, expected_type=None):
        endpoint = self._endpoint(path)
        try:
            response = self.session.get(
                endpoint,
                headers=self._headers(),
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout:
            return self._error("timeout", endpoint)
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            return self._error("http_error", endpoint, str(exc), status_code)
        except requests.JSONDecodeError as exc:
            return self._error("invalid_json", endpoint, str(exc))
        except requests.RequestException as exc:
            return self._error("connection_error", endpoint, str(exc))
        except ValueError as exc:
            return self._error("invalid_json", endpoint, str(exc))

        if expected_type is not None and not isinstance(payload, expected_type):
            return self._error(
                "invalid_payload",
                endpoint,
                f"expected {expected_type.__name__}, got {type(payload).__name__}",
            )
        return payload

    def _disabled_error(self):
        return {
            "error": "Orchestrator integration is disabled in settings",
            "error_code": "disabled",
        }

    def _error(self, code, endpoint, detail=None, status_code=None):
        result = {
            "error": f"Orchestrator request failed: {code}",
            "error_code": code,
            "endpoint": endpoint,
        }
        if detail:
            result["detail"] = detail
        if status_code is not None:
            result["status_code"] = status_code
        logger.error("Orchestrator API error: %s", result)
        return result
