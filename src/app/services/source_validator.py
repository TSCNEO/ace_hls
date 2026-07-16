from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, unquote, urlparse

import requests

from app.config import Config


HASH_RE = re.compile(r"^[a-f0-9]{40}$", re.IGNORECASE)
EXTINF_ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')
UNSUPPORTED_MEDIA_SUFFIXES = (".torrent", ".acelive", ".acestream", ".acemedia")


class SourceValidationError(ValueError):
    def __init__(self, code: str, message: str, *, unreachable: bool = False):
        super().__init__(message)
        self.code = code
        self.unreachable = unreachable


@dataclass(frozen=True)
class StreamReference:
    stream_id: str
    identifier_type: str = "id"


@dataclass
class ValidationResult:
    valid: bool
    status: str
    kind: str
    normalized_url: str
    channels: list[dict[str, Any]] = field(default_factory=list)
    error_code: str | None = None
    error: str | None = None

    @property
    def channel_count(self) -> int:
        return len(self.channels)

    def public_data(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "kind": self.kind,
            "normalized_url": self.normalized_url,
            "channel_count": self.channel_count,
            "error_code": self.error_code,
            "error": self.error,
        }


def normalize_source_url(value: str) -> str:
    normalized = str(value or "").strip()
    parsed = urlparse(normalized)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise SourceValidationError("invalid_url", "La fuente debe usar una URL HTTP o HTTPS válida.")
    return normalized


def is_acestream_api_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme.lower() in {"http", "https"}
        and (parsed.hostname or "").lower() == "api.acestream.me"
        and parsed.path.rstrip("/").lower() in {"/all", "/search"}
    )


def extract_stream_reference(value: str) -> StreamReference | None:
    candidate = unquote(str(value or "").strip())
    if not candidate:
        return None

    if HASH_RE.fullmatch(candidate):
        return StreamReference(candidate.lower(), "id")

    lower = candidate.lower()
    for scheme, identifier_type in (("acestream://", "id"), ("infohash://", "infohash")):
        if lower.startswith(scheme):
            raw = candidate[len(scheme):].split("?", 1)[0].strip("/")
            return StreamReference(raw.lower(), identifier_type) if HASH_RE.fullmatch(raw) else None

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"}:
        return None

    for key, raw_value in parse_qsl(parsed.query, keep_blank_values=True):
        normalized_key = key.lower()
        decoded_value = unquote(raw_value).strip()
        if normalized_key in {"id", "content_id", "infohash"} and HASH_RE.fullmatch(decoded_value):
            identifier_type = "infohash" if normalized_key == "infohash" else "id"
            return StreamReference(decoded_value.lower(), identifier_type)
    return None


def parse_m3u(body: str, source_url: str, source_name: str) -> list[dict[str, Any]]:
    lines = body.splitlines()
    first_content = next((line.strip().lstrip("\ufeff") for line in lines if line.strip()), "")
    if not first_content.upper().startswith("#EXTM3U"):
        raise SourceValidationError("invalid_m3u_header", "La respuesta no comienza por #EXTM3U.")

    channels: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    current_extinf: str | None = None
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTINF:"):
            current_extinf = line
            continue
        if line.startswith("#") or current_extinf is None:
            continue

        reference = extract_stream_reference(line)
        if reference is None:
            current_extinf = None
            continue
        key = (reference.identifier_type, reference.stream_id)
        if key in seen:
            current_extinf = None
            continue
        seen.add(key)

        attrs = {key.lower(): value for key, value in EXTINF_ATTR_RE.findall(current_extinf)}
        name = current_extinf.rsplit(",", 1)[-1].strip().replace(" [ACESTREAM]", "") or "Unknown"
        channels.append({
            "id": reference.stream_id,
            "identifier_type": reference.identifier_type,
            "name": name,
            "logo": attrs.get("tvg-logo", ""),
            "group": attrs.get("group-title", source_name or "General"),
            "tvg_id": attrs.get("tvg-id", ""),
            "source": source_url,
        })
        current_extinf = None

    if not channels:
        media_urls = [line.strip() for line in lines if line.strip().lower().endswith(UNSUPPORTED_MEDIA_SUFFIXES)]
        if media_urls:
            raise SourceValidationError(
                "unsupported_acexy_reference",
                "La lista contiene recursos AceStream por archivo que AceXY no puede normalizar a id/infohash.",
            )
        raise SourceValidationError("no_acestream_channels", "La fuente no contiene canales AceStream compatibles.")
    return channels


