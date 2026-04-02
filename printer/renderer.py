"""Label rasterization: TSPL text BITMAP, font cache (local/web), and mono bitmap decode for preview."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from config.models import ServerConfig
from printer.builder import BITMAP_BITS_PER_BYTE, MM_PER_INCH, pack_mono_bitmap_rows

TSPL_BUILTIN_FONTS = {"1", "2", "3", "4", "5", "6", "7", "8"}
FONT_URL_PREFIXES = ("http://", "https://")
FONT_SPEC_DEFAULT = "__default__"
FONT_CACHE_FILE_EXT = ".font"
FONT_CACHE_META_EXT = ".meta.json"
FONT_FETCH_DEFAULT_TIMEOUT_SECONDS = 5.0
RASTER_TEXT_THRESHOLD = 128
RASTER_TEXT_SIDE_PADDING_PX = 1
RASTER_TEXT_TOP_BOTTOM_PADDING_PX = 1
RASTER_TEXT_MIN_PX = 1
PIL_DEFAULT_TTF_FILENAMES = ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
# Sniff first bytes of a font download to reject HTML error pages / CSS.
FONT_DOWNLOAD_HTML_SNIFF_BYTES = 512
# WOFF / WOFF2 — Pillow expects TTF/OTF on disk; these fail with "unknown file format".
FONT_MAGIC_WOFF = b"wOFF"
FONT_MAGIC_WOFF2 = b"wOF2"
# Named family → fontconfig / Google Fonts CSS (must get TTF in CSS for Pillow).
# Chrome-/Firefox-style User-Agents receive WOFF2 only; a minimal WebKit UA gets truetype URLs.
GOOGLE_FONTS_CSS_BROWSER_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
FONTCONFIG_FC_MATCH_TIMEOUT_SECONDS = 8.0
TTF_URL_IN_CSS_RE = re.compile(
    r"src\s*:\s*url\s*\(\s*(https?://[^)'\"]+\.ttf)\s*\)",
    re.IGNORECASE | re.MULTILINE,
)
DEFAULT_TTF_RELATIVE_PATHS = (
    "truetype/dejavu/DejaVuSans.ttf",
    "truetype/dejavu/DejaVuSans-Bold.ttf",
    "truetype/liberation/LiberationSans-Regular.ttf",
    "truetype/liberation/LiberationSans-Bold.ttf",
)
DEFAULT_TTF_ABSOLUTE_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)


def _resolve_default_ttf_file(server_cfg: ServerConfig) -> Path | None:
    # 1) Prefer Pillow bundled fonts (if shipped).
    try:
        from PIL import ImageFont as PilImageFont

        pil_fonts_dir = Path(getattr(PilImageFont, "__file__", "")).resolve().parent / "fonts"
        for candidate_name in PIL_DEFAULT_TTF_FILENAMES:
            candidate = pil_fonts_dir / candidate_name
            if candidate.is_file():
                return candidate
    except Exception:
        # Keep fallback behavior robust: absence of bundled fonts should not break rasterization.
        pass

    # 2) Common system locations (works well on most Debian/RPi images).
    for p_str in DEFAULT_TTF_ABSOLUTE_PATHS:
        p = Path(p_str)
        if p.is_file():
            return p

    # 3) Search within configured local font roots for common relative paths.
    for root_str in getattr(server_cfg, "font_local_roots", []) or []:
        root = Path(str(root_str)).expanduser()
        for rel in DEFAULT_TTF_RELATIVE_PATHS:
            candidate = root / rel
            if candidate.is_file():
                return candidate

    return None


@dataclass(frozen=True)
class RasterizedBitmap:
    width_bytes: int
    height_dots: int
    payload: bytes


def mono_tspl_payload_to_pil_image(width_bytes: int, height_dots: int, payload: bytes):
    """Decode TSPL-style mono rows (MSB first, bit 1 = paper white) to a Pillow ``L`` image."""
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError("Pillow is required for bitmap decoding") from e
    w = width_bytes * BITMAP_BITS_PER_BYTE
    need = width_bytes * height_dots
    if len(payload) < need:
        raise ValueError(f"bitmap payload length {len(payload)} < expected {need}")
    img = Image.new("L", (w, height_dots), 255)
    pix = img.load()
    for y in range(height_dots):
        row_base = y * width_bytes
        for x in range(w):
            bi = x // BITMAP_BITS_PER_BYTE
            bit_idx = (BITMAP_BITS_PER_BYTE - 1) - (x % BITMAP_BITS_PER_BYTE)
            b = payload[row_base + bi]
            bit = (b >> bit_idx) & 1
            pix[x, y] = 255 if bit else 0
    return img


def rasterized_bitmap_to_pil_image(rb: RasterizedBitmap):
    """Same pixels as sent in TSPL BITMAP for raster text (and matching unpack)."""
    return mono_tspl_payload_to_pil_image(rb.width_bytes, rb.height_dots, rb.payload)


def is_tspl_builtin_font(font: str) -> bool:
    return font.strip() in TSPL_BUILTIN_FONTS


def is_web_font_spec(font_spec: str) -> bool:
    s = font_spec.strip().lower()
    return s.startswith(FONT_URL_PREFIXES)


def looks_like_filesystem_path(font_spec: str) -> bool:
    s = font_spec.strip()
    if not s:
        return False
    if s.startswith("/") or s.startswith("./") or s.startswith("../"):
        return True
    if s.startswith("~"):
        return True
    if "\\" in s or "/" in s:
        return True
    if len(s) >= 2 and s[1] == ":":
        return True
    return False


def is_named_font_family(font_spec: str) -> bool:
    """True when ``font`` is a family name (not builtin, path, URL, or ``__default__``)."""
    s = font_spec.strip()
    if not s or s == FONT_SPEC_DEFAULT:
        return False
    if is_tspl_builtin_font(s):
        return False
    if is_web_font_spec(s):
        return False
    if looks_like_filesystem_path(s):
        return False
    return True


def raster_font_size_mm_to_px(size_mm: float, dpi: int) -> int:
    raw = size_mm * dpi / MM_PER_INCH
    return max(RASTER_TEXT_MIN_PX, int(math.ceil(raw)))


def _downloaded_bytes_look_like_html(data: bytes) -> bool:
    head = data[:FONT_DOWNLOAD_HTML_SNIFF_BYTES].lstrip().lower()
    return (
        head.startswith(b"<!doctype")
        or head.startswith(b"<html")
        or head.startswith(b"<head")
    )


def _raise_if_font_bytes_unusable_for_pillow(data: bytes, source: str) -> None:
    """Reject HTML and webfont containers Pillow cannot open as TTF/OTF."""
    if _downloaded_bytes_look_like_html(data):
        raise ValueError(
            f"{source}: content looks like HTML, not a font file. "
            "Use a direct URL to a .ttf or .otf file."
        )
    if len(data) >= 4:
        if data[:4] == FONT_MAGIC_WOFF:
            raise ValueError(
                f"{source}: WOFF is not supported (Pillow needs raw TTF/OTF). "
                "Use a direct .ttf or .otf link (e.g. from google-webfonts-helper or the font vendor)."
            )
        if data[:4] == FONT_MAGIC_WOFF2:
            raise ValueError(
                f"{source}: WOFF2 is not supported (Pillow needs raw TTF/OTF). "
                "Use a direct .ttf or .otf link."
            )


def _delete_font_cache_entry(font_file: Path) -> None:
    """Remove a cached web font and its sidecar meta so a bad file can be re-downloaded."""
    try:
        font_file.unlink(missing_ok=True)
    except OSError:
        pass
    meta = font_file.with_suffix(FONT_CACHE_META_EXT)
    try:
        meta.unlink(missing_ok=True)
    except OSError:
        pass


def _load_truetype_font(path: Path, size_px: int):
    """Pillow uses OSError for unreadable fonts; map to RuntimeError so HTTP layer returns render_error."""
    try:
        head = path.read_bytes()[:FONT_DOWNLOAD_HTML_SNIFF_BYTES]
    except OSError as e:
        raise RuntimeError(f"Cannot read font file {path}: {e}") from e
    _raise_if_font_bytes_unusable_for_pillow(head, str(path))
    try:
        from PIL import ImageFont

        return ImageFont.truetype(str(path), size_px)
    except OSError as e:
        raise RuntimeError(
            f"Raster font failed to load (need TTF/OTF that Pillow can read): {path}: {e}"
        ) from e


def _cache_basename(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _load_cache_meta(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache_meta(path: Path, meta: dict[str, Any]) -> None:
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _is_path_within(root: Path, p: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _normalize_allowed_roots(server_cfg: ServerConfig, cfg_path: Path) -> list[Path]:
    raw = getattr(server_cfg, "font_local_roots", []) or []
    roots: list[Path] = []
    for item in raw:
        try:
            val = str(item).strip()
        except Exception:
            continue
        if not val:
            continue
        p = Path(val)
        if not p.is_absolute():
            p = (cfg_path.parent / p).resolve()
        roots.append(p.resolve())
    return roots


def _resolve_local_font_path(font_spec: str, server_cfg: ServerConfig, cfg_path: Path) -> Path:
    p = Path(font_spec.strip())
    if not p.is_absolute():
        p = (cfg_path.parent / p).resolve()
    else:
        p = p.resolve()
    roots = _normalize_allowed_roots(server_cfg, cfg_path)
    if roots and not any(_is_path_within(r, p) for r in roots):
        raise ValueError(f"Local font path is outside allowed roots: {p}")
    if not p.is_file():
        raise FileNotFoundError(f"Font file not found: {p}")
    return p


def _font_cache_dir(server_cfg: ServerConfig, cfg_path: Path) -> Path:
    raw = getattr(server_cfg, "font_cache_dir", ".tspl-font-cache")
    s = str(raw).strip() if raw is not None else ".tspl-font-cache"
    p = Path(s)
    if not p.is_absolute():
        p = (cfg_path.parent / p).resolve()
    return p


def ensure_font_cache_dir(server_cfg: ServerConfig, cfg_path: Path) -> Path:
    p = _font_cache_dir(server_cfg, cfg_path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _font_fetch_timeout_seconds(server_cfg: ServerConfig) -> float:
    raw = getattr(server_cfg, "font_fetch_timeout_seconds", FONT_FETCH_DEFAULT_TIMEOUT_SECONDS)
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return FONT_FETCH_DEFAULT_TIMEOUT_SECONDS
    return max(0.1, n)


def _fetch_web_font_to_cache(url: str, server_cfg: ServerConfig, cfg_path: Path) -> Path:
    cache_dir = _font_cache_dir(server_cfg, cfg_path)
    cache_dir.mkdir(parents=True, exist_ok=True)
    base = _cache_basename(url)
    font_file = cache_dir / f"{base}{FONT_CACHE_FILE_EXT}"
    meta_file = cache_dir / f"{base}{FONT_CACHE_META_EXT}"
    meta = _load_cache_meta(meta_file)
    headers: dict[str, str] = {}
    etag = meta.get("etag")
    modified = meta.get("last_modified")
    if isinstance(etag, str) and etag:
        headers["If-None-Match"] = etag
    if isinstance(modified, str) and modified:
        headers["If-Modified-Since"] = modified
    req = urlrequest.Request(url, headers=headers, method="GET")
    timeout = _font_fetch_timeout_seconds(server_cfg)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status == 304 and font_file.is_file():
                try:
                    head = font_file.read_bytes()[:FONT_DOWNLOAD_HTML_SNIFF_BYTES]
                    _raise_if_font_bytes_unusable_for_pillow(head, f"Cached font from {url}")
                    return font_file
                except ValueError:
                    _delete_font_cache_entry(font_file)
                    return _fetch_web_font_to_cache(url, server_cfg, cfg_path)
            data = resp.read()
            if not data:
                raise ValueError(f"Downloaded empty font data from {url}")
            _raise_if_font_bytes_unusable_for_pillow(data, url)
            font_file.write_bytes(data)
            new_meta: dict[str, Any] = {"url": url}
            hdr_etag = resp.headers.get("ETag")
            hdr_mod = resp.headers.get("Last-Modified")
            if hdr_etag:
                new_meta["etag"] = hdr_etag
            if hdr_mod:
                new_meta["last_modified"] = hdr_mod
            _save_cache_meta(meta_file, new_meta)
            return font_file
    except urlerror.HTTPError as e:
        if e.code == 304 and font_file.is_file():
            try:
                head = font_file.read_bytes()[:FONT_DOWNLOAD_HTML_SNIFF_BYTES]
                _raise_if_font_bytes_unusable_for_pillow(head, f"Cached font from {url}")
                return font_file
            except ValueError:
                _delete_font_cache_entry(font_file)
                return _fetch_web_font_to_cache(url, server_cfg, cfg_path)
        if font_file.is_file():
            try:
                head = font_file.read_bytes()[:FONT_DOWNLOAD_HTML_SNIFF_BYTES]
                _raise_if_font_bytes_unusable_for_pillow(head, str(font_file))
                return font_file
            except ValueError:
                _delete_font_cache_entry(font_file)
        raise ValueError(f"Failed to download font URL {url}: HTTP {e.code}") from e
    except (urlerror.URLError, TimeoutError) as e:
        if font_file.is_file():
            try:
                head = font_file.read_bytes()[:FONT_DOWNLOAD_HTML_SNIFF_BYTES]
                _raise_if_font_bytes_unusable_for_pillow(head, str(font_file))
                return font_file
            except ValueError:
                _delete_font_cache_entry(font_file)
        raise ValueError(f"Failed to download font URL {url}: {e}") from e


def _css_weight_to_fc_weight(w: int) -> int:
    w = max(100, min(900, int(round(w / 100)) * 100))
    return {
        100: 0,
        200: 40,
        300: 50,
        400: 80,
        500: 100,
        600: 180,
        700: 200,
        800: 205,
        900: 210,
    }[w]


def try_fontconfig_font_file(family: str, weight: int, italic: bool) -> Path | None:
    """If ``fc-match`` finds the requested family (not a fallback), return the font file path."""
    fc_w = _css_weight_to_fc_weight(weight)
    slant = 100 if italic else 0
    pattern = f"{family}:weight={fc_w}:slant={slant}"
    try:
        proc = subprocess.run(
            ["fc-match", "-f", "%{family}\t%{file}\n", pattern],
            capture_output=True,
            text=True,
            timeout=FONTCONFIG_FC_MATCH_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    line = proc.stdout.strip()
    if not line or "\t" not in line:
        return None
    got_family, path_str = line.split("\t", 1)
    if got_family.strip().lower() != family.strip().lower():
        return None
    p = Path(path_str.strip())
    if p.is_file():
        return p
    return None


def fetch_google_fonts_ttf_url(
    family: str,
    weight: int,
    italic: bool,
    server_cfg: ServerConfig,
) -> str:
    """GET Google Fonts CSS (browser UA) and return the first truetype URL."""
    w = max(100, min(900, int(round(weight / 100)) * 100))
    it = 1 if italic else 0
    fam_q = urlparse.quote(family.strip(), safe="")
    axis = f"ital,wght@{it},{w}"
    css_url = f"https://fonts.googleapis.com/css2?family={fam_q}:{axis}&display=swap"
    req = urlrequest.Request(
        css_url,
        headers={"User-Agent": GOOGLE_FONTS_CSS_BROWSER_USER_AGENT},
        method="GET",
    )
    timeout = _font_fetch_timeout_seconds(server_cfg)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            css = resp.read().decode("utf-8", errors="replace")
    except (urlerror.URLError, TimeoutError, OSError) as e:
        raise ValueError(
            f"Could not fetch Google Fonts stylesheet for {family!r}: {e}"
        ) from e
    m = TTF_URL_IN_CSS_RE.search(css)
    if not m:
        if "404" in css or "Not Found" in css:
            raise ValueError(
                f"Google Fonts has no CSS for family {family!r} with weight {w} and "
                f"style {'italic' if italic else 'normal'}. Check spelling or pick another variant."
            )
        raise ValueError(
            f"No TTF URL in Google Fonts CSS for {family!r} (got WOFF only or empty). "
            "Try another weight or use a direct .ttf URL in font."
        )
    return m.group(1)


def resolve_named_font_family(
    family: str,
    weight: int,
    font_style: str,
    server_cfg: ServerConfig,
    cfg_path: Path,
) -> Path:
    """Resolve a font family name to a local path (fontconfig) or cached download (Google)."""
    italic = font_style.strip().lower() == "italic"
    w = max(100, min(900, int(round(weight / 100)) * 100))
    local = try_fontconfig_font_file(family, w, italic)
    if local is not None:
        return local
    ttf_url = fetch_google_fonts_ttf_url(family, w, italic, server_cfg)
    return _fetch_web_font_to_cache(ttf_url, server_cfg, cfg_path)


def resolve_font_file(
    font_spec: str,
    server_cfg: ServerConfig,
    cfg_path: Path,
    *,
    font_weight: int = 400,
    font_style: str = "normal",
) -> Path:
    spec = font_spec.strip()
    if spec == FONT_SPEC_DEFAULT:
        raise ValueError("Default bitmap font does not use a file path")
    if is_web_font_spec(spec):
        return _fetch_web_font_to_cache(spec, server_cfg, cfg_path)
    if is_named_font_family(spec):
        return resolve_named_font_family(spec, font_weight, font_style, server_cfg, cfg_path)
    return _resolve_local_font_path(spec, server_cfg, cfg_path)


def rasterize_text_bitmap(
    text: str,
    font_spec: str,
    size_mm: float,
    dpi: int,
    server_cfg: ServerConfig,
    cfg_path: Path,
    *,
    font_weight: int = 400,
    font_style: str = "normal",
) -> RasterizedBitmap:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as e:
        raise RuntimeError("Pillow is required for bitmap font rendering") from e
    spec = font_spec.strip()
    # Map label ``size_mm`` to the font's nominal pixel size (Pillow TrueType ``size`` ≈ em).
    # Do **not** scale the font so the ink bbox height matches a target: that shrinks lines
    # with descenders relative to cap-height-only text. Bbox size varies with glyphs; type size does not.
    px = raster_font_size_mm_to_px(size_mm, dpi)

    if spec == FONT_SPEC_DEFAULT:
        # Pillow's `load_default()` is a fixed-size bitmap font and ignores ``px``.
        # Use a scalable TrueType font instead so size_mm behaves as expected.
        font_file = _resolve_default_ttf_file(server_cfg)
        if font_file is None:
            font = ImageFont.load_default()
        else:
            font = _load_truetype_font(font_file, px)
    else:
        font_file = resolve_font_file(
            spec,
            server_cfg,
            cfg_path,
            font_weight=font_weight,
            font_style=font_style,
        )
        font = _load_truetype_font(font_file, px)

    probe = Image.new("L", (1, 1), 255)
    probe_draw = ImageDraw.Draw(probe)
    left, top, right, bottom = probe_draw.textbbox((0, 0), text, font=font)
    text_w = max(1, right - left)
    text_h = max(1, bottom - top)
    canvas_w = text_w + (2 * RASTER_TEXT_SIDE_PADDING_PX)
    canvas_h = text_h + (2 * RASTER_TEXT_TOP_BOTTOM_PADDING_PX)

    img = Image.new("L", (canvas_w, canvas_h), 255)
    draw = ImageDraw.Draw(img)
    draw_x = RASTER_TEXT_SIDE_PADDING_PX - left
    draw_y = RASTER_TEXT_TOP_BOTTOM_PADDING_PX - top
    draw.text((draw_x, draw_y), text, font=font, fill=0)

    data = img.load()
    rows: list[list[bool]] = []
    for y in range(canvas_h):
        row: list[bool] = []
        for x in range(canvas_w):
            # TSPL BITMAP bit encoding is printer-dependent; empirical observation:
            # `1` produces white (paper) and `0` produces black (print).
            # Our image uses 255 for white and 0 for black, so invert the threshold mapping.
            row.append(int(data[x, y]) >= RASTER_TEXT_THRESHOLD)
        rows.append(row)

    width_bytes, height_dots, payload = pack_mono_bitmap_rows(rows)
    return RasterizedBitmap(
        width_bytes=width_bytes,
        height_dots=height_dots,
        payload=payload,
    )
