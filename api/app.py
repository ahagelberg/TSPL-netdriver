"""FastAPI app: JSON API under /api/v1, static UI at /."""

from __future__ import annotations

import argparse
import logging
import os
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware, SAFELISTED_HEADERS
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.schemas import (
    ErrEnvelope,
    LabelPrintBody,
    OkEnvelope,
    RawPrintBody,
    TemplatePreviewBody,
    TemplatePrintBody,
    TemplateTestBody,
    UsbDiscoverData,
    UsbDiscoverDevice,
)
from config.config_store import bootstrap_config, save_config_atomic
from config.models import AppConfig, LabelSize
from usb_access.subsystem import PrinterDeviceNotFoundError, UsbSubsystem
from app_logging.runtime_log import LOGGER_NAME, append_exception_fields
from printer.print_service import PrintService
from config.state import get_config, get_config_path
from printer.renderer import ensure_font_cache_dir

API_PREFIX = "/api/v1"
logger = logging.getLogger(LOGGER_NAME)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _json_err(
    code: str,
    message: str,
    status: int,
    *,
    exc: BaseException | None = None,
) -> JSONResponse:
    err: dict[str, Any] = {"code": code, "message": message}
    append_exception_fields(err, exc)
    body = ErrEnvelope(error=err).model_dump()
    return JSONResponse(content=body, status_code=status)


def _validation_error_summary(exc: RequestValidationError) -> str:
    """Human-readable message from FastAPI/Pydantic validation errors."""
    parts: list[str] = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        loc_bits = [str(x) for x in loc if x not in ("body", "query", "path", "header")]
        loc_s = ".".join(loc_bits)
        msg = err.get("msg") or "invalid"
        parts.append(f"{loc_s}: {msg}" if loc_s else msg)
    return "; ".join(parts) if parts else "Validation failed"


# CORS preflight and browser cross-origin API calls (WordPress admin JS, etc.).
CORS_ALLOW_METHODS = ("GET", "POST", "OPTIONS")
CORS_ALLOW_HEADERS = (
    "Authorization",
    "Content-Type",
    "Accept",
    "X-API-Key",
)
# Browser cache duration for preflight (OPTIONS) responses.
CORS_PREFLIGHT_MAX_AGE_SECONDS = 600
# Successful preflight body is empty.
HTTP_STATUS_NO_CONTENT = 204
_cors_empty_allowlist_warned = False


def _split_netloc_host_port(netloc: str) -> tuple[str, str | None]:
    """Return (host, port_or_none). IPv6 uses bracket form."""
    if netloc.startswith("["):
        end = netloc.find("]")
        if end == -1:
            return netloc, None
        host = netloc[: end + 1]
        if len(netloc) > end + 1 and netloc[end + 1] == ":":
            return host, netloc[end + 2 :]
        return host, None
    if ":" in netloc:
        host, rest = netloc.rsplit(":", 1)
        if rest.isdigit():
            return host, rest
    return netloc, None


def _join_host_port(host: str, port: str | None) -> str:
    if not port:
        return host
    return f"{host}:{port}"


def _is_ipv4_or_localhost_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    if host.startswith("["):
        return True
    parts = host.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


def _netloc_www_variants(netloc: str) -> list[str]:
    """www and apex hostnames (same port). Skips IPs and localhost."""
    host, port = _split_netloc_host_port(netloc)
    if _is_ipv4_or_localhost_host(host):
        return [netloc]
    if host.startswith("["):
        return [netloc]
    if host.lower().startswith("www."):
        short = host[4:]
        a = _join_host_port(short, port)
        b = netloc
        return [a, b] if a != b else [netloc]
    a = netloc
    b = _join_host_port(f"www.{host}", port)
    return [a, b] if a != b else [netloc]


def _single_config_origin_variants(origin: str) -> list[str]:
    """http/https and www/apex variants for one configured origin string."""
    if origin == "*":
        return ["*"]
    try:
        parsed = urlparse(origin)
    except Exception:
        return [origin]
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return [origin]
    out: list[str] = []
    seen: set[str] = set()
    for nl in _netloc_www_variants(parsed.netloc):
        for scheme in ("http", "https"):
            v = f"{scheme}://{nl}"
            if v not in seen:
                out.append(v)
                seen.add(v)
    return out


