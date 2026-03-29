"""Enumerate USB devices (pyudev) for USB identity — VID/PID/serial for libusb matching."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import pyudev

# Name substrings (lowercase) for UI filter “likely label printer”.
NAME_HINT_SUBSTRING_PRINTER = "printer"
NAME_HINT_SUBSTRING_XPRINTER = "xprinter"


def usb_device_key(
    vendor_id: int,
    product_id: int,
    serial: str | None,
) -> str:
    """Stable id for UI rows and dedup: lowercase hex VID/PID plus serial string."""
    sn = (serial or "").strip()
    return f"{vendor_id:04x}:{product_id:04x}:{sn}"


@dataclass(frozen=True)
class UsbDeviceEntry:
    """One USB gadget from udev with identity fields for matching the libusb device."""

    device_key: str
    label: str
    vendor_id: int
    product_id: int
    serial: str | None
    manufacturer: str | None
    product: str | None


def name_suggests_tspl_printer(
    manufacturer: str | None, product: str | None
) -> bool:
    blob = f"{manufacturer or ''} {product or ''}".lower()
    return (
        NAME_HINT_SUBSTRING_PRINTER in blob
        or NAME_HINT_SUBSTRING_XPRINTER in blob
    )


def usb_serial_matches(a: str | None, b: str | None) -> bool:
    """USB serial strings from udev vs config may differ in case or whitespace."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return a.strip().upper() == b.strip().upper()


def _format_dropdown_label(
    manufacturer: str | None,
    product: str | None,
    vendor_id: int,
    product_id: int,
) -> str:
    left = f"{(manufacturer or '').strip()} — {(product or '').strip()}".strip(" —")
    if not left:
        left = "USB device"
    return f"{left} ({vendor_id:04X}:{product_id:04X})"


def _parse_id(device: pyudev.Device, key: str) -> int | None:
    raw = device.properties.get(key)
    if raw is None:
        return None
    raw = raw.strip()
    try:
        return int(raw, 16)
    except ValueError:
        try:
            return int(raw)
        except ValueError:
            return None


def _merge_usb_entries_by_key(entries: list[UsbDeviceEntry]) -> list[UsbDeviceEntry]:
    """Same VID/PID/serial can appear twice; collapse to one row."""
    groups: dict[str, list[UsbDeviceEntry]] = defaultdict(list)
    for e in entries:
        groups[e.device_key].append(e)
    return [g[0] for g in groups.values()]


def list_usb_devices() -> list[UsbDeviceEntry]:
    """Walk kernel USB devices (pyudev usb_device). Identity only — no /dev node for printing."""
    context = pyudev.Context()
    raw: list[UsbDeviceEntry] = []

    for device in context.list_devices(subsystem="usb"):
        if device.properties.get("DEVTYPE") != "usb_device":
            continue
        vid = _parse_id(device, "ID_VENDOR_ID")
        pid = _parse_id(device, "ID_MODEL_ID")
        if vid is None or pid is None:
            continue
        serial = device.properties.get("ID_SERIAL_SHORT") or device.properties.get(
            "ID_SERIAL"
        )
        if serial is not None and serial == "":
            serial = None
        mfr = device.properties.get("ID_VENDOR_FROM_DATABASE") or device.properties.get(
            "ID_VENDOR"
        )
        prod = device.properties.get("ID_MODEL_FROM_DATABASE") or device.properties.get(
            "ID_MODEL"
        )
        key = usb_device_key(vid, pid, serial)
        label = _format_dropdown_label(mfr, prod, vid, pid)
        raw.append(
            UsbDeviceEntry(
                device_key=key,
                label=label,
                vendor_id=vid,
                product_id=pid,
                serial=serial,
                manufacturer=mfr,
                product=prod,
            )
        )

    out = _merge_usb_entries_by_key(raw)
    out.sort(key=lambda e: e.label.lower())
    return out
