# TSPL netdriver

Small **FastAPI** service: JSON configuration, API key, USB **TSPL** label printing, HTML UI at `/`.

**Architecture:** There is **no server-side proxy** from WordPress to TSPL: only the **browser** calls this API. The WordPress host does **not** need network access to the machine running TSPL. For cross-origin admin UIs, configure **CORS** on this service (see **[API.md](API.md)** → CORS).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp tspl_driver/config.example.json config.json
# Edit config.json — set server.api_key and bind_address/port as needed.
```

## Run

```bash
.venv/bin/python -m tspl_driver
```

Or set `TSPL_DRIVER_CONFIG` to an absolute path for the JSON config file.

Open the printed bind address (default `http://127.0.0.1:8787`). Paste the API key in the UI and click **Store key**.

## API

See **[API.md](API.md)**.

## Requirements

- Linux, **libusb** (e.g. `libusb-1.0-0`), and **PyUSB**. Printing is **only** via **USB bulk OUT** through libusb — the service does **not** open `/dev/usb/lp*`, `/dev/lp*`, `/dev/ttyACM*`, `/dev/ttyUSB*`, or raw **`/dev/bus/usb/...`** for a naive `write()`.
- **Permissions:** The process must be allowed to open the USB device for control/bulk transfers. Typical fixes: install **udev** rules matching your **VID/PID** (e.g. `SUBSYSTEM=="usb", ATTR{idVendor}=="1fc9", ATTR{idProduct}=="2016", MODE="0664", GROUP="plugdev"`) and run the service as a user in **`plugdev`**, or use **`TAG+="uaccess"`** where appropriate. Test temporarily with **root** only to confirm it is a permission issue.
