"""FastAPI app: JSON API under /api/v1, static UI at /."""

from __future__ import annotations

import logging
import os
import secrets
import shutil
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

from tspl_driver.api_schemas import (
    ErrEnvelope,
    OkEnvelope,
    RawPrintBody,
    TemplatePrintBody,
    TemplateTestBody,
    UsbDiscoverData,
    UsbDiscoverDevice,
)
from tspl_driver.config_store import load_config, save_config_atomic
from tspl_driver.models import AppConfig
from tspl_driver.print_usb import PrinterDeviceNotFoundError, send_tspl_to_printer
from tspl_driver.state import get_config, get_config_path, init_state
from tspl_driver.template_render import get_label_size, render_template_tspl
from tspl_driver.tspl.builder import build_test_label_tspl
from tspl_driver.runtime_log import LOGGER_NAME, append_exception_fields
from tspl_driver.usb_discover import list_usb_devices, name_suggests_tspl_printer

API_PREFIX = "/api/v1"
logger = logging.getLogger(LOGGER_NAME)
STATIC_DIR = Path(__file__).resolve().parent / "static"

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"
EXAMPLE_CONFIG_PATH = APP_DIR / "config.example.json"
if not EXAMPLE_CONFIG_PATH.is_file():
    EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config.example.json"


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
            exc.errors().__repr__(),
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
        return _json_err("http_error", str(exc.detail), exc.status_code)

    @app.get("/")
    async def index() -> FileResponse:
        index_path = STATIC_DIR / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=404, detail="UI not found")
        return FileResponse(index_path)

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
        save_config_atomic(path, body)
        return OkEnvelope(data=body.model_dump(mode="json")).model_dump()

    @v1.get("/usb/discover")
    async def usb_discover(show_all: bool = False) -> dict:
        logger.debug("usb/discover show_all=%s", show_all)
        all_devices = list_usb_devices()
        name_matched = [
            x
            for x in all_devices
            if name_suggests_tspl_printer(x.manufacturer, x.product)
        ]
        listed = all_devices if show_all else name_matched
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
            usb_total=len(all_devices),
            tspl_like_count=len(name_matched),
        )
        return OkEnvelope(data=payload.model_dump(mode="json")).model_dump()

    @v1.post("/print/template")
    async def print_template(body: TemplatePrintBody) -> dict:
        cfg = get_config()
        tpl = next((t for t in cfg.templates if t.id == body.template_id), None)
        if tpl is None:
            return _json_err("not_found", f"Unknown template {body.template_id!r}", 404)
        pr = next((p for p in cfg.printers if p.id == body.printer_id), None)
        if pr is None:
            return _json_err("not_found", f"Unknown printer {body.printer_id!r}", 404)
        try:
            logger.debug(
                "print/template template_id=%s printer_id=%s",
                body.template_id,
                body.printer_id,
            )
            ls = get_label_size(cfg, tpl.label_size_id)
            merged_data = {**tpl.test_data, **body.data}
            payload = render_template_tspl(tpl, ls, pr, merged_data)
            logger.debug("print/template %d bytes printer_id=%s", len(payload), body.printer_id)
            send_tspl_to_printer(pr, payload)
        except ValueError as e:
            logger.warning("template render failed: %s", e)
            return _json_err("render_error", str(e), 422, exc=e)
        except KeyError as e:
            logger.warning("missing key: %s", e)
            return _json_err("not_found", str(e), 404, exc=e)
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
            send_tspl_to_printer(pr, raw)
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
        pr = next((p for p in cfg.printers if p.id == printer_id), None)
        if pr is None:
            return _json_err("not_found", f"Unknown printer {printer_id!r}", 404)
        try:
            ls = get_label_size(cfg, pr.default_label_size_id)
        except KeyError as e:
            logger.warning("printer test: missing label size: %s", e)
            return _json_err(
                "config_error",
                f"Printer default label size missing for {printer_id!r}",
                422,
                exc=e,
            )
        try:
            logger.debug("printer test printer_id=%s", printer_id)
            payload = build_test_label_tspl(
                width_mm=ls.width_mm,
                height_mm=ls.height_mm,
                gap_mm=ls.gap_mm,
                dpi=pr.dpi,
                direction=pr.direction,
                offset_x_mm=pr.offset_x_mm,
                offset_y_mm=pr.offset_y_mm,
                text_encoding=pr.text_encoding,
            )
            logger.debug("printer test %d bytes printer_id=%s", len(payload), printer_id)
            send_tspl_to_printer(pr, payload)
        except PrinterDeviceNotFoundError as e:
            logger.error("device not found: %s", e)
            return _json_err("device_not_found", str(e), 503, exc=e)
        except OSError as e:
            logger.error("I/O error writing to printer: %s", e)
            return _json_err("io_error", str(e), 503, exc=e)
        return OkEnvelope(data={"tested": True}).model_dump()

    @v1.post("/templates/{template_id}/test")
    async def template_test(template_id: str, body: TemplateTestBody) -> dict:
        cfg = get_config()
        tpl = next((t for t in cfg.templates if t.id == template_id), None)
        if tpl is None:
            return _json_err("not_found", f"Unknown template {template_id!r}", 404)
        pr = next((p for p in cfg.printers if p.id == body.printer_id), None)
        if pr is None:
            return _json_err("not_found", f"Unknown printer {body.printer_id!r}", 404)
        try:
            logger.debug(
                "template test template_id=%s printer_id=%s",
                template_id,
                body.printer_id,
            )
            ls = get_label_size(cfg, tpl.label_size_id)
            merged_data = {**tpl.test_data, **body.data}
            payload = render_template_tspl(tpl, ls, pr, merged_data)
            logger.debug("template test %d bytes printer_id=%s", len(payload), body.printer_id)
            send_tspl_to_printer(pr, payload)
        except ValueError as e:
            logger.warning("template test render failed: %s", e)
            return _json_err("render_error", str(e), 422, exc=e)
        except KeyError as e:
            logger.warning("template test missing key: %s", e)
            return _json_err("not_found", str(e), 404, exc=e)
        except PrinterDeviceNotFoundError as e:
            logger.error("device not found: %s", e)
            return _json_err("device_not_found", str(e), 503, exc=e)
        except OSError as e:
            logger.error("I/O error writing to printer: %s", e)
            return _json_err("io_error", str(e), 503, exc=e)
        return OkEnvelope(data={"tested": True}).model_dump()

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


def bootstrap_config() -> tuple[Path, AppConfig]:
    path_str = os.environ.get("TSPL_DRIVER_CONFIG", str(DEFAULT_CONFIG_PATH))
    path = Path(path_str).resolve()
    if not path.exists():
        if not EXAMPLE_CONFIG_PATH.is_file():
            raise FileNotFoundError(f"Missing {EXAMPLE_CONFIG_PATH}")
        shutil.copy(EXAMPLE_CONFIG_PATH, path)
    cfg = load_config(path)
    init_state(path)
    return path, cfg


def get_app() -> FastAPI:
    """Uvicorn factory."""
    return create_app()
