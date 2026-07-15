from unittest.mock import Mock, patch

import requests

from app.services.orchestrator import OrchestratorService


def enabled_service(response):
    session = Mock()
    session.get.return_value = response
    service = OrchestratorService(session=session)
    service.base_url = "http://orchestrator:8000"
    service.api_prefix = "/api/v1"
    service.token = "secret"
    service.timeout = 5
    service.is_enabled = Mock(return_value=True)
    return service, session


def json_response(payload):
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_engines_use_current_api_prefix_and_bearer_auth():
    service, session = enabled_service(json_response([{"container_id": "engine-1"}]))

    assert service.get_engines() == [{"container_id": "engine-1"}]
    session.get.assert_called_once_with(
        "http://orchestrator:8000/api/v1/engines",
        headers={
            "Accept": "application/json",
            "User-Agent": "AceHLS-Viewer/2.4",
            "DNT": "1",
            "Authorization": "Bearer secret",
        },
        params=None,
        timeout=5,
    )


def test_streams_request_started_filter():
    service, session = enabled_service(json_response([]))

    assert service.get_streams() == []
    assert session.get.call_args.kwargs["params"] == {"status": "started"}
    assert session.get.call_args.args[0].endswith("/api/v1/streams")


def test_overview_uses_current_management_endpoint():
    service, session = enabled_service(json_response({"status": "healthy"}))

    assert service.get_overview() == {"status": "healthy"}
    assert session.get.call_args.args[0].endswith("/api/v1/orchestrator/status")


def test_http_errors_are_structured_instead_of_raising():
    response = Mock()
    response.status_code = 404
    response.raise_for_status.side_effect = requests.HTTPError("not found", response=response)
    service, _ = enabled_service(response)

    result = service.get_engines()

    assert result["error_code"] == "http_error"
    assert result["status_code"] == 404
    assert result["endpoint"].endswith("/api/v1/engines")


def test_connection_info_never_exposes_token():
    service, _ = enabled_service(json_response([]))

    result = service.connection_info()

    assert result["authenticated"] is True
    assert "token" not in result
    assert "secret" not in str(result)


def test_disabled_streams_do_not_call_upstream():
    service, session = enabled_service(json_response([]))
    service.is_enabled = Mock(return_value=False)

    assert service.get_streams() == []
    session.get.assert_not_called()
