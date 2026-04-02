# TSPL netdriver

Small **FastAPI** service: JSON configuration, API key, USB **TSPL** label printing, HTML UI at `/`.

**Architecture:** There is **no server-side proxy** from WordPress to TSPL: only the **browser** calls this API. The WordPress host does **not** need network access to the machine running TSPL. For cross-origin admin UIs, configure **CORS** on this service (see **[API.md](API.md)** → CORS).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp config.example.json config.json
# Edit config.json — set server.api_key and bind_address/port as needed.
```

Run **`pip install -e .`** again after `git pull` whenever packages or `[tool.setuptools]` in `pyproject.toml` change (new folders under the project root). Otherwise the `tspl-driver` console script may fail with `ModuleNotFoundError` for a package that exists on disk.

## Run

From the repository root:

```bash
./start
```

Verbose logging to stderr (driver + uvicorn):

```bash
./start --log debug
```

Or invoke the installed entry point directly:

```bash
.venv/bin/tspl-driver
.venv/bin/tspl-driver --log debug
```

Or run without going through the console script (adds the repo root to `sys.path`):

```bash
.venv/bin/python __main__.py
.venv/bin/python __main__.py --log debug
```

**Config file path:** By default the service reads `./config.json` next to the process working directory. Override with an absolute path:

```bash
export TSPL_DRIVER_CONFIG=/path/to/config.json
./start
```

Open the printed bind address (default `http://127.0.0.1:8787`). Paste the API key in the UI and click **Store key**.

## Install to `/opt` and systemd

From a clone of this repository (requires **rsync**):

```bash
sudo ./install-to-opt.sh
```

This copies the tree to `/opt/tspl-netdriver` (excluding `.venv`, `.git`, `config.json`, caches), creates group **`plugdev`** if missing, creates a system user **`tspl`** and adds it to **`plugdev`**, installs **`/etc/sudoers.d/tspl-netdriver`** so **`tspl`** may run **`/usr/bin/python3 /opt/tspl-netdriver/refresh_udev_from_config.py`** as root without a password (that script writes udev rules for USB), runs **`refresh_udev_from_config.py`** once, runs **`pip install -e .`**, seeds **`config.json`** from the example if missing, installs **`systemd/tspl-netdriver.service`** into `/etc/systemd/system/`, and reloads **systemd**.

**Overrides:** `TSPL_INSTALL_ROOT` (default `/opt/tspl-netdriver`), `TSPL_SERVICE_USER` (default `tspl`).

After saving configuration in the UI (or **`PUT /api/v1/config`**), the service refreshes **`/etc/udev/rules.d/70-tspl-netdriver.rules`** from the printers in **`config.json`** via that sudo rule—no root login required. Unplug/replug the printer or reboot if the device node still has old permissions. Re-run **`install-to-opt.sh`** after upgrades to refresh the installed files and sudoers line.

Then:

```bash
sudo systemctl enable --now tspl-netdriver.service
```

### Uninstall (`/opt` install)

Removes the systemd unit, sudoers drop-in, udev rules file, and the install directory (including **`config.json`** and the venv). Removes the service user **only** if their home directory equals the install root (as created by **`install-to-opt.sh`**); otherwise it deletes the tree only and leaves that account alone. Does **not** delete the system **`plugdev`** group.

```bash
sudo ./uninstall-to-opt.sh --yes
```

Use the same **`TSPL_INSTALL_ROOT`** / **`TSPL_SERVICE_USER`** as for install if you overrode them.

## Layout (Python packages)

| Package        | Role |
|----------------|------|
| `api`          | FastAPI app, JSON schemas, CLI entry (`run`) |
| `config`       | Pydantic models for `config.json`, load/save, process-wide config path |
| `printer`      | TSPL building, rendering, template/print orchestration |
| `usb_access`   | USB discovery (udev) and TSPL over USB bulk OUT (PyUSB) |
| `app_logging`  | Shared logger name and `--log` / JSON error diagnostics |

Root modules include `main` (re-exports `api.app` for compatibility).

## API

See **[API.md](API.md)**.

## Requirements

- Linux, **libusb** (e.g. `libusb-1.0-0`), and **PyUSB**. Printing is **only** via **USB bulk OUT** through libusb — the service does **not** open `/dev/usb/lp*`, `/dev/lp*`, `/dev/ttyACM*`, `/dev/ttyUSB*`, or raw **`/dev/bus/usb/...`** for a naive `write()`.
- **Permissions:** The service user must be able to open the raw USB device nodes under **`/dev/bus/usb/`** (PyUSB / libusb). **`install-to-opt.sh`** adds **`tspl`** to **`plugdev`**, installs passwordless **`sudo`** for **`refresh_udev_from_config.py`** only, and writes initial udev rules. Saving **`config.json`** (UI or API) runs that script so new printers get udev entries at runtime. **`SupplementaryGroups=plugdev`** is set in the shipped systemd unit. For a dev install without the script, add equivalent **udev** rules and **sudo**/group setup yourself.
