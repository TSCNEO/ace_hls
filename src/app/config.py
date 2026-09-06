import os


def _env_with_legacy(primary: str, legacy: str, default: str | None = None) -> str | None:
    value = os.environ.get(primary)
    if value is not None:
        return value
    return os.environ.get(legacy, default)


def _stream_target_value(
    primary: str,
    orchestrator: str,
    legacy: str,
    backend: str,
    default: str,
) -> str:
    """Resolve a stream target while preserving v2.x aliases."""
    if primary in os.environ:
        return os.environ[primary]
    if backend == "orchestrator":
        return os.environ.get(orchestrator, default)
    return os.environ.get(legacy, default)


def _url_host(host: str) -> str:
    """Add brackets to a raw IPv6 host before placing it in a URL."""
    normalized = host.strip()
    if normalized.startswith("[") and normalized.endswith("]"):
        return normalized
    return f"[{normalized}]" if ":" in normalized else normalized


def _validated_port(name: str, value: str | int) -> str:
    """Return a validated TCP port as text for URL composition."""
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return str(port)


class Config:
    # AceHLS Settings
    ACE_HLS_PORT = int(os.environ.get("ACE_HLS_PORT", 8088))
    CACHE_DURATION = int(os.environ.get("CACHE_DURATION", 300))
    PLAYLIST_REFRESH_INTERVAL = max(60, int(os.environ.get("PLAYLIST_REFRESH_INTERVAL", 900)))
    FFMPEG_RW_TIMEOUT = max(5, int(os.environ.get("FFMPEG_RW_TIMEOUT", 60)))
    HLS_IDLE_TIMEOUT = max(60, int(os.environ.get("HLS_IDLE_TIMEOUT", 120)))
    SOURCE_CONNECT_TIMEOUT = max(1, int(os.environ.get("SOURCE_CONNECT_TIMEOUT", 8)))
    SOURCE_READ_TIMEOUT = max(1, int(os.environ.get("SOURCE_READ_TIMEOUT", 30)))
    SOURCE_MAX_BYTES = max(1024, int(os.environ.get("SOURCE_MAX_BYTES", 10 * 1024 * 1024)))
    SOURCE_TLS_VERIFY = os.environ.get("SOURCE_TLS_VERIFY", "false").lower() == "true"
    SOURCE_REFRESH_WORKERS = max(1, int(os.environ.get("SOURCE_REFRESH_WORKERS", 4)))
    # Use absolute path to avoid confusion with send_from_directory
    DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
    
    # External Resources
    URL_ORIGEN = os.environ.get("URL_ORIGEN", "")
    
    # Streaming proxy. ACEXY_* remain aliases throughout the v2.x series.
    STREAM_BACKEND_CONFIGURED = "STREAM_BACKEND" in os.environ
    STREAM_BACKEND = os.environ.get("STREAM_BACKEND", "acexy").strip().lower()
    if STREAM_BACKEND not in {"acexy", "orchestrator"}:
        raise ValueError("STREAM_BACKEND must be 'acexy' or 'orchestrator'")

    ORCHESTRATOR_MODE = os.environ.get("ORCHESTRATOR_MODE", "local").strip().lower()
    if ORCHESTRATOR_MODE not in {"local", "remote"}:
        raise ValueError("ORCHESTRATOR_MODE must be 'local' or 'remote'")
    ORCHESTRATOR_HOST = os.environ.get("ORCHESTRATOR_HOST", "orchestrator").strip()
    if not ORCHESTRATOR_HOST:
        raise ValueError("ORCHESTRATOR_HOST cannot be empty")
    ORCHESTRATOR_PORT = _validated_port(
        "ORCHESTRATOR_PORT",
        os.environ.get("ORCHESTRATOR_PORT", "8000").strip(),
    )

    STREAM_PROXY_HOST = _stream_target_value(
        "STREAM_PROXY_HOST",
        "ORCHESTRATOR_HOST",
        "ACEXY_IP",
        STREAM_BACKEND,
        ORCHESTRATOR_HOST if STREAM_BACKEND == "orchestrator" else "127.0.0.1",
    ).strip()
    if not STREAM_PROXY_HOST:
        raise ValueError("STREAM_PROXY_HOST cannot be empty")
    STREAM_PROXY_PORT = _validated_port(
        "STREAM_PROXY_PORT",
        _stream_target_value(
            "STREAM_PROXY_PORT",
            "ORCHESTRATOR_PORT",
            "ACEXY_PORT",
            STREAM_BACKEND,
            ORCHESTRATOR_PORT if STREAM_BACKEND == "orchestrator" else "8080",
        ),
    )
    STREAM_PUBLIC_PORT = int(
        _validated_port(
            "STREAM_PUBLIC_PORT",
            os.environ.get("STREAM_PUBLIC_PORT", STREAM_PROXY_PORT),
        )
    )
    STREAM_PUBLIC_ENDPOINT = _env_with_legacy(
        "STREAM_PUBLIC_ENDPOINT",
        "ACEXY_PUBLIC_ENDPOINT",
        "",
    )

    ACEXY_IP = STREAM_PROXY_HOST
    ACEXY_PORT = STREAM_PROXY_PORT
    ACEXY_API_TOKEN = os.environ.get("ACEXY_API_TOKEN", "defaultpassword")

    # AceStream Orchestrator management API (Go unified API uses /api/v1).
    ORCHESTRATOR_URL = (
        os.environ.get("ORCHESTRATOR_URL")
        or f"http://{_url_host(ORCHESTRATOR_HOST)}:{ORCHESTRATOR_PORT}"
    ).rstrip('/')
    ORCHESTRATOR_API_PREFIX = os.environ.get("ORCHESTRATOR_API_PREFIX", "/api/v1").strip()
    if ORCHESTRATOR_API_PREFIX and not ORCHESTRATOR_API_PREFIX.startswith('/'):
        ORCHESTRATOR_API_PREFIX = f"/{ORCHESTRATOR_API_PREFIX}"
    ORCHESTRATOR_API_PREFIX = ORCHESTRATOR_API_PREFIX.rstrip('/')
    ORCHESTRATOR_API_TOKEN = os.environ.get("ORCHESTRATOR_API_TOKEN", ACEXY_API_TOKEN)
    ORCHESTRATOR_TIMEOUT = max(1.0, float(os.environ.get("ORCHESTRATOR_TIMEOUT", 5)))

    # Transcoding
    ENABLE_TRANSCODE = os.environ.get("ENABLE_TRANSCODE", "false").lower() == "true"
    TRANSCODE_720P_BITRATE = os.environ.get("TRANSCODE_720P_BITRATE", "2500k")
    TRANSCODE_480P_BITRATE = os.environ.get("TRANSCODE_480P_BITRATE", "1000k")
    TRANSCODE_COMPAT_CRF = os.environ.get("TRANSCODE_COMPAT_CRF", "23")

    # Optional endpoint used in playlists consumed outside the Docker network.
    ACEXY_PUBLIC_ENDPOINT = STREAM_PUBLIC_ENDPOINT or None
    ACEXY_PUBLIC_TOKEN = os.environ.get("ACEXY_PUBLIC_TOKEN", None)

    # Paths
    JSON_FILE = os.path.join(DATA_DIR, "channels.json")
    SOURCE_CACHE_DIR = os.path.join(DATA_DIR, "source_cache")
    SOURCES_FILE = os.path.join(DATA_DIR, "sources.json")
    CUSTOM_CHANNELS_FILE = os.path.join(DATA_DIR, "custom_channels.json")
    M3U_FILE = os.path.join(DATA_DIR, "ace_hls.m3u")
    HLS_DIR = os.path.join(DATA_DIR, "hls")

    # MylinkPaste DoH resolver settings
    MYLINKPASTE_DOMAIN_SUFFIX = os.environ.get("MYLINKPASTE_DOMAIN_SUFFIX", "elcano.top").strip().lstrip(".")
    MYLINKPASTE_DOH_PRIMARY = os.environ.get("MYLINKPASTE_DOH_PRIMARY", "https://dns.google/resolve").strip()
    MYLINKPASTE_DOH_BACKUP = os.environ.get("MYLINKPASTE_DOH_BACKUP", "https://cloudflare-dns.com/dns-query").strip()
