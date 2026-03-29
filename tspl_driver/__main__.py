"""CLI entry: `python -m tspl_driver` or `tspl-driver`."""

from __future__ import annotations

import argparse
import logging

from tspl_driver.runtime_log import LOGGER_NAME, configure_logging


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TSPL network driver (FastAPI + Uvicorn).",
    )
    parser.add_argument(
        "--log",
        metavar="LEVEL",
        nargs="?",
        const="debug",
        choices=("debug", "info", "warning", "error"),
        default=None,
        help=(
            "Log to stderr for tspl_driver and uvicorn. "
            "LEVEL: debug, info, warning, error. "
            "If --log is given with no value, debug is used."
        ),
    )
    return parser.parse_args()


def main() -> None:
    import uvicorn

    from tspl_driver.main import _normalize_cors_origins, bootstrap_config, get_app

    args = _parse_args()
    if args.log is not None:
        configure_logging(args.log)

    path, cfg = bootstrap_config()
    log = logging.getLogger(LOGGER_NAME)
    cors_raw = list(cfg.server.cors_origins or [])
    cors_eff = _normalize_cors_origins(cors_raw)
    log.info(
        "loaded config %s, listening on %s:%s",
        path,
        cfg.server.bind_address,
        cfg.server.port,
    )
    log.info(
        "CORS server.cors_origins raw=%s — effective count=%s (first entries %s)",
        cors_raw,
        len(cors_eff),
        cors_eff[:8],
    )

    run_kw: dict = {
        "factory": True,
        "host": cfg.server.bind_address,
        "port": cfg.server.port,
    }
    if args.log is not None:
        run_kw["log_level"] = args.log

    uvicorn.run(get_app, **run_kw)


if __name__ == "__main__":
    main()
