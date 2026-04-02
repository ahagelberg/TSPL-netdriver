"""Run the root-only udev refresh helper after saving config (passwordless sudo for ``tspl``)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from app_logging.runtime_log import LOGGER_NAME

_log = logging.getLogger(f"{LOGGER_NAME}.udev_refresh")

# Must match sudoers installed by install-to-opt.sh (system interpreter, not the venv).
_UDEV_REFRESH_PYTHON = Path("/usr/bin/python3")


def try_refresh_udev_rules() -> None:
    """Call ``refresh_udev_from_config.py`` via sudo; no-op if the script is missing or sudo fails."""
    repo_root = Path(__file__).resolve().parent.parent
    script = repo_root / "refresh_udev_from_config.py"
    if not script.is_file():
        return
    if shutil.which("sudo") is None:
        _log.warning("sudo not found; skipping udev refresh")
        return
    if not _UDEV_REFRESH_PYTHON.is_file():
        _log.warning("%s missing; skipping udev refresh", _UDEV_REFRESH_PYTHON)
        return
    try:
        cp = subprocess.run(
            ["sudo", "-n", str(_UDEV_REFRESH_PYTHON), str(script)],
            check=False,
            timeout=60,
            capture_output=True,
            text=True,
        )
        if cp.returncode != 0:
            _log.warning(
                "udev refresh exit %s stderr=%s",
                cp.returncode,
                (cp.stderr or "").strip(),
            )
        else:
            _log.info("udev rules refreshed for USB printers")
    except (OSError, subprocess.TimeoutExpired) as e:
        _log.warning("udev refresh failed: %s", e)
