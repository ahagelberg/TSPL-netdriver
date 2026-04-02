# TSPL driver HTTP API

Base path for JSON API: **`/api/v1`**. Request bodies use **`Content-Type: application/json`** unless noted.

## Browser UI and static files (no API key)

These routes do **not** use API authentication (the HTML pages load scripts that call **`/api/v1/...`** with a key stored in the browser):

| Route | Purpose |
|--------|---------|
| **`GET /`** | **Print label** UI (default): choose template, printer, and data for a print job. |
| **`GET /config.html`** | **Configuration** UI: server settings, label sizes, **templates**, printers, USB discovery, and **TSPL debug**. |
| **`GET /print.html`** | Same as **`GET /`** (alias for bookmarks). |
| **`GET /favicon.ico`** | Favicon (served from the static directory). |
| **`GET /static/...`** | Static assets (`app.css`, `app.js`, `api.js`, `print-page.js`, etc.). |

There is **no** separate template designer page and **no** **`GET /template-designer.html`** endpoint.

**All `/api/v1/...` routes require authentication** (see below).

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

## Templates, ad-hoc labels, and graphical elements

Saved **templates** (`config.templates[].elements`), **inline** label jobs (**`POST /api/v1/print/label`**), and **PNG preview** (**`POST /api/v1/preview/template`**) all use the same **`elements`** array shape: a list of objects with a **`type`** discriminator. Units are **millimetres** for positions and sizes on the label, except where noted. The printer’s **`dpi`** converts mm to dots; **`REFERENCE`** (offsets) from the printer config applies before element coordinates.

