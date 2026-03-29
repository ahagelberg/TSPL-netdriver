# TSPL driver HTTP API

Base path for JSON API: **`/api/v1`**. Request bodies use **`Content-Type: application/json`** unless noted.

The service also serves **`GET /`** (HTML UI) and static files under **`/static/`** without API authentication. **All `/api/v1/...` routes require authentication** (see below).

Printing to hardware uses **USB bulk OUT** (libusb); the API does not use kernel printer nodes or CUPS.

---

## Authentication

Send the shared secret from `config.json` → **`server.api_key`** using **one** of:

- `Authorization: Bearer <api_key>`
- `X-API-Key: <api_key>`

Missing or wrong key → **`401`**:

```json
{ "ok": false, "error": { "code": "unauthorized", "message": "Invalid or missing API key" } }
```

---

## CORS (browser clients)

When **JavaScript in the browser** (for example WordPress admin) calls this API from a **different origin** than the TSPL service, the browser enforces CORS. **WordPress PHP does not need to reach the printer**; only the **user’s browser** must be able to reach the TSPL host.

Configure allowed origins in **`config.json`** → **`server.cors_origins`**: a JSON array of full origins, e.g. **`["https://your-wordpress-site.com"]`**. The browser’s **`Origin`** must match an allowed entry (scheme, host, port, no trailing slash). This service **also** allows the **other** of **`http://`** / **`https://`** for the **same host and port**, and **`www.`** vs apex hostname for the **same port** (so listing **`https://invize.se`** also allows **`http://www.invize.se`**, etc.). **IPs** (e.g. the TSPL host) and **`localhost`** are not expanded. Subdomains other than **`www`** still need to be listed explicitly. The service must echo **`Access-Control-Allow-Origin`** for that origin on API responses (and preflight). Prefer the real site origin and keep **`server.api_key`** secret; **`"*"`** is only for quick tests.

If **`server.cors_origins`** is empty, you can set environment variable **`TSPL_CORS_ORIGINS`** to a comma-separated list of origins (same semantics as the config array). Non-empty **`server.cors_origins`** takes precedence over the env var.

**Typical headers** (when CORS is enabled and the request **`Origin`** matches):

- **`Access-Control-Allow-Origin`**: the matching origin (or `*` if configured that way)
- **`Access-Control-Allow-Methods`**: `GET`, `POST`, `OPTIONS`
- **`Access-Control-Allow-Headers`**: `Authorization`, `Content-Type`, `Accept`, `X-API-Key`

**Preflight:** Browsers send **`OPTIONS`** before some cross-origin requests. Starlette answers most preflights with **`200`** and an empty body; the service also registers **`OPTIONS`** on **`/api/v1/*`** so preflight never falls through as **`405 Method Not Allowed`**. **`GET`**, **`POST`**, and **`OPTIONS`** are allowed.

**Private network (Chrome):** Requests from a **public** origin (e.g. `https://invize.se`) to a **private** LAN address (e.g. `http://192.168.x.x`) use an extra preflight (`Access-Control-Request-Private-Network`). This server sets **`allow_private_network`** in CORS middleware so that preflight can succeed.

**Process restart:** CORS origins are fixed when the process starts. After changing **`server.cors_origins`** or **`TSPL_CORS_ORIGINS`**, **restart** the TSPL service so new values apply.

---

## Response shape

- **Success:** `{ "ok": true, "data": … }`
- **Error (most failures):** `{ "ok": false, "error": { "code": "<string>", "message": "<string>", … } }`

Optional **`error`** fields when the process was started with **`--log`** (any level):

- **`errno`**, **`strerror`**, **`filename`** — present for **`OSError`** (e.g. USB I/O).
- **`traceback`** — full traceback only when log level is **DEBUG**.

**Request body validation** (malformed JSON or invalid body shape for FastAPI/Pydantic) → **`422`** with `code: "validation_error"` and a **`message`** derived from validation details.

---

## Error `code` values (non-exhaustive)

| `code` | Typical HTTP | Meaning |
|--------|----------------|--------|
| `unauthorized` | 401 | Bad or missing API key |
| `not_found` | 404 | Unknown template, printer, or label reference |
| `validation_error` | 422 | Request body / query validation failed |
| `render_error` | 422 | Template render failed (e.g. missing placeholder keys) |
| `config_error` | 422 | Config inconsistent (e.g. printer test with missing default label size) |
| `device_not_found` | 503 | No matching USB device for the printer’s VID/PID/serial |
| `io_error` | 503 | USB or other I/O failure while sending to the printer |
| `http_error` | varies | Generic handler error |

---

## Endpoints

