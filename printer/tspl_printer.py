"""TSPL label rendering: template/inline elements to bytes; raster text via printer.renderer."""

from __future__ import annotations

import base64
import binascii
import re
from io import BytesIO
from pathlib import Path

from config.models import LabelSize, PrinterConfig, ServerConfig, TemplateConfig
from printer.base import Printer
from printer.builder import (
    TSPL_BITMAP_MODE_OVERWRITE,
    TSPL_DIRECTION_180,
    build_bitmap_command_bytes,
    build_box_command,
    build_circle_command,
    build_label_preamble,
    build_print_command,
    build_text_command_bytes,
    line_width_mm_to_box_dots,
    mm_to_dots,
)
from printer.renderer import (
    FONT_SPEC_DEFAULT,
    is_tspl_builtin_font,
    mono_tspl_payload_to_pil_image,
    rasterize_text_bitmap,
    rasterized_bitmap_to_pil_image,
)

_PLACEHOLDER_RE = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")
# Same 180° as TSPL DIRECTION 1 so preview matches peeled label; no extra flip.
TSPL_PREVIEW_ROTATION_DEGREES = 180

# Built-in printer self-test pattern (TEXT + raster BITMAP), positions in mm from label origin.
TEST_LABEL_TEXT_MM_X = 2.0
TEST_LABEL_TEXT_MM_Y = 2.0
TEST_LABEL_BITMAP_MM_X = 2.0
TEST_LABEL_BITMAP_MM_Y = 8.0
TEST_LABEL_BUILTIN_TEXT = "TSPL test"
TEST_LABEL_RASTER_TEXT = "Raster test"
TEST_LABEL_RASTER_SIZE_MM = 3.0
TEST_LABEL_RASTER_FONT = FONT_SPEC_DEFAULT


def _paste_l_mode(canvas, patch, left: int, top: int) -> None:
    """Paste ``L`` mode ``patch`` onto ``canvas`` at (left, top); clip to canvas bounds."""
    cw, ch = canvas.size
    pw, ph = patch.size
    if left >= cw or top >= ch or left + pw <= 0 or top + ph <= 0:
        return
    sx = max(0, -left)
    sy = max(0, -top)
    dx = max(0, left)
    dy = max(0, top)
    crop_w = min(pw - sx, cw - dx)
    crop_h = min(ph - sy, ch - dy)
    if crop_w <= 0 or crop_h <= 0:
        return
    part = patch.crop((sx, sy, sx + crop_w, sy + crop_h))
    canvas.paste(part, (dx, dy))


def required_placeholder_keys(template: TemplateConfig) -> set[str]:
    keys: set[str] = set()
    for el in template.elements:
        if el.type == "text":
            keys.update(_PLACEHOLDER_RE.findall(el.content))
    return keys