| `type` | Purpose |
|--------|---------|
| **`text`** | TSPL **`TEXT`** (built-in font) or raster **`BITMAP`** (scalable font); see **[Fonts and text rendering](#fonts-and-text-rendering)**. |
| **`box`** | Rectangle outline (**TSPL `BOX`**). |
| **`circle`** | Circle outline (**TSPL `CIRCLE`**). |
| **`bitmap`** | Raw monochrome image (**TSPL `BITMAP`**), payload supplied as base64. |

**Placeholders:** In **`text`**, **`content`** may include `{{name}}` tokens. At render time, each name must appear in the merged **`data`** object (template print merges **`test_data`** with request **`data`**; inline print uses **`data`** only). Missing keys → **`422`** `render_error`.

### `type: "text"`

| Field | Type | Default | Notes |
|-------|------|---------|--------|
| `x` | number | — | Horizontal position from label origin (mm). Allowed range **`-50`…`500`**. |
| `y` | number | — | Vertical position from label origin (mm). Same range as **`x`**. |
| `font` | string | `"3"` | **Built-in:** exactly **`"1"`**…**`"8"`** → TSPL **`TEXT`** with that font slot. **Raster:** any other non-empty string — path, URL, **`__default__`**, or named family; see **[Fonts and text rendering](#fonts-and-text-rendering)**. Max length **4096**. |
| `size` | number | `3.0` | **Built-in fonts:** stored but not applied to **`TEXT`** magnification (fixed factors in the command). **Raster fonts:** nominal **em height in millimetres** (must be positive, up to **`50`**); converted to a Pillow TrueType pixel size from the printer **`dpi`** (typographic em size, not scaling to fit ink bounds). |
| `font_weight` | integer | `400` | **`100`**…**`900`**, snapped to nearest **`100`**. Used for **raster** / named fonts only; **ignored** for built-in **`TEXT`**. |
| `font_style` | string | `"normal"` | **`"normal"`** or **`"italic"`**. Raster / named fonts only; **ignored** for built-in **`TEXT`**. |
| `content` | string | — | Non-empty; may include **`{{placeholder}}`** tokens. Max length **4096**. |

### `type: "box"`

| Field | Type | Default | Notes |
|-------|------|---------|--------|
| `x` | number | — | Top-left corner **X** (mm), **`-50`…`500`**. |
| `y` | number | — | Top-left corner **Y** (mm), same range. |
| `width` | number | — | Rectangle width (mm), positive, up to **`500`**. |
| `height` | number | — | Rectangle height (mm), same bounds as **`width`**. |
| `line_width` | number | `0.25` | Border thickness (mm), positive, up to **`10`**; converted to TSPL **`BOX`** line thickness in dots (minimum **1** dot). |

### `type: "circle"`

| Field | Type | Default | Notes |
|-------|------|---------|--------|
| `x` | number | — | **Upper-left** corner of the circle’s bounding square (**TSPL `CIRCLE`** convention), **X** (mm), **`-50`…`500`**. |
| `y` | number | — | Upper-left **Y** (mm), same range. |
| `diameter` | number | — | Diameter (mm), positive, up to **`500`**. |
| `line_width` | number | `0.3` | Stroke thickness (mm), positive, up to **`10`**. |

### `type: "bitmap"`

Embedded mono bitmap (e.g. pre-rendered graphics). Position is in **mm**; dimensions are in **dots**.

| Field | Type | Notes |
|-------|------|--------|
| `x` | number | Dot placement **X** (mm), **`-50`…`500`**. |
| `y` | number | Dot placement **Y** (mm), same range. |
| `width` | integer | Width **in dots** (`1`…`20000`). Row packing: **`ceil(width / 8)`** bytes per row. |
| `height` | integer | Height **in dots** (`1`…`20000`). |
| `data` | string | Non-empty **base64** of the raw TSPL **`BITMAP`** payload (row-major, MSB-first per byte as used by the driver). Decoded length must equal **`ceil(width / 8) × height`**. |

Unknown extra keys on an element object are **ignored** (Pydantic **`extra="ignore"`**).

---

## Endpoints

| Method | Path | Body | Success `data` |
|--------|------|------|----------------|
| `GET` | `/api/v1/health` | — | `{ "status": "ok" }` |
| `GET` | `/api/v1/config` | — | Full config object (see **Config** below) |
| `PUT` | `/api/v1/config` | Full config object | Same object as saved |
| `GET` | `/api/v1/templates/{template_id}` | — | One template object (includes computed **`placeholder_keys`**) |
| `GET` | `/api/v1/usb/discover` | Query: optional `show_all` | See **USB discover** |
| `POST` | `/api/v1/print/template` | [Template print body](#post-apiv1printtemplate) | `{ "printed": true }` |
| `POST` | `/api/v1/print/label` | [Inline label print body](#post-apiv1printlabel) | `{ "printed": true }` |
| `POST` | `/api/v1/preview/template` | [Template preview body](#post-apiv1previewtemplate) | Raw **PNG** body (not `{ ok, data }`) |
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
  - **`device_key`** — Stable string: lowercase hex **`vid`**: **`pid`**, then **`@`**, then the Linux **sysfs** USB device name (same as **`usb_port_path`**, e.g. `1fc9:2016@1-2.3`). This distinguishes two identical models on different ports even when **`serial`** is missing or duplicated.
  - **`label`** — Short display string (manufacturer/product, IDs, and port path).
  - **`vendor_id`**, **`product_id`** — Integers `0`…`65535`.
  - **`usb_port_path`** — Linux sysfs name for that gadget (e.g. `1-2.3`); store in **`printers[].usb_port_path`** to target that physical port.
  - **`serial`**, **`manufacturer`**, **`product`** — Nullable strings from udev.

- **`usb_total`** — Count of all enumerated USB devices (before the name filter).

- **`tspl_like_count`** — Count of devices that match the printer / Xprinter **name** heuristic among the same full enumeration (used for UI hints; equals the size of the name-filtered set over **all** devices, not only the current `devices` list).

---

### `GET /api/v1/templates/{template_id}`

Returns one template from the loaded config. The response includes **`placeholder_keys`** (derived from `text` elements). Unknown **`template_id`** → **`404`** `not_found`.

---

### `POST /api/v1/print/template`

**Body**

| Field | Type | Required |
|-------|------|----------|
| `template_id` | string | Yes |
| `printer_id` | string | Yes |
| `data` | object of string values | No (default `{}`) |

Non-string values in **`data`** are coerced to strings. Template placeholders `{{name}}` are filled from **`data`** merged with the template’s **`test_data`** (request **`data`** overrides **`test_data`** for the same keys). **Graphical elements** (`elements` array): see **[Templates, ad-hoc labels, and graphical elements](#templates-ad-hoc-labels-and-graphical-elements)**. How **`text`** elements choose between TSPL **`TEXT`** and raster **`BITMAP`** is in **[Fonts and text rendering](#fonts-and-text-rendering)**.

**Errors:** Unknown template or printer → **`404`** `not_found`. Missing placeholder keys → **`422`** `render_error`. USB issues → **`503`** `device_not_found` or `io_error`.

---

### `POST /api/v1/print/raw`

**Body**

| Field | Type | Required |
|-------|------|----------|
| `printer_id` | string | Yes |
| `tspl` | string | Yes (non-empty) |

The **`tspl`** string is encoded with the selected printer’s **`text_encoding`** (Python codec name, e.g. **`utf-8`**, **`cp1252`**, **`cp865`** for PC865; unencodable characters are replaced) and sent as-is; no automatic `SIZE`/`GAP` is added. Match the encoding the printer expects (often PC865 on basic Nordic models).

The **TSPL debug** section on the configuration page (**`GET /config.html`**) calls this endpoint with the selected printer and textarea contents.

---

### `POST /api/v1/print/label`

Prints an inline, ad-hoc label definition (no saved template required).

**Body**

| Field | Type | Required |
|-------|------|----------|
| `printer_id` | string | Yes |
| `label_size` | object | Yes |
| `elements` | array | Yes (can be empty) |
| `data` | object of string values | No (default `{}`) |

`label_size` fields (values are **millimetres**; field names omit unit suffix):

- `width` (number, `> 0`, `<= 500`)
- `height` (number, `> 0`, `<= 500`)
- `gap` (number, `>= 0`, `<= 50`, default `2.0`)

`elements` uses the same element model as saved templates — see **[Templates, ad-hoc labels, and graphical elements](#templates-ad-hoc-labels-and-graphical-elements)** and **[Fonts and text rendering](#fonts-and-text-rendering)** for **`text`**. Placeholders are filled from **`data`** only (no **`test_data`** on this endpoint).

**Example**

```json
{
  "printer_id": "usb-printer-1",
  "label_size": { "width": 40, "height": 30, "gap": 2 },
  "elements": [
    { "type": "box", "x": 1, "y": 1, "width": 38, "height": 28, "line_width": 0.25 },
    { "type": "text", "x": 3, "y": 5, "font": "3", "size": 3, "content": "{{line1}}" }
  ],
  "data": { "line1": "Hello" }
}
```

**Errors:** Unknown printer → **`404`** `not_found`. Invalid/missing placeholders or render issues → **`422`** `render_error`. USB issues → **`503`** `device_not_found` or `io_error`.

---

### `POST /api/v1/printers/{printer_id}/test`

Runs a small built-in test label using the printer’s **`default_label_size_id`** preset and the printer’s **`dpi`**, **`direction`**, offsets, and **`text_encoding`**.

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

### `POST /api/v1/preview/template`

Returns a **PNG** image of the label as rasterized by the server (same pipeline as print for **raster** text, boxes, circles, and embedded bitmaps; built-in **TSPL** fonts are approximated with the default raster font in the preview image). **Not** JSON: use **`Accept: image/png`** or treat the response as binary. **`Cache-Control: no-store`**.

**Body**

| Field | Type | Required |
|-------|------|----------|
| `printer_id` | string | Yes |
| `label_size_id` | string | Yes (must exist in config **`label_sizes`**) |
| `elements` | array | No (default `[]`) |
| `test_data` | object of string values | No (default `{}`) |
| `data` | object of string values | No (default `{}`) |

Placeholders are resolved from **`test_data`** merged with **`data`** (same as template print). **`elements`** must satisfy the same shape as **[Templates, ad-hoc labels, and graphical elements](#templates-ad-hoc-labels-and-graphical-elements)**.

**Errors:** Unknown printer or label size → **`404`** `not_found`. Missing placeholder keys or render failure → **`422`** `render_error`. Requires **Pillow** for preview generation.

---

## Fonts and text rendering

Each **`text`** element has **`font`** (string), **`size`** (positive number), **`font_weight`** (CSS weight, default **`400`**), and **`font_style`** (**`normal`** or **`italic`**, default **`normal`**). The implementation distinguishes **TSPL built-in** fonts from **raster** (TrueType/OpenType via Pillow) output.

### Built-in TSPL fonts (`font` is `"1"` … `"8"`)

- After trimming, **`font`** must be **exactly** one of **`"1"`** through **`"8"`** (printer font slots in the TSPL **`TEXT`** command).
- Output is a TSPL **`TEXT`** line. The visible string is encoded with the job printer’s **`text_encoding`** (Python codec name on **`printers[]`**; invalid code points are replaced, not fatal).
- The element’s **`size`** field is **not** applied on this path: magnification in the generated command is fixed; use the printer manual for how the font index affects size and style.
- **`font_weight`** and **`font_style`** are **ignored** for built-in **`TEXT`** (the printer font slot carries the design).

### Raster fonts (any other `font` value)

- Text is rendered to a **monochrome bitmap** with **Pillow** and emitted as TSPL **`BITMAP`** in **overwrite** mode. **Pillow must be installed**; otherwise raster text raises a runtime error.
- **`size`** is the nominal **em height in millimetres** (not dots). The renderer converts mm to a Pillow **TrueType** pixel size using the printer’s **`dpi`** and draws at that typographic size (bitmap width/height follow the glyph outline, not a forced fit to a target box).
- **`font_weight`** is a CSS-style value **`100`…`900`** (stored values are snapped to the nearest **100**). **`font_style`** selects upright vs italic when resolving a font file.

#### Default raster font (`__default__`)

- **`font`** may be the literal **`__default__`**. The service picks a scalable **TrueType** font without you passing a path: it prefers Pillow’s bundled **DejaVu** fonts (if present), then common paths under **`/usr/share/fonts`** (e.g. DejaVu, Liberation on typical Debian/Raspberry Pi images), then searches under each **`server.font_local_roots`** entry for the same relative paths (e.g. `truetype/dejavu/DejaVuSans.ttf`). If nothing is found, it falls back to Pillow’s tiny **`load_default()`** bitmap font (fixed appearance; **`size`** may not match mm intent as well).

#### Named font families (not a path or URL)

- If **`font`** is **not** built-in, not **`__default__`**, not a **`http(s):`** URL, and not **path-like** (no `/`, `\`, Windows drive prefix, etc.), it is treated as a **family name** (e.g. **`Roboto`**, **`Open Sans`**).
- Resolution order:
  1. **`fc-match`** (**fontconfig**), if available: match **`family`**, **`font_weight`**, and **`font_style`** to a **local** font file. The resolved **family** must equal the requested name (no silent substitution to a fallback face).
  2. Otherwise **Google Fonts**: request the CSS from **`fonts.googleapis.com/css2`** with axis **`ital,wght`**. The service uses a **minimal WebKit `User-Agent`** when fetching that CSS so Google returns **`format('truetype')`** links (modern Chrome/Firefox UAs get **WOFF2** only, which Pillow cannot load). Extract the first **`.ttf`** URL, then download and cache it like any other web font (**`font_cache_dir`**, **`font_fetch_timeout_seconds`**).
- **`font_weight`** / **`font_style`** apply both to fontconfig matching and to the Google Fonts CSS request.

#### Local font paths

- **`font`** may be a path to a font file (typically **`.ttf`** / **`.otf`**) that Pillow can load.
- **Relative** paths are resolved from the **directory containing the config file** (same rule as **`font_cache_dir`**).
- If **`server.font_local_roots`** is **non-empty**, the resolved **absolute** path must lie **inside** one of those directories (after normalization). If the list is **empty**, any readable path is allowed.
- Items in **`font_local_roots`** may be relative to the config file directory.

#### Web fonts (`http://` / `https://`)

- **`font`** may be a full **`http://`** or **`https://`** URL. The file is downloaded with **`urllib`** and cached on disk. The URL must point to a **font file** (typically **`.ttf`** or **`.otf`**), not a CSS or HTML page (e.g. Google Fonts “stylesheet” links). **WOFF** / **WOFF2** responses are rejected before caching (Pillow cannot use them as **`truetype`** inputs). Invalid cached files (HTML, WOFF, etc.) are removed when detected so the next request can re-download if the URL is fixed.
- Cache directory: **`server.font_cache_dir`** (relative paths are resolved from the config file directory; the directory is created when config is saved).
- Stored files: **`{SHA-256 of URL}.font`** plus a **`*.meta.json`** sidecar (URL, **`ETag`**, **`Last-Modified`**). Conditional requests (**`If-None-Match`**, **`If-Modified-Since`**) are used; **`304 Not Modified`** keeps the existing cache file.
- Download timeout: **`server.font_fetch_timeout_seconds`** (seconds, bounded in config validation).

### Encoding: built-in `TEXT` vs raster `BITMAP`

| Path | Bytes on the wire |
|------|-------------------|
| Built-in **`TEXT`** | Printer **`text_encoding`** (e.g. **`utf-8`**, **`cp865`**) |
| Raster **`BITMAP`** | Glyphs come from the font file / renderer; there is no separate printer code page step |

### Printer self-test

**`POST /api/v1/printers/{printer_id}/test`** prints a small pattern that includes both a built-in **`TEXT`** line and a raster **`BITMAP`** line using **`__default__`**, so you can verify USB output and default font resolution on the host.

---

## Config (`GET`/`PUT /api/v1/config`)

Top-level keys: **`server`**, **`label_sizes`**, **`printers`**, **`templates`**.

### `server`

| Field | Type | Notes |
|-------|------|--------|
| `bind_address` | string | Non-empty |
| `port` | integer | `1`…`65535` |
| `api_key` | string | Min length **8** |
| `font_cache_dir` | string | Directory for cached downloaded web fonts (see **[Fonts and text rendering](#fonts-and-text-rendering)**). Relative paths resolve from the config file directory. |
| `font_fetch_timeout_seconds` | number | HTTP/HTTPS timeout for web font downloads (`> 0`, `<= 120`). |
| `font_local_roots` | array of strings | Optional allow-list for **local** font paths used in **`text`** elements (see **[Fonts and text rendering](#fonts-and-text-rendering)**). Empty allows any readable absolute path; non-empty restricts resolved paths to these roots. |
| `cors_origins` | array of strings | Browser **`Origin`** values allowed for CORS; empty disables CORS middleware (see **CORS (browser clients)**). Optional env: **`TSPL_CORS_ORIGINS`** when this array is empty. |

### `label_sizes[]`

| Field | Type | Notes |
|-------|------|--------|
| `id` | string | `^[a-zA-Z0-9_-]+$` |
| `name` | string | Non-empty |
| `width`, `height` | number | `> 0`, `≤ 500` (mm) |
| `gap` | number | `≥ 0`, `≤ 50` (mm) |

### `printers[]`

| Field | Type | Notes |
|-------|------|--------|
| `id` | string | `^[a-zA-Z0-9_-]+$` |
| `name` | string | Non-empty |
| `vendor_id`, `product_id` | integer | `0`…`65535` |
| `serial` | string or null | USB **iSerial** string when helpful |
| `usb_port_path` | string or null | Linux sysfs USB device name (e.g. `1-2.3`) from **`GET /usb/discover`**; when set, printing matches this port and ignores duplicate/wrong **serial** |
| `default_label_size_id` | string | Must exist in `label_sizes` |
| `offset_x`, `offset_y` | number | `-100`…`100` (mm) |
| `direction` | `0` or `1` | `0` = default, `1` = 180°; other integers are normalized to `0` or `1` on read |
| `dpi` | integer | `100`…`600`, default `203` |
| `text_encoding` | string | Python codec name for **`TEXT`** string payloads and for **`POST /print/raw`** body bytes; default **`utf-8`**. For **PC865** (IBM Nordic / DOS Nordic), use **`cp865`**. |

Unknown extra keys on a printer object are **ignored**.

### `templates[]`

| Field | Type | Notes |
|-------|------|--------|
| `id` | string | `^[a-zA-Z0-9_-]+$` |
| `name` | string | Non-empty |
| `label_size_id` | string | Must exist in `label_sizes` |
| `elements` | array | Graphical elements: full field list and units in **[Templates, ad-hoc labels, and graphical elements](#templates-ad-hoc-labels-and-graphical-elements)** and **[Fonts and text rendering](#fonts-and-text-rendering)** for **`text`**. |
| `test_data` | object | String values; keys are placeholder names for tests |

**Computed (read-only in API responses):** each template may include **`placeholder_keys`**: an array of placeholder names derived from `text` elements’ `{{name}}` patterns.

**Id rule:** Every **`id`** in **`label_sizes`**, **`printers`**, and **`templates`** must be **globally unique** across those three arrays.

---

**Maintenance:** Update this file when **`/api/v1/...`** routes, request/response JSON, or unauthenticated HTML/static routes change.
