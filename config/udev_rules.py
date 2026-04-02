"""Generate udev rules so group plugdev can open USB devices (libusb) for configured printers."""

from __future__ import annotations

import json
from pathlib import Path


def udev_rules_text_from_config_file(config_path: Path) -> str:
    """Build rules file contents from ``config.json`` printer vendor_id / product_id pairs."""
    data = json.loads(config_path.read_text(encoding="utf-8"))
    pairs: set[tuple[int, int]] = set()
    for p in data.get("printers", []):
        try:
            pairs.add((int(p["vendor_id"]), int(p["product_id"])))
        except (KeyError, TypeError, ValueError):
            continue
    lines = [
        "# TSPL netdriver — USB access for libusb (group plugdev). Regenerated when config is saved.",
        "# Service user must be in group plugdev (systemd SupplementaryGroups).",
    ]
    if not pairs:
        lines.append(
            "# No printers — add a printer in the UI, save config, then unplug/replug the device or reboot."
        )
    for vid, pid in sorted(pairs):
        lines.append(
            f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vid:04x}", ATTR{{idProduct}}=="{pid:04x}", '
            'MODE="0664", GROUP="plugdev"'
        )
    return "\n".join(lines) + "\n"
