from __future__ import annotations

import fcntl
import json
import os
import threading
import time
import uuid
from copy import deepcopy

from app.config import Config
from app.services.source_validator import extract_stream_reference
from app.services.storage import atomic_write_json


CUSTOM_SCHEMA_VERSION = 1


class CustomChannelError(RuntimeError):
    code = "custom_channel_error"


class CustomChannelNotFound(CustomChannelError):
    code = "custom_channel_not_found"


class DuplicateCustomChannel(CustomChannelError):
    code = "duplicate_custom_channel"


class CustomChannelManager:
    def __init__(self):
        self._thread_lock = threading.RLock()

    @property
    def _lock_file(self) -> str:
        return f"{Config.CUSTOM_CHANNELS_FILE}.lock"

    def _read_locked(self) -> dict:
        if not os.path.exists(Config.CUSTOM_CHANNELS_FILE):
            document = {"schema_version": CUSTOM_SCHEMA_VERSION, "channels": []}
            atomic_write_json(Config.CUSTOM_CHANNELS_FILE, document)
            return document
        with open(Config.CUSTOM_CHANNELS_FILE, "r", encoding="utf-8") as handle:
            document = json.load(handle)
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != CUSTOM_SCHEMA_VERSION
            or not isinstance(document.get("channels"), list)
        ):
            raise CustomChannelError("custom_channels.json no usa un esquema compatible.")
        return document

    def _with_document(self, callback=None):
        os.makedirs(Config.DATA_DIR, exist_ok=True)
        with self._thread_lock:
            with open(self._lock_file, "a+", encoding="utf-8") as process_lock:
                fcntl.flock(process_lock.fileno(), fcntl.LOCK_EX)
                document = self._read_locked()
                result = callback(document) if callback else None
                if callback:
                    atomic_write_json(Config.CUSTOM_CHANNELS_FILE, document)
                return deepcopy(document), result

    def get_channels(self) -> list[dict]:
        document, _ = self._with_document()
        return document["channels"]

    def _normalize(self, payload: dict, existing: dict | None = None) -> dict:
        name = str(payload.get("name", existing.get("name") if existing else "") or "").strip()
        raw_reference = payload.get("stream_id", payload.get("content_id", ""))
        if not raw_reference and existing:
            raw_reference = existing["stream_id"]
        reference = extract_stream_reference(str(raw_reference or ""))
        if not name:
            raise CustomChannelError("El nombre del canal es obligatorio.")
        if reference is None:
            raise CustomChannelError("El identificador AceStream no es válido.")
        now = time.time()
        return {
            "id": existing["id"] if existing else f"custom-{uuid.uuid4().hex}",
            "name": name,
            "stream_id": reference.stream_id,
            "identifier_type": reference.identifier_type,
            "group": str(payload.get("group", existing.get("group") if existing else "Personalizados") or "Personalizados").strip(),
            "logo": str(payload.get("logo", existing.get("logo") if existing else "") or "").strip(),
            "tvg_id": str(payload.get("tvg_id", existing.get("tvg_id") if existing else "") or "").strip(),
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }

    @staticmethod
    def _ensure_unique(channels: list[dict], candidate: dict) -> None:
        for channel in channels:
            if channel["id"] == candidate["id"]:
                continue
            if (
                channel.get("identifier_type", "id") == candidate["identifier_type"]
                and channel.get("stream_id") == candidate["stream_id"]
            ):
                raise DuplicateCustomChannel("Ya existe un canal personalizado con ese identificador.")

    def create(self, payload: dict) -> dict:
        def mutate(document):
            channel = self._normalize(payload)
            self._ensure_unique(document["channels"], channel)
            document["channels"].append(channel)
            return channel

        _, channel = self._with_document(mutate)
        return deepcopy(channel)

    def update(self, channel_id: str, payload: dict) -> dict:
        def mutate(document):
            existing = next((item for item in document["channels"] if item.get("id") == channel_id), None)
            if existing is None:
                raise CustomChannelNotFound(f"No existe el canal {channel_id}.")
            updated = self._normalize(payload, existing)
            self._ensure_unique(document["channels"], updated)
            existing.clear()
            existing.update(updated)
            return existing

        _, channel = self._with_document(mutate)
        return deepcopy(channel)

    def delete(self, channel_id: str) -> dict:
        def mutate(document):
            for index, channel in enumerate(document["channels"]):
                if channel.get("id") == channel_id:
                    return document["channels"].pop(index)
            raise CustomChannelNotFound(f"No existe el canal {channel_id}.")

        _, channel = self._with_document(mutate)
        return deepcopy(channel)

    def normalized_channels(self) -> list[dict]:
        return [
            {
                "id": channel["stream_id"],
                "identifier_type": channel.get("identifier_type", "id"),
                "name": channel["name"],
                "logo": channel.get("logo", ""),
                "group": channel.get("group", "Personalizados"),
                "tvg_id": channel.get("tvg_id", ""),
                "source": "custom",
                "source_id": "custom",
            }
            for channel in self.get_channels()
        ]


custom_channel_manager = CustomChannelManager()