def _iter_api_objects(value: Any):
    if isinstance(value, list):
        for item in value:
            yield from _iter_api_objects(item)
    elif isinstance(value, dict):
        if any(key in value for key in ("infohash", "content_id", "id")):
            yield value
        for key in ("result", "results", "items", "data"):
            if key in value:
                yield from _iter_api_objects(value[key])


def parse_acestream_api(body: str, source_url: str, source_name: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SourceValidationError("invalid_json", "La API AceStream no devolvió JSON válido.") from exc

    channels: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in _iter_api_objects(payload):
        reference = None
        for key in ("infohash", "content_id", "id"):
            value = str(item.get(key) or "").strip()
            if HASH_RE.fullmatch(value):
                reference = StreamReference(value.lower(), "infohash" if key == "infohash" else "id")
                break
        if reference is None:
            continue
        identity = (reference.identifier_type, reference.stream_id)
        if identity in seen:
            continue
        seen.add(identity)
        channels.append({
            "id": reference.stream_id,
            "identifier_type": reference.identifier_type,
            "name": str(item.get("name") or item.get("title") or reference.stream_id),
            "logo": str(item.get("logo") or item.get("icon") or ""),
            "group": str(item.get("group") or item.get("category") or source_name or "AceStream API"),
            "tvg_id": str(item.get("tvg_id") or item.get("tvg-id") or ""),
            "source": source_url,
        })

    if not channels:
        raise SourceValidationError("no_acestream_channels", "La API no contiene ningún infohash o content_id válido.")
    return channels


class SourceValidator:
    def __init__(self, session=requests):
        self.session = session

    def validate(self, url: str, source_name: str = "") -> ValidationResult:
        kind = "unknown"
        try:
            normalized_url = normalize_source_url(url)
            kind = "acestream_api" if is_acestream_api_url(normalized_url) else "m3u"
            body = self._fetch(normalized_url)
            channels = (
                parse_acestream_api(body, normalized_url, source_name)
                if kind == "acestream_api"
                else parse_m3u(body, normalized_url, source_name)
            )
            return ValidationResult(True, "valid", kind, normalized_url, channels)
        except SourceValidationError as exc:
            return ValidationResult(
                False,
                "unreachable" if exc.unreachable else "invalid",
                kind,
                str(url or "").strip(),
                error_code=exc.code,
                error=str(exc),
            )

    def _fetch(self, url: str) -> str:
        response = None
        try:
            response = self.session.get(
                url,
                timeout=(Config.SOURCE_CONNECT_TIMEOUT, Config.SOURCE_READ_TIMEOUT),
                verify=Config.SOURCE_TLS_VERIFY,
                allow_redirects=True,
                stream=True,
                headers={"User-Agent": "AceHLS-SourceValidator/2.5"},
            )
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > Config.SOURCE_MAX_BYTES:
                    raise SourceValidationError("response_too_large", "La fuente supera el límite de 10 MiB.")
                chunks.append(chunk)
            encoding = response.encoding or "utf-8"
            return b"".join(chunks).decode(encoding, "replace")
        except SourceValidationError:
            raise
        except requests.RequestException as exc:
            raise SourceValidationError("source_unreachable", f"No se pudo descargar la fuente: {exc}", unreachable=True) from exc
        finally:
            if response is not None:
                response.close()


source_validator = SourceValidator()
