"""USB bulk OUT for TSPL via libusb (PyUSB) — the only print transport for this service."""

from __future__ import annotations

import errno
import logging
from typing import Any, cast

import usb.core
import usb.util

from tspl_driver.runtime_log import LOGGER_NAME
from tspl_driver.usb_discover import usb_serial_matches

_log = logging.getLogger(f"{LOGGER_NAME}.usb_bulk")

# Max bytes per usb_bulk write (stay below typical 16 KiB high-speed limits).
USB_BULK_CHUNK_BYTES = 8192


class UsbBulkDeviceNotFoundError(Exception):
    """No matching USB device or no bulk OUT endpoint."""


def _pick_bulk_out_endpoint(dev: usb.core.Device) -> tuple[usb.core.Interface, Any]:
    """First interface with a BULK OUT endpoint (typical vendor-class TSPL gadgets)."""
    try:
        dev.set_configuration()
    except usb.core.USBError as e:
        _log.debug("set_configuration: %s (continuing if device already configured)", e)
    cfg = dev.get_active_configuration()
    for intf in cfg:
        ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: (
                usb.util.endpoint_direction(cast(int, e.bEndpointAddress))
                == usb.util.ENDPOINT_OUT
                and usb.util.endpoint_type(cast(int, e.bmAttributes))
                == usb.util.ENDPOINT_TYPE_BULK
            ),
        )
        if ep_out is not None:
            return intf, ep_out
    raise UsbBulkDeviceNotFoundError("No bulk OUT endpoint on this USB configuration")


def _detach_kernel_drivers(dev: usb.core.Device, intf: usb.core.Interface) -> None:
    n = intf.bInterfaceNumber
    try:
        if dev.is_kernel_driver_active(n):
            dev.detach_kernel_driver(n)
    except (NotImplementedError, usb.core.USBError) as e:
        _log.debug("detach_kernel_driver(%s): %s", n, e)


def find_usb_device(
    vendor_id: int,
    product_id: int,
    serial: str | None,
) -> usb.core.Device | None:
    """Locate device by VID/PID and optional serial (iSerial)."""
    found = list(
        usb.core.find(find_all=True, idVendor=vendor_id, idProduct=product_id)
    )
    if not found:
        return None
    if serial is None:
        return found[0]
    for dev in found:
        sn = None
        if dev.iSerialNumber:
            try:
                sn = usb.util.get_string(dev, dev.iSerialNumber)
            except (usb.core.USBError, ValueError) as e:
                # ValueError: no langid — often descriptor read denied until claimed/opened.
                _log.debug("USB serial string unreadable: %s", e)
                sn = None
        if usb_serial_matches(sn, serial):
            return dev
    return None


def write_tspl_usb_bulk(
    vendor_id: int,
    product_id: int,
    serial: str | None,
    payload: bytes,
) -> None:
    """
    Send TSPL bytes via USB bulk OUT (no kernel printer/tty driver on the data path).
    Requires permission to access the raw USB device (udev, plugdev, or root).
    """
    dev = find_usb_device(vendor_id, product_id, serial)
    if dev is None:
        raise UsbBulkDeviceNotFoundError(
            f"No USB device {vendor_id:#06x}:{product_id:#06x}"
            + (f" serial {serial!r}" if serial else "")
        )
    intf, ep_out = _pick_bulk_out_endpoint(dev)
    _detach_kernel_drivers(dev, intf)
    usb.util.claim_interface(dev, intf.bInterfaceNumber)
    try:
        offset = 0
        while offset < len(payload):
            chunk = payload[offset : offset + USB_BULK_CHUNK_BYTES]
            written = ep_out.write(chunk)
            if written <= 0:
                raise OSError(
                    errno.EIO,
                    "USB bulk write returned no progress",
                )
            offset += written
    finally:
        try:
            usb.util.release_interface(dev, intf.bInterfaceNumber)
        except usb.core.USBError:
            pass
        dr = getattr(dev, "dispose_resources", None)
        if callable(dr):
            try:
                dr()
            except Exception:
                pass
