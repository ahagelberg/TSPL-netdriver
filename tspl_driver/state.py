"""Process-wide config path and loaded config (single-worker assumption)."""

from __future__ import annotations

import threading
from pathlib import Path

from tspl_driver.models import AppConfig

_lock = threading.Lock()
_config_path: Path | None = None
_config: AppConfig | None = None


def init_state(path: Path, cfg: AppConfig) -> None:
    global _config_path, _config
    with _lock:
        _config_path = path
        _config = cfg


def get_config_path() -> Path:
    with _lock:
        if _config_path is None:
            raise RuntimeError("Config not initialized")
        return _config_path


def get_config() -> AppConfig:
    with _lock:
        if _config is None:
            raise RuntimeError("Config not initialized")
        return _config


def set_config(cfg: AppConfig) -> None:
    global _config
    with _lock:
        _config = cfg