| Method | Path | Body | Success `data` |
|--------|------|------|----------------|
| `GET` | `/api/v1/health` | — | `{ "status": "ok" }` |
| `GET` | `/api/v1/config` | — | Full config object (see **Config** below) |
| `PUT` | `/api/v1/config` | Full config object | Same object as saved |
| `GET` | `/api/v1/usb/discover` | Query: optional `show_all` | See **USB discover** |
| `POST` | `/api/v1/print/template` | [Template print body](#post-apiv1printtemplate) | `{ "printed": true }` |
| `POST` | `/api/v1/print/raw` | [Raw print body](#post-apiv1printraw) | `{ "printed": true }` |
| `POST` | `/api/v1/printers/{printer_id}/test` | `{}` (empty JSON object) | `{ "tested": true }` |
| `POST` | `/api/v1/templates/{template_id}/test` | [Template test body](#post-apiv1templatestemplate_idtest) | `{ "tested": true }` |

Path parameters **`printer_id`** and **`template_id`** are the corresponding **`id`** strings from config.

---

### `GET /api/v1/usb/discover`

**Query parameters**

- **`show_all`** (optional, default `false`): If `true`, **`devices`** lists every USB gadget returned by enumeration. If `false`, **`devices`** only includes gadgets whose **manufacturer** / **product** string contains **`printer`** or **`xprinter`** (case-insensitive).

**Success `data`**

- **`devices`:** Array of objects:
  - **`device_key`** — Stable string: lowercase hex **`vid`**, **`pid`**, and **`serial`** as `vvvv:pppp:<serial>`, where `<serial>` is the raw serial string or empty if none (e.g. `1fc9:2016:0123456789AB`).
  - **`label`** — Short display string (manufacturer/product and IDs).
  - **`vendor_id`**, **`product_id`** — Integers `0`…`65535`.
  - **`serial`**, **`manufacturer`**, **`product`** — Nullable strings from udev.

- **`usb_total`** — Count of all enumerated USB devices (before the name filter).

- **`tspl_like_count`** — Count of devices that match the printer / Xprinter **name** heuristic among the same full enumeration (used for UI hints; equals the size of the name-filtered set over **all** devices, not only the current `devices` list).

---

### `POST /api/v1/print/template`

**Body**

| Field | Type | Required |
|-------|------|----------|
| `template_id` | string | Yes |
| `printer_id` | string | Yes |
| `data` | object of string values | No (default `{}`) |

Non-string values in **`data`** are coerced to strings. Template placeholders `{{name}}` are filled from **`data`** merged with the template’s **`test_data`** (request **`data`** overrides **`test_data`** for the same keys).

**Errors:** Unknown template or printer → **`404`** `not_found`. Missing placeholder keys → **`422`** `render_error`. USB issues → **`503`** `device_not_found` or `io_error`.

---

### `POST /api/v1/print/raw`

**Body**

| Field | Type | Required |
|-------|------|----------|
| `printer_id` | string | Yes |
| `tspl` | string | Yes (non-empty) |

The **`tspl`** string is encoded as UTF-8 (invalid sequences replaced) and sent as-is; no automatic `SIZE`/`GAP` is added.

The web UI **TSPL debug** panel at the bottom of the page calls this endpoint with the selected printer and textarea contents.

---

### `POST /api/v1/printers/{printer_id}/test`

Runs a small built-in test label using the printer’s **`default_label_size_id`** preset and the printer’s **`dpi`**, **`direction`**, and offsets.

**Body:** `{}`

**Errors:** Unknown printer → **`404`**. Missing or invalid default label size → **`422`** `config_error`. USB issues → **`503`**.

---

### `POST /api/v1/templates/{template_id}/test`

**Body**

| Field | Type | Required |
|-------|------|----------|
| `printer_id` | string | Yes |
| `data` | object of string values | No (default `{}`) |

Rendering uses the template’s **`label_size_id`** and merges **`test_data`** with **`data`** like template print.

---

## Config (`GET`/`PUT /api/v1/config`)

Top-level keys: **`server`**, **`label_sizes`**, **`printers`**, **`templates`**.

### `server`

| Field | Type | Notes |
|-------|------|--------|
| `bind_address` | string | Non-empty |
| `port` | integer | `1`…`65535` |
| `api_key` | string | Min length **8** |
| `cors_origins` | array of strings | Browser **`Origin`** values allowed for CORS; empty disables CORS middleware (see **CORS (browser clients)**). Optional env: **`TSPL_CORS_ORIGINS`** when this array is empty. |

### `label_sizes[]`

| Field | Type | Notes |
|-------|------|--------|
| `id` | string | `^[a-zA-Z0-9_-]+$` |
| `name` | string | Non-empty |
| `width_mm`, `height_mm` | number | `> 0`, `≤ 500` |
| `gap_mm` | number | `≥ 0`, `≤ 50` |

### `printers[]`

| Field | Type | Notes |
|-------|------|--------|
| `id` | string | `^[a-zA-Z0-9_-]+$` |
| `name` | string | Non-empty |
| `vendor_id`, `product_id` | integer | `0`…`65535` |
| `serial` | string or null | USB serial for matching |
| `default_label_size_id` | string | Must exist in `label_sizes` |
| `offset_x_mm`, `offset_y_mm` | number | `-100`…`100` |
| `direction` | `0` or `1` | `0` = default, `1` = 180°; other integers are normalized to `0` or `1` on read |
| `dpi` | integer | `100`…`600`, default `203` |

Unknown extra keys on a printer object are **ignored** (e.g. legacy fields from older configs).

### `templates[]`

| Field | Type | Notes |
|-------|------|--------|
| `id` | string | `^[a-zA-Z0-9_-]+$` |
| `name` | string | Non-empty |
| `label_size_id` | string | Must exist in `label_sizes` |
| `elements` | array | Each item: `type` (only `"text"`), `x_mm`, `y_mm`, `font` (default `"3"`, max length 8), `content` (placeholders `{{name}}`, max length 4096) |
| `test_data` | object | String values; keys are placeholder names for tests |

**Id rule:** Every **`id`** in **`label_sizes`**, **`printers`**, and **`templates`** must be **globally unique** across those three arrays.

---

**Update this file when routes or JSON fields change.**
