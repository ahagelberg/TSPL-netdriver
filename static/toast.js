/* global document, window, globalThis */
(function () {
  const TOAST_DURATION_MS = 5000;
  const TOAST_EXIT_MS = 260;
  const TOAST_MAX_COUNT = 5;

  function ensureHost() {
    let host = document.getElementById("toastHost");
    if (!host) {
      host = document.createElement("div");
      host.id = "toastHost";
      host.className = "toast-host";
      host.setAttribute("aria-live", "polite");
      document.body.appendChild(host);
    }
    return host;
  }

  function trimExcess(host) {
    while (host.children.length >= TOAST_MAX_COUNT) {
      const first = host.firstChild;
      if (first) {
        host.removeChild(first);
      } else {
        break;
      }
    }
  }

  function show(message, variant) {
    if (!message || typeof message !== "string") {
      return;
    }
    const v =
      variant === "error" ? "error" : variant === "info" ? "info" : "success";
    const host = ensureHost();
    trimExcess(host);
    const el = document.createElement("div");
    el.className = "toast toast--" + v;
    el.setAttribute("role", "status");
    el.textContent = message;
    host.appendChild(el);
    requestAnimationFrame(function () {
      el.classList.add("toast--visible");
    });
    window.setTimeout(function () {
      el.classList.remove("toast--visible");
      window.setTimeout(function () {
        if (el.parentNode) {
          el.parentNode.removeChild(el);
        }
      }, TOAST_EXIT_MS);
    }, TOAST_DURATION_MS);
  }

  function normalizeVariant(isErrorOrVariant) {
    if (isErrorOrVariant === true || isErrorOrVariant === "error") {
      return "error";
    }
    if (isErrorOrVariant === "info") {
      return "info";
    }
    return "success";
  }

  globalThis.tsplToast = {
    show: show,
    normalizeVariant: normalizeVariant,
  };
})();