def fill_placeholders(content: str, data: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in data:
            raise KeyError(key)
        val = data[key]
        return val.replace('"', "'")

    return _PLACEHOLDER_RE.sub(repl, content)


class TsplPrinter(Printer):
    """TSPL printer driver: build job bytes; USB send is done by ``UsbSubsystem``."""

    def __init__(self, server_cfg: ServerConfig, cfg_path: Path) -> None:
        self._server_cfg = server_cfg
        self._cfg_path = cfg_path

    def render_template(
        self,
        template: TemplateConfig,
        label_size: LabelSize,
        printer: PrinterConfig,
        data: dict[str, str],
    ) -> bytes:
        req = required_placeholder_keys(template)
        missing = req - data.keys()
        if missing:
            raise ValueError(f"Missing data keys: {sorted(missing)}")
        dpi = printer.dpi
        enc = printer.text_encoding
        preamble_b = build_label_preamble(
            width=label_size.width,
            height=label_size.height,
            gap=label_size.gap,
            dpi=dpi,
            direction=printer.direction,
            offset_x=printer.offset_x,
            offset_y=printer.offset_y,
        ).encode("ascii")
        parts: list[bytes] = [preamble_b]
        for el in template.elements:
            if el.type == "text":
                text = fill_placeholders(el.content, data)
                xd = mm_to_dots(el.x, dpi)
                yd = mm_to_dots(el.y, dpi)
                if is_tspl_builtin_font(el.font):
                    parts.append(build_text_command_bytes(xd, yd, el.font, text, enc))
                else:
                    bitmap = rasterize_text_bitmap(
                        text=text,
                        font_spec=el.font,
                        size_mm=el.size,
                        dpi=dpi,
                        server_cfg=self._server_cfg,
                        cfg_path=self._cfg_path,
                        font_weight=el.font_weight,
                        font_style=el.font_style,
                    )
                    parts.append(
                        build_bitmap_command_bytes(
                            xd,
                            yd,
                            bitmap.width_bytes,
                            bitmap.height_dots,
                            TSPL_BITMAP_MODE_OVERWRITE,
                            bitmap.payload,
                        )
                    )
            elif el.type == "box":
                x1 = mm_to_dots(el.x, dpi)
                y1 = mm_to_dots(el.y, dpi)
                x2 = mm_to_dots(el.x + el.width, dpi)
                y2 = mm_to_dots(el.y + el.height, dpi)
                lw_dots = line_width_mm_to_box_dots(el.line_width, dpi)
                parts.append(build_box_command(x1, y1, x2, y2, lw_dots))
            elif el.type == "circle":
                x0 = mm_to_dots(el.x, dpi)
                y0 = mm_to_dots(el.y, dpi)
                d_dots = max(1, mm_to_dots(el.diameter, dpi))
                t_dots = line_width_mm_to_box_dots(el.line_width, dpi)
                parts.append(build_circle_command(x0, y0, d_dots, t_dots))
            elif el.type == "bitmap":
                try:
                    raw = base64.b64decode(el.data, validate=True)
                except (ValueError, binascii.Error) as e:
                    raise ValueError("bitmap data must be valid base64") from e
                xd = mm_to_dots(el.x, dpi)
                yd = mm_to_dots(el.y, dpi)
                wb = max(1, (el.width + 7) // 8)
                expect = wb * el.height
                if len(raw) != expect:
                    raise ValueError(
                        f"bitmap payload length {len(raw)} != expected {expect} for "
                        f"width={el.width} height={el.height}"
                    )
                parts.append(
                    build_bitmap_command_bytes(
                        xd,
                        yd,
                        wb,
                        el.height,
                        TSPL_BITMAP_MODE_OVERWRITE,
                        raw,
                    )
                )
        parts.append(build_print_command(1).encode("ascii"))
        return b"".join(parts)

    def render_template_to_png_bytes(
        self,
        template: TemplateConfig,
        label_size: LabelSize,
        printer: PrinterConfig,
        data: dict[str, str],
    ) -> bytes:
        """Raster preview: same geometry and same ``rasterize_text_bitmap`` as ``render_template`` for text."""
        img = self._render_template_to_pil_image(template, label_size, printer, data)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _render_template_to_pil_image(
        self,
        template: TemplateConfig,
        label_size: LabelSize,
        printer: PrinterConfig,
        data: dict[str, str],
    ):
        """Build label image at printer DPI. Builtin TSPL fonts use default raster font for preview pixels."""
        try:
            from PIL import Image, ImageDraw
        except ImportError as e:
            raise RuntimeError("Pillow is required for template preview") from e
        req = required_placeholder_keys(template)
        missing = req - data.keys()
        if missing:
            raise ValueError(f"Missing data keys: {sorted(missing)}")
        dpi = printer.dpi
        ox = mm_to_dots(printer.offset_x, dpi)
        oy = mm_to_dots(printer.offset_y, dpi)
        w_dots = mm_to_dots(label_size.width, dpi)
        h_dots = mm_to_dots(label_size.height, dpi)
        img = Image.new("L", (max(1, w_dots), max(1, h_dots)), 255)
        draw = ImageDraw.Draw(img)
        for el in template.elements:
            if el.type == "text":
                text = fill_placeholders(el.content, data)
                xd = mm_to_dots(el.x, dpi)
                yd = mm_to_dots(el.y, dpi)
                if is_tspl_builtin_font(el.font):
                    rb = rasterize_text_bitmap(
                        text=text,
                        font_spec=FONT_SPEC_DEFAULT,
                        size_mm=el.size,
                        dpi=dpi,
                        server_cfg=self._server_cfg,
                        cfg_path=self._cfg_path,
                    )
                else:
                    rb = rasterize_text_bitmap(
                        text=text,
                        font_spec=el.font,
                        size_mm=el.size,
                        dpi=dpi,
                        server_cfg=self._server_cfg,
                        cfg_path=self._cfg_path,
                        font_weight=el.font_weight,
                        font_style=el.font_style,
                    )
                patch = rasterized_bitmap_to_pil_image(rb)
                _paste_l_mode(img, patch, ox + xd, oy + yd)
            elif el.type == "box":
                x1 = ox + mm_to_dots(el.x, dpi)
                y1 = oy + mm_to_dots(el.y, dpi)
                x2 = ox + mm_to_dots(el.x + el.width, dpi)
                y2 = oy + mm_to_dots(el.y + el.height, dpi)
                lw_dots = line_width_mm_to_box_dots(el.line_width, dpi)
                draw.rectangle([x1, y1, x2, y2], outline=0, width=max(1, int(lw_dots)))
            elif el.type == "circle":
                x0 = ox + mm_to_dots(el.x, dpi)
                y0 = oy + mm_to_dots(el.y, dpi)
                d_dots = max(1, mm_to_dots(el.diameter, dpi))
                t_dots = max(1, int(line_width_mm_to_box_dots(el.line_width, dpi)))
                draw.ellipse([x0, y0, x0 + d_dots, y0 + d_dots], outline=0, width=t_dots)
            elif el.type == "bitmap":
                try:
                    raw = base64.b64decode(el.data, validate=True)
                except (ValueError, binascii.Error) as e:
                    raise ValueError("bitmap data must be valid base64") from e
                xd = ox + mm_to_dots(el.x, dpi)
                yd = oy + mm_to_dots(el.y, dpi)
                wb = max(1, (el.width + 7) // 8)
                expect = wb * el.height
                if len(raw) != expect:
                    raise ValueError(
                        f"bitmap payload length {len(raw)} != expected {expect} for "
                        f"width={el.width} height={el.height}"
                    )
                patch = mono_tspl_payload_to_pil_image(wb, el.height, raw)
                _paste_l_mode(img, patch, xd, yd)
        if printer.direction == TSPL_DIRECTION_180:
            img = img.rotate(TSPL_PREVIEW_ROTATION_DEGREES, expand=False)
        return img

    def render_printer_test_pattern(self, label_size: LabelSize, printer: PrinterConfig) -> bytes:
        """One label with built-in TEXT and a raster BITMAP line; same geometry as normal jobs."""
        dpi = printer.dpi
        enc = printer.text_encoding
        preamble_b = build_label_preamble(
            width=label_size.width,
            height=label_size.height,
            gap=label_size.gap,
            dpi=dpi,
            direction=printer.direction,
            offset_x=printer.offset_x,
            offset_y=printer.offset_y,
        ).encode("ascii")
        x0 = mm_to_dots(TEST_LABEL_TEXT_MM_X, dpi)
        y0 = mm_to_dots(TEST_LABEL_TEXT_MM_Y, dpi)
        tx = build_text_command_bytes(x0, y0, "3", TEST_LABEL_BUILTIN_TEXT, enc)
        bx = mm_to_dots(TEST_LABEL_BITMAP_MM_X, dpi)
        by = mm_to_dots(TEST_LABEL_BITMAP_MM_Y, dpi)
        bmp = rasterize_text_bitmap(
            text=TEST_LABEL_RASTER_TEXT,
            font_spec=TEST_LABEL_RASTER_FONT,
            size_mm=TEST_LABEL_RASTER_SIZE_MM,
            dpi=dpi,
            server_cfg=self._server_cfg,
            cfg_path=self._cfg_path,
        )
        bcmd = build_bitmap_command_bytes(
            bx,
            by,
            bmp.width_bytes,
            bmp.height_dots,
            TSPL_BITMAP_MODE_OVERWRITE,
            bmp.payload,
        )
        return preamble_b + tx + bcmd + build_print_command(1).encode("ascii")
