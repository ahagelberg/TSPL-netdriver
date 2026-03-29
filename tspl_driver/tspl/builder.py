"""Build TSPL command strings: SIZE, GAP, DIRECTION, REFERENCE, TEXT, PRINT."""

from __future__ import annotations

# TSPL: SIZE/GAP use millimeters; TEXT coordinates and REFERENCE use dots (see TSC manual).
# Supported printers here only accept DIRECTION 0 (default) or 1 (180°).
TSPL_DIRECTION_DEFAULT = 0
TSPL_DIRECTION_180 = 1

TSPL_TEXT_ROTATION = 0
MM_PER_INCH = 25.4

# Decimal places for SIZE / GAP millimeter values in TSPL (TSC manual: SIZE w mm, h mm).
TSPL_MM_DECIMAL_PLACES = 2


def _format_mm_for_tspl(mm: float) -> str:
    s = f"{mm:.{TSPL_MM_DECIMAL_PLACES}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def mm_to_dots(mm: float, dpi: int) -> int:
    return max(0, int(round(mm * dpi / MM_PER_INCH)))


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
    """Opening commands before content (SIZE, GAP, DIRECTION, REFERENCE)."""
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
    """Single TSC TEXT line; escapes double quotes in payload."""
    safe = text.replace('"', "'")
    # TSPL/TS2 TEXT line: two comma-separated integers are mandatory before the string
    # (TSC TSPL/TSPL2 grammar); this driver does not expose them as options.
    return f'TEXT {x_dots},{y_dots},"{font}",{TSPL_TEXT_ROTATION},1,1,"{safe}"\r\n'


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
    x0 = mm_to_dots(2.0, dpi)
    y0 = mm_to_dots(2.0, dpi)
    body = build_text_command(x0, y0, "3", "TSPL test")
    end = build_print_command(1)
    return (preamble + body + end).encode("utf-8", errors="replace")
