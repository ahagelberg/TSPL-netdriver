"""Load and save config.json with atomic replace."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from .models import AppConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config.example.json"


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


def bootstrap_config() -> tuple[Path, AppConfig]:
    """Ensure config file exists, load it, init app state and font cache."""
    from printer.renderer import ensure_font_cache_dir

    from .state import init_state

    path_str = os.environ.get("TSPL_DRIVER_CONFIG", str(DEFAULT_CONFIG_PATH))
    path = Path(path_str).resolve()
    if not path.exists():
        if not EXAMPLE_CONFIG_PATH.is_file():
            raise FileNotFoundError(f"Missing {EXAMPLE_CONFIG_PATH}")
        shutil.copy(EXAMPLE_CONFIG_PATH, path)
    cfg = load_config(path)
    ensure_font_cache_dir(cfg.server, path)
    init_state(path)
    return path, cfg
