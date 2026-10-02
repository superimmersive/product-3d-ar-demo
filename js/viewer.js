(function () {
  var MODEL_VIEWER_SRC = "https://ajax.googleapis.com/ajax/libs/model-viewer/4.0.0/model-viewer.min.js";
  var DEFAULT_ORBIT = "35deg 70deg auto";

  var dialog = document.getElementById("viewer");
  if (!dialog) return;

  var title = dialog.querySelector("#viewer-title");
  var stage = dialog.querySelector(".viewer__stage");
  var loading = dialog.querySelector(".viewer__load");
  var loadingLabel = loading.querySelector("span:last-child");
  var arButton = dialog.querySelector(".viewer__ar");
  var closeButton = dialog.querySelector(".viewer__close");
  var qr = dialog.querySelector(".viewer__qr");
  var qrCanvas = qr.querySelector("canvas");
  var qrUrl = qr.querySelector(".viewer__qr-url");
  var qrTitle = qr.querySelector(".viewer__qr-title");
  var scriptPromise = null;
  var preloaded = {};
  var viewer = null;
  var currentCard = null;
  var returnFocus = null;

  var device = detectDevice();

  function detectDevice() {
    var ua = navigator.userAgent;
    if (/iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)) {
      return "ios";
    }
    if (/Android/i.test(ua)) return "android";
    return "desktop";
  }

  function loadModelViewer() {
    if (window.customElements && customElements.get("model-viewer")) return Promise.resolve();
    if (scriptPromise) return scriptPromise;
    scriptPromise = new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.type = "module";
      script.src = MODEL_VIEWER_SRC;
      script.onload = function () {
        customElements.whenDefined("model-viewer").then(resolve);
      };
      script.onerror = reject;
      document.head.appendChild(script);
    });
    return scriptPromise;
  }

  function preload(src) {
    loadModelViewer();
    if (preloaded[src]) return;
    preloaded[src] = true;
    var link = document.createElement("link");
    link.rel = "prefetch";
    link.as = "fetch";
    link.href = src;
    document.head.appendChild(link);
  }

  function ensureViewer() {
    if (viewer) return viewer;
    viewer = document.createElement("model-viewer");
    viewer.setAttribute("camera-controls", "");
    viewer.setAttribute("touch-action", "none");
    viewer.setAttribute("shadow-intensity", "0.9");
    viewer.setAttribute("shadow-softness", "0.8");
    viewer.setAttribute("environment-image", "neutral");
    viewer.setAttribute("exposure", "1.05");
    viewer.setAttribute("tone-mapping", "aces");
    viewer.setAttribute("interaction-prompt", "none");
    viewer.setAttribute("camera-orbit", DEFAULT_ORBIT);
    viewer.setAttribute("ar", "");
    viewer.setAttribute("ar-scale", "auto");
    viewer.setAttribute("ar-placement", "floor");
    if (device === "ios") viewer.setAttribute("ar-modes", "quick-look");
    if (device === "android") viewer.setAttribute("ar-modes", "scene-viewer");
    viewer.innerHTML = '<button slot="ar-button" hidden></button>';
    viewer.addEventListener("progress", function (event) {
      var amount = event.detail && event.detail.totalProgress;
      if (amount == null || amount >= 1) return;
      loadingLabel.textContent = "Loading model " + Math.round(amount * 100) + "%";
    });
    viewer.addEventListener("load", function () {
      loading.hidden = true;
    });
    viewer.addEventListener("error", function () {
      loadingLabel.textContent = "Model could not load";
      loading.classList.add("is-error");
    });
    viewer.addEventListener("ar-status", function (event) {
      if (event.detail && event.detail.status === "failed") showArMessage("AR could not start on this device.");
    });
    stage.appendChild(viewer);
    return viewer;
  }

  function isLocalHost() {
    return /^(localhost|127\.0\.0\.1)$/i.test(location.hostname);
  }

  function phoneUrl(productId, name) {
    var dir = location.pathname.replace(/[^/]*$/, "");
    var path = dir + "ar.html?m=" + encodeURIComponent(productId) + "&t=" + encodeURIComponent(name);
    if (!isLocalHost()) return Promise.resolve(location.origin + path);
    return fetch("/lan.json", { cache: "no-store" })
      .then(function (res) { return res.json(); })
      .then(function (info) { return info.origin + path; })
      .catch(function () { return location.origin + path; });
  }

  function qrColour() {
    var value = getComputedStyle(document.documentElement).getPropertyValue("--brand-dark").trim();
    return /^#[0-9a-f]{6}$/i.test(value) ? value : "#000000";
  }

  function showQr() {
    if (!currentCard) return;
    qr.hidden = false;
    qrTitle.textContent = "Scan with your phone";
    arButton.classList.add("is-on");
    phoneUrl(currentCard.getAttribute("data-product"), currentCard.getAttribute("data-title") || "").then(function (url) {
      qrUrl.textContent = url;
      if (!window.QRCode || !QRCode.toCanvas) throw new Error("QR library missing");
      QRCode.toCanvas(qrCanvas, url, {
        width: 220,
        margin: 1,
        color: { dark: qrColour(), light: "#ffffff" }
      }, function (err) {
        if (err) qrTitle.textContent = "Could not build scan code";
      });
    }).catch(function () {
      qrTitle.textContent = "Could not build scan code";
    });
  }

  function hideQr() {
    qr.hidden = true;
    arButton.classList.remove("is-on");
  }

  function showArMessage(text) {
    loading.hidden = false;
    loading.classList.add("is-error");
    loadingLabel.textContent = text;
    setTimeout(function () {
      if (viewer && viewer.loaded) {
        loading.hidden = true;
        loading.classList.remove("is-error");
      }
    }, 3000);
  }

  function viewInAr() {
    if (device === "desktop") {
      if (qr.hidden) showQr();
      else hideQr();
      return;
    }
    if (!viewer || !viewer.loaded) return;
    if (viewer.canActivateAR) viewer.activateAR();
    else showArMessage(device === "ios"
      ? "AR Quick Look is not available in this browser. Open the page in Safari."
      : "Scene Viewer is not available. Install or update Google Play Services for AR.");
  }

  function open(card) {
    var src = card.getAttribute("data-model");
    var usdz = card.getAttribute("data-usdz");
    currentCard = card;
    returnFocus = document.activeElement;
    title.textContent = card.getAttribute("data-title") || "";
    hideQr();
    loading.hidden = false;
    loading.classList.remove("is-error");
    loadingLabel.textContent = "Loading model";

    dialog.hidden = false;
    document.body.classList.add("has-viewer");
    requestAnimationFrame(function () {
      dialog.classList.add("is-open");
      closeButton.focus();
    });

    loadModelViewer().then(function () {
      var mv = ensureViewer();
      if (usdz) mv.setAttribute("ios-src", usdz);
      else mv.removeAttribute("ios-src");
      mv.setAttribute("camera-orbit", card.getAttribute("data-orbit") || DEFAULT_ORBIT);
      if (mv.jumpCameraToGoal) mv.jumpCameraToGoal();
      if (mv.getAttribute("src") === src && mv.loaded) {
        loading.hidden = true;
        return;
      }
      mv.setAttribute("alt", title.textContent + " 3D model");
      mv.setAttribute("src", src);
    }).catch(function () {
      loadingLabel.textContent = "3D viewer could not load";
      loading.classList.add("is-error");
    });
  }

  function close() {
    if (dialog.hidden) return;
    hideQr();
    dialog.classList.remove("is-open");
    document.body.classList.remove("has-viewer");
    setTimeout(function () {
      dialog.hidden = true;
    }, 200);
    if (location.hash.indexOf("#3d=") === 0) {
      history.replaceState(null, "", location.pathname + location.search);
    }
    if (returnFocus && returnFocus.focus) returnFocus.focus();
  }

  var cards = document.querySelectorAll(".has-model");
  cards.forEach(function (card) {
    var src = card.getAttribute("data-model");
    card.addEventListener("pointerenter", function () {
      preload(src);
    });
    card.addEventListener("focusin", function () {
      preload(src);
    });
    card.querySelectorAll(".product__media, .product__view").forEach(function (trigger) {
      trigger.addEventListener("click", function () {
        open(card);
      });
    });
  });

  dialog.querySelectorAll("[data-close]").forEach(function (el) {
    el.addEventListener("click", close);
  });
  qr.querySelector(".viewer__qr-close").addEventListener("click", hideQr);
  arButton.addEventListener("click", viewInAr);

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    if (!qr.hidden) hideQr();
    else close();
  });

  function openById(id, scroll) {
    cards.forEach(function (card) {
      if (card.getAttribute("data-product") !== id) return;
      if (scroll) card.scrollIntoView({ block: "center" });
      open(card);
    });
  }

  document.querySelectorAll("[data-open-3d]").forEach(function (trigger) {
    trigger.addEventListener("click", function () {
      openById(trigger.getAttribute("data-open-3d"), false);
    });
  });

  var match = location.hash.match(/^#3d=(.+)$/);
  if (match) openById(decodeURIComponent(match[1]), true);
})();
