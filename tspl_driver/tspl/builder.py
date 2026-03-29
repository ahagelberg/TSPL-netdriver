"""Build TSPL command strings: SIZE, GAP, DIRECTION, REFERENCE, TEXT, PRINT."""

from __future__ import annotations

import codecs
import math

# TSPL: SIZE/GAP use millimeters; TEXT coordinates and REFERENCE use dots (see TSC manual).
# Supported printers here only accept DIRECTION 0 (default) or 1 (180°).
TSPL_DIRECTION_DEFAULT = 0
TSPL_DIRECTION_180 = 1

TSPL_TEXT_ROTATION = 0
MM_PER_INCH = 25.4
# TSPL BOX fifth parameter is line thickness in dots; must not be 0.
TSPL_BOX_LINE_MIN_DOTS = 1
# Test label: TEXT position from label origin (mm).
TEST_LABEL_MARGIN_MM = 2.0

# Decimal places for SIZE / GAP millimeter values in TSPL (TSC manual: SIZE w mm, h mm).
TSPL_MM_DECIMAL_PLACES = 2


def _format_mm_for_tspl(mm: float) -> str:
    s = f"{mm:.{TSPL_MM_DECIMAL_PLACES}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def mm_to_dots(mm: float, dpi: int) -> int:
    return max(0, int(round(mm * dpi / MM_PER_INCH)))


def line_width_mm_to_box_dots(line_width_mm: float, dpi: int) -> int:
    """Border width in mm → TSPL BOX thickness in dots (ceil, never 0 for positive mm)."""
    raw = line_width_mm * dpi / MM_PER_INCH
    return max(TSPL_BOX_LINE_MIN_DOTS, int(math.ceil(raw)))


def build_label_preamble(
    *,
    width_mm: float,
    height_mm: float,
    gap_mm: float,
    dpi: int,
    direction: int,
    offset_x_mm: float,
    offset_y_mm: float,
) -> str:
    """Opening commands before content (CLS, SIZE, GAP, DIRECTION, REFERENCE)."""
    off_x = mm_to_dots(offset_x_mm, dpi)
    off_y = mm_to_dots(offset_y_mm, dpi)
    if direction not in (TSPL_DIRECTION_DEFAULT, TSPL_DIRECTION_180):
        direction = TSPL_DIRECTION_DEFAULT
    w_mm = _format_mm_for_tspl(width_mm)
    h_mm = _format_mm_for_tspl(height_mm)
    g_mm = _format_mm_for_tspl(gap_mm)
    lines = [
        "CLS",
        f"SIZE {w_mm} mm,{h_mm} mm",
        f"GAP {g_mm} mm,0 mm",
        f"DIRECTION {direction}",
        f"REFERENCE {off_x},{off_y}",
    ]
    return "\r\n".join(lines) + "\r\n"


def build_text_command(
    x_dots: int,
    y_dots: int,
    font: str,
    text: str,
) -> str:
    """Single TSC TEXT line (UTF-8 job); prefer build_text_command_bytes for other encodings."""
    safe = text.replace('"', "'")
    return f'TEXT {x_dots},{y_dots},"{font}",{TSPL_TEXT_ROTATION},1,1,"{safe}"\r\n'


def build_text_command_bytes(
    x_dots: int,
    y_dots: int,
    font: str,
    text: str,
    encoding: str,
) -> bytes:
    """Single TEXT line: ASCII prefix/suffix, quoted payload encoded with the printer codec."""
    try:
        codecs.lookup(encoding)
    except LookupError:
        encoding = "utf-8"
    safe = text.replace('"', "'")
    payload = safe.encode(encoding, errors="replace")
    head = (
        f'TEXT {x_dots},{y_dots},"{font}",{TSPL_TEXT_ROTATION},1,1,"'.encode("ascii")
    )
    return head + payload + b'"\r\n'


def build_box_command(
    x1_dots: int,
    y1_dots: int,
    x2_dots: int,
    y2_dots: int,
    line_width_dots: int,
) -> bytes:
    """TSPL BOX: outline from (x1,y1) to (x2,y2); coordinates and thickness in dots (TSC manual)."""
    x_lo = min(x1_dots, x2_dots)
    x_hi = max(x1_dots, x2_dots)
    y_lo = min(y1_dots, y2_dots)
    y_hi = max(y1_dots, y2_dots)
    lw = max(TSPL_BOX_LINE_MIN_DOTS, line_width_dots)
    return f"BOX {x_lo},{y_lo},{x_hi},{y_hi},{lw}\r\n".encode("ascii")


def build_print_command(copies: int = 1) -> str:
    return f"PRINT {copies},1\r\n"


def build_test_label_tspl(
    *,
    width_mm: float,
    height_mm: float,
    gap_mm: float,
    dpi: int,
    direction: int,
    offset_x_mm: float,
    offset_y_mm: float,
    text_encoding: str = "utf-8",
) -> bytes:
    """Minimal test pattern; caller supplies the same geometry as a real job (label + printer)."""
    preamble = build_label_preamble(
        width_mm=width_mm,
        height_mm=height_mm,
        gap_mm=gap_mm,
        dpi=dpi,
        direction=direction,
        offset_x_mm=offset_x_mm,
        offset_y_mm=offset_y_mm,
    )
    x0 = mm_to_dots(TEST_LABEL_MARGIN_MM, dpi)
    y0 = mm_to_dots(TEST_LABEL_MARGIN_MM, dpi)
    body = build_text_command_bytes(x0, y0, "3", "TSPL test", text_encoding)
    end = build_print_command(1).encode("ascii")
    return preamble.encode("ascii") + body + end
