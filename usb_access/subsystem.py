"""Send TSPL to the printer via USB bulk OUT (libusb / PyUSB only)."""

from __future__ import annotations

import errno
import logging

import usb.core

from config.models import PrinterConfig
from app_logging.runtime_log import LOGGER_NAME
from usb_access.bulk import UsbBulkDeviceNotFoundError, write_tspl_usb_bulk
from usb_access.discover import UsbDeviceEntry, list_usb_devices, name_suggests_tspl_printer

_log = logging.getLogger(f"{LOGGER_NAME}.usb_access.subsystem")

# Cap debug log size so a huge job does not flood stderr.
TSPL_DEBUG_LOG_MAX_CHARS = 65536
TSPL_DEBUG_TRUNCATION_MARKER = "\n... [TSPL debug log truncated]\n"


def _tspl_payload_for_debug_log(payload: bytes) -> str:
    """UTF-8 text for DEBUG logs; invalid bytes become U+FFFD."""
    text = payload.decode("utf-8", errors="replace")
    if len(text) > TSPL_DEBUG_LOG_MAX_CHARS:
        return text[: TSPL_DEBUG_LOG_MAX_CHARS] + TSPL_DEBUG_TRUNCATION_MARKER
    return text


class PrinterDeviceNotFoundError(Exception):
    """No USB device or bulk OUT endpoint matches the configured printer."""


def send_tspl_to_printer(printer: PrinterConfig, payload: bytes) -> None:
    """
    Write TSPL through libusb bulk OUT to the device selected by VID/PID,
    optional usb_port_path (Linux sysfs name), and optional serial when port is unset.
    """
    if _log.isEnabledFor(logging.DEBUG):
        _log.debug(
            "send_tspl_to_printer printer=%s vid=%#06x pid=%#06x serial=%s port=%s bytes=%d",
            printer.id,
            printer.vendor_id,
            printer.product_id,
            printer.serial,
            printer.usb_port_path,
            len(payload),
        )
        _log.debug(
            "TSPL sent to printer %s:\n%s",
            printer.id,
            _tspl_payload_for_debug_log(payload),
        )
    try:
        write_tspl_usb_bulk(
            printer.vendor_id,
            printer.product_id,
            printer.serial,
            payload,
            printer.usb_port_path,
        )
    except UsbBulkDeviceNotFoundError as e:
        hint = ""
        if printer.usb_port_path:
            hint = f" port {printer.usb_port_path!r}"
        elif printer.serial:
            hint = f" serial {printer.serial!r}"
        raise PrinterDeviceNotFoundError(
            f"No USB bulk device for {printer.vendor_id:#06x}:{printer.product_id:#06x}{hint}"
        ) from e
    except usb.core.USBError as e:
        raise OSError(errno.EIO, f"USB bulk write failed: {e}") from e


class UsbSubsystem:
    """Coordinates USB discovery (udev) and TSPL bulk OUT (libusb)."""

    def discover_devices(self, *, show_all: bool) -> tuple[list[UsbDeviceEntry], int, int]:
        all_devices = list_usb_devices()
        name_matched = [
            x for x in all_devices if name_suggests_tspl_printer(x.manufacturer, x.product)
        ]
        listed = all_devices if show_all else name_matched
        return listed, len(all_devices), len(name_matched)

    def send_tspl(self, printer: PrinterConfig, payload: bytes) -> None:
        send_tspl_to_printer(printer, payload)
