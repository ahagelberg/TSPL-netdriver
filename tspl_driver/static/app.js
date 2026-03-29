/* global fetch, localStorage, document, window */
(function () {
  const API_BASE = "/api/v1";
  const STORAGE_KEY_API = "tspl_driver_api_key";
  const STORAGE_USB_SHOW_ALL = "tspl_driver_usb_show_all";
  const SECRET_TOGGLE_SHOW = "Show";
  const SECRET_TOGGLE_HIDE = "Hide";
  const DEFAULT_TEMPLATE_ELEMENTS_JSON =
    '[{"type":"text","x_mm":2,"y_mm":2,"font":"3","content":"{{line1}}"}]';
  const DEFAULT_TEST_DATA_JSON = '{"line1":"Test"}';

  let appConfig = null;
  /** Likely TSPL devices from last GET /usb/discover (`data.devices`). */
  let usbDevices = [];

  function $(id) {
    return document.getElementById(id);
  }

  function setStatus(message, isError) {
    const el = $("globalStatus");
    el.textContent = message || "";
    el.classList.toggle("status--ok", Boolean(message) && !isError);
    el.classList.toggle("status--err", Boolean(message) && isError);
  }

  function setDebugPanelStatus(message, isError) {
    const el = $("debugPanelStatus");
    if (!el) {
      return;
    }
    el.textContent = message || "";
    el.classList.toggle("status--ok", Boolean(message) && !isError);
    el.classList.toggle("status--err", Boolean(message) && isError);
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

  function authHeaders() {
    const k = localStorage.getItem(STORAGE_KEY_API);
    const h = { "Content-Type": "application/json" };
    if (k) {
      h.Authorization = "Bearer " + k;
    }
    return h;
  }

  async function apiJson(method, path, body) {
    const opts = { method: method, headers: authHeaders() };
    if (body !== undefined) {
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(API_BASE + path, opts);
    const j = await r.json().catch(function () {
      return { ok: false, error: { message: r.statusText || "Bad JSON" } };
    });
    if (!r.ok) {
      const msg =
        (j.error && j.error.message) ||
        (typeof j.detail === "string" ? j.detail : "") ||
        r.statusText;
      throw new Error(msg || "Request failed");
    }
    if (j.ok === false) {
      const msg = (j.error && j.error.message) || "Request failed";
      throw new Error(msg);
    }
    return j.data !== undefined ? j.data : j;
  }

  function readServerFromDom() {
    const port = parseInt($("srvPort").value, 10);
    return {
      bind_address: $("srvBind").value.trim(),
      port: Number.isFinite(port) ? port : 8787,
      api_key: $("srvApiKey").value,
    };
  }

  function writeServerToDom() {
    if (!appConfig) {
      return;
    }
    $("srvBind").value = appConfig.server.bind_address;
    $("srvPort").value = String(appConfig.server.port);
    $("srvApiKey").value = appConfig.server.api_key;
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
        width_mm: parseFloat(card.querySelector(".js-size-w").value) || 50,
        height_mm: parseFloat(card.querySelector(".js-size-h").value) || 30,
        gap_mm: parseFloat(card.querySelector(".js-size-g").value) || 2,
      });
    });
    return out;
  }

  function setCardTitle(el, text) {
    if (el) {
      el.textContent = text;
    }
  }

  function renderSizes() {
    const root = $("listSizes");
    root.textContent = "";
    if (!appConfig) {
      return;
    }
    appConfig.label_sizes.forEach(function (s) {
      const article = document.createElement("article");
      article.className = "card js-size-card";
      article.innerHTML =
        '<div class="card__header">' +
        '  <h3 class="card__headline js-size-card-title"></h3>' +
        '  <div class="card__actions">' +
        '    <button type="button" class="btn btn--toolbar js-size-save">Save</button>' +
        '    <button type="button" class="btn btn--danger js-size-remove">Remove</button>' +
        "  </div>" +
        "</div>" +
        '<div class="card__body">' +
        '  <p class="card__kicker">Identity</p>' +
        '  <div class="card__grid card__grid--2">' +
        '    <label class="field"><span class="field__label">Preset id</span>' +
        '      <input type="text" class="field__input js-size-id" /></label>' +
        '    <label class="field"><span class="field__label">Name</span>' +
        '      <input type="text" class="field__input js-size-name" /></label>' +
        "  </div>" +
        '  <p class="card__kicker">Dimensions</p>' +
        '  <div class="card__grid card__grid--3">' +
        '    <label class="field"><span class="field__label">Width mm</span>' +
        '      <input type="number" class="field__input js-size-w" step="0.1" /></label>' +
        '    <label class="field"><span class="field__label">Height mm</span>' +
        '      <input type="number" class="field__input js-size-h" step="0.1" /></label>' +
        '    <label class="field"><span class="field__label">Gap mm</span>' +
        '      <input type="number" class="field__input js-size-g" step="0.1" /></label>' +
        "  </div>" +
        "</div>";
      root.appendChild(article);
      const titleEl = article.querySelector(".js-size-card-title");
      setCardTitle(titleEl, s.name || s.id);
      article.querySelector(".js-size-id").value = s.id;
      article.querySelector(".js-size-name").value = s.name;
      article.querySelector(".js-size-w").value = String(s.width_mm);
      article.querySelector(".js-size-h").value = String(s.height_mm);
      article.querySelector(".js-size-g").value = String(s.gap_mm);
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
      article.querySelector(".js-size-remove").addEventListener("click", function () {
        const cards = Array.prototype.slice.call(
          $("listSizes").querySelectorAll(".js-size-card")
        );
        const idx = cards.indexOf(article);
        if (idx >= 0) {
          appConfig.label_sizes.splice(idx, 1);
        }
        renderSizes();
      });
      article.querySelector(".js-size-save").addEventListener("click", function () {
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
    for (i = 0; i < usbDevices.length; i++) {
      const d = usbDevices[i];
      if (d.vendor_id !== p.vendor_id || d.product_id !== p.product_id) {
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
      const printerLike = {
        vendor_id: parseInt(card.querySelector(".js-pr-vid").value, 10) || 0,
        product_id: parseInt(card.querySelector(".js-pr-pid").value, 10) || 0,
        serial:
          card.querySelector(".js-pr-ser").value.trim() === ""
            ? null
            : card.querySelector(".js-pr-ser").value.trim(),
      };
      fillUsbSelect(sel, printerLike);
    });
  }

  function renderTemplates() {
    const root = $("listTemplates");
    root.textContent = "";
    if (!appConfig) {
      return;
    }
    const firstLs = appConfig.label_sizes[0] && appConfig.label_sizes[0].id;
    appConfig.templates.forEach(function (t) {
      const article = document.createElement("article");
      article.className = "card js-tpl-card";
      article.innerHTML =
        '<div class="card__header">' +
        '  <h3 class="card__headline js-tpl-card-title"></h3>' +
        '  <div class="card__actions">' +
        '    <button type="button" class="btn btn--toolbar js-tpl-save">Save</button>' +
        '    <button type="button" class="btn btn--toolbar js-tpl-test-open">Test</button>' +
        '    <button type="button" class="btn btn--danger js-tpl-remove">Remove</button>' +
        "  </div>" +
        "</div>" +
        '<div class="card__body">' +
        '  <p class="card__kicker">Identity</p>' +
        '  <div class="card__grid card__grid--2">' +
        '    <label class="field"><span class="field__label">Template id</span>' +
        '      <input type="text" class="field__input js-tpl-id" /></label>' +
        '    <label class="field"><span class="field__label">Name</span>' +
        '      <input type="text" class="field__input js-tpl-name" /></label>' +
        "  </div>" +
        '  <label class="field"><span class="field__label">Label size</span>' +
        '    <select class="field__select js-tpl-ls"></select></label>' +
        '  <p class="card__kicker">Layout (JSON)</p>' +
        '  <label class="field"><span class="field__label">Elements</span>' +
        '    <textarea class="field__input field__input--code js-tpl-elements"></textarea></label>' +
        '  <p class="card__kicker">Test data</p>' +
        '  <label class="field"><span class="field__label">Placeholder values (JSON object)</span>' +
        '    <textarea class="field__input field__input--code js-tpl-test-data" rows="4"></textarea>' +
        '    <span class="field__hint">Used when you click <strong>Test</strong> and as the default <code>data</code> for <code>POST /templates/…/test</code>.</span></label>' +
        "</div>";
      root.appendChild(article);
      const titleEl = article.querySelector(".js-tpl-card-title");
      setCardTitle(titleEl, t.name || t.id);
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
      article.querySelector(".js-tpl-name").addEventListener("input", function () {
        const nm = this.value.trim();
        const idv = article.querySelector(".js-tpl-id").value.trim();
        setCardTitle(titleEl, nm || idv || "Template");
      });
      article.querySelector(".js-tpl-remove").addEventListener("click", function () {
        const cards = Array.prototype.slice.call(
          $("listTemplates").querySelectorAll(".js-tpl-card")
        );
        const idx = cards.indexOf(article);
        if (idx >= 0) {
          appConfig.templates.splice(idx, 1);
        }
        renderTemplates();
      });
      article.querySelector(".js-tpl-test-open").addEventListener("click", function () {
        const id = article.querySelector(".js-tpl-id").value.trim();
        openTplTestModal(id || t.id);
      });
      article.querySelector(".js-tpl-save").addEventListener("click", function () {
        saveConfig("Saved.");
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
      out.push({
        id: idEl.value.trim(),
        name: card.querySelector(".js-pr-name").value.trim() || idEl.value.trim(),
        vendor_id: Number.isFinite(vid) ? vid : 0,
        product_id: Number.isFinite(pid) ? pid : 0,
        serial: ser === "" ? null : ser,
        default_label_size_id: card.querySelector(".js-pr-ls").value,
        offset_x_mm: parseFloat(card.querySelector(".js-pr-ox").value) || 0,
        offset_y_mm: parseFloat(card.querySelector(".js-pr-oy").value) || 0,
        direction: Number.isFinite(dir) ? dir : 0,
        dpi: 203,
      });
    });
    return out;
  }

  function renderPrinters() {
    const root = $("listPrinters");
    root.textContent = "";
    if (!appConfig) {
      syncDebugPrinterPanel();
      return;
    }
    const firstLs = appConfig.label_sizes[0] && appConfig.label_sizes[0].id;
    appConfig.printers.forEach(function (p) {
      const article = document.createElement("article");
      article.className = "card js-pr-card";
      article.innerHTML =
        '<div class="card__header">' +
        '  <h3 class="card__headline js-pr-card-title"></h3>' +
        '  <div class="card__actions">' +
        '    <button type="button" class="btn btn--toolbar js-pr-save">Save</button>' +
        '    <button type="button" class="btn btn--toolbar js-pr-test">Test print</button>' +
        '    <button type="button" class="btn btn--danger js-pr-remove">Remove</button>' +
        "  </div>" +
        "</div>" +
        '<div class="card__body">' +
        '  <p class="card__kicker">Identity</p>' +
        '  <div class="card__grid card__grid--2">' +
        '    <label class="field"><span class="field__label">Printer id (for API)</span>' +
        '      <input type="text" class="field__input js-pr-id" /></label>' +
        '    <label class="field"><span class="field__label">Display name</span>' +
        '      <input type="text" class="field__input js-pr-name" /></label>' +
        "  </div>" +
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
        '  <p class="card__kicker">Label</p>' +
        '  <label class="field"><span class="field__label">Label size preset</span>' +
        '    <select class="field__select js-pr-ls"></select></label>' +
        '  <p class="card__kicker">Offsets &amp; rotation</p>' +
        '  <div class="card__grid card__grid--3">' +
        '    <label class="field"><span class="field__label">X offset mm</span>' +
        '      <input type="number" class="field__input js-pr-ox" step="0.1" /></label>' +
        '    <label class="field"><span class="field__label">Y offset mm</span>' +
        '      <input type="number" class="field__input js-pr-oy" step="0.1" /></label>' +
        '    <label class="field"><span class="field__label">Print direction</span>' +
        '      <select class="field__select js-pr-dir">' +
        '        <option value="0">Default</option>' +
        '        <option value="1">180° (upside down)</option>' +
        "      </select></label>" +
        "  </div>" +
        "</div>";
      root.appendChild(article);
      const titleEl = article.querySelector(".js-pr-card-title");
      setCardTitle(titleEl, p.name || p.id);
      article.querySelector(".js-pr-id").value = p.id;
      article.querySelector(".js-pr-name").value = p.name;
      article.querySelector(".js-pr-vid").value = String(p.vendor_id);
      article.querySelector(".js-pr-pid").value = String(p.product_id);
      article.querySelector(".js-pr-ser").value = p.serial || "";
      const usbSel = article.querySelector(".js-pr-usb-pick");
      fillUsbSelect(usbSel, {
        vendor_id: p.vendor_id,
        product_id: p.product_id,
        serial: p.serial || null,
      });
      usbSel.addEventListener("change", function () {
        const v = usbSel.value;
        const nameInput = article.querySelector(".js-pr-name");
        if (v === "") {
          article.querySelector(".js-pr-vid").value = "0";
          article.querySelector(".js-pr-pid").value = "0";
          article.querySelector(".js-pr-ser").value = "";
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
      article.querySelector(".js-pr-ox").value = String(p.offset_x_mm);
      article.querySelector(".js-pr-oy").value = String(p.offset_y_mm);
      article.querySelector(".js-pr-dir").value = p.direction === 1 ? "1" : "0";
      article.querySelector(".js-pr-name").addEventListener("input", function () {
        const nm = this.value.trim();
        const idv = article.querySelector(".js-pr-id").value.trim();
        setCardTitle(titleEl, nm || idv || "Printer");
      });
      article.querySelector(".js-pr-test").addEventListener("click", function () {
        const currentId = article.querySelector(".js-pr-id").value.trim();
        if (!currentId) {
          setStatus("Set a printer id first.", true);
          return;
        }
        testPrinter(currentId);
      });
      article.querySelector(".js-pr-remove").addEventListener("click", function () {
        const cards = Array.prototype.slice.call(
          $("listPrinters").querySelectorAll(".js-pr-card")
        );
        const idx = cards.indexOf(article);
        if (idx >= 0) {
          appConfig.printers.splice(idx, 1);
        }
        renderPrinters();
      });
      article.querySelector(".js-pr-save").addEventListener("click", function () {
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
  }

  function readFullConfigFromDom() {
    return {
      server: readServerFromDom(),
      label_sizes: readSizesFromDom(),
      templates: readTemplatesFromDom(),
      printers: readPrintersFromDom(),
    };
  }

  async function saveConfig(partialMsg) {
    let cfg;
    try {
      cfg = readFullConfigFromDom();
    } catch (e) {
      setStatus(e.message || String(e), true);
      return;
    }
    try {
      await apiJson("PUT", "/config", cfg);
      appConfig = cfg;
      setStatus(partialMsg || "Saved.", false);
      renderSizes();
      renderTemplates();
      renderPrinters();
    } catch (e) {
      setStatus(e.message || String(e), true);
    }
  }

  async function loadConfig() {
    try {
      appConfig = await apiJson("GET", "/config");
      writeServerToDom();
      renderSizes();
      renderTemplates();
      renderPrinters();
      setStatus("Loaded.", false);
    } catch (e) {
      setStatus(e.message || String(e), true);
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

  function openTplTestModal(templateId) {
    $("tplTestId").value = templateId;
    $("tplTestModal").classList.remove("is-hidden");
    $("tplTestModal").setAttribute("aria-hidden", "false");
    const sel = $("tplTestPrinter");
    sel.textContent = "";
    if (appConfig) {
      appConfig.printers.forEach(function (p) {
        const o = document.createElement("option");
        o.value = p.id;
        o.textContent = p.name + " (" + p.id + ")";
        sel.appendChild(o);
      });
    }
  }

  function closeTplTestModal() {
    $("tplTestModal").classList.add("is-hidden");
    $("tplTestModal").setAttribute("aria-hidden", "true");
  }

  async function runTplTest() {
    const tid = $("tplTestId").value;
    const pid = $("tplTestPrinter").value;
    try {
      await apiJson("POST", "/templates/" + encodeURIComponent(tid) + "/test", {
        printer_id: pid,
        data: {},
      });
      setStatus("Template test sent.", false);
      closeTplTestModal();
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
  wireSecretReveal("btnToggleSrvApiKey", "srvApiKey", "config API key");

  $("btnDebugSend").addEventListener("click", function () {
    sendDebugTspl();
  });

  $("btnSaveKey").addEventListener("click", function () {
    const v = $("apiKeyInput").value.trim();
    if (v) {
      localStorage.setItem(STORAGE_KEY_API, v);
    } else {
      localStorage.removeItem(STORAGE_KEY_API);
    }
    setStatus("Key stored in browser.", false);
    loadConfig();
  });

  $("btnSaveServer").addEventListener("click", function () {
    saveConfig("Server settings saved.");
  });

  $("btnSaveSizes").addEventListener("click", function () {
    saveConfig("Label sizes saved.");
  });

  $("btnSaveTpl").addEventListener("click", function () {
    saveConfig("Templates saved.");
  });

  $("btnSavePrinters").addEventListener("click", function () {
    saveConfig("Printers saved.");
  });

  $("btnAddSize").addEventListener("click", function () {
    if (!appConfig) {
      return;
    }
    appConfig.label_sizes.push({
      id: "size-" + Date.now(),
      name: "New size",
      width_mm: 50,
      height_mm: 30,
      gap_mm: 2,
    });
    renderSizes();
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
      default_label_size_id: appConfig.label_sizes[0].id,
      offset_x_mm: 0,
      offset_y_mm: 0,
      direction: 0,
      dpi: 203,
    });
    renderPrinters();
    if (usbDevices.length === 0) {
      refreshUsb();
    } else {
      syncUsbDropdowns();
    }
  });

  $("tplTestClose").addEventListener("click", closeTplTestModal);
  $("tplTestRun").addEventListener("click", runTplTest);

  $("tplTestModal").addEventListener("click", function (e) {
    if (e.target.classList.contains("modal__backdrop")) {
      closeTplTestModal();
    }
  });

  if (localStorage.getItem(STORAGE_KEY_API)) {
    $("apiKeyInput").value = localStorage.getItem(STORAGE_KEY_API);
    loadConfig().then(function () {
      refreshUsb();
    });
  } else {
    setStatus("Enter API key and click Store key.", false);
  }
  syncDebugPrinterPanel();
})();
