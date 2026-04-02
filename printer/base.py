"""Printer abstraction: TSPL implementation in tspl_printer."""

from __future__ import annotations

from abc import ABC, abstractmethod

from config.models import LabelSize, PrinterConfig, TemplateConfig


class Printer(ABC):
    """Renders label jobs to TSPL bytes for a target printer configuration."""

    @abstractmethod
    def render_template(
        self,
        template: TemplateConfig,
        label_size: LabelSize,
        printer: PrinterConfig,
        data: dict[str, str],
    ) -> bytes:
        """Full template job including preamble and PRINT."""

    @abstractmethod
    def render_printer_test_pattern(
        self,
        label_size: LabelSize,
        printer: PrinterConfig,
    ) -> bytes:
        """Hardware self-test label (TEXT + raster)."""
