#!/usr/bin/env bash
# Remove TSPL netdriver install created by install-to-opt.sh (systemd, sudoers, udev, /opt tree, service user).
# Does not remove the system group plugdev (may be used by other packages).
#
# Usage:
#   sudo ./uninstall-to-opt.sh --yes
# Optional environment overrides (must match what you used for install):
#   TSPL_INSTALL_ROOT=/opt/tspl-netdriver
#   TSPL_SERVICE_USER=tspl
#
set -euo pipefail

INSTALL_ROOT="${TSPL_INSTALL_ROOT:-/opt/tspl-netdriver}"
SERVICE_USER="${TSPL_SERVICE_USER:-tspl}"
SERVICE_NAME="tspl-netdriver.service"
SUDOERS_D="/etc/sudoers.d/tspl-netdriver"
# Must match refresh_udev_from_config.py (UDEV_RULES_PATH) — only file this app writes under rules.d.
UDEV_RULES="/etc/udev/rules.d/70-tspl-netdriver.rules"
SYSTEMD_UNIT="/etc/systemd/system/${SERVICE_NAME}"

if [[ -z "${INSTALL_ROOT}" || "${INSTALL_ROOT}" == "/" ]]; then
  echo "Refusing unsafe TSPL_INSTALL_ROOT." >&2
  exit 1
fi
case "${INSTALL_ROOT}" in
  /*) ;;
  *)
    echo "TSPL_INSTALL_ROOT must be an absolute path." >&2
    exit 1
    ;;
esac

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (e.g. sudo $0 --yes)." >&2
  exit 1
fi

if [[ "${1:-}" != "--yes" ]]; then
  echo "This will:"
  echo "  - stop and disable ${SERVICE_NAME}"
  echo "  - remove ${SYSTEMD_UNIT}, ${SUDOERS_D}, ${UDEV_RULES}"
  echo "  - delete ${INSTALL_ROOT}"
  echo "  - remove user ${SERVICE_USER} only if their home directory is ${INSTALL_ROOT} (install layout)"
  echo "It will not remove the plugdev group."
  echo "Run: sudo $0 --yes"
  exit 1
fi

systemctl disable --now "${SERVICE_NAME}" 2>/dev/null || true
rm -f "${SYSTEMD_UNIT}"
systemctl daemon-reload

rm -f "${SUDOERS_D}"

rm -f "${UDEV_RULES}"
if command -v udevadm >/dev/null 2>&1; then
  udevadm control --reload-rules
  udevadm trigger --subsystem-match=usb
fi

if id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  USER_HOME=$(getent passwd "${SERVICE_USER}" | cut -d: -f6)
  if [[ "${USER_HOME}" == "${INSTALL_ROOT}" ]]; then
    userdel -r "${SERVICE_USER}"
  else
    echo "User ${SERVICE_USER} home is ${USER_HOME}, not ${INSTALL_ROOT}; leaving the account. Removing install tree only."
    rm -rf "${INSTALL_ROOT}"
  fi
else
  rm -rf "${INSTALL_ROOT}"
fi

echo "TSPL netdriver uninstall finished (${INSTALL_ROOT}, systemd, sudoers, udev rules)."
