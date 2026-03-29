"""Send TSPL to the printer via USB bulk OUT (libusb / PyUSB only)."""

from __future__ import annotations

import errno
import logging

import usb.core

from tspl_driver.models import PrinterConfig
from tspl_driver.runtime_log import LOGGER_NAME
from tspl_driver.usb_bulk import UsbBulkDeviceNotFoundError, write_tspl_usb_bulk

_log = logging.getLogger(f"{LOGGER_NAME}.print_usb")

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
    Write TSPL through libusb bulk OUT to the device selected by VID/PID and
    optional serial.
    """
    if _log.isEnabledFor(logging.DEBUG):
        _log.debug(
            "send_tspl_to_printer printer=%s vid=%#06x pid=%#06x serial=%s bytes=%d",
            printer.id,
            printer.vendor_id,
            printer.product_id,
            printer.serial,
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
        )
    except UsbBulkDeviceNotFoundError as e:
        raise PrinterDeviceNotFoundError(
            f"No USB bulk device for {printer.vendor_id:#06x}:{printer.product_id:#06x}"
            + (f" serial {printer.serial!r}" if printer.serial else "")
        ) from e
    except usb.core.USBError as e:
        raise OSError(errno.EIO, f"USB bulk write failed: {e}") from e
