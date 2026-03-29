"""Linux USB sysfs-style names (bus + port chain) to disambiguate identical VID/PID/serial."""

from __future__ import annotations

import usb.core


def linux_usb_sys_name_from_pyusb(dev: usb.core.Device) -> str | None:
    """
    Build the same string as udev/sysfs usb_device sys_name (e.g. 1-2.3).
    Used to pick one device when iSerial duplicates or is wrong.
    """
    bus = dev.bus
    pnums = getattr(dev, "port_numbers", None)
    if bus is None or not pnums:
        return None
    return f"{int(bus)}-{'.'.join(str(p) for p in pnums)}"
