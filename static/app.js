/* global document, window, Image */
(function () {
  const toast = window.tsplToast;
  if (!toast) {
    throw new Error("Load toast.js before app.js");
  }
  const api = window.tsplDriverApi;
  if (!api) {
    throw new Error("Load api.js before app.js");
  }
  const getStoredApiKey = api.getStoredApiKey;
  const setStoredApiKey = api.setStoredApiKey;
  const apiJson = api.apiJson;
  const apiBlob = api.apiBlob;
  /** Preview uses same raster path as print; path is relative to API_BASE in api.js. */
  const API_PATH_TEMPLATE_PREVIEW = "/preview/template";
  const STORAGE_USB_SHOW_ALL = "tspl_driver_usb_show_all";
  const BODY_CLASS_STATE_CONNECTING = "app-state--connecting";
  const BODY_CLASS_STATE_READY = "app-state--ready";
  const BODY_CLASS_STATE_OFFLINE = "app-state--offline";
  const DEFAULT_TEMPLATE_ELEMENTS_JSON =
    '[{"type":"text","x":2,"y":2,"font":"3","size":3,"content":"{{line1}}"}]';
  const DEFAULT_TEST_DATA_JSON = '{"line1":"Sample"}';
  const ACC_ITEM_OPEN_CLASS = "accordion__item--open";
  const ACC_CARD_SIZE = ".js-size-card";
  const ACC_CARD_TPL = ".js-tpl-card";
  const ACC_CARD_PR = ".js-pr-card";
  const ACC_ID_SIZE = ".js-size-id";
  const ACC_ID_TPL = ".js-tpl-id";
  const ACC_ID_PR = ".js-pr-id";
  const SECRET_TOGGLE_SHOW = "Show";
  const SECRET_TOGGLE_HIDE = "Hide";
  /** Python codec names for printer TEXT payloads (see printer manual for best match). */
  const PRINTER_TEXT_ENCODING_OPTIONS = [
    { value: "utf-8", label: "UTF-8" },
    { value: "cp1252", label: "Windows-1252 (Western European)" },
    { value: "iso8859-1", label: "ISO-8859-1 (Latin-1)" },
    { value: "iso8859-15", label: "ISO-8859-15 (Latin-9, euro)" },
    { value: "cp865", label: "PC865 / IBM Nordic (Python cp865)" },
  ];
  /** Aligns with ``config.models.TemplateBitmapElement`` max dimensions. */
  const BITMAP_ELEMENT_MAX_WIDTH_DOTS = 20000;
  const BITMAP_ELEMENT_MAX_HEIGHT_DOTS = 20000;
  /** Aligns with ``printer.builder.BITMAP_BITS_PER_BYTE``. */
  const BITMAP_BITS_PER_BYTE = 8;
  /** Aligns with ``printer.renderer.RASTER_TEXT_THRESHOLD``: luma >= threshold → paper (white bit). */
  const IMAGE_BITMAP_LUMA_THRESHOLD = 128;
  const IMAGE_BITMAP_LUMA_R = 0.299;
  const IMAGE_BITMAP_LUMA_G = 0.587;
  const IMAGE_BITMAP_LUMA_B = 0.114;
  /** Pixels with alpha below this are treated as transparent (paper white). */
  const IMAGE_BITMAP_ALPHA_CUTOUT = 128;
  const CLIPBOARD_CHUNK_BYTES = 32768;
  /** Aligns with ``printer.builder.mm_to_dots`` / ``MM_PER_INCH``. */
  const MM_PER_INCH = 25.4;
  /** Bayer 4×4 matrix (values 0–15). */
  const BAYER_MATRIX_4 = [
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5],
  ];
  /** Bayer 8×8 matrix (values 0–63). */
  const BAYER_MATRIX_8 = [
    [0, 48, 12, 60, 3, 51, 15, 63],
    [32, 16, 44, 28, 35, 19, 47, 31],
    [8, 56, 4, 52, 11, 59, 7, 55],
    [40, 24, 36, 20, 43, 27, 39, 23],
    [2, 50, 14, 62, 1, 49, 13, 61],
    [34, 18, 46, 30, 33, 17, 45, 29],
    [10, 58, 6, 54, 9, 57, 5, 53],
    [42, 26, 38, 22, 41, 25, 37, 21],
  ];
  const BAYER_ORDERED_DIVISOR_4 = 16;
  const BAYER_ORDERED_DIVISOR_8 = 64;
  const DITHER_MODE_THRESHOLD = "threshold";
  const DITHER_MODE_FLOYD_STEINBERG = "floydsteinberg";
  const DITHER_MODE_ORDERED_4 = "ordered4";
  const DITHER_MODE_ORDERED_8 = "ordered8";
  /** Uniform scale to fit inside mm box (letterbox); preserves aspect ratio. */
  const BITMAP_SCALE_MODE_FIT = "fit";
  /** Distort image to fill the mm box exactly. */
  const BITMAP_SCALE_MODE_STRETCH = "stretch";

  let appConfig = null;
  /** Likely TSPL devices from last GET /usb/discover (`data.devices`). */
  let usbDevices = [];

  function $(id) {
    return document.getElementById(id);
  }

  function setStatus(message, isErrorOrVariant) {
    if (!message) {
      return;
    }
    toast.show(message, toast.normalizeVariant(isErrorOrVariant));
  }

  function setDebugPanelStatus(message, isError) {
    if (!message) {
      return;
    }
    toast.show(message, toast.normalizeVariant(isError));
  }

  function syncDebugPrinterPanel() {
    const sel = $("debugPrinterSelect");
    const btn = $("btnDebugSend");
    if (!sel || !btn) {
      return;
    }
    const prev = sel.value;
    sel.textContent = "";
    if (!appConfig || appConfig.printers.length === 0) {
      const o = document.createElement("option");
      o.value = "";
      o.textContent = "— Add a printer first —";
      sel.appendChild(o);
      sel.disabled = true;
      btn.disabled = true;
      return;
    }
    sel.disabled = false;
    btn.disabled = false;
    appConfig.printers.forEach(function (p) {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name + " (" + p.id + ")";
      sel.appendChild(opt);
    });
    if (prev && appConfig.printers.some(function (p) { return p.id === prev; })) {
      sel.value = prev;
    }
  }

  function getPrinterDpiForBitmapHelper(printerId) {
    if (!appConfig || !printerId) {
      return 203;
    }
    for (let i = 0; i < appConfig.printers.length; i++) {
      if (appConfig.printers[i].id === printerId) {
        const d = Number(appConfig.printers[i].dpi);
        if (isFinite(d) && d > 0) {
          return Math.round(d);
        }
        return 203;
      }
    }
    return 203;
  }

  function updateBitmapHelperDpiHint() {
    const sel = $("bitmapHelperPrinter");
    const dpiEl = $("bitmapHelperDpiDisplay");
    if (!dpiEl) {
      return;
    }
    if (!sel || !sel.value || !appConfig) {
      dpiEl.textContent = "—";
      return;
    }
    dpiEl.textContent = String(getPrinterDpiForBitmapHelper(sel.value)) + " dpi";
  }

  function syncBitmapHelperPrinterSelect() {
    const sel = $("bitmapHelperPrinter");
    if (!sel) {
      return;
    }
    const prev = sel.value;
    sel.textContent = "";
    if (!appConfig || appConfig.printers.length === 0) {
      const o = document.createElement("option");
      o.value = "";
      o.textContent = "— Add a printer first —";
      sel.appendChild(o);
      sel.disabled = true;
      updateBitmapHelperDpiHint();
      return;
    }
    sel.disabled = false;
    appConfig.printers.forEach(function (p) {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name + " (" + p.id + ")";
      sel.appendChild(opt);
    });
    if (prev && appConfig.printers.some(function (p) { return p.id === prev; })) {
      sel.value = prev;
    }
    updateBitmapHelperDpiHint();
  }

  function mmToDotsAtDpi(mm, dpi) {
    return Math.max(0, Math.round((mm * dpi) / MM_PER_INCH));
  }

  function clampFloatChannel(v) {
    return v < 0 ? 0 : v > 255 ? 255 : v;
  }

  function uint8ToBase64(bytes) {
    let binary = "";
    for (let i = 0; i < bytes.length; i += CLIPBOARD_CHUNK_BYTES) {
      const slice = bytes.subarray(i, i + CLIPBOARD_CHUNK_BYTES);
      binary += String.fromCharCode.apply(null, slice);
    }
    return btoa(binary);
  }

  /**
   * Same packing as ``printer.builder.pack_mono_bitmap_rows``: True → TSPL bit 1 (paper white).
   * @param {boolean[][]} rows
   */
  function packMonoBitmapRows(rows) {
    if (!rows.length) {
      return { widthBytes: 0, height: 0, payload: new Uint8Array(0) };
    }
    const height = rows.length;
    let width = 0;
    for (let ri = 0; ri < rows.length; ri++) {
      if (rows[ri].length > width) {
        width = rows[ri].length;
      }
    }
    const widthBytes = Math.max(1, Math.ceil(width / BITMAP_BITS_PER_BYTE));
    const totalBitsPerRow = widthBytes * BITMAP_BITS_PER_BYTE;
    const out = new Uint8Array(height * widthBytes);
    for (let y = 0; y < height; y++) {
      const row = rows[y];
      const base = y * widthBytes;
      for (let x = 0; x < row.length; x++) {
        if (!row[x]) {
          continue;
        }
        const byteIdx = (x / BITMAP_BITS_PER_BYTE) | 0;
        const bitIdx = BITMAP_BITS_PER_BYTE - 1 - (x % BITMAP_BITS_PER_BYTE);
        out[base + byteIdx] |= 1 << bitIdx;
      }
      for (let x = width; x < totalBitsPerRow; x++) {
        const byteIdx = (x / BITMAP_BITS_PER_BYTE) | 0;
        const bitIdx = BITMAP_BITS_PER_BYTE - 1 - (x % BITMAP_BITS_PER_BYTE);
        out[base + byteIdx] |= 1 << bitIdx;
      }
    }
    return { widthBytes: widthBytes, height: height, payload: out };
  }

  function imageDataToGrayscale(imageData, width, height) {
    const d = imageData.data;
    const out = new Float32Array(width * height);
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const i = (y * width + x) * 4;
        const a = d[i + 3];
        if (a < IMAGE_BITMAP_ALPHA_CUTOUT) {
          out[y * width + x] = 255;
        } else {
          out[y * width + x] =
            IMAGE_BITMAP_LUMA_R * d[i] +
            IMAGE_BITMAP_LUMA_G * d[i + 1] +
            IMAGE_BITMAP_LUMA_B * d[i + 2];
        }
      }
    }
    return out;
  }

  function ditherThreshold(gray, width, height) {
    const rows = [];
    for (let y = 0; y < height; y++) {
      const row = [];
      for (let x = 0; x < width; x++) {
        row.push(gray[y * width + x] >= IMAGE_BITMAP_LUMA_THRESHOLD);
      }
      rows.push(row);
    }
    return rows;
  }

  function ditherFloydSteinberg(gray, width, height) {
    const buf = new Float32Array(gray);
    const rows = [];
    for (let y = 0; y < height; y++) {
      const row = [];
      for (let x = 0; x < width; x++) {
        const idx = y * width + x;
        let old = buf[idx];
        old = clampFloatChannel(old);
        const newv = old < 128 ? 0 : 255;
        row.push(newv >= 128);
        const err = old - newv;
        if (x + 1 < width) {
          buf[idx + 1] = clampFloatChannel(buf[idx + 1] + err * (7 / 16));
        }
        if (y + 1 < height) {
          if (x > 0) {
            buf[idx + width - 1] = clampFloatChannel(
              buf[idx + width - 1] + err * (3 / 16)
            );
          }
          buf[idx + width] = clampFloatChannel(buf[idx + width] + err * (5 / 16));
          if (x + 1 < width) {
            buf[idx + width + 1] = clampFloatChannel(
              buf[idx + width + 1] + err * (1 / 16)
            );
          }
        }
      }
      rows.push(row);
    }
    return rows;
  }

  function ditherOrderedBayer(gray, width, height, matrix, divisor) {
    const n = matrix.length;
    const rows = [];
    for (let y = 0; y < height; y++) {
      const row = [];
      for (let x = 0; x < width; x++) {
        const t = ((matrix[y % n][x % n] + 0.5) / divisor) * 255;
        row.push(gray[y * width + x] >= t);
      }
      rows.push(row);
    }
    return rows;
  }

  function applyDither(gray, width, height, mode) {
    if (mode === DITHER_MODE_FLOYD_STEINBERG) {
      return ditherFloydSteinberg(gray, width, height);
    }
    if (mode === DITHER_MODE_ORDERED_4) {
      return ditherOrderedBayer(
        gray,
        width,
        height,
        BAYER_MATRIX_4,
        BAYER_ORDERED_DIVISOR_4
      );
    }
    if (mode === DITHER_MODE_ORDERED_8) {
      return ditherOrderedBayer(
        gray,
        width,
        height,
        BAYER_MATRIX_8,
        BAYER_ORDERED_DIVISOR_8
      );
    }
    return ditherThreshold(gray, width, height);
  }

  function fileToImageBitmapPayload(file, options, callback) {
    const widthMm = options.widthMm;
    const heightMm = options.heightMm;
    const dpi = options.dpi;
    const ditherMode = options.ditherMode || DITHER_MODE_THRESHOLD;
    const scaleMode = options.scaleMode || BITMAP_SCALE_MODE_FIT;
    if (widthMm <= 0 || heightMm <= 0 || !isFinite(widthMm) || !isFinite(heightMm)) {
      callback(new Error("Width and height (mm) must be positive."));
      return;
    }
    if (!dpi || dpi <= 0) {
      callback(new Error("Invalid printer dpi."));
      return;
    }
    const wDots = mmToDotsAtDpi(widthMm, dpi);
    const hDots = mmToDotsAtDpi(heightMm, dpi);
    if (wDots < 1 || hDots < 1) {
      callback(new Error("Size in mm is too small for the selected dpi."));
      return;
    }
    if (wDots > BITMAP_ELEMENT_MAX_WIDTH_DOTS || hDots > BITMAP_ELEMENT_MAX_HEIGHT_DOTS) {
      callback(
        new Error(
          "Bitmap would be " +
            wDots +
            "×" +
            hDots +
            " dots; max " +
            BITMAP_ELEMENT_MAX_WIDTH_DOTS +
            "×" +
            BITMAP_ELEMENT_MAX_HEIGHT_DOTS +
            "."
        )
      );
      return;
    }
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = function () {
      URL.revokeObjectURL(url);
      if (img.naturalWidth < 1 || img.naturalHeight < 1) {
        callback(new Error("Image has zero size."));
        return;
      }
      const canvas = document.createElement("canvas");
      canvas.width = wDots;
      canvas.height = hDots;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        callback(new Error("Canvas is not available."));
        return;
      }
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, wDots, hDots);
      const iw = img.naturalWidth;
      const ih = img.naturalHeight;
      if (scaleMode === BITMAP_SCALE_MODE_STRETCH) {
        ctx.drawImage(img, 0, 0, wDots, hDots);
      } else {
        const scale = Math.min(wDots / iw, hDots / ih);
        let dw = Math.max(1, Math.round(iw * scale));
        let dh = Math.max(1, Math.round(ih * scale));
        if (dw > wDots) {
          dw = wDots;
        }
        if (dh > hDots) {
          dh = hDots;
        }
        const dx = Math.floor((wDots - dw) / 2);
        const dy = Math.floor((hDots - dh) / 2);
        ctx.drawImage(img, 0, 0, iw, ih, dx, dy, dw, dh);
      }
      const id = ctx.getImageData(0, 0, wDots, hDots);
      const gray = imageDataToGrayscale(id, wDots, hDots);
      const rows = applyDither(gray, wDots, hDots, ditherMode);
      const packed = packMonoBitmapRows(rows);
      const expectedLen = packed.widthBytes * packed.height;
      if (packed.payload.length !== expectedLen) {
        callback(new Error("Internal pack size mismatch."));
        return;
      }
      const b64 = uint8ToBase64(packed.payload);
      const element = {
        type: "bitmap",
        x: 0,
        y: 0,
        width: wDots,
        height: hDots,
        data: b64,
      };
      const jsonText = JSON.stringify(element, null, 2);
      callback(null, {
        width: wDots,
        height: hDots,
        widthMm: widthMm,
        heightMm: heightMm,
        dpi: dpi,
        ditherMode: ditherMode,
        scaleMode: scaleMode,
        widthBytes: packed.widthBytes,
        payloadLength: packed.payload.length,
        base64: b64,
        jsonText: jsonText,
      });
    };
    img.onerror = function () {
      URL.revokeObjectURL(url);
      callback(new Error("Could not decode image."));
    };
    img.src = url;
  }

  function wireBitmapHelper() {
    const fileInput = $("bitmapHelperFile");
    const out = $("bitmapHelperOutput");
    const btnJson = $("btnBitmapHelperCopyJson");
    const btnB64 = $("btnBitmapHelperCopyB64");
    const printerSel = $("bitmapHelperPrinter");
    const ditherSel = $("bitmapHelperDither");
    const widthMmEl = $("bitmapHelperWidthMm");
    const heightMmEl = $("bitmapHelperHeightMm");
    const scaleModeEl = $("bitmapHelperScaleMode");
    if (
      !fileInput ||
      !out ||
      !btnJson ||
      !btnB64 ||
      !printerSel ||
      !ditherSel ||
      !widthMmEl ||
      !heightMmEl ||
      !scaleModeEl
    ) {
      return;
    }
    let lastB64 = "";
    let lastJson = "";

    function setHelperStatus(msg, variant) {
      if (!msg) {
        return;
      }
      toast.show(msg, variant);
    }

    function copyText(text, okMsg) {
      if (!text) {
        setHelperStatus("Nothing to copy; choose an image first.", "error");
        return;
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(
          function () {
            setHelperStatus(okMsg, "success");
          },
          function () {
            setHelperStatus("Clipboard failed.", "error");
          }
        );
      } else {
        out.select();
        document.execCommand("copy");
        setHelperStatus(okMsg + " (fallback).", "success");
      }
    }

    function readHelperOptions() {
      const pid = printerSel.value;
      if (!pid) {
        return { error: "Choose a printer first." };
      }
      const dpi = getPrinterDpiForBitmapHelper(pid);
      const w = parseFloat(widthMmEl.value);
      const h = parseFloat(heightMmEl.value);
      if (!isFinite(w) || !isFinite(h) || w <= 0 || h <= 0) {
        return { error: "Enter valid width and height (mm)." };
      }
      const ditherMode = ditherSel.value || DITHER_MODE_THRESHOLD;
      const sm = scaleModeEl.value;
      const scaleMode =
        sm === BITMAP_SCALE_MODE_STRETCH ? BITMAP_SCALE_MODE_STRETCH : BITMAP_SCALE_MODE_FIT;
      return {
        dpi: dpi,
        widthMm: w,
        heightMm: h,
        ditherMode: ditherMode,
        scaleMode: scaleMode,
      };
    }

    printerSel.addEventListener("change", function () {
      updateBitmapHelperDpiHint();
    });

    fileInput.addEventListener("change", function () {
      const f = fileInput.files && fileInput.files[0];
      if (!f) {
        return;
      }
      const opts = readHelperOptions();
      if (opts.error) {
        setHelperStatus(opts.error, "error");
        fileInput.value = "";
        return;
      }
      setHelperStatus("Processing…", "info");
      out.value = "";
      lastB64 = "";
      lastJson = "";
      fileToImageBitmapPayload(f, opts, function (err, result) {
        fileInput.value = "";
        if (err) {
          setHelperStatus(err.message || String(err), "error");
          return;
        }
        lastB64 = result.base64;
        lastJson = result.jsonText;
        out.value = result.jsonText;
        setHelperStatus(
          "OK: " +
            result.widthMm +
            "×" +
            result.heightMm +
            " mm @ " +
            result.dpi +
            " dpi → " +
            result.width +
            "×" +
            result.height +
            " dots (" +
            result.ditherMode +
            ", " +
            result.scaleMode +
            "), " +
            result.widthBytes +
            " bytes/row, payload " +
            result.payloadLength +
            " bytes.",
          "success"
        );
      });
    });

    btnJson.addEventListener("click", function () {
      copyText(lastJson, "Element JSON copied.");
    });
    btnB64.addEventListener("click", function () {
      copyText(lastB64, "Base64 copied.");
    });
  }

  function wireBitmapHelperModal() {
    const modal = $("bitmapHelperModal");
    const btnOpen = $("btnOpenBitmapHelper");
    const btnClose = $("btnCloseBitmapHelper");
    const backdrop = $("bitmapHelperBackdrop");
    if (!modal || !btnOpen || !btnClose || !backdrop) {
      return;
    }
    function openModal() {
      modal.classList.remove("is-hidden");
      modal.setAttribute("aria-hidden", "false");
      syncBitmapHelperPrinterSelect();
    }
    function closeModal() {
      modal.classList.add("is-hidden");
      modal.setAttribute("aria-hidden", "true");
    }
    btnOpen.addEventListener("click", function () {
      openModal();
    });
    btnClose.addEventListener("click", function () {
      closeModal();
    });
    backdrop.addEventListener("click", function () {
      closeModal();
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "Escape") {
        return;
      }
      if (modal.classList.contains("is-hidden")) {
        return;
      }
      closeModal();
    });
  }

  async function sendDebugTspl() {
    setDebugPanelStatus("", false);
    const pid = $("debugPrinterSelect").value;
    const tspl = $("debugTsplInput").value;
    if (!pid) {
      setDebugPanelStatus("Choose a printer.", true);
      return;
    }
    if (!tspl.trim()) {
      setDebugPanelStatus("Enter TSPL commands.", true);
      return;
    }
    try {
      await apiJson("POST", "/print/raw", {
        printer_id: pid,
        tspl: tspl,
      });
      setDebugPanelStatus("Sent to printer.", false);
    } catch (e) {
      setDebugPanelStatus(e.message || String(e), true);
    }
  }

  function wireSecretReveal(btnId, inputId, nameForAria) {
    const btn = $(btnId);
    const inp = $(inputId);
    if (!btn || !inp) {
      return;
    }
    function applyState(revealed) {
      inp.type = revealed ? "text" : "password";
      btn.setAttribute("aria-pressed", revealed ? "true" : "false");
      btn.textContent = revealed ? SECRET_TOGGLE_HIDE : SECRET_TOGGLE_SHOW;
      btn.setAttribute(
        "aria-label",
        (revealed ? "Hide " : "Show ") + nameForAria
      );
    }
    btn.addEventListener("click", function () {
      applyState(inp.type === "password");
    });
    applyState(false);
  }

  function parseCorsOriginsText(text) {
    if (!text || !String(text).trim()) {
      return [];
    }
    return String(text)
      .split(/[\r\n,]+/)
      .map(function (s) {
        return s.trim();
      })
      .filter(Boolean);
  }

  function readServerFromDom() {
    const port = parseInt($("srvPort").value, 10);
    const corsEl = $("srvCorsOrigins");
    const rootsEl = $("srvFontLocalRoots");
    const timeoutRaw = parseFloat($("srvFontFetchTimeout").value);
    let corsOrigins;
    if (corsEl) {
      corsOrigins = parseCorsOriginsText(corsEl.value);
    } else if (appConfig && appConfig.server && Array.isArray(appConfig.server.cors_origins)) {
      corsOrigins = appConfig.server.cors_origins.slice();
    } else {
      corsOrigins = [];
    }
    return {
      bind_address: $("srvBind").value.trim(),
      port: Number.isFinite(port) ? port : 8787,
      api_key: $("srvApiKey").value,
      font_cache_dir: $("srvFontCacheDir").value.trim() || ".tspl-font-cache",
      font_fetch_timeout_seconds: Number.isFinite(timeoutRaw) ? timeoutRaw : 5.0,
      font_local_roots: rootsEl ? parseCorsOriginsText(rootsEl.value) : [],
      cors_origins: corsOrigins,
    };
  }

  function writeServerToDom() {
    if (!appConfig) {
      return;
    }
    $("srvBind").value = appConfig.server.bind_address;
    $("srvPort").value = String(appConfig.server.port);
    $("srvApiKey").value = appConfig.server.api_key;
    const corsEl = $("srvCorsOrigins");
    if (corsEl) {
      const co = appConfig.server.cors_origins;
      corsEl.value = Array.isArray(co) ? co.join("\n") : "";
    }
    $("srvFontCacheDir").value = appConfig.server.font_cache_dir || ".tspl-font-cache";
    $("srvFontFetchTimeout").value = String(
      appConfig.server.font_fetch_timeout_seconds == null
        ? 5.0
        : appConfig.server.font_fetch_timeout_seconds
    );
    const rootsEl = $("srvFontLocalRoots");
    if (rootsEl) {
      const roots = appConfig.server.font_local_roots;
      rootsEl.value = Array.isArray(roots) ? roots.join("\n") : "";
    }
  }

  function readSizesFromDom() {
    const cards = $("listSizes").querySelectorAll(".js-size-card");
    const out = [];
    cards.forEach(function (card) {
      const id = card.querySelector(".js-size-id");
      if (!id || !id.value.trim()) {
        return;
      }
      out.push({
        id: id.value.trim(),
        name: card.querySelector(".js-size-name").value.trim() || id.value.trim(),
        width: parseFloat(card.querySelector(".js-size-w").value) || 50,
        height: parseFloat(card.querySelector(".js-size-h").value) || 30,
        gap: parseFloat(card.querySelector(".js-size-g").value) || 2,
      });
    });
    return out;
  }

  function setCardTitle(el, text) {
    if (el) {
      el.textContent = text;
    }
  }

  function wireAccordionHeader(item, headerBtn) {
    const panel = item.querySelector(".accordion__panel");
    if (!panel || !headerBtn) {
      return;
    }
    headerBtn.setAttribute("aria-expanded", "false");
    headerBtn.addEventListener("click", function () {
      const open = item.classList.toggle(ACC_ITEM_OPEN_CLASS);
      headerBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  function collectOpenAccordionIds(rootEl, cardSelector, idInputSelector) {
    const ids = new Set();
    if (!rootEl) {
      return ids;
    }
    rootEl.querySelectorAll(cardSelector).forEach(function (card) {
      if (!card.classList.contains(ACC_ITEM_OPEN_CLASS)) {
        return;
      }
      const idEl = card.querySelector(idInputSelector);
      const v = idEl && idEl.value.trim();
      if (v) {
        ids.add(v);
      }
    });
    return ids;
  }

  function applyOpenAccordionIds(rootEl, cardSelector, idInputSelector, openIds) {
    if (!rootEl || !openIds || openIds.size === 0) {
      return;
    }
    rootEl.querySelectorAll(cardSelector).forEach(function (card) {
      const idEl = card.querySelector(idInputSelector);
      const v = idEl && idEl.value.trim();
      if (!v || !openIds.has(v)) {
        return;
      }
      card.classList.add(ACC_ITEM_OPEN_CLASS);
      const header = card.querySelector(".accordion__header");
      if (header) {
        header.setAttribute("aria-expanded", "true");
      }
    });
  }

  function renderSizes() {
    const root = $("listSizes");
    root.textContent = "";
    if (!appConfig) {
      return;
    }
    appConfig.label_sizes.forEach(function (s) {
      const article = document.createElement("article");
      article.className = "accordion__item card js-size-card";
      article.innerHTML =
        '<button type="button" class="accordion__header">' +
        '  <span class="accordion__title js-size-card-title"></span>' +
        '  <span class="accordion__chevron" aria-hidden="true"></span>' +
        "</button>" +
        '<div class="accordion__panel">' +
        '  <div class="card__body">' +
        '    <div class="accordion__toolbar">' +
        '      <button type="button" class="btn js-size-save">Save</button>' +
        '      <button type="button" class="btn btn--danger js-size-remove">Remove</button>' +
        "    </div>" +
        '    <p class="card__kicker">Identity</p>' +
        '    <div class="card__grid card__grid--2">' +
        '      <label class="field"><span class="field__label">Preset id</span>' +
        '        <input type="text" class="field__input js-size-id" /></label>' +
        '      <label class="field"><span class="field__label">Name</span>' +
        '        <input type="text" class="field__input js-size-name" /></label>' +
        "    </div>" +
        '    <p class="card__kicker">Dimensions</p>' +
        '    <div class="card__grid card__grid--3">' +
        '      <label class="field"><span class="field__label">Width (mm)</span>' +
        '        <input type="number" class="field__input js-size-w" step="0.1" /></label>' +
        '      <label class="field"><span class="field__label">Height (mm)</span>' +
        '        <input type="number" class="field__input js-size-h" step="0.1" /></label>' +
        '      <label class="field"><span class="field__label">Gap (mm)</span>' +
        '        <input type="number" class="field__input js-size-g" step="0.1" /></label>' +
        "    </div>" +
        "  </div>" +
        "</div>";
      root.appendChild(article);
      const titleEl = article.querySelector(".js-size-card-title");
      setCardTitle(titleEl, s.name || s.id);
      wireAccordionHeader(article, article.querySelector(".accordion__header"));
      article.querySelector(".js-size-id").value = s.id;
      article.querySelector(".js-size-name").value = s.name;
      article.querySelector(".js-size-w").value = String(s.width);
      article.querySelector(".js-size-h").value = String(s.height);
      article.querySelector(".js-size-g").value = String(s.gap);
      article.querySelector(".js-size-name").addEventListener("input", function () {
        const nm = this.value.trim();
        const idv = article.querySelector(".js-size-id").value.trim();
        setCardTitle(titleEl, nm || idv || "Label size");
      });
      article.querySelector(".js-size-id").addEventListener("input", function () {
        const idv = this.value.trim();
        const nm = article.querySelector(".js-size-name").value.trim();
        if (!nm) {
          setCardTitle(titleEl, idv || "Label size");
        }
      });
      article.querySelector(".js-size-remove").addEventListener("click", function (ev) {
        ev.stopPropagation();
        const label = (s.name || s.id) + " (" + s.id + ")";
        if (
          !window.confirm(
            'Remove label size "' + label + '"? Printers or templates that use it must be edited if you save.'
          )
        ) {
          return;
        }
        const cards = Array.prototype.slice.call(
          $("listSizes").querySelectorAll(".js-size-card")
        );
        const idx = cards.indexOf(article);
        if (idx >= 0) {
          appConfig.label_sizes.splice(idx, 1);
        }
        renderSizes();
        saveConfig("Label size removed.")
          .then(function (ok) {
            if (ok === false) {
              loadConfig().catch(function () {});
            }
          })
          .catch(function () {
            loadConfig().catch(function () {});
          });
      });
      article.querySelector(".js-size-save").addEventListener("click", function (ev) {
        ev.stopPropagation();
        saveConfig("Saved.");
      });
    });
  }

  function readTemplatesFromDom() {
    const cards = $("listTemplates").querySelectorAll(".js-tpl-card");
    const out = [];
    cards.forEach(function (card) {
      const idEl = card.querySelector(".js-tpl-id");
      if (!idEl || !idEl.value.trim()) {
        return;
      }
      let elements = [];
      try {
        elements = JSON.parse(card.querySelector(".js-tpl-elements").value);
      } catch (e) {
        throw new Error("Invalid JSON in template " + idEl.value);
      }
      let testData = {};
      try {
        testData = JSON.parse(card.querySelector(".js-tpl-test-data").value);
      } catch (e) {
        throw new Error("Invalid test data JSON in template " + idEl.value);
      }
      if (testData === null || typeof testData !== "object" || Array.isArray(testData)) {
        throw new Error("Test data must be a JSON object in template " + idEl.value);
      }
      const testDataStr = {};
      Object.keys(testData).forEach(function (k) {
        testDataStr[k] = String(testData[k]);
      });
      out.push({
        id: idEl.value.trim(),
        name: card.querySelector(".js-tpl-name").value.trim() || idEl.value.trim(),
        label_size_id: card.querySelector(".js-tpl-ls").value,
        elements: elements,
        test_data: testDataStr,
      });
    });
    return out;
  }

  function labelSizeOptionsHtml(selectedId) {
    if (!appConfig) {
      return "";
    }
    return appConfig.label_sizes
      .map(function (ls) {
        const sel = ls.id === selectedId ? " selected" : "";
        return (
          '<option value="' +
          escapeAttr(ls.id) +
          '"' +
          sel +
          ">" +
          escapeAttr(ls.name) +
          "</option>"
        );
      })
      .join("");
  }

  function escapeAttr(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
  }

  function usbSerialMatches(a, b) {
    if (a == null && b == null) {
      return true;
    }
    if (a == null || b == null) {
      return false;
    }
    return String(a).trim().toUpperCase() === String(b).trim().toUpperCase();
  }

  function findUsbIndexForPrinter(p) {
    let i;
    const wantPort =
      p.usb_port_path && String(p.usb_port_path).trim() !== ""
        ? String(p.usb_port_path).trim()
        : null;
    for (i = 0; i < usbDevices.length; i++) {
      const d = usbDevices[i];
      if (d.vendor_id !== p.vendor_id || d.product_id !== p.product_id) {
        continue;
      }
      if (wantPort) {
        if (d.usb_port_path === wantPort) {
          return i;
        }
        continue;
      }
      if (p.serial) {
        if (usbSerialMatches(d.serial, p.serial)) {
          return i;
        }
      } else {
        return i;
      }
    }
    return -1;
  }

  function fillUsbSelect(selectEl, printerLike) {
    selectEl.textContent = "";
    const oManual = document.createElement("option");
    oManual.value = "";
    oManual.textContent = "— Choose USB device —";
    selectEl.appendChild(oManual);
    usbDevices.forEach(function (d) {
      const o = document.createElement("option");
      o.value = d.device_key;
      o.textContent = d.label;
      selectEl.appendChild(o);
    });
    let chosen = "";
    const pick = findUsbIndexForPrinter(printerLike);
    if (pick >= 0 && usbDevices[pick]) {
      chosen = usbDevices[pick].device_key;
    }
    selectEl.value = chosen;
  }

  function syncUsbDropdowns() {
    const cards = document.querySelectorAll(".js-pr-card");
    cards.forEach(function (card) {
      const sel = card.querySelector(".js-pr-usb-pick");
      if (!sel) {
        return;
      }
      const portEl = card.querySelector(".js-pr-usb-port");
      const portVal = portEl && portEl.value.trim() !== "" ? portEl.value.trim() : null;
      const printerLike = {
        vendor_id: parseInt(card.querySelector(".js-pr-vid").value, 10) || 0,
        product_id: parseInt(card.querySelector(".js-pr-pid").value, 10) || 0,
        serial:
          card.querySelector(".js-pr-ser").value.trim() === ""
            ? null
            : card.querySelector(".js-pr-ser").value.trim(),
        usb_port_path: portVal,
      };
      fillUsbSelect(sel, printerLike);
    });
  }

  function revokeTemplatePreviewUrl(article) {
    const u = article._previewObjectUrl;
    if (u) {
      URL.revokeObjectURL(u);
      article._previewObjectUrl = null;
    }
    const img = article.querySelector(".js-tpl-preview-img");
    if (img) {
      img.removeAttribute("src");
      img.onload = null;
      img.onerror = null;
    }
    const frame = article.querySelector(".js-tpl-preview-frame");
    if (frame) {
      frame.classList.remove("template-preview__frame--has-image");
    }
  }

  function renderTemplates() {
    const root = $("listTemplates");
    if (!root) {
      return;
    }
    root.textContent = "";
    if (!appConfig) {
      return;
    }
    const firstLs = appConfig.label_sizes[0] && appConfig.label_sizes[0].id;
    if (appConfig.templates.length === 0) {
      const empty = document.createElement("p");
      empty.className = "accordion-list__empty";
      empty.textContent =
        "No templates yet. Add a template to define layout and text fields.";
      root.appendChild(empty);
      return;
    }
    appConfig.templates.forEach(function (t) {
      const article = document.createElement("article");
      article.className = "accordion__item card js-tpl-card";
      article.innerHTML =
        '<button type="button" class="accordion__header">' +
        '  <span class="accordion__title js-tpl-card-title"></span>' +
        '  <span class="accordion__chevron" aria-hidden="true"></span>' +
        "</button>" +
        '<div class="accordion__panel">' +
        '  <div class="card__body">' +
        '    <div class="accordion__toolbar">' +
        '      <button type="button" class="btn js-tpl-save">Save</button>' +
        '      <button type="button" class="btn btn--toolbar js-tpl-test">Test print</button>' +
        '      <button type="button" class="btn btn--toolbar js-tpl-preview">Preview</button>' +
        '      <button type="button" class="btn btn--danger js-tpl-remove">Remove</button>' +
        "    </div>" +
        '    <p class="card__kicker">Identity</p>' +
        '    <div class="card__grid card__grid--2">' +
        '      <label class="field"><span class="field__label">Template id</span>' +
        '        <input type="text" class="field__input js-tpl-id" /></label>' +
        '      <label class="field"><span class="field__label">Name</span>' +
        '        <input type="text" class="field__input js-tpl-name" /></label>' +
        "    </div>" +
        '    <label class="field"><span class="field__label">Label size</span>' +
        '      <select class="field__select js-tpl-ls"></select></label>' +
        '    <label class="field"><span class="field__label">Test on printer</span>' +
        '      <select class="field__select js-tpl-test-printer"></select></label>' +
        '    <p class="card__kicker">Layout (JSON)</p>' +
        '    <label class="field"><span class="field__label">Elements</span>' +
        '      <textarea class="field__input field__input--code js-tpl-elements tpl-elements__textarea"></textarea></label>' +
        '    <p class="card__kicker">Test data</p>' +
        '    <label class="field"><span class="field__label">Placeholder values (JSON object)</span>' +
        '      <textarea class="field__input field__input--code js-tpl-test-data" rows="4"></textarea>' +
        '      <span class="field__hint">Used for Test print, Preview, and as defaults when printing.</span></label>' +
        '    <aside class="template-editor__preview" aria-label="Label preview">' +
        '      <p class="card__kicker">Preview</p>' +
        '      <div class="template-preview__frame js-tpl-preview-frame">' +
        '        <img class="template-preview__img js-tpl-preview-img" alt="Raster preview of label" />' +
        '        <p class="template-preview__placeholder">Click Preview to render (same raster as print).</p>' +
        "      </div>" +
        "    </aside>" +
        "  </div>" +
        "</div>";
      root.appendChild(article);
      const titleEl = article.querySelector(".js-tpl-card-title");
      setCardTitle(titleEl, t.name || t.id);
      wireAccordionHeader(article, article.querySelector(".accordion__header"));
      article.querySelector(".js-tpl-id").value = t.id;
      article.querySelector(".js-tpl-name").value = t.name;
      const sel = article.querySelector(".js-tpl-ls");
      sel.innerHTML = labelSizeOptionsHtml(t.label_size_id || firstLs);
      if (!t.label_size_id && firstLs) {
        sel.value = firstLs;
      }
      article.querySelector(".js-tpl-elements").value = JSON.stringify(
        t.elements || [],
        null,
        2
      );
      article.querySelector(".js-tpl-test-data").value = JSON.stringify(
        t.test_data || {},
        null,
        2
      );
      const testPr = article.querySelector(".js-tpl-test-printer");
      testPr.textContent = "";
      if (appConfig.printers.length === 0) {
        const o = document.createElement("option");
        o.value = "";
        o.textContent = "— Add a printer first —";
        testPr.appendChild(o);
        testPr.disabled = true;
      } else {
        testPr.disabled = false;
        appConfig.printers.forEach(function (p) {
          const o = document.createElement("option");
          o.value = p.id;
          o.textContent = p.name + " (" + p.id + ")";
          testPr.appendChild(o);
        });
      }
      article.querySelector(".js-tpl-name").addEventListener("input", function () {
        const nm = this.value.trim();
        const idv = article.querySelector(".js-tpl-id").value.trim();
        setCardTitle(titleEl, nm || idv || "Template");
      });
      article.querySelector(".js-tpl-remove").addEventListener("click", function (ev) {
        ev.stopPropagation();
        const label = (t.name || t.id) + " (" + t.id + ")";
        if (!window.confirm('Remove template "' + label + '"?')) {
          return;
        }
        revokeTemplatePreviewUrl(article);
        const cards = Array.prototype.slice.call(
          $("listTemplates").querySelectorAll(".js-tpl-card")
        );
        const idx = cards.indexOf(article);
        if (idx >= 0) {
          appConfig.templates.splice(idx, 1);
        }
        renderTemplates();
        saveConfig("Template removed.")
          .then(function (ok) {
            if (ok === false) {
              loadConfig().catch(function () {});
            }
          })
          .catch(function () {
            loadConfig().catch(function () {});
          });
      });
      article.querySelector(".js-tpl-save").addEventListener("click", function (ev) {
        ev.stopPropagation();
        saveConfig("Saved.");
      });
      article.querySelector(".js-tpl-test").addEventListener("click", function (ev) {
        ev.stopPropagation();
        const tid = article.querySelector(".js-tpl-id").value.trim();
        const pid = article.querySelector(".js-tpl-test-printer").value;
        if (!tid) {
          setStatus("Set a template id first.", true);
          return;
        }
        if (!pid) {
          setStatus("Choose a printer for the test.", true);
          return;
        }
        apiJson("POST", "/templates/" + encodeURIComponent(tid) + "/test", {
          printer_id: pid,
          data: {},
        })
          .then(function () {
            setStatus("Template test sent.", false);
          })
          .catch(function (e) {
            setStatus(e.message || String(e), true);
          });
      });
      article.querySelector(".js-tpl-preview").addEventListener("click", function (ev) {
        ev.stopPropagation();
        const pid = article.querySelector(".js-tpl-test-printer").value;
        const lsid = article.querySelector(".js-tpl-ls").value;
        if (!pid) {
          setStatus("Choose a printer for preview.", true);
          return;
        }
        if (!lsid) {
          setStatus("Choose a label size.", true);
          return;
        }
        let elements;
        try {
          elements = JSON.parse(article.querySelector(".js-tpl-elements").value);
        } catch (e) {
          setStatus("Elements JSON is invalid.", true);
          return;
        }
        if (!Array.isArray(elements)) {
          setStatus("Elements must be a JSON array.", true);
          return;
        }
        let testData;
        try {
          testData = JSON.parse(article.querySelector(".js-tpl-test-data").value || "{}");
        } catch (e) {
          setStatus("Test data JSON is invalid.", true);
          return;
        }
        if (testData === null || typeof testData !== "object" || Array.isArray(testData)) {
          setStatus("Test data must be a JSON object.", true);
          return;
        }
        const frame = article.querySelector(".js-tpl-preview-frame");
        const img = article.querySelector(".js-tpl-preview-img");
        const prevUrl = article._previewObjectUrl;
        apiBlob("POST", API_PATH_TEMPLATE_PREVIEW, {
          printer_id: pid,
          label_size_id: lsid,
          elements: elements,
          test_data: testData,
          data: {},
        })
          .then(function (blob) {
            const nextUrl = URL.createObjectURL(blob);
            article._previewObjectUrl = nextUrl;
            img.onload = function () {
              img.onload = null;
              img.onerror = null;
              if (prevUrl) {
                URL.revokeObjectURL(prevUrl);
              }
              frame.classList.add("template-preview__frame--has-image");
            };
            img.onerror = function () {
              img.onload = null;
              img.onerror = null;
              URL.revokeObjectURL(nextUrl);
              article._previewObjectUrl = prevUrl || null;
              if (prevUrl) {
                img.src = prevUrl;
              } else {
                img.removeAttribute("src");
                frame.classList.remove("template-preview__frame--has-image");
              }
              setStatus("Preview image failed to load.", true);
            };
            img.src = nextUrl;
            setStatus("Preview updated.", false);
          })
          .catch(function (e) {
            setStatus(e.message || String(e), true);
          });
      });
    });
  }

  function readPrintersFromDom() {
    const cards = $("listPrinters").querySelectorAll(".js-pr-card");
    const out = [];
    cards.forEach(function (card) {
      const idEl = card.querySelector(".js-pr-id");
      if (!idEl || !idEl.value.trim()) {
        return;
      }
      const dirRaw = parseInt(card.querySelector(".js-pr-dir").value, 10);
      const dir = dirRaw === 1 ? 1 : 0;
      const vid = parseInt(card.querySelector(".js-pr-vid").value, 10);
      const pid = parseInt(card.querySelector(".js-pr-pid").value, 10);
      const ser = card.querySelector(".js-pr-ser").value.trim();
      const usbPort = card.querySelector(".js-pr-usb-port");
      const portStr = usbPort && usbPort.value.trim() !== "" ? usbPort.value.trim() : null;
      out.push({
        id: idEl.value.trim(),
        name: card.querySelector(".js-pr-name").value.trim() || idEl.value.trim(),
        vendor_id: Number.isFinite(vid) ? vid : 0,
        product_id: Number.isFinite(pid) ? pid : 0,
        serial: ser === "" ? null : ser,
        usb_port_path: portStr,
        default_label_size_id: card.querySelector(".js-pr-ls").value,
        offset_x: parseFloat(card.querySelector(".js-pr-ox").value) || 0,
        offset_y: parseFloat(card.querySelector(".js-pr-oy").value) || 0,
        direction: Number.isFinite(dir) ? dir : 0,
        dpi: 203,
        text_encoding: (function () {
          const el = card.querySelector(".js-pr-encoding");
          const v = el && el.value ? el.value.trim() : "";
          return v || "utf-8";
        })(),
      });
    });
    return out;
  }

  function renderPrinters() {
    const root = $("listPrinters");
    root.textContent = "";
    if (!appConfig) {
      syncDebugPrinterPanel();
      syncBitmapHelperPrinterSelect();
      return;
    }
    const firstLs = appConfig.label_sizes[0] && appConfig.label_sizes[0].id;
    appConfig.printers.forEach(function (p) {
      const article = document.createElement("article");
      article.className = "accordion__item card js-pr-card";
      article.innerHTML =
        '<button type="button" class="accordion__header">' +
        '  <span class="accordion__title js-pr-card-title"></span>' +
        '  <span class="accordion__chevron" aria-hidden="true"></span>' +
        "</button>" +
        '<div class="accordion__panel">' +
        '  <div class="card__body">' +
        '    <div class="accordion__toolbar">' +
        '      <button type="button" class="btn js-pr-save">Save</button>' +
        '      <button type="button" class="btn btn--toolbar js-pr-test">Test print</button>' +
        '      <button type="button" class="btn btn--danger js-pr-remove">Remove</button>' +
        "    </div>" +
        '    <p class="card__kicker">Identity</p>' +
        '    <div class="card__grid card__grid--2">' +
        '      <label class="field"><span class="field__label">Printer id</span>' +
        '        <input type="text" class="field__input js-pr-id" /></label>' +
        '      <label class="field"><span class="field__label">Display name</span>' +
        '        <input type="text" class="field__input js-pr-name" /></label>' +
        "    </div>" +
        '  <p class="card__kicker">Physical USB device</p>' +
        '  <div class="card__grid card__grid--usb-row">' +
        '    <label class="field field--usb-device">' +
        '      <span class="field__label">This printer is the following device</span>' +
        '      <select class="field__select field__select--usb-device js-pr-usb-pick"></select>' +
        "    </label>" +
        '    <div class="pr-usb-actions">' +
        '      <label class="check">' +
        '        <input type="checkbox" class="js-pr-usb-show-all" />' +
        "        <span>Show all USB devices</span>" +
        "      </label>" +
        '      <button type="button" class="btn btn--secondary js-pr-usb-refresh">Refresh USB</button>' +
        "    </div>" +
        "  </div>" +
        '  <input type="hidden" class="js-pr-vid" value="0" />' +
        '  <input type="hidden" class="js-pr-pid" value="0" />' +
        '  <input type="hidden" class="js-pr-ser" value="" />' +
        '  <input type="hidden" class="js-pr-usb-port" value="" />' +
        '  <p class="card__kicker">Label</p>' +
        '  <label class="field"><span class="field__label">Label size preset</span>' +
        '    <select class="field__select js-pr-ls"></select></label>' +
        '  <p class="card__kicker">Offsets &amp; rotation</p>' +
        '  <div class="card__grid card__grid--3">' +
        '    <label class="field"><span class="field__label">X offset (mm)</span>' +
        '      <input type="number" class="field__input js-pr-ox" step="0.1" /></label>' +
        '    <label class="field"><span class="field__label">Y offset (mm)</span>' +
        '      <input type="number" class="field__input js-pr-oy" step="0.1" /></label>' +
        '    <label class="field"><span class="field__label">Print direction</span>' +
        '      <select class="field__select js-pr-dir">' +
        '        <option value="0">Default</option>' +
        '        <option value="1">180° (upside down)</option>' +
        "      </select></label>" +
        "  </div>" +
        '  <p class="card__kicker">Text encoding</p>' +
        '  <label class="field"><span class="field__label">TEXT payload encoding</span>' +
        '    <select class="field__select js-pr-encoding"></select></label>' +
        '  <p class="field__hint">If the manual lists <strong>code page PC865</strong>, choose <strong>PC865 / IBM Nordic (Python cp865)</strong> above.</p>' +
        "  </div>" +
        "</div>";
      root.appendChild(article);
      const titleEl = article.querySelector(".js-pr-card-title");
      setCardTitle(titleEl, p.name || p.id);
      wireAccordionHeader(article, article.querySelector(".accordion__header"));
      article.querySelector(".js-pr-id").value = p.id;
      article.querySelector(".js-pr-name").value = p.name;
      article.querySelector(".js-pr-vid").value = String(p.vendor_id);
      article.querySelector(".js-pr-pid").value = String(p.product_id);
      article.querySelector(".js-pr-ser").value = p.serial || "";
      article.querySelector(".js-pr-usb-port").value = p.usb_port_path || "";
      const usbSel = article.querySelector(".js-pr-usb-pick");
      fillUsbSelect(usbSel, {
        vendor_id: p.vendor_id,
        product_id: p.product_id,
        serial: p.serial || null,
        usb_port_path: p.usb_port_path || null,
      });
      usbSel.addEventListener("change", function () {
        const v = usbSel.value;
        const nameInput = article.querySelector(".js-pr-name");
        if (v === "") {
          article.querySelector(".js-pr-vid").value = "0";
          article.querySelector(".js-pr-pid").value = "0";
          article.querySelector(".js-pr-ser").value = "";
          article.querySelector(".js-pr-usb-port").value = "";
          return;
        }
        const d = usbDevices.find(function (x) {
          return x.device_key === v;
        });
        if (!d) {
          return;
        }
        article.querySelector(".js-pr-vid").value = String(d.vendor_id);
        article.querySelector(".js-pr-pid").value = String(d.product_id);
        article.querySelector(".js-pr-ser").value = d.serial || "";
        article.querySelector(".js-pr-usb-port").value = d.usb_port_path || "";
        const friendly = (
          (d.manufacturer || "") +
          " " +
          (d.product || "")
        ).trim();
        if (friendly && (!nameInput.value.trim() || nameInput.value === "New printer")) {
          nameInput.value = friendly;
          setCardTitle(titleEl, friendly);
        }
      });
      const lsSel = article.querySelector(".js-pr-ls");
      lsSel.innerHTML = labelSizeOptionsHtml(p.default_label_size_id || firstLs);
      article.querySelector(".js-pr-ox").value = String(p.offset_x);
      article.querySelector(".js-pr-oy").value = String(p.offset_y);
      article.querySelector(".js-pr-dir").value = p.direction === 1 ? "1" : "0";
      const encSel = article.querySelector(".js-pr-encoding");
      const encVal = p.text_encoding || "utf-8";
      encSel.textContent = "";
      let encMatched = false;
      PRINTER_TEXT_ENCODING_OPTIONS.forEach(function (opt) {
        const o = document.createElement("option");
        o.value = opt.value;
        o.textContent = opt.label;
        if (opt.value === encVal) {
          o.selected = true;
          encMatched = true;
        }
        encSel.appendChild(o);
      });
      if (!encMatched) {
        const o = document.createElement("option");
        o.value = encVal;
        o.textContent = encVal + " (custom)";
        o.selected = true;
        encSel.appendChild(o);
      }
      article.querySelector(".js-pr-name").addEventListener("input", function () {
        const nm = this.value.trim();
        const idv = article.querySelector(".js-pr-id").value.trim();
        setCardTitle(titleEl, nm || idv || "Printer");
      });
      article.querySelector(".js-pr-test").addEventListener("click", function (ev) {
        ev.stopPropagation();
        const currentId = article.querySelector(".js-pr-id").value.trim();
        if (!currentId) {
          setStatus("Set a printer id first.", true);
          return;
        }
        testPrinter(currentId);
      });
      article.querySelector(".js-pr-remove").addEventListener("click", function (ev) {
        ev.stopPropagation();
        const label = (p.name || p.id) + " (" + p.id + ")";
        if (!window.confirm('Remove printer "' + label + '"?')) {
          return;
        }
        const cards = Array.prototype.slice.call(
          $("listPrinters").querySelectorAll(".js-pr-card")
        );
        const idx = cards.indexOf(article);
        if (idx >= 0) {
          appConfig.printers.splice(idx, 1);
        }
        renderPrinters();
        saveConfig("Printer removed.")
          .then(function (ok) {
            if (ok === false) {
              loadConfig().catch(function () {});
            }
          })
          .catch(function () {
            loadConfig().catch(function () {});
          });
      });
      article.querySelector(".js-pr-save").addEventListener("click", function (ev) {
        ev.stopPropagation();
        saveConfig("Saved.");
      });
      article.querySelector(".js-pr-usb-refresh").addEventListener("click", function () {
        refreshUsb();
      });
      const showAllCb = article.querySelector(".js-pr-usb-show-all");
      showAllCb.checked = localStorage.getItem(STORAGE_USB_SHOW_ALL) === "1";
      showAllCb.addEventListener("change", function () {
        const on = showAllCb.checked;
        localStorage.setItem(STORAGE_USB_SHOW_ALL, on ? "1" : "0");
        document.querySelectorAll(".js-pr-usb-show-all").forEach(function (cb) {
          cb.checked = on;
        });
        refreshUsb();
      });
    });
    syncDebugPrinterPanel();
    syncBitmapHelperPrinterSelect();
  }

  function readFullConfigFromDom() {
    return {
      server: readServerFromDom(),
      label_sizes: readSizesFromDom(),
      templates: readTemplatesFromDom(),
      printers: readPrintersFromDom(),
    };
  }

  /**
   * Persists DOM config to the server. Returns true if saved, false if validation
   * of the current form failed (no network call). Rejects only on API/network error.
   */
  async function saveConfig(partialMsg) {
    let cfg;
    try {
      cfg = readFullConfigFromDom();
    } catch (e) {
      setStatus(e.message || String(e), true);
      return false;
    }
    try {
      const openSizes = collectOpenAccordionIds($("listSizes"), ACC_CARD_SIZE, ACC_ID_SIZE);
      const openTpls = collectOpenAccordionIds($("listTemplates"), ACC_CARD_TPL, ACC_ID_TPL);
      const openPrs = collectOpenAccordionIds($("listPrinters"), ACC_CARD_PR, ACC_ID_PR);
      await apiJson("PUT", "/config", cfg);
      appConfig = cfg;
      setStatus(partialMsg || "Saved.", false);
      renderSizes();
      applyOpenAccordionIds($("listSizes"), ACC_CARD_SIZE, ACC_ID_SIZE, openSizes);
      renderTemplates();
      applyOpenAccordionIds($("listTemplates"), ACC_CARD_TPL, ACC_ID_TPL, openTpls);
      renderPrinters();
      applyOpenAccordionIds($("listPrinters"), ACC_CARD_PR, ACC_ID_PR, openPrs);
      return true;
    } catch (e) {
      setStatus(e.message || String(e), true);
      throw e;
    }
  }

  async function loadConfig(options) {
    const suppressErrorStatus = options && options.suppressErrorStatus;
    try {
      appConfig = await apiJson("GET", "/config");
      writeServerToDom();
      renderSizes();
      renderTemplates();
      renderPrinters();
      setStatus("Loaded.", false);
    } catch (e) {
      if (!suppressErrorStatus) {
        setStatus(e.message || String(e), true);
      }
      throw e;
    }
  }

  function setBodyAppState(state) {
    const body = document.body;
    body.classList.remove(
      BODY_CLASS_STATE_CONNECTING,
      BODY_CLASS_STATE_READY,
      BODY_CLASS_STATE_OFFLINE
    );
    if (state === "connecting") {
      body.classList.add(BODY_CLASS_STATE_CONNECTING);
    } else if (state === "ready") {
      body.classList.add(BODY_CLASS_STATE_READY);
    } else if (state === "offline") {
      body.classList.add(BODY_CLASS_STATE_OFFLINE);
    }
  }

  function setConnectionGateStatus(message, errorPass) {
    if (!message) {
      return;
    }
    if (errorPass === true) {
      toast.show(message, "error");
    } else if (errorPass === false) {
      toast.show(message, "success");
    } else {
      toast.show(message, "info");
    }
  }

  function persistApiKeyFromInput() {
    const inp = $("apiKeyInput");
    if (!inp) {
      return;
    }
    setStoredApiKey(inp.value);
  }

  async function connectAndLoad() {
    if (!$("connectionGate")) {
      await loadConfig();
      return;
    }
    setConnectionGateStatus("Connecting…");
    setBodyAppState("connecting");
    try {
      await loadConfig({ suppressErrorStatus: true });
      setBodyAppState("ready");
      await refreshUsb();
    } catch (e) {
      setBodyAppState("offline");
      setConnectionGateStatus(e.message || String(e), true);
    }
  }

  async function testPrinter(printerId) {
    try {
      await apiJson("POST", "/printers/" + encodeURIComponent(printerId) + "/test", {});
      setStatus("Printer test sent.", false);
    } catch (e) {
      setStatus(e.message || String(e), true);
    }
  }

  function usbShowAllEnabled() {
    const el = document.querySelector(".js-pr-usb-show-all");
    if (el) {
      return el.checked;
    }
    return localStorage.getItem(STORAGE_USB_SHOW_ALL) === "1";
  }

  function usbDiscoverPath() {
    if (usbShowAllEnabled()) {
      return "/usb/discover?show_all=true";
    }
    return "/usb/discover";
  }

  async function refreshUsb() {
    try {
      const res = await apiJson("GET", usbDiscoverPath());
      usbDevices = res.devices || [];
      setStatus("USB list refreshed.", false);
      syncUsbDropdowns();
    } catch (e) {
      setStatus(e.message || String(e), true);
    }
  }

  wireSecretReveal("btnToggleApiKey", "apiKeyInput", "API key");
  wireSecretReveal("btnToggleSrvApiKey", "srvApiKey", "service API key");

  wireBitmapHelper();
  wireBitmapHelperModal();

  $("btnDebugSend").addEventListener("click", function () {
    sendDebugTspl();
  });

  const btnConnect = $("btnConnect");
  if (btnConnect) {
    btnConnect.addEventListener("click", function () {
      persistApiKeyFromInput();
      connectAndLoad();
    });
  }
  const apiKeyInputEl = $("apiKeyInput");
  if (apiKeyInputEl) {
    apiKeyInputEl.addEventListener("blur", persistApiKeyFromInput);
  }

  $("btnSaveServer").addEventListener("click", function () {
    saveConfig("Server settings saved.");
  });

  $("btnAddTpl").addEventListener("click", function () {
    if (!appConfig || appConfig.label_sizes.length === 0) {
      setStatus("Add a label size first.", true);
      return;
    }
    appConfig.templates.push({
      id: "tpl-" + Date.now(),
      name: "New template",
      label_size_id: appConfig.label_sizes[0].id,
      elements: JSON.parse(DEFAULT_TEMPLATE_ELEMENTS_JSON),
      test_data: JSON.parse(DEFAULT_TEST_DATA_JSON),
    });
    renderTemplates();
  });

  $("btnAddSize").addEventListener("click", function () {
    if (!appConfig) {
      return;
    }
    appConfig.label_sizes.push({
      id: "size-" + Date.now(),
      name: "New size",
      width: 50,
      height: 30,
      gap: 2,
    });
    renderSizes();
  });

  $("btnAddPrinter").addEventListener("click", function () {
    if (!appConfig || appConfig.label_sizes.length === 0) {
      setStatus("Add a label size first.", true);
      return;
    }
    appConfig.printers.push({
      id: "printer-" + Date.now(),
      name: "New printer",
      vendor_id: 0,
      product_id: 0,
      serial: null,
      usb_port_path: null,
      default_label_size_id: appConfig.label_sizes[0].id,
      offset_x: 0,
      offset_y: 0,
      direction: 0,
      dpi: 203,
      text_encoding: "utf-8",
    });
    renderPrinters();
    if (usbDevices.length === 0) {
      refreshUsb();
    } else {
      syncUsbDropdowns();
    }
  });

  if (apiKeyInputEl && getStoredApiKey()) {
    apiKeyInputEl.value = getStoredApiKey();
  }
  syncDebugPrinterPanel();
  syncBitmapHelperPrinterSelect();
  if ($("connectionGate")) {
    connectAndLoad();
  } else {
    loadConfig()
      .then(function () {
        return refreshUsb();
      })
      .catch(function () {});
  }
})();
