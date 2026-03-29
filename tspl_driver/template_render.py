"""Fill template elements and emit TSPL bytes."""

from __future__ import annotations

import re

from tspl_driver.models import AppConfig, LabelSize, PrinterConfig, TemplateConfig
from tspl_driver.tspl.builder import (
    build_label_preamble,
    build_print_command,
    build_text_command,
    mm_to_dots,
)

_PLACEHOLDER_RE = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")


def required_placeholder_keys(template: TemplateConfig) -> set[str]:
    keys: set[str] = set()
    for el in template.elements:
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


def render_template_tspl(
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
    preamble = build_label_preamble(
        width_mm=label_size.width_mm,
        height_mm=label_size.height_mm,
        gap_mm=label_size.gap_mm,
        dpi=dpi,
        direction=printer.direction,
        offset_x_mm=printer.offset_x_mm,
        offset_y_mm=printer.offset_y_mm,
    )
    parts: list[str] = [preamble]
    for el in template.elements:
        text = fill_placeholders(el.content, data)
        xd = mm_to_dots(el.x_mm, dpi)
        yd = mm_to_dots(el.y_mm, dpi)
        parts.append(build_text_command(xd, yd, el.font, text))
    parts.append(build_print_command(1))
    return "".join(parts).encode("utf-8", errors="replace")


def get_label_size(cfg: AppConfig, label_size_id: str) -> LabelSize:
    for ls in cfg.label_sizes:
        if ls.id == label_size_id:
            return ls
    raise KeyError(label_size_id)
