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
- **Permissions:** The process must be allowed to open the USB device for control/bulk transfers. Typical fixes: install **udev** rules matching your **VID/PID** (e.g. `SUBSYSTEM=="usb", ATTR{idVendor}=="1fc9", ATTR{idProduct}=="2016", MODE="0664", GROUP="plugdev"`) and run the service as a user in **`plugdev`**, or use **`TAG+="uaccess"`** where appropriate. Test temporarily with **root** only to confirm it is a permission issue.
