/* global document, window, URL */
(function () {
  const SECRET_TOGGLE_SHOW = "Show";
  const SECRET_TOGGLE_HIDE = "Hide";
  const INPUT_CLASS = "field__input";
  const PLACEHOLDER_FIELD_CLASS = "print-page__ph-field";
  /** Session snapshot for template, printer, and placeholder values (this tab only). */
  const SESSION_KEY_PRINT_LABEL = "tspl_print_label_session_v1";
  const PERSIST_DEBOUNCE_MS = 400;
  const BODY_CLASS_STATE_CONNECTING = "app-state--connecting";
  const BODY_CLASS_STATE_READY = "app-state--ready";
  const BODY_CLASS_STATE_OFFLINE = "app-state--offline";
  /** Same endpoint as the configuration UI; path is relative to ``api.js`` API_BASE. */
  const API_PATH_TEMPLATE_PREVIEW = "/preview/template";

  const toast = window.tsplToast;
  if (!toast) {
    throw new Error("Load toast.js before print-page.js");
  }
  const api = window.tsplDriverApi;
  if (!api) {
    throw new Error("Load api.js before print-page.js");
  }
  const apiJson = api.apiJson;
  const apiBlob = api.apiBlob;
  const getStoredApiKey = api.getStoredApiKey;
  const setStoredApiKey = api.setStoredApiKey;

  function $(id) {
    return document.getElementById(id);
  }

  function setStatus(message, isErrorOrVariant) {
    if (!message) {
      return;
    }
    toast.show(message, toast.normalizeVariant(isErrorOrVariant));
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

  function readPrintSession() {
    try {
      const raw = sessionStorage.getItem(SESSION_KEY_PRINT_LABEL);
      if (!raw) {
        return null;
      }
      const o = JSON.parse(raw);
      if (!o || typeof o !== "object") {
        return null;
      }
      return o;
    } catch (e) {
      return null;
    }
  }

  function writePrintSession(obj) {
    try {
      sessionStorage.setItem(SESSION_KEY_PRINT_LABEL, JSON.stringify(obj));
    } catch (e) {
      // Quota or private mode; ignore.
    }
  }

  function debounce(fn, ms) {
    let t = null;
    return function () {
      const args = arguments;
      const ctx = this;
      clearTimeout(t);
      t = setTimeout(function () {
        fn.apply(ctx, args);
      }, ms);
    };
  }

  let cachedConfig = null;
  let printPreviewObjectUrl = null;

  function revokePrintPreviewUrl() {
    if (printPreviewObjectUrl) {
      URL.revokeObjectURL(printPreviewObjectUrl);
      printPreviewObjectUrl = null;
    }
    const img = $("printPreviewImg");
    const frame = $("printPreviewFrame");
    if (img) {
      img.removeAttribute("src");
      img.onload = null;
      img.onerror = null;
    }
    if (frame) {
      frame.classList.remove("template-preview__frame--has-image");
    }
  }

  function collectPlaceholderData() {
    const data = {};
    document.querySelectorAll("[data-placeholder-key]").forEach(function (inp) {
      const k = inp.getAttribute("data-placeholder-key");
      data[k] = inp.value;
    });
    return data;
  }

  function defaultPrinterForTemplate(tpl) {
    if (!cachedConfig || !tpl) {
      return "";
    }
    const ls = tpl.label_size_id;
    const first = cachedConfig.printers.find(function (p) {
      return p.default_label_size_id === ls;
    });
    return first ? first.id : (cachedConfig.printers[0] && cachedConfig.printers[0].id) || "";
  }

  function mergeDataForTemplate(tpl, sess) {
    const out = {};
    if (!tpl) {
      return out;
    }
    const keys = tpl.placeholder_keys || [];
    const sessionData =
      sess && sess.data && typeof sess.data === "object" ? sess.data : {};
    const testData = tpl.test_data || {};
    keys.forEach(function (key) {
      if (Object.prototype.hasOwnProperty.call(sessionData, key)) {
        out[key] = sessionData[key];
      } else if (testData[key] !== undefined && testData[key] !== null) {
        out[key] = testData[key];
      } else {
        out[key] = "";
      }
    });
    return out;
  }

  function humanizePlaceholderKey(key) {
    return String(key)
      .replace(/_/g, " ")
      .replace(/\b\w/g, function (c) {
        return c.toUpperCase();
      });
  }

  function labelSizeSummary(tpl) {
    if (!cachedConfig || !tpl) {
      return "";
    }
    const ls = cachedConfig.label_sizes.find(function (x) {
      return x.id === tpl.label_size_id;
    });
    if (!ls) {
      return "";
    }
    return ls.name + " (" + ls.width + "×" + ls.height + " mm)";
  }

  function currentTemplate() {
    const id = $("printTemplateSelect").value;
    if (!cachedConfig || !id) {
      return null;
    }
    return cachedConfig.templates.find(function (t) {
      return t.id === id;
    }) || null;
  }

  function buildSessionSnapshot() {
    const tpl = currentTemplate();
    const pid = $("printPrinterSelect").value;
    return {
      templateId: tpl ? tpl.id : "",
      printerId: pid,
      data: collectPlaceholderData(),
    };
  }

  function persistPrintSession() {
    writePrintSession(buildSessionSnapshot());
  }

  const persistPrintSessionDebounced = debounce(persistPrintSession, PERSIST_DEBOUNCE_MS);

  function fillPrinterSelect(selectedId) {
    const sel = $("printPrinterSelect");
    sel.textContent = "";
    if (!cachedConfig) {
      return;
    }
    cachedConfig.printers.forEach(function (p) {
      const o = document.createElement("option");
      o.value = p.id;
      o.textContent = p.name + " (" + p.id + ")";
      sel.appendChild(o);
    });
    if (selectedId && cachedConfig.printers.some(function (p) { return p.id === selectedId; })) {
      sel.value = selectedId;
    }
  }

  function updateTemplateMeta(tpl) {
    const meta = $("printTemplateMeta");
    if (!meta) {
      return;
    }
    if (!tpl) {
      meta.textContent = "";
      return;
    }
    const summary = labelSizeSummary(tpl);
    meta.textContent = summary ? "Label size: " + summary : "";
  }

  function updateDataEmptyUi(tpl) {
    const emptyEl = $("printDataEmpty");
    if (!emptyEl) {
      return;
    }
    const n = tpl && tpl.placeholder_keys ? tpl.placeholder_keys.length : 0;
    emptyEl.classList.toggle("is-hidden", n !== 0);
  }

  function renderPlaceholderInputs(tpl, mergedData) {
    const root = $("printPlaceholderFields");
    root.textContent = "";
    if (!tpl) {
      return;
    }
    const keys = tpl.placeholder_keys || [];
    keys.forEach(function (key) {
      const wrap = document.createElement("label");
      wrap.className = "field " + PLACEHOLDER_FIELD_CLASS;
      const span = document.createElement("span");
      span.className = "field__label";
      span.textContent = humanizePlaceholderKey(key);
      const inp = document.createElement("input");
      inp.type = "text";
      inp.className = INPUT_CLASS;
      inp.dataset.placeholderKey = key;
      inp.autocomplete = "off";
      const v = mergedData[key];
      inp.value = v !== undefined && v !== null ? String(v) : "";
      wrap.appendChild(span);
      wrap.appendChild(inp);
      root.appendChild(wrap);
    });
  }

  function syncTemplateUi() {
    const tpl = currentTemplate();
    const sess = readPrintSession();
    let printerId = "";
    if (tpl && sess && sess.printerId) {
      if (cachedConfig.printers.some(function (p) { return p.id === sess.printerId; })) {
        printerId = sess.printerId;
      }
    }
    if (!printerId && tpl) {
      printerId = defaultPrinterForTemplate(tpl);
    }
    fillPrinterSelect(printerId);

    const hint = $("printDefaultHint");
    if (tpl && printerId && defaultPrinterForTemplate(tpl) === printerId) {
      hint.textContent =
        "Printer matches this template’s label size by default (you can still change it).";
    } else if (tpl) {
      hint.textContent =
        "Pick any printer; ensure the label roll matches the template’s label size.";
    } else {
      hint.textContent = "";
    }

    updateTemplateMeta(tpl);
    updateDataEmptyUi(tpl);
    const merged = mergeDataForTemplate(tpl, sess);
    renderPlaceholderInputs(tpl, merged);
    revokePrintPreviewUrl();
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

  function setPrintConnectionGateStatus(message, errorPass) {
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

  function hydratePrintApiKeyInput() {
    const keyInput = $("printApiKey");
    const stored = getStoredApiKey();
    if (keyInput && stored) {
      keyInput.value = stored;
    }
  }

  function persistPrintApiKeyFromInput() {
    const inp = $("printApiKey");
    if (!inp) {
      return;
    }
    setStoredApiKey(inp.value);
  }

  async function loadPrintConfig(options) {
    const suppress = options && options.suppressErrorStatus;
    try {
      cachedConfig = await apiJson("GET", "/config");
      const ts = $("printTemplateSelect");
      ts.textContent = "";
      if (cachedConfig.templates.length === 0) {
        const o = document.createElement("option");
        o.value = "";
        o.textContent = "— No templates in config —";
        ts.appendChild(o);
        ts.disabled = true;
        $("printPrinterSelect").disabled = true;
        $("printSubmit").disabled = true;
        $("printPreviewBtn").disabled = true;
        syncTemplateUi();
        setStatus("No templates configured. Add templates on the configuration page.", true);
        return;
      }
      ts.disabled = false;
      $("printPrinterSelect").disabled = false;
      $("printSubmit").disabled = false;
      $("printPreviewBtn").disabled = false;
      cachedConfig.templates.forEach(function (t) {
        const o = document.createElement("option");
        o.value = t.id;
        o.textContent = (t.name || t.id) + " (" + t.id + ")";
        ts.appendChild(o);
      });

      const sess = readPrintSession();
      if (sess && sess.templateId && cachedConfig.templates.some(function (t) { return t.id === sess.templateId; })) {
        ts.value = sess.templateId;
      }

      syncTemplateUi();
      setStatus("Ready.", false);
    } catch (e) {
      if (!suppress) {
        setStatus(e.message || String(e), true);
      }
      throw e;
    }
  }

  async function connectAndLoad() {
    if (!$("connectionGate")) {
      hydratePrintApiKeyInput();
      await loadPrintConfig();
      return;
    }
    hydratePrintApiKeyInput();
    setPrintConnectionGateStatus("Connecting…");
    setBodyAppState("connecting");
    try {
      await loadPrintConfig({ suppressErrorStatus: true });
      setBodyAppState("ready");
    } catch (e) {
      setBodyAppState("offline");
      setPrintConnectionGateStatus(e.message || String(e), true);
    }
  }

  async function submitPrint() {
    persistPrintApiKeyFromInput();
    const tpl = currentTemplate();
    if (!tpl) {
      setStatus("Choose a template.", true);
      return;
    }
    const pid = $("printPrinterSelect").value;
    if (!pid) {
      setStatus("Choose a printer.", true);
      return;
    }
    const data = collectPlaceholderData();
    try {
      await apiJson("POST", "/print/template", {
        template_id: tpl.id,
        printer_id: pid,
        data: data,
      });
      persistPrintSession();
      setStatus("Sent to printer.", false);
    } catch (e) {
      setStatus(e.message || String(e), true);
    }
  }

  async function submitPreview() {
    persistPrintApiKeyFromInput();
    const tpl = currentTemplate();
    if (!tpl) {
      setStatus("Choose a template.", true);
      return;
    }
    const pid = $("printPrinterSelect").value;
    if (!pid) {
      setStatus("Choose a printer.", true);
      return;
    }
    const data = collectPlaceholderData();
    const prevUrl = printPreviewObjectUrl;
    setStatus("Rendering preview…", "info");
    const img = $("printPreviewImg");
    const frame = $("printPreviewFrame");
    try {
      const blob = await apiBlob("POST", API_PATH_TEMPLATE_PREVIEW, {
        printer_id: pid,
        label_size_id: tpl.label_size_id,
        elements: tpl.elements || [],
        test_data: tpl.test_data || {},
        data: data,
      });
      const nextUrl = URL.createObjectURL(blob);
      printPreviewObjectUrl = nextUrl;
      img.onload = function () {
        img.onload = null;
        img.onerror = null;
        if (prevUrl) {
          URL.revokeObjectURL(prevUrl);
        }
        frame.classList.add("template-preview__frame--has-image");
        setStatus("Preview updated.", false);
      };
      img.onerror = function () {
        img.onload = null;
        img.onerror = null;
        URL.revokeObjectURL(nextUrl);
        printPreviewObjectUrl = prevUrl || null;
        if (prevUrl) {
          img.src = prevUrl;
        } else {
          img.removeAttribute("src");
          frame.classList.remove("template-preview__frame--has-image");
        }
        setStatus("Preview image failed to load.", true);
      };
      img.src = nextUrl;
    } catch (e) {
      setStatus(e.message || String(e), true);
    }
  }

  wireSecretReveal("printBtnToggleKey", "printApiKey", "API key");
  const printBtnConnect = $("printBtnConnect");
  if (printBtnConnect) {
    printBtnConnect.addEventListener("click", function () {
      persistPrintApiKeyFromInput();
      connectAndLoad();
    });
  }
  const printApiKeyEl = $("printApiKey");
  if (printApiKeyEl) {
    printApiKeyEl.addEventListener("blur", persistPrintApiKeyFromInput);
  }
  $("printSubmit").addEventListener("click", function () {
    submitPrint();
  });
  $("printPreviewBtn").addEventListener("click", function () {
    submitPreview();
  });

  $("printTemplateSelect").addEventListener("change", function () {
    syncTemplateUi();
    persistPrintSession();
  });

  $("printPrinterSelect").addEventListener("change", function () {
    persistPrintSession();
  });

  const phRoot = $("printPlaceholderFields");
  if (phRoot) {
    phRoot.addEventListener("input", function () {
      persistPrintSessionDebounced();
    });
  }

  window.addEventListener("beforeunload", function () {
    persistPrintSession();
    revokePrintPreviewUrl();
  });

  connectAndLoad();
})();