def _normalize_cors_origins(origins: list[str]) -> list[str]:
    """Expand configured origins: http/https, www/apex for real hostnames (not IPs)."""
    if not origins:
        return []
    if any(o == "*" for o in origins):
        return ["*"]
    out: list[str] = []
    seen: set[str] = set()
    for o in origins:
        if not o:
            continue
        for v in _single_config_origin_variants(o):
            if v not in seen:
                out.append(v)
                seen.add(v)
    return out


def _effective_cors_origins() -> list[str]:
    """Origins from config, or TSPL_CORS_ORIGINS env if config list is empty."""
    try:
        cfg = get_config()
        from_cfg = list(cfg.server.cors_origins or [])
    except RuntimeError:
        from_cfg = []
    if from_cfg:
        raw = from_cfg
    else:
        env_raw = os.environ.get("TSPL_CORS_ORIGINS", "").strip()
        if not env_raw:
            return []
        raw = [x.strip() for x in env_raw.split(",") if x.strip()]
    return _normalize_cors_origins(raw)


def _maybe_warn_cors_allowlist_empty(origin: str | None) -> None:
    """One-time WARNING when browser sends Origin but server.cors_origins is empty."""
    global _cors_empty_allowlist_warned
    if not origin or _cors_empty_allowlist_warned:
        return
    if _effective_cors_origins():
        return
    _cors_empty_allowlist_warned = True
    try:
        path = str(get_config_path())
    except RuntimeError:
        path = "?"
    logger.warning(
        "CORS disabled: server.cors_origins is empty in loaded config (%s). "
        "Browser Origin was %r. Edit that JSON (server.cors_origins) or PUT /api/v1/config, then restart.",
        path,
        origin,
    )


def _cors_preflight_headers_for_request(request: Request) -> dict[str, str]:
    """Same CORS preflight fields as Starlette CORSMiddleware for explicit OPTIONS routes."""
    origin = request.headers.get("origin")
    allowed_origins = _effective_cors_origins()
    if not origin or origin not in allowed_origins:
        if not allowed_origins and origin:
            _maybe_warn_cors_allowlist_empty(origin)
        elif logger.isEnabledFor(logging.DEBUG) and origin:
            logger.debug(
                "cors preflight: Origin %r not in allowed set (sample %s)",
                origin,
                allowed_origins[:8],
            )
        return {}
    allow_headers = sorted(SAFELISTED_HEADERS | set(CORS_ALLOW_HEADERS))
    headers: dict[str, str] = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": ", ".join(CORS_ALLOW_METHODS),
        "Access-Control-Allow-Headers": ", ".join(allow_headers),
        "Access-Control-Max-Age": str(CORS_PREFLIGHT_MAX_AGE_SECONDS),
        "Vary": "Origin",
    }
    if request.headers.get("access-control-request-private-network") is not None:
        headers["Access-Control-Allow-Private-Network"] = "true"
    return headers


