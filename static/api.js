/* global fetch, localStorage, globalThis */
(function () {
  const API_BASE = "/api/v1";
  /** Shared by config and print pages on the same origin (scheme + host + port). */
  const STORAGE_KEY_API = "tspl_driver_api_key";
  // How many FastAPI/Pydantic validation entries to show (first errors are usually enough).
  const VALIDATION_ERROR_SUMMARY_MAX = 3;

  function getStoredApiKey() {
    return localStorage.getItem(STORAGE_KEY_API);
  }

  function setStoredApiKey(value) {
    const v = String(value || "").trim();
    if (v) {
      localStorage.setItem(STORAGE_KEY_API, v);
    } else {
      localStorage.removeItem(STORAGE_KEY_API);
    }
  }

  function messageFromApiErrorJson(j, r) {
    if (!j || typeof j !== "object") {
      return (r && r.statusText) || "Request failed";
    }
    if (j.error && typeof j.error.message === "string" && j.error.message) {
      return j.error.message;
    }
    const d = j.detail;
    if (typeof d === "string" && d) {
      return d;
    }
    if (Array.isArray(d) && d.length > 0) {
      const parts = [];
      for (let i = 0; i < d.length && i < VALIDATION_ERROR_SUMMARY_MAX; i += 1) {
        const item = d[i];
        if (!item || typeof item !== "object") {
          continue;
        }
        const msg = item.msg;
        if (typeof msg !== "string" || !msg) {
          continue;
        }
        const loc = item.loc;
        let locPath = "";
        if (Array.isArray(loc)) {
          const segs = loc.filter(function (x) {
            return x !== "body" && x !== "query" && x !== "path" && x !== "header";
          });
          locPath = segs.join(".");
        }
        parts.push(locPath ? locPath + ": " + msg : msg);
      }
      if (parts.length > 0) {
        return parts.join("; ");
      }
    }
    if (
      d &&
      typeof d === "object" &&
      !Array.isArray(d) &&
      typeof d.message === "string" &&
      d.message
    ) {
      return d.message;
    }
    return (r && r.statusText) || "Request failed";
  }

  function authHeaders() {
    const k = getStoredApiKey();
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
      throw new Error(messageFromApiErrorJson(j, r));
    }
    if (j.ok === false) {
      throw new Error(messageFromApiErrorJson(j, r));
    }
    return j.data !== undefined ? j.data : j;
  }

  async function apiBlob(method, path, body) {
    const opts = { method: method, headers: authHeaders() };
    if (body !== undefined) {
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(API_BASE + path, opts);
    if (!r.ok) {
      const ct = r.headers.get("Content-Type") || "";
      let msg = r.statusText || "Request failed";
      if (ct.indexOf("application/json") !== -1) {
        const j = await r.json().catch(function () {
          return null;
        });
        if (j) {
          msg = messageFromApiErrorJson(j, r);
        }
      }
      throw new Error(msg);
    }
    return r.blob();
  }

  globalThis.tsplDriverApi = {
    API_BASE: API_BASE,
    STORAGE_KEY_API: STORAGE_KEY_API,
    getStoredApiKey: getStoredApiKey,
    setStoredApiKey: setStoredApiKey,
    authHeaders: authHeaders,
    apiJson: apiJson,
    apiBlob: apiBlob,
  };
})();
