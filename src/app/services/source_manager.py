from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
import time
import uuid
from copy import deepcopy
from urllib.parse import urlparse

from app.config import Config
from app.services.storage import atomic_write_json


logger = logging.getLogger(__name__)
SOURCE_SCHEMA_VERSION = 2


class SourceRegistryError(RuntimeError):
    code = "source_registry_error"


class UnsupportedSourceSchema(SourceRegistryError):
    code = "unsupported_source_schema"


class SourceNotFound(SourceRegistryError):
    code = "source_not_found"


class DuplicateSource(SourceRegistryError):
    code = "duplicate_source"


class SourceManager:
    def __init__(self):
        self._thread_lock = threading.RLock()

    @property
    def _lock_file(self) -> str:
        return f"{Config.SOURCES_FILE}.lock"

    @property
    def _backup_file(self) -> str:
        return os.path.join(Config.DATA_DIR, "sources.v1.backup.json")

    def _default_document(self) -> dict:
        sources = []
        if Config.URL_ORIGEN:
            now = time.time()
            sources.append(self._new_source(Config.URL_ORIGEN, self._name_for_url(Config.URL_ORIGEN, []), now))
        return {"schema_version": SOURCE_SCHEMA_VERSION, "sources": sources}

    def _new_source(self, url: str, name: str, now: float | None = None, *, deterministic: bool = False) -> dict:
        timestamp = time.time() if now is None else now
        source_uuid = uuid.uuid5(uuid.NAMESPACE_URL, url).hex if deterministic else uuid.uuid4().hex
        return {
            "id": f"src-{source_uuid}",
            "name": name.strip(),
            "url": url.strip(),
            "kind": "m3u",
            "enabled": True,
            "created_at": timestamp,
            "updated_at": timestamp,
            "validation": {
                "status": "pending",
                "checked_at": None,
                "channel_count": 0,
                "error": None,
            },
            "refresh": {
                "last_success_at": None,
                "using_cache": False,
                "last_error": None,
            },
        }

    def _name_for_url(self, url: str, existing_names: list[str]) -> str:
        host = (urlparse(url).hostname or "Fuente").strip() or "Fuente"
        base = host
        suffix = 2
        lowered = {name.lower() for name in existing_names}
        while host.lower() in lowered:
            host = f"{base} {suffix}"
            suffix += 1
        return host

    def _migrate_v1(self, legacy: list) -> dict:
        if not os.path.exists(self._backup_file):
            atomic_write_json(self._backup_file, legacy)

        migrated = []
        names: list[str] = []
        for item in legacy:
            if not isinstance(item, dict) or not str(item.get("url") or "").strip():
                continue
            url = str(item["url"]).strip()
            name = self._name_for_url(url, names)
            names.append(name)
            created_at = item.get("added_at") if isinstance(item.get("added_at"), (int, float)) else time.time()
            migrated.append(self._new_source(url, name, created_at, deterministic=True))

        document = {"schema_version": SOURCE_SCHEMA_VERSION, "sources": migrated}
        atomic_write_json(Config.SOURCES_FILE, document)
        logger.info("Migrated %s legacy sources to schema v2.", len(migrated))
        return document

    def _read_locked(self) -> dict:
        if not os.path.exists(Config.SOURCES_FILE):
            document = self._default_document()
            atomic_write_json(Config.SOURCES_FILE, document)
            return document

        try:
            with open(Config.SOURCES_FILE, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise SourceRegistryError("sources.json contiene JSON corrupto; no se ha sobrescrito.") from exc
        if isinstance(payload, list):
            return self._migrate_v1(payload)
        if not isinstance(payload, dict):
            raise SourceRegistryError("El registro de fuentes no contiene un objeto o lista válido.")
        version = payload.get("schema_version")
        if version != SOURCE_SCHEMA_VERSION:
            if isinstance(version, int) and version > SOURCE_SCHEMA_VERSION:
                raise UnsupportedSourceSchema(
                    f"sources.json usa el esquema futuro v{version}; esta versión solo admite v{SOURCE_SCHEMA_VERSION}."
                )
            raise SourceRegistryError(f"Versión de sources.json no compatible: {version!r}.")
        if not isinstance(payload.get("sources"), list):
            raise SourceRegistryError("sources.json no contiene una lista sources válida.")
        return payload

    def _with_document(self, callback=None):
        os.makedirs(Config.DATA_DIR, exist_ok=True)
        with self._thread_lock:
            with open(self._lock_file, "a+", encoding="utf-8") as process_lock:
                fcntl.flock(process_lock.fileno(), fcntl.LOCK_EX)
                document = self._read_locked()
                result = callback(document) if callback else None
                if callback:
                    atomic_write_json(Config.SOURCES_FILE, document)
                return deepcopy(document), result

    def get_document(self) -> dict:
        document, _ = self._with_document()
        return document

    def get_sources(self) -> list[dict]:
        return self.get_document()["sources"]

    def get_source(self, source_id: str) -> dict:
        for source in self.get_sources():
            if source.get("id") == source_id:
                return source
        raise SourceNotFound(f"No existe la fuente {source_id}.")

    @staticmethod
    def apply_validation(source: dict, validation) -> None:
        source["kind"] = validation.kind if validation.kind != "unknown" else source.get("kind", "m3u")
        source["validation"] = {
            "status": validation.status,
            "checked_at": time.time(),
            "channel_count": validation.channel_count,
            "error": validation.error,
        }

    def create_source(self, *, name: str, url: str, validation, allow_invalid_disabled: bool = False) -> dict:
        clean_name = str(name or "").strip()
        clean_url = str(url or "").strip()
        if not clean_name:
            raise SourceRegistryError("El nombre de la fuente es obligatorio.")
        if not validation.valid and not allow_invalid_disabled:
            raise SourceRegistryError(validation.error or "La fuente no es válida.")

        def mutate(document):
            sources = document["sources"]
            if any(source.get("url", "").lower() == clean_url.lower() for source in sources):
                raise DuplicateSource("Ya existe una fuente con esa URL.")
            source = self._new_source(clean_url, clean_name)
            source["enabled"] = bool(validation.valid)
            self.apply_validation(source, validation)
            sources.append(source)
            return source

        _, source = self._with_document(mutate)
        return deepcopy(source)

    def update_source(
        self,
        source_id: str,
        changes: dict,
        *,
        validation=None,
        allow_invalid_disabled: bool = False,
    ) -> dict:
        def mutate(document):
            sources = document["sources"]
            source = next((item for item in sources if item.get("id") == source_id), None)
            if source is None:
                raise SourceNotFound(f"No existe la fuente {source_id}.")

            next_url = str(changes.get("url", source["url"]) or "").strip()
            next_name = str(changes.get("name", source["name"]) or "").strip()
            if not next_name:
                raise SourceRegistryError("El nombre de la fuente es obligatorio.")
            if any(
                item.get("id") != source_id and item.get("url", "").lower() == next_url.lower()
                for item in sources
            ):
                raise DuplicateSource("Ya existe una fuente con esa URL.")

            wants_enabled = bool(changes.get("enabled", source.get("enabled", True)))
            needs_validation = next_url != source["url"] or (wants_enabled and not source.get("enabled"))
            if needs_validation and validation is None:
                raise SourceRegistryError("La fuente debe validarse antes de cambiar la URL o activarse.")
            if validation is not None and not validation.valid and not allow_invalid_disabled:
                raise SourceRegistryError(validation.error or "La fuente no es válida.")

            source["name"] = next_name
            source["url"] = next_url
            source["enabled"] = wants_enabled
            if validation is not None:
                self.apply_validation(source, validation)
                if not validation.valid:
                    source["enabled"] = False
            source["updated_at"] = time.time()
            return source

        _, source = self._with_document(mutate)
        return deepcopy(source)

    def record_refresh(self, source_id: str, *, validation=None, success=False, using_cache=False, error=None) -> None:
        def mutate(document):
            source = next((item for item in document["sources"] if item.get("id") == source_id), None)
            if source is None:
                return
            if validation is not None:
                self.apply_validation(source, validation)
            source["refresh"] = {
                "last_success_at": time.time() if success else source.get("refresh", {}).get("last_success_at"),
                "using_cache": bool(using_cache),
                "last_error": error,
            }
            source["updated_at"] = time.time()

        self._with_document(mutate)

    def delete_source(self, source_id: str) -> dict:
        def mutate(document):
            for index, source in enumerate(document["sources"]):
                if source.get("id") == source_id:
                    return document["sources"].pop(index)
            raise SourceNotFound(f"No existe la fuente {source_id}.")

        _, removed = self._with_document(mutate)
        return deepcopy(removed)

    def delete_source_by_url(self, url: str) -> dict:
        target = str(url or "").strip().lower()
        for source in self.get_sources():
            if source.get("url", "").lower() == target:
                return self.delete_source(source["id"])
        raise SourceNotFound("No existe una fuente con esa URL.")


source_manager = SourceManager()