class EnsureApiCorsHeadersMiddleware:
    """If Starlette CORSMiddleware omits Access-Control-Allow-Origin on a response, add it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if not path.startswith(API_PREFIX):
            await self.app(scope, receive, send)
            return
        origin = Headers(scope=scope).get("origin")
        if not origin:
            await self.app(scope, receive, send)
            return
        allowed = _effective_cors_origins()
        if not allowed or origin not in allowed:
            if not allowed:
                _maybe_warn_cors_allowlist_empty(origin)
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                hdrs = MutableHeaders(scope=message)
                if "access-control-allow-origin" not in hdrs:
                    hdrs["Access-Control-Allow-Origin"] = origin
                    hdrs.add_vary_header("Origin")
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _register_cors_middleware(app: FastAPI) -> None:
    origins = _effective_cors_origins()
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=list(CORS_ALLOW_METHODS),
        allow_headers=list(CORS_ALLOW_HEADERS),
        max_age=CORS_PREFLIGHT_MAX_AGE_SECONDS,
        # Public https site → LAN http TSPL (Chrome Private Network Access preflight).
        allow_private_network=True,
    )
    app.add_middleware(EnsureApiCorsHeadersMiddleware)


def verify_api_key(request: Request) -> None:
    cfg = get_config()
    auth = request.headers.get("Authorization") or ""
    prefix = "Bearer "
    token = None
    if auth.startswith(prefix):
        token = auth[len(prefix) :].strip()
    if not token:
        token = request.headers.get("X-API-Key")
    expected = cfg.server.api_key
    if not token:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "Invalid or missing API key"},
        )
    # compare_digest() only allows ASCII for str; UTF-8 bytes support any key characters.
    try:
        got = token.encode("utf-8")
        want = expected.encode("utf-8")
    except UnicodeError:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "Invalid or missing API key"},
        )
    if len(got) != len(want):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "Invalid or missing API key"},
        )
    if not secrets.compare_digest(got, want):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "Invalid or missing API key"},
        )


def create_app() -> FastAPI:
    try:
        get_config()
    except RuntimeError:
        bootstrap_config()
    app = FastAPI(title="TSPL driver", version="0.1.0")
    _register_cors_middleware(app)

    @app.exception_handler(RequestValidationError)
    async def validation_exc(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning("request validation failed: %s", exc.errors())
        return _json_err(
            "validation_error",
            _validation_error_summary(exc),
            422,
            exc=exc,
        )

    @app.exception_handler(HTTPException)
    async def http_exc(request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            return JSONResponse(
                content={"ok": False, "error": exc.detail},
                status_code=exc.status_code,
            )
        if isinstance(exc.detail, list):
            return _json_err(
                "http_error",
                "; ".join(str(x) for x in exc.detail) or "Request failed",
                exc.status_code,
            )
        return _json_err("http_error", str(exc.detail), exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled API error")
        return _json_err(
            "internal_error",
            str(exc) or "Internal server error",
            500,
            exc=exc,
        )

    def _ui_file_response(filename: str) -> FileResponse:
        path = STATIC_DIR / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail="UI not found")
        return FileResponse(path)

    @app.get("/")
    async def root_print_page() -> FileResponse:
        """Label printing UI (default landing page)."""
        return _ui_file_response("print.html")

    @app.get("/config.html")
    async def config_page() -> FileResponse:
        """Printer / template configuration UI."""
        return _ui_file_response("index.html")

    @app.get("/favicon.ico")
    async def favicon() -> FileResponse:
        """Browsers request /favicon.ico by default; static files live under /static/."""
        path = STATIC_DIR / "favicon.svg"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Favicon not found")
        return FileResponse(path, media_type="image/svg+xml")

    @app.get("/print.html")
    async def print_page_alias() -> FileResponse:
        """Same UI as ``GET /`` (bookmark compatibility)."""
        return _ui_file_response("print.html")

    v1 = APIRouter(prefix=API_PREFIX, dependencies=[Depends(verify_api_key)])

    @v1.get("/health")
    async def health() -> dict:
        return OkEnvelope(data={"status": "ok"}).model_dump()

    @v1.get("/config")
    async def read_config() -> dict:
        return OkEnvelope(data=get_config().model_dump(mode="json")).model_dump()

    @v1.put("/config")
    async def write_config(body: AppConfig) -> dict:
        path = get_config_path()
        try:
            ensure_font_cache_dir(body.server, path)
            save_config_atomic(path, body)
        except OSError as e:
            logger.error("config save failed: %s", e)
            return _json_err(
                "io_error",
                str(e) or "Could not save configuration file",
                500,
                exc=e,
            )
        return OkEnvelope(data=body.model_dump(mode="json")).model_dump()

    @v1.get("/templates/{template_id}")
    async def get_template(template_id: str) -> dict:
        cfg = get_config()
        tpl = next((t for t in cfg.templates if t.id == template_id), None)
        if tpl is None:
            return _json_err("not_found", f"Unknown template {template_id!r}", 404)
        return OkEnvelope(data=tpl.model_dump(mode="json")).model_dump()

    @v1.get("/usb/discover")
    async def usb_discover(show_all: bool = False) -> dict:
        logger.debug("usb/discover show_all=%s", show_all)
        listed, usb_total, tspl_like_count = UsbSubsystem().discover_devices(
            show_all=show_all
        )
        rows = [
            UsbDiscoverDevice(
                device_key=x.device_key,
                label=x.label,
                vendor_id=x.vendor_id,
                product_id=x.product_id,
                serial=x.serial,
                usb_port_path=x.usb_port_path,
                manufacturer=x.manufacturer,
                product=x.product,
            )
            for x in listed
        ]
        payload = UsbDiscoverData(
            devices=rows,
            usb_total=usb_total,
            tspl_like_count=tspl_like_count,
        )
        return OkEnvelope(data=payload.model_dump(mode="json")).model_dump()

    @v1.post("/print/template")
    async def print_template(body: TemplatePrintBody) -> dict:
        cfg = get_config()
        try:
            logger.debug(
                "print/template template_id=%s printer_id=%s",
                body.template_id,
                body.printer_id,
            )
            nbytes = PrintService().print_template_job(
                cfg,
                template_id=body.template_id,
                printer_id=body.printer_id,
                data=body.data,
            )
            logger.debug(
                "print/template %d bytes printer_id=%s",
                nbytes,
                body.printer_id,
            )
        except ValueError as e:
            msg = str(e)
            if msg.startswith("Unknown template ") or msg.startswith("Unknown printer "):
                return _json_err("not_found", msg, 404, exc=e)
            logger.warning("template render failed: %s", e)
            return _json_err("render_error", msg, 422, exc=e)
        except KeyError as e:
            logger.warning("missing key: %s", e)
            return _json_err("not_found", str(e), 404, exc=e)
        except RuntimeError as e:
            logger.warning("template render runtime failed: %s", e)
            return _json_err("render_error", str(e), 422, exc=e)
        except PrinterDeviceNotFoundError as e:
            logger.error("device not found: %s", e)
            return _json_err("device_not_found", str(e), 503, exc=e)
        except OSError as e:
            logger.error("I/O error writing to printer: %s", e)
            return _json_err("io_error", str(e), 503, exc=e)
        return OkEnvelope(data={"printed": True}).model_dump()

    @v1.post("/print/label")
    async def print_label(body: LabelPrintBody) -> dict:
        cfg = get_config()
        try:
            logger.debug("print/label printer_id=%s", body.printer_id)
            ls = LabelSize(
                id="inline-label-size",
                name="Inline label size",
                width=body.label_size.width,
                height=body.label_size.height,
                gap=body.label_size.gap,
            )
            nbytes = PrintService().print_inline_label(
                cfg,
                printer_id=body.printer_id,
                label_size=ls,
                elements=body.elements,
                data=body.data,
            )
            logger.debug("print/label %d bytes printer_id=%s", nbytes, body.printer_id)
        except ValueError as e:
            msg = str(e)
            if msg.startswith("Unknown printer "):
                return _json_err("not_found", msg, 404, exc=e)
            logger.warning("inline label render failed: %s", e)
            return _json_err("render_error", msg, 422, exc=e)
        except RuntimeError as e:
            logger.warning("inline label runtime failed: %s", e)
            return _json_err("render_error", str(e), 422, exc=e)
        except PrinterDeviceNotFoundError as e:
            logger.error("device not found: %s", e)
            return _json_err("device_not_found", str(e), 503, exc=e)
        except OSError as e:
            logger.error("I/O error writing to printer: %s", e)
            return _json_err("io_error", str(e), 503, exc=e)
        return OkEnvelope(data={"printed": True}).model_dump()

    @v1.post("/print/raw")
    async def print_raw(body: RawPrintBody) -> dict:
        cfg = get_config()
        pr = next((p for p in cfg.printers if p.id == body.printer_id), None)
        if pr is None:
            return _json_err("not_found", f"Unknown printer {body.printer_id!r}", 404)
        try:
            logger.debug("print/raw printer_id=%s", body.printer_id)
            raw = body.tspl.encode(pr.text_encoding, errors="replace")
            logger.debug("print/raw %d bytes", len(raw))
            UsbSubsystem().send_tspl(pr, raw)
        except PrinterDeviceNotFoundError as e:
            logger.error("device not found: %s", e)
            return _json_err("device_not_found", str(e), 503, exc=e)
        except OSError as e:
            logger.error("I/O error writing to printer: %s", e)
            return _json_err("io_error", str(e), 503, exc=e)
        return OkEnvelope(data={"printed": True}).model_dump()

    @v1.post("/printers/{printer_id}/test")
    async def printer_test(printer_id: str) -> dict:
        cfg = get_config()
        try:
            logger.debug("printer test printer_id=%s", printer_id)
            nbytes = PrintService().print_printer_test(cfg, printer_id=printer_id)
            logger.debug("printer test %d bytes printer_id=%s", nbytes, printer_id)
        except ValueError as e:
            msg = str(e)
            if msg.startswith("Unknown printer "):
                return _json_err("not_found", msg, 404, exc=e)
            logger.warning("printer test failed: %s", e)
            return _json_err("render_error", msg, 422, exc=e)
        except KeyError:
            logger.warning(
                "printer test: missing label size for printer %r",
                printer_id,
            )
            return _json_err(
                "config_error",
                f"Printer default label size missing for {printer_id!r}",
                422,
            )
        except PrinterDeviceNotFoundError as e:
            logger.error("device not found: %s", e)
            return _json_err("device_not_found", str(e), 503, exc=e)
        except OSError as e:
            logger.error("I/O error writing to printer: %s", e)
            return _json_err("io_error", str(e), 503, exc=e)
        except RuntimeError as e:
            logger.warning("printer test runtime failed: %s", e)
            return _json_err("render_error", str(e), 422, exc=e)
        return OkEnvelope(data={"tested": True}).model_dump()

    @v1.post("/templates/{template_id}/test")
    async def template_test(template_id: str, body: TemplateTestBody) -> dict:
        cfg = get_config()
        try:
            logger.debug(
                "template test template_id=%s printer_id=%s",
                template_id,
                body.printer_id,
            )
            nbytes = PrintService().print_template_test(
                cfg,
                template_id=template_id,
                printer_id=body.printer_id,
                data=body.data,
            )
            logger.debug(
                "template test %d bytes printer_id=%s",
                nbytes,
                body.printer_id,
            )
        except ValueError as e:
            msg = str(e)
            if msg.startswith("Unknown template ") or msg.startswith("Unknown printer "):
                return _json_err("not_found", msg, 404, exc=e)
            logger.warning("template test render failed: %s", e)
            return _json_err("render_error", msg, 422, exc=e)
        except KeyError as e:
            logger.warning("template test missing key: %s", e)
            return _json_err("not_found", str(e), 404, exc=e)
        except RuntimeError as e:
            logger.warning("template test runtime failed: %s", e)
            return _json_err("render_error", str(e), 422, exc=e)
        except PrinterDeviceNotFoundError as e:
            logger.error("device not found: %s", e)
            return _json_err("device_not_found", str(e), 503, exc=e)
        except OSError as e:
            logger.error("I/O error writing to printer: %s", e)
            return _json_err("io_error", str(e), 503, exc=e)
        return OkEnvelope(data={"tested": True}).model_dump()

    @v1.post("/preview/template")
    async def template_preview_png(body: TemplatePreviewBody) -> Response:
        cfg = get_config()
        try:
            png = PrintService().preview_template_png(
                cfg,
                printer_id=body.printer_id,
                label_size_id=body.label_size_id,
                elements=body.elements,
                test_data=body.test_data,
                data=body.data,
            )
        except ValueError as e:
            msg = str(e)
            if msg.startswith("Unknown printer "):
                return _json_err("not_found", msg, 404, exc=e)
            logger.warning("template preview render failed: %s", e)
            return _json_err("render_error", msg, 422, exc=e)
        except KeyError as e:
            lid = e.args[0] if e.args else str(e)
            logger.warning("template preview: unknown label size %r", lid)
            return _json_err("not_found", f"Unknown label size {lid!r}", 404, exc=e)
        except RuntimeError as e:
            logger.warning("template preview runtime failed: %s", e)
            return _json_err("render_error", str(e), 422, exc=e)
        return Response(
            content=png,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    # Preflight must succeed without API key. Headers are set here too: middleware alone
    # does not always merge Access-Control-* onto this 204 (e.g. some OPTIONS paths).
    @app.options(f"{API_PREFIX}/{{full_path:path}}")
    async def api_v1_options(request: Request, full_path: str) -> Response:
        return Response(
            status_code=HTTP_STATUS_NO_CONTENT,
            headers=_cors_preflight_headers_for_request(request),
        )

    app.include_router(v1)

    if STATIC_DIR.is_dir():
        app.mount(
            "/static",
            StaticFiles(directory=str(STATIC_DIR)),
            name="static",
        )

    return app


def get_app() -> FastAPI:
    """Uvicorn factory."""
    return create_app()


def _parse_cli_args() -> argparse.Namespace:
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
            "Log to stderr for the driver and uvicorn. "
            "LEVEL: debug, info, warning, error. "
            "If --log is given with no value, debug is used."
        ),
    )
    return parser.parse_args()


def run() -> None:
    """Console script entry (`tspl-driver`) and `python -m` when wired via __main__."""
    import logging

    import uvicorn

    from app_logging.runtime_log import configure_logging

    args = _parse_cli_args()
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
