"""CLI-configured logging and optional verbose API error payloads."""

from __future__ import annotations

import logging
import sys
import traceback
from typing import Any

_LOG_LEVEL_EFFECTIVE: int | None = None

LOGGER_NAME = "tspl_driver"


def configure_logging(level_name: str) -> None:
    """Configure root + tspl_driver loggers; call once before uvicorn starts."""
    global _LOG_LEVEL_EFFECTIVE
    level = getattr(logging, level_name.upper(), logging.INFO)
    _LOG_LEVEL_EFFECTIVE = level
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
        force=True,
    )
    logging.getLogger(LOGGER_NAME).setLevel(level)


def logging_configured() -> bool:
    return _LOG_LEVEL_EFFECTIVE is not None


def include_oserror_fields() -> bool:
    """Extra errno/strerror in JSON when any --log level was set."""
    return _LOG_LEVEL_EFFECTIVE is not None


def include_traceback_in_json() -> bool:
    """Full traceback in JSON only at DEBUG."""
    return _LOG_LEVEL_EFFECTIVE is not None and _LOG_LEVEL_EFFECTIVE <= logging.DEBUG


def append_exception_fields(err: dict[str, Any], exc: BaseException | None) -> None:
    """Attach diagnostic fields when --log was used (and traceback when DEBUG)."""
    if exc is None:
        return
    if include_oserror_fields() and isinstance(exc, OSError):
        err["errno"] = exc.errno
        err["strerror"] = exc.strerror or ""
        if exc.filename is not None:
            err["filename"] = str(exc.filename)
    if include_traceback_in_json():
        err["traceback"] = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
