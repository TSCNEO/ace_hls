from urllib.parse import urlencode, urlsplit

from app.config import Config


LOCAL_INDICATORS = {"127.0.0.1", "localhost", "0.0.0.0", "acexy", "acestream", "orchestrator"}


def normalize_public_endpoint(value):
    endpoint = str(value or "").strip().rstrip("/")
    if not endpoint:
        return ""
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("El endpoint público debe ser una URL HTTP o HTTPS válida.")
    if parsed.query or parsed.fragment:
        raise ValueError("El endpoint público no puede contener query ni fragmento.")
    return endpoint


def _request_hostname(request_host):
    parsed = urlsplit(f"//{request_host}")
    hostname = parsed.hostname or str(request_host).split(":", 1)[0]
    return f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname


def get_stream_public_base(request_host):
    from app.services.settings_manager import settings_manager

    settings = settings_manager.get_all()
    configured = settings.get("stream_public_endpoint") or Config.STREAM_PUBLIC_ENDPOINT
    if configured:
        return normalize_public_endpoint(configured)

    target_host = Config.STREAM_PROXY_HOST
    if target_host.lower() in LOCAL_INDICATORS:
        target_host = _request_hostname(request_host)
    elif ":" in target_host and not target_host.startswith("["):
        target_host = f"[{target_host}]"
    return f"http://{target_host}:{Config.STREAM_PUBLIC_PORT}"


def get_stream_url_for_client(request_host, ace_id=None, identifier_type="id"):
    from app.services.settings_manager import settings_manager

    base_url = f"{get_stream_public_base(request_host)}/ace/getstream"
    params = {}
    if ace_id:
        query_key = "infohash" if identifier_type == "infohash" else "id"
        params[query_key] = ace_id

    # Orchestrator management authentication is Bearer-only and must never be
    # embedded in playback URLs. Query tokens remain an AceXY compatibility aid.
    if Config.STREAM_BACKEND == "acexy":
        public_token = settings_manager.get("stream_public_token", "")
        if public_token:
            params["token"] = public_token

    return f"{base_url}?{urlencode(params)}" if params else base_url


def get_stream_proxy_host_for_server():
    internal_host = Config.STREAM_PROXY_HOST
    if internal_host in ['127.0.0.1', 'localhost', '0.0.0.0']:
        internal_host = Config.STREAM_BACKEND
    return internal_host
