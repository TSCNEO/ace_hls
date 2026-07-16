import json
from unittest.mock import Mock, patch

import pytest
from flask import Flask

from app import routes
from app.config import Config, _env_with_legacy
from app.services.orchestrator import OrchestratorService
from app.services.settings_manager import SettingsManager
from app.utils import (
    get_stream_public_base,
    get_stream_url_for_client,
    normalize_public_endpoint,
)


def test_new_environment_name_has_priority(monkeypatch):
    monkeypatch.setenv("STREAM_PROXY_HOST", "orchestrator")
    monkeypatch.setenv("ACEXY_IP", "legacy-acexy")

    assert _env_with_legacy("STREAM_PROXY_HOST", "ACEXY_IP") == "orchestrator"


def test_legacy_environment_name_remains_a_fallback(monkeypatch):
    monkeypatch.delenv("STREAM_PROXY_HOST", raising=False)
    monkeypatch.setenv("ACEXY_IP", "legacy-acexy")

    assert _env_with_legacy("STREAM_PROXY_HOST", "ACEXY_IP") == "legacy-acexy"


@pytest.mark.parametrize(
    ("request_host", "expected"),
    [
        ("192.168.1.20:8088", "http://192.168.1.20:8000"),
        ("ace.internal:8088", "http://ace.internal:8000"),
        ("[fd00::20]:8088", "http://[fd00::20]:8000"),
    ],
)
def test_public_endpoint_is_derived_from_request_host(request_host, expected):
    with patch.multiple(
        Config,
        STREAM_PROXY_HOST="orchestrator",
        STREAM_PUBLIC_PORT=8000,
        STREAM_PUBLIC_ENDPOINT="",
    ):
        with patch("app.services.settings_manager.settings_manager.get_all", return_value={}):
            assert get_stream_public_base(request_host) == expected


def test_explicit_public_endpoint_has_absolute_priority():
    settings = {"stream_public_endpoint": "https://streams.internal/proxy/"}
    with patch.multiple(Config, STREAM_PROXY_HOST="orchestrator", STREAM_PUBLIC_ENDPOINT=""):
        with patch("app.services.settings_manager.settings_manager.get_all", return_value=settings):
            assert get_stream_public_base("192.168.1.20:8088") == "https://streams.internal/proxy"


def test_orchestrator_playback_url_never_contains_management_token():
    settings = {"stream_public_token": "must-not-leak"}
    with patch.multiple(
        Config,
        STREAM_BACKEND="orchestrator",
        STREAM_PROXY_HOST="orchestrator",
        STREAM_PUBLIC_PORT=8000,
        STREAM_PUBLIC_ENDPOINT="",
    ):
        with patch("app.services.settings_manager.settings_manager.get_all", return_value=settings):
            url = get_stream_url_for_client("10.0.0.4:8088", "a" * 40, "infohash")

    assert url == f"http://10.0.0.4:8000/ace/getstream?infohash={'a' * 40}"
    assert "must-not-leak" not in url


def test_acexy_playback_keeps_legacy_query_token():
    settings = {"stream_public_token": "legacy-token"}
    with patch.multiple(
        Config,
        STREAM_BACKEND="acexy",
        STREAM_PROXY_HOST="acexy",
        STREAM_PUBLIC_PORT=8080,
        STREAM_PUBLIC_ENDPOINT="",
    ):
        with patch("app.services.settings_manager.settings_manager.get_all", return_value=settings):
            url = get_stream_url_for_client("10.0.0.4:8088", "channel-id")

    assert url == "http://10.0.0.4:8080/ace/getstream?id=channel-id&token=legacy-token"


def test_settings_file_migrates_legacy_public_keys_atomically(tmp_path):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps(
            {
                "acexy_public_endpoint": "https://streams.internal/",
                "acexy_public_token": "legacy-token",
                "orchestrator_enabled": True,
            }
        ),
        encoding="utf-8",
    )

    with patch.object(Config, "DATA_DIR", str(tmp_path)):
        manager = SettingsManager()
        settings = manager.get_all()

    assert settings["stream_public_endpoint"] == "https://streams.internal"
    assert settings["stream_public_token"] == "legacy-token"
    assert settings["orchestrator_enabled"] is True
    assert "acexy_public_endpoint" not in settings
    assert "acexy_public_token" not in settings
    assert json.loads(settings_file.read_text(encoding="utf-8")) == settings


def test_invalid_public_endpoint_is_rejected():
    with pytest.raises(ValueError):
        normalize_public_endpoint("javascript:alert(1)")


def test_backend_environment_controls_orchestrator_activation():
    service = OrchestratorService()
    with patch.multiple(Config, STREAM_BACKEND_CONFIGURED=True, STREAM_BACKEND="orchestrator"):
        assert service.is_enabled() is True
    with patch.multiple(Config, STREAM_BACKEND_CONFIGURED=True, STREAM_BACKEND="acexy"):
        assert service.is_enabled() is False


def test_connection_info_contains_no_token():
    service = OrchestratorService()
    service.token = "super-secret"
    with patch.multiple(
        Config,
        STREAM_BACKEND_CONFIGURED=True,
        STREAM_BACKEND="orchestrator",
        STREAM_PROXY_HOST="orchestrator",
        STREAM_PROXY_PORT="8000",
        STREAM_PUBLIC_PORT=8000,
        STREAM_PUBLIC_ENDPOINT="",
    ):
        with patch("app.services.settings_manager.settings_manager.get_all", return_value={}):
            result = service.connection_info("192.168.1.30:8088")

    assert result["public_endpoint"] == "http://192.168.1.30:8000"
    assert result["panel_url"] == "http://192.168.1.30:8000/panel"
    assert result["authenticated"] is True
    assert "super-secret" not in str(result)


def test_health_uses_the_orchestrator_proxy_health_endpoint():
    app = Flask(__name__)
    upstream = Mock(status_code=200)
    with app.test_request_context("/health"):
        with patch.multiple(
            Config,
            STREAM_BACKEND="orchestrator",
            STREAM_PROXY_HOST="orchestrator",
            STREAM_PROXY_PORT="8000",
        ):
            with patch.object(routes.shutil, "disk_usage", return_value=(1024**3, 0, 1024**3)):
                with patch.object(routes.requests, "get", return_value=upstream) as request_get:
                    response, status_code = routes.health_check()

    payload = response.get_json()
    request_get.assert_called_once_with("http://orchestrator:8000/proxy/health", timeout=2)
    assert status_code == 200
    assert payload["components"]["stream_proxy"]["backend"] == "orchestrator"
    assert payload["components"]["acexy"] == payload["components"]["stream_proxy"]
