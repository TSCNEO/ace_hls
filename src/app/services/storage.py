import json
import os
import tempfile
from typing import Any


def atomic_write_text(destination: str, content: str) -> None:
    """Write shared persistent data using fsync plus atomic replacement."""
    directory = os.path.dirname(destination) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".ace-hls-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_json(destination: str, payload: Any) -> None:
    atomic_write_text(destination, json.dumps(payload, indent=2, ensure_ascii=False))
