"""Orchestration: resolve config, render TSPL, send to printer."""

from __future__ import annotations

from pathlib import Path

from config.models import AppConfig, LabelSize, ServerConfig, TemplateConfig, TemplateElement
from config.state import get_config_path
from printer.tspl_printer import TsplPrinter
from usb_access.subsystem import UsbSubsystem


def get_label_size(cfg: AppConfig, label_size_id: str) -> LabelSize:
    for ls in cfg.label_sizes:
        if ls.id == label_size_id:
            return ls
    raise KeyError(label_size_id)


class PrintService:
    def __init__(self, cfg_path: Path | None = None) -> None:
        self._cfg_path = cfg_path
        self._usb = UsbSubsystem()

    def _path(self) -> Path:
        return self._cfg_path if self._cfg_path is not None else get_config_path()

    def _make_tspl_printer(self, server_cfg: ServerConfig) -> TsplPrinter:
        return TsplPrinter(server_cfg, self._path())

    def print_template_job(
        self,
        cfg: AppConfig,
        *,
        template_id: str,
        printer_id: str,
        data: dict[str, str],
    ) -> int:
        tpl = next((t for t in cfg.templates if t.id == template_id), None)
        if tpl is None:
            raise ValueError(f"Unknown template {template_id!r}")
        pr = next((p for p in cfg.printers if p.id == printer_id), None)
        if pr is None:
            raise ValueError(f"Unknown printer {printer_id!r}")
        ls = get_label_size(cfg, tpl.label_size_id)
        merged = {**tpl.test_data, **data}
        payload = self._make_tspl_printer(cfg.server).render_template(tpl, ls, pr, merged)
        self._usb.send_tspl(pr, payload)
        return len(payload)

    def print_inline_label(
        self,
        cfg: AppConfig,
        *,
        printer_id: str,
        label_size: LabelSize,
        elements: list[TemplateElement],
        data: dict[str, str],
    ) -> int:
        pr = next((p for p in cfg.printers if p.id == printer_id), None)
        if pr is None:
            raise ValueError(f"Unknown printer {printer_id!r}")
        tpl = TemplateConfig(
            id="inline-template",
            name="Inline template",
            label_size_id=label_size.id,
            elements=elements,
            test_data={},
        )
        payload = self._make_tspl_printer(cfg.server).render_template(tpl, label_size, pr, data)
        self._usb.send_tspl(pr, payload)
        return len(payload)

    def print_template_test(
        self,
        cfg: AppConfig,
        *,
        template_id: str,
        printer_id: str,
        data: dict[str, str],
    ) -> int:
        return self.print_template_job(
            cfg,
            template_id=template_id,
            printer_id=printer_id,
            data=data,
        )

    def preview_template_png(
        self,
        cfg: AppConfig,
        *,
        printer_id: str,
        label_size_id: str,
        elements: list[TemplateElement],
        test_data: dict[str, str],
        data: dict[str, str],
    ) -> bytes:
        pr = next((p for p in cfg.printers if p.id == printer_id), None)
        if pr is None:
            raise ValueError(f"Unknown printer {printer_id!r}")
        ls = get_label_size(cfg, label_size_id)
        merged = {**test_data, **data}
        tpl = TemplateConfig(
            id="preview",
            name="preview",
            label_size_id=label_size_id,
            elements=elements,
            test_data=test_data,
        )
        return self._make_tspl_printer(cfg.server).render_template_to_png_bytes(tpl, ls, pr, merged)

    def print_printer_test(self, cfg: AppConfig, *, printer_id: str) -> int:
        pr = next((p for p in cfg.printers if p.id == printer_id), None)
        if pr is None:
            raise ValueError(f"Unknown printer {printer_id!r}")
        ls = get_label_size(cfg, pr.default_label_size_id)
        payload = self._make_tspl_printer(cfg.server).render_printer_test_pattern(ls, pr)
        self._usb.send_tspl(pr, payload)
        return len(payload)
