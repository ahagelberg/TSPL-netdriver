#!/usr/bin/env bash
# Install TSPL netdriver under /opt and register the systemd unit.
# Run from the repository (or any cwd); paths are derived from this script.
#
# Usage:
#   sudo ./install-to-opt.sh
# Optional environment overrides:
#   TSPL_INSTALL_ROOT=/opt/tspl-netdriver
#   TSPL_SERVICE_USER=tspl
#
set -euo pipefail

INSTALL_ROOT="${TSPL_INSTALL_ROOT:-/opt/tspl-netdriver}"
SERVICE_USER="${TSPL_SERVICE_USER:-tspl}"
SERVICE_NAME="tspl-netdriver.service"

REPO_ROOT=$(cd "$(dirname "$0")" && pwd)

RSYNC_EXCLUDES=(
  --exclude '.venv/'
  --exclude '.git/'
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude '*.pyo'
  --exclude '.pytest_cache/'
  --exclude '.mypy_cache/'
  --exclude '.cursor/'
  --exclude '.tspl-font-cache/'
  --exclude '*.egg-info/'
  --exclude 'dist/'
  --exclude 'build/'
  --exclude 'config.json'
)

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (e.g. sudo $0)." >&2
  exit 1
fi

if [[ ! -f "${REPO_ROOT}/pyproject.toml" ]] || [[ ! -f "${REPO_ROOT}/systemd/${SERVICE_NAME}" ]]; then
  echo "Expected a checkout at ${REPO_ROOT} (pyproject.toml and systemd/${SERVICE_NAME})." >&2
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required." >&2
  exit 1
fi

echo "Installing from ${REPO_ROOT} to ${INSTALL_ROOT}"

mkdir -p "${INSTALL_ROOT}"
# No --delete: preserve files under INSTALL_ROOT that are not in the repo (e.g. local config tweaks).
rsync -a "${RSYNC_EXCLUDES[@]}" "${REPO_ROOT}/" "${INSTALL_ROOT}/"

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir "${INSTALL_ROOT}" --shell /usr/sbin/nologin "${SERVICE_USER}"
  echo "Created system user ${SERVICE_USER}"
fi

if getent group plugdev >/dev/null 2>&1; then
  usermod -aG plugdev "${SERVICE_USER}"
fi

if [[ ! -f "${INSTALL_ROOT}/config.json" ]]; then
  cp "${INSTALL_ROOT}/config.example.json" "${INSTALL_ROOT}/config.json"
  echo "Created ${INSTALL_ROOT}/config.json from config.example.json — edit server.api_key and bind settings."
fi

chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_ROOT}"

if [[ ! -x "${INSTALL_ROOT}/.venv/bin/python" ]]; then
  sudo -u "${SERVICE_USER}" python3 -m venv "${INSTALL_ROOT}/.venv"
fi
sudo -u "${SERVICE_USER}" "${INSTALL_ROOT}/.venv/bin/pip" install --upgrade pip setuptools wheel
sudo -u "${SERVICE_USER}" "${INSTALL_ROOT}/.venv/bin/pip" install -e "${INSTALL_ROOT}"

install -m 644 "${INSTALL_ROOT}/systemd/${SERVICE_NAME}" "/etc/systemd/system/${SERVICE_NAME}"
systemctl daemon-reload

echo ""
echo "Installed ${INSTALL_ROOT} and /etc/systemd/system/${SERVICE_NAME}"
echo "Start and enable:"
echo "  systemctl enable --now ${SERVICE_NAME}"
echo "  systemctl status ${SERVICE_NAME}"
