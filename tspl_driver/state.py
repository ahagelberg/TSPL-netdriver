"""Process-wide config path; each read loads from disk (safe with multiple API workers)."""

from __future__ import annotations

import threading
from pathlib import Path

from tspl_driver.config_store import load_config
from tspl_driver.models import AppConfig

_lock = threading.Lock()
_config_path: Path | None = None


def init_state(path: Path) -> None:
    global _config_path
    with _lock:
        _config_path = path.resolve()


def get_config_path() -> Path:
    with _lock:
        if _config_path is None:
            raise RuntimeError("Config not initialized")
        return _config_path


def get_config() -> AppConfig:
    """Load current config from disk so all workers see updates after PUT /config."""
    path = get_config_path()
    return load_config(path)
