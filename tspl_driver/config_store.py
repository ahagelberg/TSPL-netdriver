"""Load and save config.json with atomic replace."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from tspl_driver.models import AppConfig


def load_config(path: Path) -> AppConfig:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    return AppConfig.model_validate(data)


def save_config_atomic(path: Path, config: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(mode="json")
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=".config_", suffix=".tmp", text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
