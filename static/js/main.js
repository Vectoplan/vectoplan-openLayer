(function () {
  "use strict";

  // ───────────────────────────────────────────────────────────
  // Console / Safe Helpers
  // ───────────────────────────────────────────────────────────

  function logInfo() {
    try { console.info.apply(console, arguments); } catch (_) {}
  }

  function logWarn() {
    try { console.warn.apply(console, arguments); } catch (_) {}
  }

  function logError() {
    try { console.error.apply(console, arguments); } catch (_) {}
  }

  function noop() {}

  function nowMs() {
    try { return Date.now(); } catch (_) { return new Date().getTime(); }
  }

  function safeCall(fn, fallback) {
    try { return fn(); } catch (_) { return fallback; }
  }

  function toArray(value) {
    if (Array.isArray(value)) { return value.slice(); }
    if (value == null) { return []; }
    return [value];
  }

  function asText(value, fallback) {
    try {
      if (value == null) { return fallback || ""; }
      return String(value);
    } catch (_) {
      return fallback || "";
    }
  }

  function hasText(value) {
    return asText(value, "").trim() !== "";
  }

  function asBool(value, fallback) {
    if (typeof value === "boolean") { return value; }
    if (value == null) { return !!fallback; }

    var v = asText(value, "").trim().toLowerCase();
    if (v === "1" || v === "true" || v === "yes" || v === "y" || v === "on" || v === "ja") { return true; }
    if (v === "0" || v === "false" || v === "no" || v === "n" || v === "off" || v === "nein") { return false; }

    return !!fallback;
  }

  function numOr(value, fallback) {
    var n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function q(selector, root) {
    try { return (root || document).querySelector(selector); } catch (_) { return null; }
  }

  function qa(selector, root) {
    try { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); } catch (_) { return []; }
  }

  function cloneJson(value, fallback) {
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (_) {
      return fallback;
    }
  }

  function cloneObject(value, fallback) {
    if (value && typeof value === "object") {
      return cloneJson(value, fallback || {});
    }
    return fallback || {};
  }

  function setHidden(el, hidden) {
    try {
      if (!el) { return; }
      if (hidden) { el.setAttribute("hidden", "hidden"); }
      else { el.removeAttribute("hidden"); }
    } catch (_) {}
  }

  function setText(el, text) {
    try {
      if (el) { el.textContent = asText(text, ""); }
    } catch (_) {}
  }

  function setDisabled(el, disabled) {
    try {
      if (!el) { return; }
      el.disabled = !!disabled;
    } catch (_) {}
  }

  function setPressed(el, pressed) {
    try {
      if (!el) { return; }
      el.setAttribute("aria-pressed", pressed ? "true" : "false");
    } catch (_) {}
  }

  function setExpanded(el, expanded) {
    try {
      if (!el) { return; }
      el.setAttribute("aria-expanded", expanded ? "true" : "false");
    } catch (_) {}
  }

  function isObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
  }

  function ensureObject(value) {
    return isObject(value) ? value : {};
  }

  function ensureArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function firstText() {
    var i;
    for (i = 0; i < arguments.length; i += 1) {
      if (hasText(arguments[i])) { return asText(arguments[i], "").trim(); }
    }
    return "";
  }

  function firstFinite() {
    var i;
    for (i = 0; i < arguments.length; i += 1) {
      var n = Number(arguments[i]);
      if (Number.isFinite(n)) { return n; }
    }
    return NaN;
  }

  function uniqueStrings(list) {
    var seen = {};
    var result = [];

    ensureArray(list).forEach(function (item) {
      var value = asText(item, "").trim();
      if (!value) { return; }
      if (seen[value]) { return; }
      seen[value] = true;
      result.push(value);
    });

    return result;
  }

  function escapeSelectorValue(value) {
    try {
      if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(value);
      }
    } catch (_) {}
    return asText(value, "").replace(/["\\]/g, "\\$&");
  }

  function removeNode(node) {
    try {
      if (node && node.parentNode) {
        node.parentNode.removeChild(node);
      }
    } catch (_) {}
  }

  function getPathValue(root, path) {
    try {
      var obj = root;
      var segments = Array.isArray(path) ? path : asText(path, "").split(".");
      var i;

      for (i = 0; i < segments.length; i += 1) {
        if (!obj || typeof obj !== "object") { return undefined; }
        obj = obj[segments[i]];
      }

      return obj;
    } catch (_) {
      return undefined;
    }
  }

  function firstDefinedPath(root, paths) {
    var i;
    for (i = 0; i < paths.length; i += 1) {
      var value = getPathValue(root, paths[i]);
      if (value !== undefined && value !== null) {
        return value;
      }
    }
    return undefined;
  }

  function normalizeId(value, fallback) {
    var raw = hasText(value) ? asText(value, "").trim() : asText(fallback, "").trim();
    if (!raw) { return ""; }
    return raw.replace(/\s+/g, "-");
  }

  function isPointGeometry(geometryType) {
    var g = asText(geometryType, "").toLowerCase();
    return g === "point" || g === "multipoint";
  }

  function isLineGeometry(geometryType) {
    var g = asText(geometryType, "").toLowerCase();
    return g === "linestring" || g === "multilinestring" || g === "line";
  }

  function isPolygonGeometry(geometryType) {
    var g = asText(geometryType, "").toLowerCase();
    return g === "polygon" || g === "multipolygon";
  }

  function normalizeGeometryType(value, fallback) {
    var g = asText(value, "").trim().toLowerCase();
    if (!g) { return asText(fallback, "Point"); }

    if (g === "point") { return "Point"; }
    if (g === "multipoint") { return "MultiPoint"; }
    if (g === "line" || g === "linestring") { return "LineString"; }
    if (g === "multiline" || g === "multilinestring") { return "MultiLineString"; }
    if (g === "polygon") { return "Polygon"; }
    if (g === "multipolygon") { return "MultiPolygon"; }

    return asText(fallback, "Point");
  }

  function normalizeSourceType(value, fallback) {
    var raw = asText(value, "").trim().toLowerCase();
    if (!raw) { return asText(fallback, "placeholder"); }
    if (raw === "geojson" || raw === "json") { return "geojson"; }
    if (raw === "wfs") { return "wfs"; }
    if (raw === "wms") { return "wms"; }
    if (raw === "placeholder" || raw === "mock" || raw === "demo") { return "placeholder"; }
    return asText(fallback, "placeholder");
  }

  function replaceTemplatePlaceholders(template, replacements) {
    var result = asText(template, "");
    var data = ensureObject(replacements);

    Object.keys(data).forEach(function (key) {
      var value = asText(data[key], "");
      result = result.split("{" + key + "}").join(value);
    });

    return result;
  }

  function truncateText(value, maxLength) {
    var text = asText(value, "").trim();
    var limit = clamp(numOr(maxLength, 160), 8, 2000);

    if (text.length <= limit) { return text; }
    return text.slice(0, limit) + " …";
  }

  // ───────────────────────────────────────────────────────────
  // Versions / Limits / Timeouts
  // ───────────────────────────────────────────────────────────

  var OL_VERSION = "10.6.1";
  var OLE_VERSION = "2.4.5";
  var DEFAULT_SCRIPT_TIMEOUT_MS = 25000;
  var DEFAULT_CONDITION_TIMEOUT_MS = 12000;
  var CONDITION_POLL_MS = 120;
  var DEFAULT_DATASET_CACHE_TTL_MS = 30000;
  var DEFAULT_DATASET_DETAIL_CACHE_TTL_MS = 30000;
  var DEFAULT_STYLE_REFRESH_INTERVAL_MS = 5000;
  var DEFAULT_FEATURE_CACHE_TTL_MS = 20000;
  var DEFAULT_WFS_FEATURE_LIMIT = 1000;
  var MAX_WFS_FEATURE_LIMIT = 1000;
  var DEFAULT_DATASET_RADIUS_METERS = 400;
  var MAX_DATASET_RADIUS_METERS = 400;
  var DEFAULT_DATASET_MIN_LOAD_ZOOM = 14;
  var VIEWPORT_RELOAD_DELAY_MS = 140;
  var MAX_VIEWPORT_FEATURE_CACHE_ENTRIES = 32;
  var DEFAULT_DATASET_BATCH_SIZE = 100;
  var DATASET_BATCH_DELAY_MS = 120;
  var MAX_RESPONSE_PREVIEW_LENGTH = 220;
  var MAX_STYLE_CACHE_KEYS = 64;

  // ───────────────────────────────────────────────────────────
  // Config
  // ───────────────────────────────────────────────────────────

  function isProbablyUsableMapboxToken(token) {
    var t = asText(token, "").trim();
    if (!t) { return false; }
    if (t.length < 20) { return false; }

    var upper = t.toUpperCase();
    if (upper.indexOf("CHANGE_ME") >= 0) { return false; }
    if (upper.indexOf("PLACEHOLDER") >= 0) { return false; }
    if (upper.indexOf("TOKEN_HERE") >= 0) { return false; }

    return t.indexOf("pk.") === 0 || t.indexOf("sk.") === 0;
  }

  function normalizeServiceHealth(raw) {
    raw = ensureObject(raw);
    return {
      orchestrator_client_available: asBool(raw.orchestrator_client_available, false),
      dataset_catalog_service_available: asBool(raw.dataset_catalog_service_available, false),
      dataset_source_service_available: asBool(raw.dataset_source_service_available, false),
      style_adapter_available: asBool(raw.style_adapter_available, false)
    };
  }

  function normalizeDatasetPreview(raw) {
    raw = ensureObject(raw);
    return {
      available: asBool(raw.available, false),
      dataset_count: clamp(numOr(raw.dataset_count, 0), 0, 999999),
      active_count: clamp(numOr(raw.active_count, 0), 0, 999999),
      editable_count: clamp(numOr(raw.editable_count, 0), 0, 999999),
      first_dataset_id: asText(raw.first_dataset_id, ""),
      first_dataset_title: asText(raw.first_dataset_title, ""),
      warning: asText(raw.warning, "")
    };
  }

  function normalizeConfig(raw) {
    raw = raw || {};

    var lon = clamp(numOr(raw.lon, 11.576124), -180, 180);
    var lat = clamp(numOr(raw.lat, 48.137154), -90, 90);
    var minZoom = clamp(numOr(raw.minZoom, 0), 0, 22);
    var maxZoom = clamp(numOr(raw.maxZoom, 22), minZoom, 22);
    var zoom = clamp(numOr(raw.zoom, 14), minZoom, maxZoom);
    var disableScroll = asBool(raw.disableScroll, false);
    var enableWheelZoom = asBool(raw.enableWheelZoom, !disableScroll) && !disableScroll;

    var preserveInitialView = false;
    var compactViewport = false;
    var initialDatasetPanelOpen = true;

    try {
      compactViewport = Boolean(
        window.matchMedia
        && window.matchMedia("(max-width: 640px)").matches
      );
      var initialSearchParams = new URLSearchParams(window.location.search || "");
      preserveInitialView = initialSearchParams.has("lon") && initialSearchParams.has("lat");
      var initialPanel = asText(initialSearchParams.get("initial_panel"), "").toLowerCase();
      var presentationMode = asText(initialSearchParams.get("mode"), "").toLowerCase();
      var initialPanelExplicitlyOpen = ["dataset", "datasets", "open"].indexOf(initialPanel) !== -1;
      initialDatasetPanelOpen = (
        presentationMode !== "preview"
        && initialPanelExplicitlyOpen
      ) || (
          presentationMode !== "preview"
          && !compactViewport
          && ["none", "closed", "hidden"].indexOf(initialPanel) === -1
      );
    } catch (_) {
      preserveInitialView = false;
      initialDatasetPanelOpen = !compactViewport;
    }

    var token = asText(raw.token, "");
    var usableToken = isProbablyUsableMapboxToken(token);

    var serviceHealth = normalizeServiceHealth(raw.serviceHealth);
    var datasetPreview = normalizeDatasetPreview(raw.datasetCatalogPreview);

    var datasetsApiUrlBase = hasText(raw.datasetsApiUrlBase)
      ? asText(raw.datasetsApiUrlBase, "")
      : "/api/datasets";

    var datasetsApiUrl = hasText(raw.datasetsApiUrl)
      ? asText(raw.datasetsApiUrl, "")
      : "/api/datasets?include_style_details=1&include_invalid=0";

    var datasetsApiStyleContractUrl = hasText(raw.datasetsApiStyleContractUrl)
      ? asText(raw.datasetsApiStyleContractUrl, "")
      : "/api/datasets?include_style_details=1&include_style_contract=1&include_invalid=0";

    var datasetSourceUrlTemplate = hasText(raw.datasetSourceUrlTemplate)
      ? asText(raw.datasetSourceUrlTemplate, "")
      : "/api/datasets/{dataset_id}/source";

    var datasetExportUrlTemplate = hasText(raw.datasetExportUrlTemplate)
      ? asText(raw.datasetExportUrlTemplate, "")
      : "/api/datasets/{dataset_id}/export";

    var datasetStyleUrlTemplate = hasText(raw.datasetStyleUrlTemplate)
      ? asText(raw.datasetStyleUrlTemplate, "")
      : "/api/datasets/{dataset_id}?include_style_contract=1";

    var datasetChangesUrlTemplate = hasText(raw.datasetChangesUrlTemplate)
      ? asText(raw.datasetChangesUrlTemplate, "")
      : "/api/datasets/{dataset_id}/changes";

    var orchestratorConfigured = asBool(raw.orchestratorConfigured, hasText(raw.geoserverOrchestratorUrl));
    var orchestratorClientAvailable = asBool(raw.orchestratorClientAvailable, serviceHealth.orchestrator_client_available);

    var datasetIntegrationDegraded = asBool(
      raw.datasetIntegrationDegraded,
      asBool(raw.datasetApiEnabled, false) && (
        !orchestratorConfigured ||
        !orchestratorClientAvailable ||
        !serviceHealth.dataset_catalog_service_available ||
        !serviceHealth.dataset_source_service_available
      )
    );

    return {
      token: token,
      tokenUsable: usableToken,
      styleId: hasText(raw.styleId) ? asText(raw.styleId, "") : "mapbox/light-v11",
      lon: lon,
      lat: lat,
      zoom: zoom,
      minZoom: minZoom,
      maxZoom: maxZoom,
      tileSize: clamp(numOr(raw.tileSize, 512), 128, 1024),
      disableScroll: disableScroll,
      enableWheelZoom: enableWheelZoom,
      preserveInitialView: preserveInitialView,

      serverError: asBool(raw.serverError, false),
      serverErrorMsg: asText(raw.serverErrorMsg, ""),
      serverErrorDetail: asText(raw.serverErrorDetail, ""),

      datasetApiEnabled: asBool(raw.datasetApiEnabled, false),
      editorEnabled: asBool(raw.editorEnabled, false),
      datasetMinLoadZoom: clamp(numOr(raw.datasetMinLoadZoom, DEFAULT_DATASET_MIN_LOAD_ZOOM), minZoom, maxZoom),
      datasetFeatureLimit: clamp(numOr(raw.datasetFeatureLimit, DEFAULT_WFS_FEATURE_LIMIT), 1, MAX_WFS_FEATURE_LIMIT),
      datasetRadiusMeters: clamp(numOr(raw.datasetRadiusMeters, DEFAULT_DATASET_RADIUS_METERS), 1, MAX_DATASET_RADIUS_METERS),
      datasetExportEnabled: asBool(raw.datasetExportEnabled, true),

      datasetsApiUrl: datasetsApiUrl,
      datasetsApiUrlBase: datasetsApiUrlBase,
      datasetsApiStyleContractUrl: datasetsApiStyleContractUrl,
      datasetSourceUrlTemplate: datasetSourceUrlTemplate,
      datasetExportUrlTemplate: datasetExportUrlTemplate,
      datasetStyleUrlTemplate: datasetStyleUrlTemplate,
      datasetChangesUrlTemplate: datasetChangesUrlTemplate,

      geoserverOrchestratorUrl: asText(raw.geoserverOrchestratorUrl, ""),
      orchestratorConfigured: orchestratorConfigured,
      orchestratorClientAvailable: orchestratorClientAvailable,

      mapboxTokenPresent: usableToken,
      styleRequiresMapboxToken: asBool(raw.styleRequiresMapboxToken, true),
      styleTokenMismatch: asBool(raw.styleTokenMismatch, false) || (asBool(raw.styleRequiresMapboxToken, true) && !usableToken),
      scrollSource: asText(raw.scrollSource, ""),

      initialDatasetId: asText(raw.initialDatasetId, ""),
      initialDatasetTitle: asText(raw.initialDatasetTitle, ""),
      initialDatasetPanelOpen: initialDatasetPanelOpen,
      projectPublicId: asText(raw.projectPublicId, ""),
      parcelSelectionReadonly: asBool(raw.parcelSelectionReadonly, false),

      datasetCatalogPreview: datasetPreview,
      serviceHealth: serviceHealth,
      serviceInitSummary: cloneObject(raw.serviceInitSummary, {}),
      serviceFailures: cloneObject(raw.serviceFailures, {}),
      runtimeSummary: cloneObject(raw.runtimeSummary, {}),
      datasetIntegrationDegraded: datasetIntegrationDegraded,

      ui: {
        showToolbar: asBool(raw.ui && raw.ui.showToolbar, true),
        showDatasetButton: asBool(raw.ui && raw.ui.showDatasetButton, true),
        showEditorButton: asBool(raw.ui && raw.ui.showEditorButton, false),
        showZoomButtons: asBool(raw.ui && raw.ui.showZoomButtons, false)
      }
    };
  }

  var cfg = normalizeConfig(window.OPENLAYER_CONFIG || {});

  // ───────────────────────────────────────────────────────────
  // App State
  // ───────────────────────────────────────────────────────────

  var state = {
    map: null,
    view: null,
    baseLayers: {
      mapbox: null,
      osm: null,
      usingFallbackOsm: false
    },

    location: {
      anchorLonLat: [cfg.lon, cfg.lat],
      anchorProjected: null,
      radiusProjectionUnits: cfg.datasetRadiusMeters,
      constraining: false,
      markerOverlay: null,
      markerElement: null,
      markerDragging: false,
      manualOverride: false,
      pendingLocalCoordinate: null,
      pendingLocalCoordinateUntil: 0
    },

    datasetLayer: null,
    datasetSource: null,
    activeDataset: null,

    parcelSelection: {
      panelOpen: false,
      mode: "add",
      byId: {},
      revision: 0,
      hydrated: false,
      defaultCoordinateSelectionDone: false
    },

    datasets: {
      items: [],
      byId: {},
      inflight: null,
      fetchedAt: 0,
      ttlMs: DEFAULT_DATASET_CACHE_TTL_MS,
      lastPayload: null,
      detailCache: {},
      detailCacheTtlMs: DEFAULT_DATASET_DETAIL_CACHE_TTL_MS,
      featureCache: {},
      featureCacheTtlMs: DEFAULT_FEATURE_CACHE_TTL_MS,
      initialSelectionAttempted: false,
      viewportTimer: null,
      requestController: null,
      requestSerial: 0,
      lastFeatureCount: 0,
      lastViewportKey: "",
      loading: false,
      zoomSuppressed: false
    },

    style: {
      cache: {},
      cacheOrder: [],
      refreshTimer: null,
      refreshInflight: null
    },

    editor: {
      active: false,
      loading: false,
      instance: null,
      controls: [],
      lastDatasetId: "",
      libraryReady: false
    },

    ui: {
      datasetPanelOpen: cfg.initialDatasetPanelOpen,
      editorPanelOpen: false,
      downloadPanelOpen: false,
      exportLoading: false
    }
  };

  var dom = {
    appShell: null,
    map: null,
    toolbarStack: null,

    btnDatasets: null,
    btnEditor: null,
    btnDownload: null,
    btnZoomIn: null,
    btnZoomOut: null,
    btnParcels: null,

    datasetPanel: null,
    datasetPanelLoading: null,
    datasetPanelError: null,
    datasetPanelEmpty: null,
    datasetPanelDisabledNote: null,
    datasetPanelServiceNote: null,
    datasetPanelClose: null,
    datasetList: null,
    datasetTemplate: null,

    editorPanel: null,
    editorPanelMeta: null,
    editorPanelNote: null,
    editorPanelClose: null,

    downloadPanel: null,
    downloadPanelClose: null,
    downloadStatus: null,
    downloadActions: [],
    parcelPanel: null,
    parcelPanelClose: null,
    parcelModeButtons: [],
    parcelClear: null,
    parcelCount: null,
    parcelStatus: null,
    statusBanner: null,
    statusBannerText: null,
    statusToast: null,
    statusToastTitle: null,
    statusToastText: null
  };

  // ───────────────────────────────────────────────────────────
  // DOM Bootstrap
  // ───────────────────────────────────────────────────────────

  function bindDom() {
    dom.appShell = q("#app-shell");
    dom.map = q("#map");
    dom.toolbarStack = q("#toolbar-stack");

    dom.btnDatasets = q("#toolbar-datasets-toggle");
    dom.btnEditor = q("#toolbar-editor-toggle");
    dom.btnDownload = q("#toolbar-download-toggle");
    dom.btnZoomIn = q("#toolbar-zoom-in");
    dom.btnZoomOut = q("#toolbar-zoom-out");
    dom.btnParcels = q("#toolbar-parcels-toggle");

    dom.datasetPanel = q("#dataset-panel");
    dom.datasetPanelLoading = q("#dataset-panel-loading");
    dom.datasetPanelError = q("#dataset-panel-error");
    dom.datasetPanelEmpty = q("#dataset-panel-empty");
    dom.datasetPanelDisabledNote = q("#dataset-panel-disabled-note");
    dom.datasetPanelServiceNote = q("#dataset-panel-service-note");
    dom.datasetPanelClose = q("#dataset-panel-close");
    dom.datasetList = q("#dataset-list");
    dom.datasetTemplate = q("#dataset-item-template");

    dom.editorPanel = q("#editor-panel");
    dom.editorPanelMeta = q("#editor-panel-meta");
    dom.editorPanelNote = q("#editor-panel-note");
    dom.editorPanelClose = q("#editor-panel-close");

    dom.downloadPanel = q("#download-panel");
    dom.downloadPanelClose = q("#download-panel-close");
    dom.downloadStatus = q("#download-status");
    dom.downloadActions = qa("[data-export-format]", dom.downloadPanel);
    dom.parcelPanel = q("#parcel-selection-panel");
    dom.parcelPanelClose = q("#parcel-selection-close");
    dom.parcelModeButtons = qa("[data-parcel-mode]", dom.parcelPanel);
    dom.parcelClear = q("[data-parcel-clear]", dom.parcelPanel);
    dom.parcelCount = q("[data-parcel-count]", dom.parcelPanel);
    dom.parcelStatus = q("[data-parcel-status]", dom.parcelPanel);
    dom.statusBanner = q("#map-status-banner");
    dom.statusBannerText = q("#map-status-banner-text");
    dom.statusToast = q("#map-status");
    dom.statusToastTitle = q("#map-status-title");
    dom.statusToastText = q("#map-status-text");

    try {
      if (dom.appShell && dom.appShell.classList) {
        dom.appShell.classList.add("app-shell--compact");
      }
    } catch (_) {}
  }

  // ───────────────────────────────────────────────────────────
  // UI Status / Banner
  // ───────────────────────────────────────────────────────────

  var toastTimer = null;

  function setToast(kind, title, text, durationMs) {
    try {
      if (!dom.statusToast) { return; }

      if (toastTimer) {
        clearTimeout(toastTimer);
        toastTimer = null;
      }

      dom.statusToast.classList.remove("floating-status--danger", "floating-status--success");
      dom.statusToast.classList.add(kind === "danger" ? "floating-status--danger" : "floating-status--success");

      setText(dom.statusToastTitle, title || "Status");
      setText(dom.statusToastText, text || "");
      setHidden(dom.statusToast, false);

      if (durationMs !== 0) {
        toastTimer = setTimeout(function () {
          setHidden(dom.statusToast, true);
        }, Math.max(1200, numOr(durationMs, 3400)));
      }
    } catch (_) {}
  }

  function setBanner(kind, text, visible) {
    try {
      if (!dom.statusBanner) { return; }

      dom.statusBanner.classList.remove("floating-banner--danger", "floating-banner--success");
      dom.statusBanner.classList.add(kind === "danger" ? "floating-banner--danger" : "floating-banner--success");

      if (dom.statusBannerText && hasText(text)) {
        setText(dom.statusBannerText, text);
      }

      setHidden(dom.statusBanner, !visible);
    } catch (_) {}
  }

  function syncInitialBanner() {
    if (cfg.serverError) {
      setBanner(
        "danger",
        cfg.serverErrorMsg ? ("Server-Fallback aktiv: " + cfg.serverErrorMsg) : "Server-Fallback aktiv.",
        true
      );
      return;
    }

    if (cfg.styleTokenMismatch) {
      setBanner(
        "danger",
        "Für den gewählten Mapbox-Stil ist aktuell kein gültiger Mapbox-Token verfügbar. OSM-Fallback wird genutzt.",
        true
      );
      return;
    }

    if (cfg.datasetApiEnabled && cfg.datasetIntegrationDegraded) {
      setBanner(
        "danger",
        "Die Orchestrator-/Dataset-Integration ist noch nicht vollständig bereit. Die Karte bleibt nutzbar, aber Datensatz- oder Style-Funktionen können eingeschränkt sein.",
        true
      );
      return;
    }

    if (dom.statusBanner) {
      setHidden(dom.statusBanner, true);
    }
  }

  // ───────────────────────────────────────────────────────────
  // Asset Loader
  // ───────────────────────────────────────────────────────────

  function findLoadedStylesheetBySuffix(suffix) {
    var wanted = asText(suffix, "").trim();
    if (!wanted) { return null; }

    return qa("link[rel='stylesheet']").find(function (node) {
      try {
        var href = asText(node.getAttribute("href"), "");
        return href.indexOf(wanted) >= 0;
      } catch (_) {
        return false;
      }
    }) || null;
  }

  function hasOL() {
    return !!(window.ol && window.ol.Map && window.ol.View && window.ol.layer);
  }

  function hasOLE() {
    return !!(window.ole && window.ole.Editor);
  }

  function hasOLCssLoaded() {
    return !!(
      findLoadedStylesheetBySuffix("/ol.css") ||
      findLoadedStylesheetBySuffix("ol@" + OL_VERSION + "/ol.css")
    );
  }

  function waitForCondition(checkFn, timeoutMs, intervalMs) {
    return new Promise(function (resolve, reject) {
      var started = nowMs();
      var timeout = Math.max(1000, numOr(timeoutMs, DEFAULT_CONDITION_TIMEOUT_MS));
      var interval = Math.max(50, numOr(intervalMs, CONDITION_POLL_MS));
      var timer = null;

      function stop() {
        try {
          if (timer) { clearTimeout(timer); }
        } catch (_) {}
        timer = null;
      }

      function tick() {
        var ok = false;

        try {
          ok = !!checkFn();
        } catch (_) {
          ok = false;
        }

        if (ok) {
          stop();
          resolve(true);
          return;
        }

        if (nowMs() - started >= timeout) {
          stop();
          reject(new Error("condition timeout"));
          return;
        }

        timer = setTimeout(tick, interval);
      }

      tick();
    });
  }

  function loadCss(url) {
    return new Promise(function (resolve, reject) {
      try {
        if (!hasText(url)) {
          reject(new Error("css url missing"));
          return;
        }

        var safeUrl = asText(url, "");
        var existing = q('link[href="' + escapeSelectorValue(safeUrl) + '"]');

        if (existing && existing.getAttribute("data-loaded") === "true") {
          resolve(safeUrl);
          return;
        }

        if (existing && existing.getAttribute("data-load-failed") === "true") {
          removeNode(existing);
          existing = null;
        }

        var link = existing || document.createElement("link");
        var finished = false;

        function done(err) {
          if (finished) { return; }
          finished = true;

          if (err) {
            try { link.setAttribute("data-load-failed", "true"); } catch (_) {}
            reject(err);
          } else {
            try {
              link.setAttribute("data-loaded", "true");
              link.removeAttribute("data-load-failed");
            } catch (_) {}
            resolve(safeUrl);
          }
        }

        link.rel = "stylesheet";
        link.href = safeUrl;
        link.setAttribute("data-openlayer-loader", "true");
        link.onload = function () { done(); };
        link.onerror = function () { done(new Error("css load error: " + safeUrl)); };

        if (!existing) {
          document.head.appendChild(link);
        }
      } catch (e) {
        reject(e);
      }
    });
  }

  function loadScript(url, timeoutMs, readyCheck) {
    return new Promise(function (resolve, reject) {
      try {
        if (!hasText(url)) {
          reject(new Error("script url missing"));
          return;
        }

        var safeUrl = asText(url, "");
        var existing = q('script[src="' + escapeSelectorValue(safeUrl) + '"]');

        if (existing && existing.getAttribute("data-loaded") === "true") {
          if (typeof readyCheck === "function") {
            try {
              if (readyCheck()) {
                resolve(safeUrl);
                return;
              }
            } catch (_) {}
          } else {
            resolve(safeUrl);
            return;
          }
        }

        if (existing && existing.getAttribute("data-load-failed") === "true") {
          removeNode(existing);
          existing = null;
        }

        var script = existing || document.createElement("script");
        var finished = false;
        var timer = null;

        function cleanup() {
          try { if (timer) { clearTimeout(timer); } } catch (_) {}
          timer = null;
        }

        function finish(err) {
          if (finished) { return; }
          finished = true;
          cleanup();

          if (err) {
            try { script.setAttribute("data-load-failed", "true"); } catch (_) {}
            reject(err);
          } else {
            try {
              script.setAttribute("data-loaded", "true");
              script.removeAttribute("data-load-failed");
            } catch (_) {}
            resolve(safeUrl);
          }
        }

        function onLoad() {
          if (typeof readyCheck === "function") {
            waitForCondition(readyCheck, DEFAULT_CONDITION_TIMEOUT_MS, CONDITION_POLL_MS)
              .then(function () {
                finish();
              })
              .catch(function () {
                finish(new Error("script loaded but readiness check failed: " + safeUrl));
              });
            return;
          }

          finish();
        }

        function onError() {
          finish(new Error("script load error: " + safeUrl));
        }

        script.src = safeUrl;
        script.async = false;
        script.defer = false;
        script.setAttribute("data-openlayer-loader", "true");

        script.addEventListener("load", onLoad, { once: true });
        script.addEventListener("error", onError, { once: true });

        if (!existing) {
          document.head.appendChild(script);
        }

        timer = setTimeout(function () {
          if (typeof readyCheck === "function") {
            try {
              if (readyCheck()) {
                finish();
                return;
              }
            } catch (_) {}
          }
          finish(new Error("script timeout: " + safeUrl));
        }, Math.max(2000, numOr(timeoutMs, DEFAULT_SCRIPT_TIMEOUT_MS)));
      } catch (e) {
        reject(e);
      }
    });
  }

  function tryLoadOne(urls, loader, label) {
    var list = toArray(urls).filter(function (u) { return hasText(u); });

    return list.reduce(function (promise, url) {
      return promise.catch(function (previousError) {
        if (previousError) {
          logWarn("[OpenLayer] Vorheriger Fehler bei " + label + ":", previousError && previousError.message ? previousError.message : previousError);
        }
        logWarn("[OpenLayer] Lade " + label + " von", url);
        return loader(url);
      });
    }, Promise.reject(null)).then(function (loaded) {
      logInfo("[OpenLayer] " + label + " geladen:", loaded);
      return loaded;
    });
  }

  function ensureOL() {
    if (hasOL()) { return Promise.resolve("already-present"); }

    var cssUrls = [
      "https://cdn.jsdelivr.net/npm/ol@" + OL_VERSION + "/ol.css",
      "https://unpkg.com/ol@" + OL_VERSION + "/ol.css"
    ];
    var jsUrls = [
      "https://cdn.jsdelivr.net/npm/ol@" + OL_VERSION + "/dist/ol.js",
      "https://unpkg.com/ol@" + OL_VERSION + "/dist/ol.js"
    ];

    var cssPromise;
    if (hasOLCssLoaded()) {
      cssPromise = Promise.resolve("already-present");
    } else {
      cssPromise = tryLoadOne(cssUrls, loadCss, "ol.css")
        .catch(function (e) {
          logWarn("[OpenLayer] ol.css warn:", e && e.message ? e.message : e);
          return "css-optional-failed";
        });
    }

    return cssPromise
      .then(function () {
        return tryLoadOne(jsUrls, function (u) {
          return loadScript(u, DEFAULT_SCRIPT_TIMEOUT_MS, hasOL);
        }, "ol.js");
      })
      .then(function () {
        if (!hasOL()) { throw new Error("ol missing after load"); }
        return "loaded";
      });
  }

  function ensureOLE() {
    if (hasOLE()) {
      state.editor.libraryReady = true;
      return Promise.resolve("already-present");
    }

    var cssUrls = [
      "https://cdn.jsdelivr.net/npm/ole@" + OLE_VERSION + "/style/ole.css",
      "https://unpkg.com/ole@" + OLE_VERSION + "/style/ole.css"
    ];

    var jsUrls = [
      "https://cdn.jsdelivr.net/npm/ole@" + OLE_VERSION + "/build/bundle.js",
      "https://unpkg.com/ole@" + OLE_VERSION + "/build/bundle.js",
      "https://cdn.jsdelivr.net/npm/ole@" + OLE_VERSION + "/build/index.js",
      "https://unpkg.com/ole@" + OLE_VERSION + "/build/index.js",
      "https://cdn.jsdelivr.net/npm/ole@" + OLE_VERSION + "/index.js",
      "https://unpkg.com/ole@" + OLE_VERSION + "/index.js"
    ];

    return tryLoadOne(cssUrls, loadCss, "ole.css")
      .catch(function (e) {
        logWarn("[OpenLayer] ole.css warn:", e && e.message ? e.message : e);
        return "ole-css-optional-failed";
      })
      .then(function () {
        return tryLoadOne(jsUrls, function (u) {
          return loadScript(u, DEFAULT_SCRIPT_TIMEOUT_MS, hasOLE);
        }, "ole.js");
      })
      .then(function () {
        if (!hasOLE()) { throw new Error("ole missing after load"); }
        state.editor.libraryReady = true;
        return "loaded";
      });
  }

  // ───────────────────────────────────────────────────────────
  // HTTP / URL / Dataset Helpers
  // ───────────────────────────────────────────────────────────

  function buildUrlFromTemplate(template, datasetId) {
    var rawTemplate = asText(template, "").trim();
    if (!rawTemplate) { return ""; }

    return replaceTemplatePlaceholders(rawTemplate, {
      dataset_id: asText(datasetId, ""),
      datasetId: asText(datasetId, "")
    });
  }

  function uniqueUrls(urls) {
    return uniqueStrings(
      ensureArray(urls).filter(function (url) { return hasText(url); })
    );
  }

  function buildDatasetDetailUrl(datasetId) {
    return buildUrlFromTemplate(cfg.datasetStyleUrlTemplate, datasetId);
  }

  function addRefreshQuery(rawUrl) {
    var url = asText(rawUrl, "").trim();
    if (!url) { return ""; }

    try {
      var parsed = new URL(url, window.location.href);
      parsed.searchParams.set("refresh", "1");
      parsed.searchParams.set("_ts", String(nowMs()));
      if (/^https?:\/\//i.test(url)) {
        return parsed.toString();
      }
      return parsed.pathname + parsed.search + parsed.hash;
    } catch (_) {
      return url + (url.indexOf("?") >= 0 ? "&" : "?") + "refresh=1&_ts=" + String(nowMs());
    }
  }

  function buildDatasetSourceUrl(datasetId) {
    return buildUrlFromTemplate(cfg.datasetSourceUrlTemplate, datasetId);
  }

  function buildDatasetExportUrl(datasetId) {
    return buildUrlFromTemplate(cfg.datasetExportUrlTemplate, datasetId);
  }

  function buildDatasetChangesUrl(datasetId) {
    return buildUrlFromTemplate(cfg.datasetChangesUrlTemplate, datasetId);
  }

  function enforceWfsFeatureLimit(rawUrl, limit) {
    var url = asText(rawUrl, "").trim();
    var maxFeatures = clamp(numOr(limit, DEFAULT_WFS_FEATURE_LIMIT), 1, MAX_WFS_FEATURE_LIMIT);

    if (!url) { return ""; }

    try {
      var parsed = new URL(url, window.location.href);
      var params = parsed.searchParams;

      var effectiveLimit = maxFeatures;

      params.set("count", String(effectiveLimit));
      params.set("maxFeatures", String(effectiveLimit));

      if (!hasText(params.get("outputFormat"))) {
        params.set("outputFormat", "application/json");
      }

      return parsed.toString();
    } catch (_) {
      try {
        var separator = url.indexOf("?") >= 0 ? "&" : "?";
        return url + separator + "count=" + encodeURIComponent(String(maxFeatures)) + "&maxFeatures=" + encodeURIComponent(String(maxFeatures));
      } catch (_) {
        return url;
      }
    }
  }
  function getResponseHeader(headers, name, fallbackValue) {
    try {
      if (!headers || typeof headers.get !== "function") { return fallbackValue; }
      var value = headers.get(name);
      return value === null || value === undefined || value === ""
        ? fallbackValue
        : value;
    } catch (_) {
      return fallbackValue;
    }
  }

  function fetchText(url, options) {
    if (typeof window.fetch !== "function") {
      return Promise.reject(new Error("fetch missing"));
    }

    return window.fetch(url, options || {}).then(function (response) {
      return response.text().then(function (text) {
        return {
          ok: !!response.ok,
          status: response.status,
          statusText: response.statusText,
          url: response.url || url,
          text: text,
          headers: response.headers
        };
      });
    });
  }

  function fetchJson(url, options) {
    return fetchText(url, options).then(function (result) {
      var payload = null;
      var parseError = null;

      if (hasText(result.text)) {
        try {
          payload = JSON.parse(result.text);
        } catch (e) {
          parseError = e;
        }
      }

      return {
        ok: result.ok,
        status: result.status,
        statusText: result.statusText,
        url: result.url,
        text: result.text,
        json: payload,
        parseError: parseError,
        headers: result.headers
      };
    });
  }

  function fetchFirstJson(candidateUrls, options) {
    var urls = uniqueUrls(candidateUrls);

    return urls.reduce(function (promise, url) {
      return promise.catch(function () {
        return fetchJson(url, options).then(function (result) {
          if (!result.ok) {
            throw new Error("HTTP " + result.status + " for " + url);
          }
          if (!isObject(result.json) && !Array.isArray(result.json)) {
            throw new Error("JSON payload invalid for " + url);
          }
          return result;
        });
      });
    }, Promise.reject(new Error("no_url_candidates")));
  }

  function applyFeatureLimitToGeoJsonPayload(payload, limit) {
    var maxFeatures = clamp(numOr(limit, DEFAULT_WFS_FEATURE_LIMIT), 1, MAX_WFS_FEATURE_LIMIT);

    if (!isObject(payload)) { return payload; }

    if (payload.type === "FeatureCollection" && Array.isArray(payload.features)) {
      if (payload.features.length > maxFeatures) {
        var clone = cloneObject(payload, {});
        clone.features = payload.features.slice(0, maxFeatures);
        return clone;
      }
    }

    return payload;
  }

  function isLikelyGeoJsonPayload(payload) {
    if (!isObject(payload)) { return false; }

    var type = asText(payload.type, "").trim();
    if (type === "FeatureCollection" || type === "Feature") { return true; }

    if (Array.isArray(payload.features)) { return true; }

    return false;
  }

  function readGeoJsonFeatures(jsonData) {
    try {
      if (!window.ol || !ol.format || !ol.format.GeoJSON) { return []; }

      var format = new ol.format.GeoJSON();
      var data = jsonData;

      if (Array.isArray(jsonData)) {
        data = {
          type: "FeatureCollection",
          features: jsonData
        };
      } else if (jsonData && jsonData.type === "Feature") {
        data = {
          type: "FeatureCollection",
          features: [jsonData]
        };
      }

      return format.readFeatures(data, {
        dataProjection: "EPSG:4326",
        featureProjection: state.view ? state.view.getProjection() : "EPSG:3857"
      }) || [];
    } catch (e) {
      logWarn("[OpenLayer] GeoJSON parse failed:", e && e.message ? e.message : e);
      return [];
    }
  }

  // ───────────────────────────────────────────────────────────
  // Style Contract / Dataset Normalization
  // ───────────────────────────────────────────────────────────

  function normalizeCapabilities(rawCaps, editable) {
    var base = {
      read: true,
      create: !!editable,
      update: !!editable,
      delete: !!editable
    };

    rawCaps = ensureObject(rawCaps);
    ["read", "create", "update", "delete"].forEach(function (key) {
      if (rawCaps[key] !== undefined) {
        base[key] = asBool(rawCaps[key], base[key]);
      }
    });

    return base;
  }

  function extractStyleCandidate(raw) {
    raw = ensureObject(raw);

    var candidates = [
      raw.style_contract,
      raw.styleContract,
      raw.style_details,
      raw.styleDetails,
      raw.style_summary,
      raw.styleSummary,
      raw.style,
      getPathValue(raw, "catalog_entry.style_contract"),
      getPathValue(raw, "catalog_entry.style"),
      getPathValue(raw, "catalog_entry.style_summary")
    ];

    var i;
    for (i = 0; i < candidates.length; i += 1) {
      if (isObject(candidates[i])) {
        return cloneObject(candidates[i], {});
      }
    }

    return null;
  }

  function normalizeStyleContract(rawStyle, geometryType) {
    var fallbackGeometry = normalizeGeometryType(geometryType, "Point");

    if (!isObject(rawStyle)) {
      return {
        available: false,
        geometry: fallbackGeometry,
        ruleCount: 0,
        style: null,
        rules: [],
        label: null,
        raw: null,
        cacheKey: "no-style"
      };
    }

    var styleRoot = ensureObject(rawStyle.style);
    if (!Object.keys(styleRoot).length && isObject(rawStyle.normalized_payload)) {
      styleRoot = ensureObject(rawStyle.normalized_payload);
    }
    if (!Object.keys(styleRoot).length && isObject(rawStyle.payload)) {
      styleRoot = ensureObject(rawStyle.payload);
    }
    if (!Object.keys(styleRoot).length) {
      styleRoot = ensureObject(rawStyle);
    }

    var rules = [];
    if (Array.isArray(styleRoot.rules)) {
      rules = styleRoot.rules.slice();
    } else if (Array.isArray(rawStyle.rules)) {
      rules = rawStyle.rules.slice();
    }

    var resolvedGeometry = normalizeGeometryType(
      firstText(
        rawStyle.geometry,
        styleRoot.geometry,
        geometryType
      ),
      fallbackGeometry
    );

    var normalized = {
      available: true,
      geometry: resolvedGeometry,
      ruleCount: clamp(numOr(rawStyle.rule_count, rules.length), 0, 100000),
      style: cloneObject(styleRoot, {}),
      rules: cloneJson(rules, []),
      label: isObject(rawStyle.label || styleRoot.label) ? cloneObject(rawStyle.label || styleRoot.label, {}) : null,
      raw: cloneObject(rawStyle, {}),
      cacheKey: ""
    };

    var stableDefaultStyle = cloneObject(
      styleRoot.default_style || styleRoot.default || rawStyle.default_style || rawStyle.default,
      {}
    );

    try {
      normalized.cacheKey = JSON.stringify({
        geometry: normalized.geometry,
        ruleCount: normalized.ruleCount,
        defaultStyle: Object.keys(stableDefaultStyle).length ? stableDefaultStyle : normalized.style,
        rules: normalized.rules,
        label: normalized.label
      });
    } catch (_) {
      normalized.cacheKey = "style-contract-" + resolvedGeometry + "-" + normalized.ruleCount;
    }

    return normalized;
  }

  function normalizeDatasetSource(raw, datasetId, urls) {
    raw = ensureObject(raw);
    urls = ensureObject(urls);

    var sourceRaw = ensureObject(raw.source);
    var sourceType = normalizeSourceType(
      firstText(
        sourceRaw.type,
        raw.source_type,
        raw.sourceType,
        urls.wfs_url ? "wfs" : (urls.wms_url ? "wms" : "")
      ),
      hasText(firstText(sourceRaw.url, raw.source_url, raw.sourceUrl, urls.wfs_url, urls.wms_url))
        ? (urls.wms_url && !urls.wfs_url ? "wms" : "geojson")
        : "placeholder"
    );

    var sourceFormat = firstText(
      sourceRaw.format,
      raw.source_format,
      raw.sourceFormat,
      sourceType === "wfs" ? "wfs" : (sourceType === "wms" ? "image/png" : "geojson")
    ).toLowerCase();

    var configuredLimit = cfg.datasetFeatureLimit;
    var sourceUrl = firstText(
      sourceRaw.url,
      raw.source_url,
      raw.sourceUrl,
      sourceType === "wms" ? urls.wms_url : urls.wfs_url,
      urls.source_url
    );

    if (!sourceUrl && sourceType !== "wfs" && sourceType !== "wms") {
      sourceUrl = buildDatasetSourceUrl(datasetId);
    }
    if (sourceType === "wfs" && hasText(sourceUrl)) {
      sourceUrl = enforceWfsFeatureLimit(sourceUrl, configuredLimit);
    }

    return {
      type: sourceType,
      format: sourceFormat || sourceType,
      url: sourceUrl,
      layerName: firstText(
        sourceRaw.layer_name,
        sourceRaw.layerName,
        urls.wms_layer_name,
        raw.wms_layer_name
      ),
      transparent: asBool(sourceRaw.transparent, true),
      available: asBool(sourceRaw.available, hasText(sourceUrl)),
      featureLimit: configuredLimit,
      originalUrl: firstText(
        sourceRaw.original_url,
        sourceRaw.originalUrl,
        raw.source_original_url,
        raw.sourceOriginalUrl,
        sourceUrl
      )
    };
  }

  function normalizeDatasetUrls(raw, datasetId) {
    var sourceRaw = ensureObject(raw);
    var urlsRaw = ensureObject(sourceRaw.urls || sourceRaw.URLs);

    return {
      wfs_url: firstText(urlsRaw.wfs_url, urlsRaw.wfsUrl, sourceRaw.wfs_url, sourceRaw.wfsUrl),
      wms_url: firstText(urlsRaw.wms_url, urlsRaw.wmsUrl, sourceRaw.wms_url, sourceRaw.wmsUrl),
      wms_layer_name: firstText(urlsRaw.wms_layer_name, urlsRaw.wmsLayerName, sourceRaw.wms_layer_name),
      wcs_url: firstText(urlsRaw.wcs_url, urlsRaw.wcsUrl, sourceRaw.wcs_url, sourceRaw.wcsUrl),
      capabilities_url: firstText(urlsRaw.capabilities_url, urlsRaw.capabilitiesUrl, sourceRaw.capabilities_url),
      describe_feature_type_url: firstText(urlsRaw.describe_feature_type_url, urlsRaw.describeFeatureTypeUrl, sourceRaw.describe_feature_type_url),
      style_url: firstText(urlsRaw.style_url, urlsRaw.styleUrl, sourceRaw.style_url, buildDatasetDetailUrl(datasetId)),
      catalog_url: firstText(urlsRaw.catalog_url, urlsRaw.catalogUrl, sourceRaw.catalog_url),
      sync_url: firstText(urlsRaw.sync_url, urlsRaw.syncUrl, sourceRaw.sync_url),
      source_url: firstText(urlsRaw.source_url, urlsRaw.sourceUrl, sourceRaw.source_url, buildDatasetSourceUrl(datasetId))
    };
  }

  function normalizeDatasetItem(raw, index) {
    var item = ensureObject(raw);
    var itemId = normalizeId(
      firstText(item.dataset_id, item.datasetId, item.id),
      "dataset-" + String(numOr(index, 0) + 1)
    );

    var title = firstText(item.title, item.name, item.label, itemId);
    var description = firstText(item.description, item.abstract, "");

    var geometryType = normalizeGeometryType(
      firstText(
        item.geometry_type,
        item.geometryType,
        item.style_geometry,
        item.styleGeometry
      ),
      "Point"
    );

    var urls = normalizeDatasetUrls(item, itemId);
    var source = normalizeDatasetSource(item, itemId, urls);
    var styleContract = normalizeStyleContract(extractStyleCandidate(item), geometryType);

    var warnings = uniqueStrings(
      toArray(item.warnings).concat(toArray(item.notes || []))
    );
    var errors = uniqueStrings(toArray(item.errors));

    var normalized = {
      id: itemId,
      dataset_id: itemId,
      title: title,
      description: description,
      active: asBool(item.active, true),
      editable: asBool(item.editable, false),
      geometry_type: geometryType,
      capabilities: normalizeCapabilities(item.capabilities, asBool(item.editable, false)),
      source: source,
      urls: urls,
      style_contract: styleContract,
      changes_url: firstText(item.changes_url, item.changesUrl, buildDatasetChangesUrl(itemId)),
      warnings: warnings,
      errors: errors,
      _raw: cloneObject(item, {})
    };

    return normalized;
  }

  function normalizeDatasetsPayload(payload) {
    var rawPayload = payload;
    var items = [];

    if (Array.isArray(rawPayload)) {
      items = rawPayload.slice();
      rawPayload = { items: items, status: "ok" };
    } else {
      rawPayload = ensureObject(rawPayload);
      if (Array.isArray(rawPayload.items)) {
        items = rawPayload.items.slice();
      } else if (Array.isArray(rawPayload.entries)) {
        items = rawPayload.entries.slice();
      } else {
        items = [];
      }
    }

    var normalizedItems = items.map(function (item, index) {
      return normalizeDatasetItem(item, index);
    });

    return {
      status: asText(rawPayload.status, "ok"),
      count: clamp(numOr(rawPayload.count, normalizedItems.length), 0, 999999),
      total_count: clamp(numOr(rawPayload.total_count, normalizedItems.length), 0, 999999),
      placeholder: asBool(rawPayload.placeholder, false),
      notes: toArray(rawPayload.notes),
      filters: cloneObject(rawPayload.filters, {}),
      items: normalizedItems,
      raw: cloneObject(rawPayload, {})
    };
  }

  function hasUsableStyleContract(dataset) {
    dataset = ensureObject(dataset);
    var styleContract = ensureObject(dataset.style_contract);
    return asBool(styleContract.available, false) && (
      ensureArray(styleContract.rules).length > 0 ||
      Object.keys(ensureObject(styleContract.style)).length > 0
    );
  }

  function upsertDatasetIntoState(dataset) {
    if (!dataset || !hasText(dataset.id)) { return dataset; }

    state.datasets.byId[dataset.id] = dataset;

    var replaced = false;
    state.datasets.items = ensureArray(state.datasets.items).map(function (item) {
      if (asText(item && item.id, "") === asText(dataset.id, "")) {
        replaced = true;
        return dataset;
      }
      return item;
    });

    if (!replaced) {
      state.datasets.items.push(dataset);
    }

    return dataset;
  }

  // ───────────────────────────────────────────────────────────
  // Style Helpers
  // ───────────────────────────────────────────────────────────

  function colorFromHex(hex, opacity) {
    var color = asText(hex, "").trim();
    if (!/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(color)) {
      return color;
    }

    var normalized = color.replace("#", "");
    if (normalized.length === 3) {
      normalized = normalized.split("").map(function (c) { return c + c; }).join("");
    }

    var r = parseInt(normalized.slice(0, 2), 16);
    var g = parseInt(normalized.slice(2, 4), 16);
    var b = parseInt(normalized.slice(4, 6), 16);
    var a = clamp(numOr(opacity, 1), 0, 1);

    return "rgba(" + r + ", " + g + ", " + b + ", " + a + ")";
  }

  function applyOpacityToColor(color, opacity) {
    var rawColor = asText(color, "").trim();
    var alpha = Number(opacity);

    if (!rawColor) { return rawColor; }
    if (!Number.isFinite(alpha)) { return rawColor; }

    alpha = clamp(alpha, 0, 1);

    if (/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(rawColor)) {
      return colorFromHex(rawColor, alpha);
    }

    return rawColor;
  }

  function extractStyleOptions(dataset, explicitStyle) {
    dataset = ensureObject(dataset);
    var styleContract = ensureObject(dataset.style_contract);
    var geometryType = normalizeGeometryType(dataset.geometry_type, styleContract.geometry || "Point");
    var styleRoot = ensureObject(styleContract.style);
    var override = ensureObject(explicitStyle);

    var candidates = [
      override,
      ensureObject(override.style),
      ensureObject(override.symbolizer),
      ensureObject(styleRoot.default_style),
      ensureObject(styleRoot.default),
      styleRoot
    ];

    function findValue(paths) {
      var i;
      for (i = 0; i < candidates.length; i += 1) {
        var candidate = candidates[i];
        if (!isObject(candidate)) { continue; }
        var found = firstDefinedPath(candidate, paths);
        if (found !== undefined && found !== null && found !== "") {
          return found;
        }
      }
      return undefined;
    }

    var fillColor = firstText(
      findValue([
        "fillColor",
        "fill_color",
        "fill.color",
        "fill.paint",
        "paint.fillColor",
        "paint.fill",
        "polygon.fillColor",
        "polygon.fill.color",
        "symbolizer.fillColor",
        "symbolizer.fill.color",
        "color"
      ]),
      ""
    );

    var fillOpacity = firstFinite(
      findValue([
        "fillOpacity",
        "fill_opacity",
        "fill.opacity",
        "opacity",
        "paint.fillOpacity",
        "symbolizer.fillOpacity"
      ]),
      NaN
    );

    var strokeColor = firstText(
      findValue([
        "strokeColor",
        "stroke_color",
        "stroke.color",
        "lineColor",
        "line_color",
        "outlineColor",
        "outline_color",
        "paint.strokeColor",
        "paint.stroke",
        "symbolizer.strokeColor",
        "symbolizer.stroke.color",
        "color"
      ]),
      ""
    );

    var strokeWidth = firstFinite(
      findValue([
        "strokeWidth",
        "stroke_width",
        "stroke.width",
        "lineWidth",
        "line_width",
        "outlineWidth",
        "outline_width",
        "width",
        "paint.strokeWidth",
        "symbolizer.strokeWidth",
        "symbolizer.stroke.width"
      ]),
      NaN
    );

    var radius = firstFinite(
      findValue([
        "radius",
        "circle.radius",
        "marker.radius",
        "point.radius",
        "size",
        "symbolizer.radius",
        "symbolizer.size"
      ]),
      NaN
    );

    var zIndex = Math.max(0, Math.min(10, Math.round(numOr(findValue([
      "z_index",
      "zIndex"
    ]), 0))));
    var pointFillColor = fillColor || (isPointGeometry(geometryType) ? "rgba(255, 210, 0, 0.98)" : "");
    var pointStrokeColor = strokeColor || "rgba(20,20,20,0.95)";
    var pointStrokeWidth = Number.isFinite(strokeWidth) ? clamp(strokeWidth, 0.5, 12) : 2;
    var pointRadius = Number.isFinite(radius) ? clamp(radius, 2, 24) : 6;

    var lineStrokeColor = strokeColor || "rgba(0, 229, 255, 0.95)";
    var lineStrokeWidth = Number.isFinite(strokeWidth) ? clamp(strokeWidth, 1, 12) : 4;

    var polygonFillColor = fillColor || "rgba(0, 229, 255, 0.18)";
    var polygonStrokeColor = strokeColor || "rgba(0, 229, 255, 0.95)";
    var polygonStrokeWidth = Number.isFinite(strokeWidth) ? clamp(strokeWidth, 1, 12) : 2;

    if (Number.isFinite(fillOpacity) && hasText(pointFillColor)) {
      pointFillColor = applyOpacityToColor(pointFillColor, fillOpacity);
    }
    if (Number.isFinite(fillOpacity) && hasText(polygonFillColor)) {
      polygonFillColor = applyOpacityToColor(polygonFillColor, fillOpacity);
    }

    return {
      geometryType: geometryType,
      zIndex: zIndex,
      point: {
        radius: pointRadius,
        fillColor: pointFillColor,
        strokeColor: pointStrokeColor,
        strokeWidth: pointStrokeWidth
      },
      line: {
        strokeColor: lineStrokeColor,
        strokeWidth: lineStrokeWidth
      },
      polygon: {
        fillColor: polygonFillColor,
        strokeColor: polygonStrokeColor,
        strokeWidth: polygonStrokeWidth
      }
    };
  }

  function getDefaultFeatureStyle(geometryType) {
    try {
      if (isPointGeometry(geometryType)) {
        return new ol.style.Style({
          image: new ol.style.Circle({
            radius: 6,
            fill: new ol.style.Fill({ color: "rgba(255, 210, 0, 0.98)" }),
            stroke: new ol.style.Stroke({ color: "rgba(20,20,20,0.95)", width: 2 })
          })
        });
      }

      if (isLineGeometry(geometryType)) {
        return new ol.style.Style({
          stroke: new ol.style.Stroke({
            color: "rgba(0, 229, 255, 0.95)",
            width: 4
          })
        });
      }

      return new ol.style.Style({
        fill: new ol.style.Fill({ color: "rgba(0, 229, 255, 0.18)" }),
        stroke: new ol.style.Stroke({ color: "rgba(0, 229, 255, 0.95)", width: 2 })
      });
    } catch (_) {
      return undefined;
    }
  }

  function createOlStyleSet(options) {
    var set = { point: null, line: null, polygon: null };
    try {
      set.point = new ol.style.Style({
        zIndex: options.zIndex,
        image: new ol.style.Circle({
          radius: clamp(numOr(options.point.radius, 6), 2, 24),
          fill: new ol.style.Fill({ color: asText(options.point.fillColor, "rgba(255, 210, 0, 0.98)") }),
          stroke: new ol.style.Stroke({
            color: asText(options.point.strokeColor, "rgba(20,20,20,0.95)"),
            width: clamp(numOr(options.point.strokeWidth, 2), 0.5, 12)
          })
        })
      });
    } catch (_) { set.point = getDefaultFeatureStyle("Point"); }
    try {
      set.line = new ol.style.Style({
        zIndex: options.zIndex,
        stroke: new ol.style.Stroke({
          color: asText(options.line.strokeColor, "rgba(0, 229, 255, 0.95)"),
          width: clamp(numOr(options.line.strokeWidth, 4), 0.1, 20)
        })
      });
    } catch (_) { set.line = getDefaultFeatureStyle("LineString"); }
    try {
      set.polygon = new ol.style.Style({
        zIndex: options.zIndex,
        fill: new ol.style.Fill({ color: asText(options.polygon.fillColor, "rgba(0, 229, 255, 0.18)") }),
        stroke: new ol.style.Stroke({
          color: asText(options.polygon.strokeColor, "rgba(0, 229, 255, 0.95)"),
          width: clamp(numOr(options.polygon.strokeWidth, 2), 0.1, 20)
        })
      });
    } catch (_) { set.polygon = getDefaultFeatureStyle("Polygon"); }
    return set;
  }

  function getOrCreateDatasetStyleBundle(dataset) {
    dataset = ensureObject(dataset);
    var styleContract = ensureObject(dataset.style_contract);
    var cacheKey = asText(styleContract.cacheKey, "") || ("dataset-style::" + asText(dataset.id, "unknown"));
    if (state.style.cache[cacheKey]) { return state.style.cache[cacheKey]; }

    var bundle = {
      defaultSet: createOlStyleSet(extractStyleOptions(dataset, null)),
      ruleSets: {}
    };
    ensureArray(styleContract.rules).forEach(function (rule, index) {
      rule = ensureObject(rule);
      var ruleId = firstText(rule.rule_id, rule.id, "rule-" + String(index + 1));
      bundle.ruleSets[ruleId] = createOlStyleSet(extractStyleOptions(dataset, rule.style || rule));
    });

    state.style.cache[cacheKey] = bundle;
    state.style.cacheOrder.push(cacheKey);
    while (state.style.cacheOrder.length > MAX_STYLE_CACHE_KEYS) {
      var oldest = state.style.cacheOrder.shift();
      if (oldest && state.style.cache[oldest]) { delete state.style.cache[oldest]; }
    }
    return bundle;
  }

  function getFeatureProperty(feature, fieldName) {
    if (!feature || !hasText(fieldName)) { return undefined; }
    try {
      if (typeof feature.get === "function") { return feature.get(fieldName); }
      var properties = typeof feature.getProperties === "function" ? feature.getProperties() : feature.properties;
      return isObject(properties) ? properties[fieldName] : undefined;
    } catch (_) { return undefined; }
  }

  function valuesEqual(actual, expected) {
    if (actual === expected) { return true; }
    if (actual === null || actual === undefined || expected === null || expected === undefined) { return false; }
    var actualNumber = Number(actual);
    var expectedNumber = Number(expected);
    if (String(actual).trim() !== "" && String(expected).trim() !== "" && Number.isFinite(actualNumber) && Number.isFinite(expectedNumber)) {
      return actualNumber === expectedNumber;
    }
    return String(actual) === String(expected);
  }

  function matchesStyleRule(rule, feature) {
    rule = ensureObject(rule);
    if (asBool(rule.else, false)) { return false; }
    var condition = ensureObject(rule.filter || rule.when);
    var fieldName = firstText(condition.field, condition.property, condition.attribute);
    if (!fieldName) { return false; }
    var actual = getFeatureProperty(feature, fieldName);
    var operator = "";
    var expected;
    ["eq", "ne", "gt", "gte", "lt", "lte", "in", "exists"].some(function (candidate) {
      if (Object.prototype.hasOwnProperty.call(condition, candidate)) {
        operator = candidate;
        expected = condition[candidate];
        return true;
      }
      return false;
    });
    if (!operator && hasText(condition.operator)) {
      operator = asText(condition.operator, "").toLowerCase();
      expected = condition.value;
    }
    if (operator === "eq") { return valuesEqual(actual, expected); }
    if (operator === "ne") { return !valuesEqual(actual, expected); }
    if (operator === "exists") {
      var exists = actual !== undefined && actual !== null;
      return asBool(expected, true) ? exists : !exists;
    }
    if (operator === "in") {
      return ensureArray(expected).some(function (value) { return valuesEqual(actual, value); });
    }
    var actualNumber = Number(actual);
    var expectedNumber = Number(expected);
    var useNumbers = Number.isFinite(actualNumber) && Number.isFinite(expectedNumber);
    var left = useNumbers ? actualNumber : String(actual == null ? "" : actual);
    var right = useNumbers ? expectedNumber : String(expected == null ? "" : expected);
    if (operator === "gt") { return left > right; }
    if (operator === "gte") { return left >= right; }
    if (operator === "lt") { return left < right; }
    if (operator === "lte") { return left <= right; }
    return false;
  }

  function selectStyleRule(dataset, feature) {
    var rules = ensureArray(ensureObject(dataset.style_contract).rules);
    var elseRule = null;
    var i;
    for (i = 0; i < rules.length; i += 1) {
      var rule = ensureObject(rules[i]);
      if (asBool(rule.else, false)) {
        if (!elseRule) { elseRule = rule; }
      } else if (matchesStyleRule(rule, feature)) {
        return rule;
      }
    }
    return elseRule;
  }

  function styleForGeometry(styleSet, geometryType) {
    if (!styleSet) { return undefined; }
    if (isPointGeometry(geometryType)) { return styleSet.point; }
    if (isLineGeometry(geometryType)) { return styleSet.line; }
    return styleSet.polygon;
  }

  function labelOptionsForRule(dataset, rule) {
    var styleContract = ensureObject(dataset.style_contract);
    var ruleLabel = ensureObject(rule && rule.label);
    if (Object.keys(ruleLabel).length && asBool(ruleLabel.enabled, true)) { return ruleLabel; }
    var label = ensureObject(styleContract.label);
    return Object.keys(label).length && asBool(label.enabled, true) ? label : null;
  }

  function featureLabelStyle(feature, label, geometryType) {
    if (!label || !hasText(label.field)) { return null; }
    var value = getFeatureProperty(feature, label.field);
    if (value === undefined || value === null || String(value) === "") { return null; }
    var placement = firstText(label.placement, "auto");
    var linePlacement = placement === "line" || (placement === "auto" && isLineGeometry(geometryType));
    try {
      return new ol.style.Text({
        text: Array.isArray(value) ? value.join(", ") : String(value),
        font: firstText(label.font_weight, "normal") + " " + String(clamp(numOr(label.font_size, 12), 8, 40)) + "px " + firstText(label.font_family, "sans-serif"),
        placement: linePlacement ? "line" : "point",
        textAlign: "center",
        overflow: true,
        offsetX: numOr(label.offset_x, 0),
        offsetY: numOr(label.offset_y, 0),
        fill: new ol.style.Fill({ color: firstText(label.color, "rgba(20,20,20,0.95)") }),
        stroke: clamp(numOr(label.halo_width, 2), 0, 8) > 0 ? new ol.style.Stroke({
          color: firstText(label.halo_color, "rgba(255,255,255,0.92)"),
          width: clamp(numOr(label.halo_width, 2), 0, 8) * 2
        }) : undefined
      });
    } catch (_) { return null; }
  }

  function getFeatureStyleForDataset(dataset, feature, geometryType, resolution) {
    try {
      if (!window.ol || !ol.style) { return undefined; }
      if (!hasUsableStyleContract(dataset)) { return getDefaultFeatureStyle(geometryType); }
      var bundle = getOrCreateDatasetStyleBundle(dataset);
      var rule = selectStyleRule(dataset, feature);
      var ruleId = rule ? firstText(rule.rule_id, rule.id) : "";
      var styleSet = ruleId && bundle.ruleSets[ruleId] ? bundle.ruleSets[ruleId] : bundle.defaultSet;
      var baseStyle = styleForGeometry(styleSet, geometryType);
      var labelOptions = labelOptionsForRule(dataset, rule);
      var textStyle = featureLabelStyle(feature, labelOptions, geometryType);
      if (!textStyle || !baseStyle) { return baseStyle; }
      var labelStyle = new ol.style.Style({
        text: textStyle,
        zIndex: 100 + clamp(numOr(labelOptions.priority, 5), 1, 10)
      });
      return [baseStyle, labelStyle];
    } catch (_) { return undefined; }
  }

  // Map Layer Helpers
  function buildMapboxTileUrl(styleId, token, tileSize) {
    return "https://api.mapbox.com/styles/v1/" + styleId + "/tiles/" + tileSize + "/{z}/{x}/{y}?access_token=" + encodeURIComponent(token);
  }

  function disableWheelInteraction(map) {
    try {
      map.getInteractions().forEach(function (interaction) {
        if (window.ol && ol.interaction && interaction instanceof ol.interaction.MouseWheelZoom) {
          interaction.setActive(false);
        }
      });
    } catch (e) {
      logWarn("[OpenLayer] disableWheel failed:", e && e.message ? e.message : e);
    }
  }

  function enableWheelInteraction(map) {
    try {
      map.getInteractions().forEach(function (interaction) {
        if (window.ol && ol.interaction && interaction instanceof ol.interaction.MouseWheelZoom) {
          interaction.setActive(true);
        }
      });
    } catch (e) {
      logWarn("[OpenLayer] enableWheel failed:", e && e.message ? e.message : e);
    }
  }

  function buildMapControls() {
    try {
      if (ol.control && ol.control.defaults && typeof ol.control.defaults.defaults === "function") {
        return ol.control.defaults.defaults({
          zoom: false,
          rotate: false,
          attribution: true
        });
      }
      if (ol.control && typeof ol.control.defaults === "function") {
        return ol.control.defaults({
          zoom: false,
          rotate: false,
          attribution: true
        });
      }
    } catch (_) {}
    return undefined;
  }

  function removeDefaultZoomControls(map) {
    try {
      var toRemove = [];
      map.getControls().forEach(function (control) {
        try {
          if (window.ol && ol.control && ol.control.Zoom && control instanceof ol.control.Zoom) {
            toRemove.push(control);
          }
        } catch (_) {}
      });
      toRemove.forEach(function (control) {
        try { map.removeControl(control); } catch (_) {}
      });
    } catch (_) {}
  }

  function createBaseLayers() {
    var styleId = cfg.styleId || "mapbox/light-v11";
    var tileSize = cfg.tileSize || 512;
    var tokenOk = cfg.tokenUsable;
    var wantsMapbox = asBool(cfg.styleRequiresMapboxToken, true);

    var osmLayer = null;
    var mapboxLayer = null;

    try {
      osmLayer = new ol.layer.Tile({
        source: new ol.source.OSM(),
        visible: !tokenOk || !wantsMapbox
      });
      try { osmLayer.set("layerRole", "base-osm"); } catch (_) {}
    } catch (e1) {
      logError("[OpenLayer] OSM layer create failed:", e1 && e1.message ? e1.message : e1);
    }

    if (tokenOk && wantsMapbox) {
      try {
        var source = new ol.source.XYZ({
          url: buildMapboxTileUrl(styleId, cfg.token, tileSize),
          tileSize: tileSize,
          crossOrigin: "anonymous",
          attributions: "© Mapbox © OpenStreetMap"
        });

        mapboxLayer = new ol.layer.Tile({
          source: source,
          visible: true
        });
        try { mapboxLayer.set("layerRole", "base-mapbox"); } catch (_) {}

        source.on("tileloaderror", function () {
          if (state.baseLayers.usingFallbackOsm) { return; }
          state.baseLayers.usingFallbackOsm = true;
          logWarn("[OpenLayer] Mapbox tileloaderror → OSM-Fallback");
          if (mapboxLayer) { safeCall(function () { mapboxLayer.setVisible(false); }); }
          if (osmLayer) { safeCall(function () { osmLayer.setVisible(true); }); }
          setBanner("danger", "Mapbox-Kacheln konnten nicht geladen werden. OSM-Fallback ist aktiv.", true);
          setToast("danger", "Basiskarte", "Mapbox konnte nicht geladen werden. OSM-Fallback wurde aktiviert.", 3600);
        });
      } catch (e2) {
        logWarn("[OpenLayer] Mapbox layer init failed:", e2 && e2.message ? e2.message : e2);
        mapboxLayer = null;
      }
    }

    if (!mapboxLayer && osmLayer) {
      safeCall(function () { osmLayer.setVisible(true); });
    }

    return {
      mapbox: mapboxLayer,
      osm: osmLayer
    };
  }

  function buildLocationRadiusBbox(center, radiusMeters) {
    var anchor = Array.isArray(center) ? center : [cfg.lon, cfg.lat];
    var lon = clamp(numOr(anchor[0], cfg.lon), -180, 180);
    var lat = clamp(numOr(anchor[1], cfg.lat), -90, 90);
    var radius = clamp(numOr(radiusMeters, cfg.datasetRadiusMeters), 1, MAX_DATASET_RADIUS_METERS);
    var earthRadius = 6378137;
    var latitudeRadians = lat * Math.PI / 180;
    var latitudeDelta = radius / earthRadius * 180 / Math.PI;
    var longitudeScale = Math.max(0.000001, Math.abs(Math.cos(latitudeRadians)));
    var longitudeDelta = radius / (earthRadius * longitudeScale) * 180 / Math.PI;

    return [
      clamp(lon - longitudeDelta, -180, 180),
      clamp(lat - latitudeDelta, -90, 90),
      clamp(lon + longitudeDelta, -180, 180),
      clamp(lat + latitudeDelta, -90, 90)
    ];
  }

  function initializeLocationConstraint(view, anchorProjected) {
    try {
      var latitudeRadians = cfg.lat * Math.PI / 180;
      var projectionScale = Math.max(0.01, Math.abs(Math.cos(latitudeRadians)));
      state.location.anchorLonLat = [cfg.lon, cfg.lat];
      state.location.anchorProjected = anchorProjected.slice();
      state.location.radiusProjectionUnits = cfg.datasetRadiusMeters / projectionScale;

      view.on("change:center", function () {
        constrainViewToLocationRadius();
      });
    } catch (err) {
      logWarn("[OpenLayer] location constraint init failed:", err && err.message ? err.message : err);
    }
  }

  function constrainViewToLocationRadius() {
    try {
      if (!state.view || state.location.constraining || !Array.isArray(state.location.anchorProjected)) { return false; }
      var center = state.view.getCenter();
      if (!Array.isArray(center) || center.length < 2) { return false; }

      var dx = Number(center[0]) - Number(state.location.anchorProjected[0]);
      var dy = Number(center[1]) - Number(state.location.anchorProjected[1]);
      var distance = Math.sqrt(dx * dx + dy * dy);
      var maxDistance = Math.max(1, numOr(state.location.radiusProjectionUnits, cfg.datasetRadiusMeters));
      if (!Number.isFinite(distance) || distance <= maxDistance) { return false; }

      var factor = maxDistance / distance;
      state.location.constraining = true;
      state.view.setCenter([
        Number(state.location.anchorProjected[0]) + dx * factor,
        Number(state.location.anchorProjected[1]) + dy * factor
      ]);
      state.location.constraining = false;
      return true;
    } catch (_) {
      state.location.constraining = false;
      return false;
    }
  }

  function createProjectLocationMarker(map, anchorProjected) {
    try {
      if (!map || !Array.isArray(anchorProjected) || !window.ol || !ol.Overlay) {
        return null;
      }

      var marker = document.createElement("div");
      var coordinateLabel = Number(cfg.lat).toFixed(6) + ", " + Number(cfg.lon).toFixed(6);
      marker.id = "project-location-marker";
      marker.className = "project-location-marker";
      marker.setAttribute("role", cfg.parcelSelectionReadonly ? "img" : "button");
      marker.setAttribute("tabindex", cfg.parcelSelectionReadonly ? "-1" : "0");
      marker.setAttribute("aria-label", "Zielkoordinate: " + coordinateLabel);
      marker.setAttribute("title", "Zielkoordinate: " + coordinateLabel);
      marker.setAttribute("data-lon", Number(cfg.lon).toFixed(8));
      marker.setAttribute("data-lat", Number(cfg.lat).toFixed(8));
      marker.innerHTML = [
        '<svg class="project-location-marker__icon" viewBox="0 0 40 52" aria-hidden="true" focusable="false">',
        '<path d="M20 1C9.5 1 1 9.5 1 20c0 14.25 19 31 19 31s19-16.75 19-31C39 9.5 30.5 1 20 1Z"/>',
        '<circle cx="20" cy="20" r="7"/>',
        "</svg>"
      ].join("");

      var overlay = new ol.Overlay({
        element: marker,
        position: anchorProjected.slice(),
        positioning: "bottom-center",
        stopEvent: true,
        insertFirst: false
      });

      map.addOverlay(overlay);
      state.location.markerOverlay = overlay;
      state.location.markerElement = marker;
      bindProjectLocationMarkerDrag(map, overlay, marker);
      return overlay;
    } catch (err) {
      logWarn("[OpenLayer] project location marker init failed:", err && err.message ? err.message : err);
      return null;
    }
  }

  function updateProjectLocation(lonLat, options) {
    options = options || {};
    if (!Array.isArray(lonLat) || lonLat.length < 2 || !window.ol || !ol.proj) { return false; }
    var lon = clamp(numOr(lonLat[0], cfg.lon), -180, 180);
    var lat = clamp(numOr(lonLat[1], cfg.lat), -90, 90);
    var projected = ol.proj.fromLonLat([lon, lat]);
    var projectionScale = Math.max(0.01, Math.abs(Math.cos(lat * Math.PI / 180)));

    cfg.lon = lon;
    cfg.lat = lat;
    state.location.anchorLonLat = [lon, lat];
    state.location.anchorProjected = projected.slice();
    state.location.radiusProjectionUnits = cfg.datasetRadiusMeters / projectionScale;
    if (Object.prototype.hasOwnProperty.call(options, "manualOverride")) {
      state.location.manualOverride = asBool(options.manualOverride, false);
    }
    if (options.localChange === true) {
      state.location.pendingLocalCoordinate = [lon, lat];
      state.location.pendingLocalCoordinateUntil = nowMs() + 15000;
    }
    if (state.location.markerOverlay && options.updateOverlay !== false) {
      state.location.markerOverlay.setPosition(projected);
    }
    if (state.location.markerElement) {
      var label = lat.toFixed(6) + ", " + lon.toFixed(6);
      state.location.markerElement.setAttribute("aria-label", "Zielkoordinate: " + label);
      state.location.markerElement.setAttribute("title", "Zielkoordinate: " + label + (cfg.parcelSelectionReadonly ? "" : " – zum Verschieben ziehen"));
      state.location.markerElement.setAttribute("data-lon", lon.toFixed(8));
      state.location.markerElement.setAttribute("data-lat", lat.toFixed(8));
    }
    state.datasets.lastViewportKey = "";
    state.parcelSelection.defaultCoordinateSelectionDone = false;

    if (options.notifyParent !== false) {
      try {
        window.parent.postMessage({
          type: "vectoplan-map:project-coordinate-changed",
          kind: "vectoplan-map:project-coordinate-changed",
          source: "vectoplan-openlayer",
          detail: {
            projectPublicId: cfg.projectPublicId,
            longitude: lon,
            latitude: lat,
            coordinateSpace: "wgs84",
            projectCoordinateManualOverride: state.location.manualOverride
          }
        }, "*");
      } catch (_) {}
    }

    if (options.reloadDataset !== false) {
      scheduleActiveDatasetReload({ immediate: true, force: true, reason: "project-coordinate" });
    }
    if (options.autoSelect !== false) {
      window.setTimeout(function () {
        autoSelectCoordinateParcel({ force: true });
      }, VIEWPORT_RELOAD_DELAY_MS + DATASET_BATCH_DELAY_MS);
    }
    return true;
  }

  function bindProjectLocationMarkerDrag(map, overlay, marker) {
    if (cfg.parcelSelectionReadonly || !map || !overlay || !marker) { return; }
    var pointerId = null;

    function onPointerMove(event) {
      if (!state.location.markerDragging) { return; }
      try {
        if (pointerId !== null && event.pointerId !== undefined && event.pointerId !== pointerId) { return; }
        event.preventDefault();
        event.stopPropagation();
        var coordinate = map.getCoordinateFromPixel(map.getEventPixel(event));
        if (Array.isArray(coordinate)) { overlay.setPosition(coordinate); }
      } catch (_) {}
    }

    function onPointerUp(event) {
      if (!state.location.markerDragging) { return; }
      try {
        if (pointerId !== null && event.pointerId !== undefined && event.pointerId !== pointerId) { return; }
        event.preventDefault();
        event.stopPropagation();
        var position = overlay.getPosition();
        state.location.markerDragging = false;
        marker.classList.remove("is-dragging");
        pointerId = null;
        if (Array.isArray(position)) {
          updateProjectLocation(
            ol.proj.toLonLat(position, state.view ? state.view.getProjection() : undefined),
            { manualOverride: true, localChange: true }
          );
        }
      } catch (_) {
        state.location.markerDragging = false;
        marker.classList.remove("is-dragging");
        pointerId = null;
      }
    }

    marker.addEventListener("pointerdown", function (event) {
      if (event.button !== undefined && event.button !== 0) { return; }
      event.preventDefault();
      event.stopPropagation();
      pointerId = event.pointerId !== undefined ? event.pointerId : null;
      state.location.markerDragging = true;
      marker.classList.add("is-dragging");
      try { marker.setPointerCapture(event.pointerId); } catch (_) {}
    });
    window.addEventListener("pointermove", onPointerMove, { passive: false });
    window.addEventListener("pointerup", onPointerUp, { passive: false });
    window.addEventListener("pointercancel", onPointerUp, { passive: false });
  }
  function createMap() {
    if (!hasOL()) {
      throw new Error("OpenLayers missing");
    }

    var controls = buildMapControls();
    var layers = [];
    var baseLayers = createBaseLayers();

    if (baseLayers.mapbox) { layers.push(baseLayers.mapbox); }
    if (baseLayers.osm) { layers.push(baseLayers.osm); }

    var anchorProjected = ol.proj.fromLonLat([cfg.lon, cfg.lat]);
    var view = new ol.View({
      center: anchorProjected,
      zoom: cfg.zoom,
      minZoom: cfg.minZoom,
      maxZoom: cfg.maxZoom,
      enableRotation: true
    });

    var map = new ol.Map({
      target: "map",
      layers: layers,
      view: view,
      controls: controls,
      keyboardEventTarget: document
    });

    try { removeDefaultZoomControls(map); } catch (_) {}
    try { map.addControl(new ol.control.ScaleLine()); } catch (_) {}

    if (cfg.disableScroll || !cfg.enableWheelZoom) {
      disableWheelInteraction(map);
    } else {
      enableWheelInteraction(map);
    }

    state.map = map;
    state.view = view;
    state.baseLayers = {
      mapbox: baseLayers.mapbox,
      osm: baseLayers.osm,
      usingFallbackOsm: !!cfg.styleTokenMismatch
    };

    initializeLocationConstraint(view, anchorProjected);
    createProjectLocationMarker(map, anchorProjected);

    try {
      view.on("change:resolution", function () {
        setDatasetZoomVisibility(getCurrentViewportContext());
      });
      map.on("moveend", function () {
        if (constrainViewToLocationRadius()) { return; }
        if (!setDatasetZoomVisibility(getCurrentViewportContext())) { return; }
        scheduleActiveDatasetReload({ reason: "moveend" });
      });
      map.on("change:size", function () {
        if (!setDatasetZoomVisibility(getCurrentViewportContext())) { return; }
        scheduleActiveDatasetReload({ reason: "resize" });
      });
      map.on("singleclick", handleParcelMapClick);
    } catch (_) {}
    if (cfg.styleTokenMismatch) {
      if (state.baseLayers.mapbox) { safeCall(function () { state.baseLayers.mapbox.setVisible(false); }); }
      if (state.baseLayers.osm) { safeCall(function () { state.baseLayers.osm.setVisible(true); }); }
      setBanner("danger", "Für den gewählten Mapbox-Stil ist kein gültiger Token vorhanden. OSM-Fallback ist aktiv.", true);
    }

    if (!cfg.mapboxTokenPresent && state.baseLayers.osm) {
      setToast("danger", "Basiskarte", "Kein gültiger MAPBOX_TOKEN vorhanden. OSM-Fallback aktiv.", 3200);
    }

    try {
      map.once("rendercomplete", function () {
        logInfo("[OpenLayer] Karte gerendert");
      });
    } catch (_) {}

    window.vectoMap = map;
    return map;
  }

  function zoomBy(step) {
    try {
      if (!state.view) { return; }
      var current = numOr(state.view.getZoom(), cfg.zoom);
      var next = clamp(current + step, cfg.minZoom, cfg.maxZoom);
      state.view.animate({ zoom: next, duration: 180 });
    } catch (_) {
      try {
        if (state.view) { state.view.setZoom(clamp(numOr(state.view.getZoom(), cfg.zoom) + step, cfg.minZoom, cfg.maxZoom)); }
      } catch (_) {}
    }
  }


  function getCurrentViewportContext() {
    try {
      if (!state.map || !state.view || !window.ol || !ol.proj) { return null; }
      var size = state.map.getSize();
      if (!Array.isArray(size) || size.length < 2 || size[0] <= 0 || size[1] <= 0) { return null; }

      var zoom = numOr(state.view.getZoom(), cfg.zoom);
      var projection = state.view.getProjection ? state.view.getProjection() : "EPSG:3857";
      var centerCoordinate = state.view.getCenter();
      var rawViewCenter = ol.proj.toLonLat(centerCoordinate, projection);
      var viewCenter = [
        clamp(numOr(rawViewCenter[0], cfg.lon), -180, 180),
        clamp(numOr(rawViewCenter[1], cfg.lat), -90, 90)
      ];
      var center = [cfg.lon, cfg.lat];
      var bbox = buildLocationRadiusBbox(center, cfg.datasetRadiusMeters);
      if (bbox[0] >= bbox[2] || bbox[1] >= bbox[3]) { return null; }

      return {
        zoom: zoom,
        bbox: bbox,
        center: center,
        viewCenter: viewCenter,
        locationRadiusMeters: cfg.datasetRadiusMeters,
        key: (zoom < cfg.datasetMinLoadZoom ? "below" : "active") + "::" + bbox.map(function (value) {
          return Number(value).toFixed(7);
        }).join(",")
      };
    } catch (err) {
      logWarn("[OpenLayer] viewport context failed:", err && err.message ? err.message : err);
      return null;
    }
  }

  function updateViewportIndicators(viewport) {
    viewport = viewport || getCurrentViewportContext();
    var hasDataset = !!state.activeDataset;
    var zoomAllowed = !!viewport && viewport.zoom >= cfg.datasetMinLoadZoom;
    var downloadAllowed = cfg.datasetExportEnabled && hasDataset && zoomAllowed;

    setDisabled(dom.btnDownload, !downloadAllowed);
    toArray(dom.downloadActions).forEach(function (button) {
      setDisabled(button, !downloadAllowed || state.datasets.loading || state.ui.exportLoading);
    });
  }

  function setDatasetZoomVisibility(viewport) {
    viewport = viewport || getCurrentViewportContext();
    var zoomAllowed = !!viewport && viewport.zoom >= cfg.datasetMinLoadZoom;
    var wasSuppressed = !!state.datasets.zoomSuppressed;

    try {
      if (
        state.datasetLayer &&
        typeof state.datasetLayer.getVisible === "function" &&
        state.datasetLayer.getVisible() !== zoomAllowed
      ) {
        state.datasetLayer.setVisible(zoomAllowed);
      }
    } catch (_) {}

    if (zoomAllowed) {
      state.datasets.zoomSuppressed = false;
      if (wasSuppressed) { updateViewportIndicators(viewport); }
      return true;
    }

    if (state.datasets.viewportTimer) {
      clearTimeout(state.datasets.viewportTimer);
      state.datasets.viewportTimer = null;
    }
    if (state.datasets.requestController) {
      try { state.datasets.requestController.abort(); } catch (_) {}
      state.datasets.requestController = null;
    }

    if (!wasSuppressed) {
      state.datasets.requestSerial += 1;
      state.datasets.loading = false;
      state.datasets.lastFeatureCount = 0;
      state.datasets.lastViewportKey = "";
      try {
        if (state.datasetSource) { state.datasetSource.clear(true); }
      } catch (_) {}
      updateViewportIndicators(viewport);
    }

    state.datasets.zoomSuppressed = true;
    return false;
  }

  function scheduleActiveDatasetReload(options) {
    options = options || {};
    var viewport = getCurrentViewportContext();
    if (!setDatasetZoomVisibility(viewport)) { return; }
    if (state.datasets.viewportTimer) {
      clearTimeout(state.datasets.viewportTimer);
      state.datasets.viewportTimer = null;
    }
    updateViewportIndicators(viewport);
    state.datasets.viewportTimer = setTimeout(function () {
      state.datasets.viewportTimer = null;
      reloadActiveDatasetForViewport(options).catch(noop);
    }, options.immediate ? 0 : VIEWPORT_RELOAD_DELAY_MS);
  }

  var selectedParcelStyle = null;

  function parcelFeatureId(feature, dataset) {
    var datasetId = asText(dataset && dataset.id, "dataset") || "dataset";
    var candidates = [];
    try { candidates.push(feature && feature.getId ? feature.getId() : ""); } catch (_) {}
    ["gml_id", "fid", "id", "flurstueck_id", "flstkennz", "alkis_id", "uuid"].forEach(function (name) {
      candidates.push(getFeatureProperty(feature, name));
    });
    var id = firstText.apply(null, candidates);
    if (!id) {
      try {
        var geometry = feature && feature.getGeometry ? feature.getGeometry() : null;
        var extent = geometry && geometry.getExtent ? geometry.getExtent() : [];
        id = ensureArray(extent).map(function (value) { return Number(value).toFixed(3); }).join(":");
      } catch (_) { id = ""; }
    }
    return datasetId + ":" + (id || "unknown");
  }

  function isSelectedParcelFeature(feature, dataset) {
    return !!state.parcelSelection.byId[parcelFeatureId(feature, dataset)];
  }

  function getSelectedParcelStyle() {
    if (selectedParcelStyle) { return selectedParcelStyle; }
    selectedParcelStyle = new ol.style.Style({
      fill: new ol.style.Fill({ color: "rgba(15, 98, 254, 0.44)" }),
      stroke: new ol.style.Stroke({ color: "rgba(4, 66, 190, 1)", width: 3.5 })
    });
    return selectedParcelStyle;
  }

  function parcelSelectionItems() {
    return Object.keys(state.parcelSelection.byId).sort().map(function (id) {
      return state.parcelSelection.byId[id];
    });
  }

  function parcelCatalogItems() {
    if (!state.datasetSource || !datasetLooksLikeParcels(state.activeDataset)) { return []; }
    var catalog = [];
    try {
      state.datasetSource.getFeatures().slice(0, 512).forEach(function (feature) {
        var parcel = parcelFromFeature(feature);
        if (parcel) { catalog.push(parcel); }
      });
    } catch (_) { return []; }
    return catalog;
  }

  function postParcelCatalog() {
    try {
      window.parent.postMessage({
        type: "vectoplan-map:parcel-catalog-changed",
        kind: "vectoplan-map:parcel-catalog-changed",
        source: "vectoplan-openlayer",
        detail: {
          projectPublicId: cfg.projectPublicId,
          projectCoordinate: { longitude: cfg.lon, latitude: cfg.lat },
          projectCoordinateManualOverride: state.location.manualOverride,
          availableParcels: parcelCatalogItems()
        }
      }, "*");
    } catch (_) {}
  }

  function updateParcelSelectionUi(message) {
    var count = parcelSelectionItems().length;
    setText(dom.parcelCount, count + (count === 1 ? " Grundstueck ausgewaehlt" : " Grundstuecke ausgewaehlt"));
    setText(dom.parcelStatus, message || (
      state.activeDataset
        ? "Klick auf ein Flurstueck waehlt es aus oder ab."
        : "Bitte einen Polygon-Datensatz auswaehlen."
    ));
    toArray(dom.parcelModeButtons).forEach(function (button) {
      setPressed(button, asText(button.getAttribute("data-parcel-mode"), "") === state.parcelSelection.mode);
    });
    if (dom.btnParcels) {
      dom.btnParcels.dataset.count = String(count);
      setPressed(dom.btnParcels, state.parcelSelection.panelOpen);
      setExpanded(dom.btnParcels, state.parcelSelection.panelOpen);
    }
  }

  function postParcelSelection() {
    var detail = {
      projectPublicId: cfg.projectPublicId,
      coordinateSpace: "wgs84",
      coveragePolicy: "cell-contained",
      revision: ++state.parcelSelection.revision,
      projectCoordinate: {
        longitude: cfg.lon,
        latitude: cfg.lat
      },
      projectCoordinateManualOverride: state.location.manualOverride,
      parcels: parcelSelectionItems()
    };
    try {
      window.parent.postMessage({
        type: "vectoplan-map:parcel-selection-changed",
        kind: "vectoplan-map:parcel-selection-changed",
        source: "vectoplan-openlayer",
        detail: detail
      }, "*");
    } catch (_) {}
    try { if (state.datasetLayer) { state.datasetLayer.changed(); } } catch (_) {}
    updateParcelSelectionUi();
  }

  function datasetLooksLikeParcels(dataset) {
    var item = ensureObject(dataset);
    var text = [item.id, item.title, item.name, item.slug, item.key].map(function (value) {
      return asText(value, "").toLowerCase();
    }).join(" ");
    return text.indexOf("flurst") >= 0 || text.indexOf("parcel") >= 0 || text.indexOf("alkis") >= 0;
  }

  function autoSelectCoordinateParcel(options) {
    options = options || {};
    if (!state.datasetSource || !state.activeDataset || !datasetLooksLikeParcels(state.activeDataset)) { return false; }
    if (!state.parcelSelection.hydrated && !options.force) { return false; }
    if (state.parcelSelection.defaultCoordinateSelectionDone && !options.force) { return false; }
    if (!options.force && (state.parcelSelection.revision > 0 || parcelSelectionItems().length > 0)) {
      state.parcelSelection.defaultCoordinateSelectionDone = true;
      return false;
    }
    var coordinate = state.location.anchorProjected;
    if (!Array.isArray(coordinate)) { return false; }
    var candidates = [];
    var nearestCandidates = [];
    try {
      state.datasetSource.getFeatures().forEach(function (feature) {
        var geometry = feature && feature.getGeometry ? feature.getGeometry() : null;
        if (!geometry) { return; }
        var parcel = parcelFromFeature(feature);
        if (!parcel) { return; }
        var area = typeof geometry.getArea === "function" ? numOr(geometry.getArea(), Number.MAX_SAFE_INTEGER) : Number.MAX_SAFE_INTEGER;
        if (typeof geometry.intersectsCoordinate === "function" && geometry.intersectsCoordinate(coordinate)) {
          candidates.push({ parcel: parcel, area: area, distance: 0 });
          return;
        }
        if (typeof geometry.getClosestPoint === "function") {
          var closest = geometry.getClosestPoint(coordinate);
          if (!Array.isArray(closest) || closest.length < 2) { return; }
          var dx = Number(closest[0]) - Number(coordinate[0]);
          var dy = Number(closest[1]) - Number(coordinate[1]);
          var distance = Math.sqrt(dx * dx + dy * dy);
          if (Number.isFinite(distance)) {
            nearestCandidates.push({ parcel: parcel, area: area, distance: distance });
          }
        }
      });
    } catch (_) { candidates = []; }
    // A project coordinate can lie on a road or exactly on a cadastral border.
    // Select the closest visible parcel within a bounded tolerance in that
    // case instead of leaving the map without an initial selection.
    if (!candidates.length && nearestCandidates.length) {
      nearestCandidates.sort(function (left, right) {
        return left.distance === right.distance ? left.area - right.area : left.distance - right.distance;
      });
      var nearestTolerance = Math.min(100, Math.max(15, cfg.datasetRadiusMeters * 0.15));
      if (nearestCandidates[0].distance <= nearestTolerance) {
        candidates.push(nearestCandidates[0]);
      }
    }
    if (!candidates.length) {
      state.parcelSelection.defaultCoordinateSelectionDone = true;
      return false;
    }
    candidates.sort(function (left, right) {
      return left.distance === right.distance ? left.area - right.area : left.distance - right.distance;
    });
    var selected = candidates[0].parcel;
    var alreadySelected = !!state.parcelSelection.byId[selected.parcelId];
    state.parcelSelection.byId[selected.parcelId] = selected;
    state.parcelSelection.defaultCoordinateSelectionDone = true;
    if (!alreadySelected && !cfg.parcelSelectionReadonly) {
      postParcelSelection();
    } else {
      try { if (state.datasetLayer) { state.datasetLayer.changed(); } } catch (_) {}
      updateParcelSelectionUi();
    }
    return true;
  }

  function primitiveFeatureProperties(feature) {
    var result = {};
    try {
      var properties = feature && feature.getProperties ? feature.getProperties() : {};
      Object.keys(ensureObject(properties)).sort().slice(0, 24).forEach(function (key) {
        if (key === "geometry") { return; }
        var value = properties[key];
        if (["string", "number", "boolean"].indexOf(typeof value) >= 0 || value == null) {
          result[key] = value;
        }
      });
    } catch (_) {}
    return result;
  }

  function parcelFromFeature(feature) {
    if (!feature || !state.activeDataset || !state.view) { return null; }
    try {
      var geometry = feature.getGeometry ? feature.getGeometry() : null;
      var geometryType = geometry && geometry.getType ? geometry.getType() : "";
      if (geometryType !== "Polygon" && geometryType !== "MultiPolygon") { return null; }
      var formatter = new ol.format.GeoJSON();
      var geojson = formatter.writeFeatureObject(feature, {
        featureProjection: state.view.getProjection(),
        dataProjection: "EPSG:4326"
      });
      if (!geojson || !geojson.geometry) { return null; }
      var id = parcelFeatureId(feature, state.activeDataset);
      return {
        parcelId: id,
        datasetId: asText(state.activeDataset.id, ""),
        geometry: cloneJson(geojson.geometry, {}),
        properties: primitiveFeatureProperties(feature)
      };
    } catch (error) {
      logWarn("[OpenLayer] parcel serialization failed:", error && error.message ? error.message : error);
      return null;
    }
  }

  function handleParcelMapClick(event) {
    if (cfg.parcelSelectionReadonly || !state.map || !state.datasetLayer || !datasetLooksLikeParcels(state.activeDataset)) { return; }
    var hit = null;
    try {
      hit = state.map.forEachFeatureAtPixel(event.pixel, function (feature, layer) {
        return layer === state.datasetLayer ? feature : null;
      }, { hitTolerance: 3, layerFilter: function (layer) { return layer === state.datasetLayer; } });
    } catch (_) { hit = null; }
    // Rendering-based hit detection can miss thin or mostly transparent
    // polygons. Fall back to the actual cadastral geometry at the click.
    if (!hit && state.datasetSource && Array.isArray(event.coordinate)) {
      try {
        var directCandidates = [];
        state.datasetSource.getFeatures().forEach(function (feature) {
          var geometry = feature && feature.getGeometry ? feature.getGeometry() : null;
          if (!geometry || typeof geometry.intersectsCoordinate !== "function" || !geometry.intersectsCoordinate(event.coordinate)) { return; }
          directCandidates.push({
            feature: feature,
            area: typeof geometry.getArea === "function" ? numOr(geometry.getArea(), Number.MAX_SAFE_INTEGER) : Number.MAX_SAFE_INTEGER
          });
        });
        directCandidates.sort(function (left, right) { return left.area - right.area; });
        hit = directCandidates.length ? directCandidates[0].feature : null;
      } catch (_) { hit = null; }
    }
    if (!hit) {
      updateParcelSelectionUi("Kein Grundstueck unter dem Mauszeiger gefunden.");
      return;
    }
    var parcel = parcelFromFeature(hit);
    if (!parcel) {
      updateParcelSelectionUi("Der aktive Datensatz enthaelt an dieser Stelle kein Polygon.");
      return;
    }
    if (state.parcelSelection.byId[parcel.parcelId]) {
      delete state.parcelSelection.byId[parcel.parcelId];
    } else {
      state.parcelSelection.byId[parcel.parcelId] = parcel;
    }
    postParcelSelection();
  }

  function syncParcelSelection(value) {
    var root = ensureObject(value);
    var selection = ensureObject(root.detail || root.selection || root.last_map_selection || root);
    var incomingProjectId = asText(selection.projectPublicId || selection.project_public_id, "");
    if (cfg.projectPublicId && incomingProjectId && cfg.projectPublicId !== incomingProjectId) { return; }
    var incomingRevision = numOr(selection.revision, 0);
    if (
      state.parcelSelection.hydrated
      && incomingRevision < state.parcelSelection.revision
    ) {
      return;
    }
    var incomingCoordinate = ensureObject(selection.projectCoordinate || selection.project_coordinate);
    var incomingLongitudeValue = incomingCoordinate.longitude != null
      ? incomingCoordinate.longitude
      : (incomingCoordinate.lon != null ? incomingCoordinate.lon : incomingCoordinate.lng);
    var incomingLatitudeValue = incomingCoordinate.latitude != null
      ? incomingCoordinate.latitude
      : incomingCoordinate.lat;
    var incomingLongitude = incomingLongitudeValue == null ? NaN : Number(incomingLongitudeValue);
    var incomingLatitude = incomingLatitudeValue == null ? NaN : Number(incomingLatitudeValue);
    var incomingManualOverride = selection.projectCoordinateManualOverride;
    if (incomingManualOverride == null) {
      incomingManualOverride = selection.project_coordinate_manual_override;
    }
    var pendingCoordinate = state.location.pendingLocalCoordinate;
    var pendingActive = Array.isArray(pendingCoordinate)
      && state.location.pendingLocalCoordinateUntil > nowMs();
    if (!pendingActive) {
      state.location.pendingLocalCoordinate = null;
      state.location.pendingLocalCoordinateUntil = 0;
    }
    var pendingMatchesIncoming = pendingActive
      && Number.isFinite(incomingLongitude)
      && Number.isFinite(incomingLatitude)
      && Math.abs(incomingLongitude - pendingCoordinate[0]) <= 1e-8
      && Math.abs(incomingLatitude - pendingCoordinate[1]) <= 1e-8;
    if (pendingMatchesIncoming) {
      state.location.pendingLocalCoordinate = null;
      state.location.pendingLocalCoordinateUntil = 0;
      pendingActive = false;
    }
    var coordinateSyncBlocked = state.location.markerDragging
      || (pendingActive && !pendingMatchesIncoming);
    if (!coordinateSyncBlocked && incomingManualOverride != null) {
      state.location.manualOverride = asBool(incomingManualOverride, false);
    }
    if (!coordinateSyncBlocked && Number.isFinite(incomingLongitude) && Number.isFinite(incomingLatitude)) {
      var coordinateChanged = Math.abs(incomingLongitude - cfg.lon) > 1e-10
        || Math.abs(incomingLatitude - cfg.lat) > 1e-10;
      if (coordinateChanged) {
        updateProjectLocation([incomingLongitude, incomingLatitude], {
          notifyParent: false,
          autoSelect: false,
          manualOverride: state.location.manualOverride
        });
      }
    }
    var next = {};
    ensureArray(selection.parcels || selection.features).slice(0, 64).forEach(function (entry) {
      var parcel = ensureObject(entry);
      var parcelId = asText(parcel.parcelId || parcel.parcel_id || parcel.id, "");
      var geometry = ensureObject(parcel.geometry);
      if (!parcelId || ["Polygon", "MultiPolygon"].indexOf(asText(geometry.type, "")) < 0) { return; }
      next[parcelId] = {
        parcelId: parcelId,
        datasetId: asText(parcel.datasetId || parcel.dataset_id, ""),
        geometry: cloneJson(geometry, {}),
        properties: cloneObject(parcel.properties, {})
      };
    });
    state.parcelSelection.byId = next;
    state.parcelSelection.revision = incomingRevision;
    state.parcelSelection.hydrated = true;
    state.parcelSelection.defaultCoordinateSelectionDone = Object.keys(next).length > 0;
    try { if (state.datasetLayer) { state.datasetLayer.changed(); } } catch (_) {}
    updateParcelSelectionUi();
    window.setTimeout(function () { autoSelectCoordinateParcel(); }, 0);
  }

  function requestParcelSelection() {
    try {
      window.parent.postMessage({
        type: "vectoplan-map:parcel-selection-request",
        kind: "vectoplan-map:parcel-selection-request",
        source: "vectoplan-openlayer",
        detail: { projectPublicId: cfg.projectPublicId }
      }, "*");
    } catch (_) {}
  }

  function bindParcelSelectionBridge() {
    window.addEventListener("message", function (event) {
      var message = ensureObject(event.data);
      if (asText(message.type || message.kind, "") !== "vectoplan-app:parcel-selection-sync") { return; }
      syncParcelSelection(message.detail || message.selection || message);
    });
    requestParcelSelection();
    // The map is also usable directly and older embedding shells may not yet
    // answer the state request. Do not let that optional handshake block the
    // coordinate parcel forever.
    window.setTimeout(function () {
      if (state.parcelSelection.hydrated) { return; }
      state.parcelSelection.hydrated = true;
      autoSelectCoordinateParcel();
    }, 500);
  }

  function createDatasetLayer(dataset, features) {
    var sourceConfig = ensureObject(dataset.source);
    if (normalizeSourceType(sourceConfig.type, "placeholder") === "wms") {
      var tileSource = new ol.source.TileWMS({
        url: asText(sourceConfig.url, ""),
        params: {
          LAYERS: asText(sourceConfig.layerName, ""),
          TILED: true,
          FORMAT: asText(sourceConfig.format, "image/png") || "image/png",
          TRANSPARENT: asBool(sourceConfig.transparent, true)
        },
        crossOrigin: "anonymous",
        transition: 180
      });
      var tileLayer = new ol.layer.Tile({
        source: tileSource,
        opacity: 1,
        visible: true
      });
      try { tileLayer.set("layerRole", "dataset"); } catch (_) {}
      try { tileLayer.set("datasetId", dataset.id); } catch (_) {}
      try { tileLayer.setZIndex(500); } catch (_) {}
      return { layer: tileLayer, source: tileSource };
    }

    var source = new ol.source.Vector({
      wrapX: false,
      features: toArray(features)
    });

    var layer = new ol.layer.Vector({
      source: source,
      declutter: true,
      updateWhileAnimating: false,
      updateWhileInteracting: false,
      renderBuffer: 50,
      style: function (feature, resolution) {
        var currentDataset = (
          state.activeDataset &&
          asText(state.activeDataset.id, "") === asText(dataset.id, "")
        ) ? state.activeDataset : dataset;

        if (isSelectedParcelFeature(feature, currentDataset)) {
          return getSelectedParcelStyle();
        }

        try {
          var geom = feature && feature.getGeometry ? feature.getGeometry() : null;
          var type = geom && geom.getType ? geom.getType() : currentDataset.geometry_type;
          return getFeatureStyleForDataset(currentDataset, feature, type || currentDataset.geometry_type, resolution);
        } catch (_) {
          return getFeatureStyleForDataset(currentDataset, feature, currentDataset.geometry_type, resolution);
        }
      }
    });

    try { layer.set("layerRole", "dataset"); } catch (_) {}
    try { layer.set("datasetId", dataset.id); } catch (_) {}
    try { layer.setZIndex(500); } catch (_) {}

    return {
      layer: layer,
      source: source
    };
  }

  function clearDatasetLayer() {
    if (state.datasets.requestController) {
      try { state.datasets.requestController.abort(); } catch (_) {}
      state.datasets.requestController = null;
    }
    state.datasets.requestSerial += 1;
    try {
      if (state.datasetLayer && state.map) {
        state.map.removeLayer(state.datasetLayer);
      }
    } catch (_) {}

    state.datasetLayer = null;
    state.datasetSource = null;
    state.activeDataset = null;
    state.datasets.lastFeatureCount = 0;
    state.datasets.lastViewportKey = "";
    state.datasets.loading = false;
    markActiveDatasetButton("");
    state.datasets.zoomSuppressed = false;
    updateEditorButtonState();
    updateViewportIndicators();
  }

  function fitToSource(source) {
    try {
      if (!source || !state.map || !state.view) { return; }
      var extent = source.getExtent();
      if (!extent || !Array.isArray(extent) || extent.length < 4) { return; }
      if (!isFinite(extent[0]) || !isFinite(extent[1]) || !isFinite(extent[2]) || !isFinite(extent[3])) { return; }

      var width = Math.abs(extent[2] - extent[0]);
      var height = Math.abs(extent[3] - extent[1]);

      if (width === 0 && height === 0) {
        return;
      }

      state.view.fit(extent, {
        padding: [60, 60, 60, 80],
        duration: 260,
        maxZoom: Math.min(cfg.maxZoom, 18)
      });
    } catch (_) {}
  }

  // ───────────────────────────────────────────────────────────
  // Dataset Fetch / Details / Selection
  // ───────────────────────────────────────────────────────────

  function updateDatasetPanelServiceState() {
    try {
      if (!dom.datasetPanelServiceNote) { return; }

      if (!cfg.datasetApiEnabled) {
        setHidden(dom.datasetPanelServiceNote, true);
        return;
      }

      if (!cfg.datasetIntegrationDegraded) {
        setHidden(dom.datasetPanelServiceNote, true);
        return;
      }

      var health = ensureObject(cfg.serviceHealth);
      var messages = [];

      if (!cfg.orchestratorConfigured) {
        messages.push("Orchestrator-URL fehlt");
      }
      if (!cfg.orchestratorClientAvailable && !asBool(health.orchestrator_client_available, false)) {
        messages.push("Orchestrator-Client fehlt");
      }
      if (!asBool(health.dataset_catalog_service_available, false)) {
        messages.push("Dataset-Catalog-Service nicht bereit");
      }
      if (!asBool(health.dataset_source_service_available, false)) {
        messages.push("Dataset-Source-Service nicht bereit");
      }
      if (!asBool(health.style_adapter_available, false)) {
        messages.push("Style-Adapter nicht bereit");
      }

      setText(
        dom.datasetPanelServiceNote,
        "Die Datensatzintegration ist noch nicht vollständig bereit: " + (messages.length ? messages.join(" · ") : "unbekannter Zustand") + ". Prüfe /health/ready."
      );
      setHidden(dom.datasetPanelServiceNote, false);
    } catch (_) {}
  }

  function normalizeDatasetResponseItem(rawItem, index) {
    return normalizeDatasetItem(rawItem, index);
  }

  function normalizeAndStoreDatasetsPayload(payload) {
    var normalizedPayload = normalizeDatasetsPayload(payload);

    state.datasets.items = normalizedPayload.items.slice();
    state.datasets.byId = {};

    state.datasets.items.forEach(function (item) {
      if (!item || !hasText(item.id)) { return; }
      state.datasets.byId[item.id] = item;
    });

    state.datasets.lastPayload = cloneJson(normalizedPayload, { items: [] });
    state.datasets.fetchedAt = nowMs();

    return normalizedPayload;
  }

  function fetchDatasets(force) {
    if (!cfg.datasetApiEnabled) {
      return Promise.resolve({
        status: "not_available",
        items: [],
        count: 0,
        placeholder: true,
        notes: ["dataset_api_disabled"]
      });
    }

    var freshEnough = state.datasets.lastPayload && (nowMs() - state.datasets.fetchedAt < state.datasets.ttlMs);
    if (!force && freshEnough) {
      return Promise.resolve(cloneJson(state.datasets.lastPayload, { items: [] }));
    }

    if (!force && state.datasets.inflight) {
      return state.datasets.inflight;
    }

    var candidateUrls = uniqueUrls([
      cfg.datasetsApiStyleContractUrl,
      cfg.datasetsApiUrl,
      cfg.datasetsApiUrlBase
    ]);

    if (!candidateUrls.length) {
      return Promise.reject(new Error("datasets_api_url_missing"));
    }

    state.datasets.inflight = fetchFirstJson(candidateUrls, {
      method: "GET",
      headers: { "Accept": "application/json" },
      credentials: "same-origin"
    }).then(function (result) {
      var normalizedPayload = normalizeAndStoreDatasetsPayload(result.json);
      normalizedPayload._fetched_from = result.url;
      return cloneJson(normalizedPayload, { items: [] });
    }).catch(function (err) {
      if (state.datasets.lastPayload) {
        logWarn("[OpenLayer] datasets fetch failed, stale payload used:", err && err.message ? err.message : err);
        return cloneJson(state.datasets.lastPayload, { items: [] });
      }
      throw err;
    }).finally(function () {
      state.datasets.inflight = null;
    });

    return state.datasets.inflight;
  }

  function renderDatasetList(items) {
    var list = Array.isArray(items) ? items : [];
    if (!dom.datasetList) { return; }

    dom.datasetList.innerHTML = "";

    if (!list.length) {
      setHidden(dom.datasetPanelEmpty, false);
      return;
    }

    setHidden(dom.datasetPanelEmpty, true);

    list.forEach(function (item) {
      try {
        var tpl = dom.datasetTemplate;
        var node = null;

        if (tpl && tpl.content && tpl.content.firstElementChild) {
          node = tpl.content.firstElementChild.cloneNode(true);
        } else {
          node = document.createElement("li");
          node.className = "dataset-item";
          node.innerHTML = '<button type="button" class="dataset-item__button" data-role="dataset-item-button"><span class="dataset-item__title" data-role="dataset-item-title"></span><span class="dataset-item__description" data-role="dataset-item-description" hidden></span></button>';
        }

        var button = q("[data-role='dataset-item-button']", node);
        var title = q("[data-role='dataset-item-title']", node);
        var description = q("[data-role='dataset-item-description']", node);

        var descriptionText = hasText(item.description)
          ? item.description
          : (item.warnings && item.warnings.length ? item.warnings[0] : "");

        setText(title, item.title || item.id || "Datensatz");
        if (hasText(descriptionText)) {
          setText(description, truncateText(descriptionText, 180));
          setHidden(description, false);
        } else {
          setHidden(description, true);
        }

        button.setAttribute("data-dataset-id", asText(item.id, ""));
        button.setAttribute("aria-pressed", "false");
        button.setAttribute("title", asText(item.title || item.id, "Datensatz"));

        button.addEventListener("click", function () {
          selectDataset(item.id, { closePanel: true });
        });

        dom.datasetList.appendChild(node);
      } catch (e) {
        logWarn("[OpenLayer] dataset item render failed:", e && e.message ? e.message : e);
      }
    });

    markActiveDatasetButton(state.activeDataset ? state.activeDataset.id : "");
  }

  function loadDatasetsIntoPanel(force) {
    updateDatasetPanelServiceState();

    if (!cfg.datasetApiEnabled) {
      setHidden(dom.datasetPanelDisabledNote, false);
      setHidden(dom.datasetPanelLoading, true);
      setHidden(dom.datasetPanelError, true);
      setHidden(dom.datasetPanelEmpty, true);
      if (dom.datasetList) { dom.datasetList.innerHTML = ""; }
      return Promise.resolve([]);
    }

    setHidden(dom.datasetPanelDisabledNote, true);
    setHidden(dom.datasetPanelLoading, false);
    setHidden(dom.datasetPanelError, true);
    setHidden(dom.datasetPanelEmpty, true);

    return fetchDatasets(!!force).then(function (payload) {
      var items = Array.isArray(payload.items) ? payload.items : [];
      renderDatasetList(items);
      setHidden(dom.datasetPanelLoading, true);
      setHidden(dom.datasetPanelError, true);
      setHidden(dom.datasetPanelEmpty, items.length > 0);

      maybeActivateInitialDataset(items);

      return items;
    }).catch(function (err) {
      logError("[OpenLayer] datasets fetch failed:", err && err.message ? err.message : err);
      if (dom.datasetList) { dom.datasetList.innerHTML = ""; }
      setHidden(dom.datasetPanelLoading, true);
      setHidden(dom.datasetPanelError, false);
      setHidden(dom.datasetPanelEmpty, true);
      setToast("danger", "Datensatzliste", "Die Datensatzliste konnte nicht geladen werden.", 3800);
      return [];
    });
  }

  function findDatasetById(datasetId) {
    var wanted = asText(datasetId, "");
    if (!wanted) { return null; }

    if (state.datasets.byId[wanted]) {
      return state.datasets.byId[wanted];
    }

    return (state.datasets.items || []).find(function (item) {
      return asText(item && item.id, "") === wanted;
    }) || null;
  }

  function maybeActivateInitialDataset(items) {
    if (state.datasets.initialSelectionAttempted) { return; }
    if (state.activeDataset) {
      state.datasets.initialSelectionAttempted = true;
      return;
    }

    var list = Array.isArray(items) ? items : [];
    var targetId = "";
    var explicitDatasetId = false;
    try { explicitDatasetId = new URLSearchParams(window.location.search || "").has("dataset_id"); } catch (_) {}
    var parcelDataset = list.find(function (item) { return datasetLooksLikeParcels(item); });

    if (explicitDatasetId && hasText(cfg.initialDatasetId)) {
      targetId = cfg.initialDatasetId;
    } else if (parcelDataset) {
      targetId = asText(parcelDataset.id, "");
    } else if (hasText(cfg.initialDatasetId)) {
      targetId = cfg.initialDatasetId;
    } else if (list.length === 1) {
      targetId = asText(list[0].id, "");
    }

    if (!hasText(targetId)) { return; }

    state.datasets.initialSelectionAttempted = true;

    setTimeout(function () {
      selectDataset(targetId, {
        closePanel: false,
        auto: true,
        silentIfAlreadyActive: true
      });
    }, 0);
  }

  function getDatasetDetailCacheKey(datasetId) {
    return asText(datasetId, "");
  }

  function getCachedDatasetDetail(datasetId) {
    var key = getDatasetDetailCacheKey(datasetId);
    var entry = state.datasets.detailCache[key];

    if (!entry) { return null; }
    if ((nowMs() - numOr(entry.fetchedAt, 0)) > state.datasets.detailCacheTtlMs) {
      delete state.datasets.detailCache[key];
      return null;
    }

    return cloneJson(entry.dataset, null);
  }

  function setCachedDatasetDetail(dataset) {
    if (!dataset || !hasText(dataset.id)) { return; }

    state.datasets.detailCache[getDatasetDetailCacheKey(dataset.id)] = {
      fetchedAt: nowMs(),
      dataset: cloneJson(dataset, null)
    };
  }

  function mergeDatasetRecords(baseDataset, detailPayload) {
    var baseRaw = cloneObject(baseDataset && baseDataset._raw, {});
    var detailRaw = cloneObject(detailPayload, {});
    var mergedRaw = cloneObject(baseRaw, {});

    Object.keys(detailRaw).forEach(function (key) {
      mergedRaw[key] = detailRaw[key];
    });

    return normalizeDatasetItem(mergedRaw, 0);
  }

  function fetchDatasetDetails(dataset, force) {
    dataset = ensureObject(dataset);

    if (!hasText(dataset.id)) {
      return Promise.resolve(dataset);
    }

    if (!force && hasUsableStyleContract(dataset)) {
      return Promise.resolve(dataset);
    }

    if (!force) {
      var cached = getCachedDatasetDetail(dataset.id);
      if (cached) {
        return Promise.resolve(cached);
      }
    }

    var detailUrl = buildDatasetDetailUrl(dataset.id);
    if (force) {
      detailUrl = addRefreshQuery(detailUrl);
    }
    if (!hasText(detailUrl)) {
      return Promise.resolve(dataset);
    }

    return fetchJson(detailUrl, {
      method: "GET",
      headers: { "Accept": "application/json" },
      credentials: "same-origin",
      cache: force ? "no-store" : "default"
    }).then(function (result) {
      if (!result.ok || !isObject(result.json)) {
        return dataset;
      }

      var merged = mergeDatasetRecords(dataset, result.json);
      setCachedDatasetDetail(merged);
      upsertDatasetIntoState(merged);
      return merged;
    }).catch(function () {
      return dataset;
    });
  }

  function getFeatureCacheKey(dataset, sourceUrl) {
    return asText(dataset && dataset.id, "") + "::" + asText(sourceUrl, "");
  }

  function getCachedFeaturePayload(dataset, sourceUrl) {
    var cacheKey = getFeatureCacheKey(dataset, sourceUrl);
    var entry = state.datasets.featureCache[cacheKey];

    if (!entry) { return null; }
    if ((nowMs() - numOr(entry.fetchedAt, 0)) > state.datasets.featureCacheTtlMs) {
      delete state.datasets.featureCache[cacheKey];
      return null;
    }

    return cloneJson(entry.payload, null);
  }

  function setCachedFeaturePayload(dataset, sourceUrl, payload) {
    var cacheKey = getFeatureCacheKey(dataset, sourceUrl);
    state.datasets.featureCache[cacheKey] = {
      fetchedAt: nowMs(),
      payload: cloneJson(payload, null)
    };
    var cacheKeys = Object.keys(state.datasets.featureCache);
    while (cacheKeys.length > MAX_VIEWPORT_FEATURE_CACHE_ENTRIES) {
      delete state.datasets.featureCache[cacheKeys.shift()];
    }
  }

  function buildDatasetFetchUrl(dataset, viewport, requestOptions) {
    dataset = ensureObject(dataset);
    viewport = viewport || getCurrentViewportContext();
    requestOptions = requestOptions || {};
    var sourceUrl = buildDatasetSourceUrl(dataset.id);

    if (!sourceUrl || !viewport || !Array.isArray(viewport.bbox)) { return ""; }

    try {
      var parsed = new URL(sourceUrl, window.location.href);
      parsed.searchParams.set("bbox", viewport.bbox.map(function (value) {
        return Number(value).toFixed(8);
      }).join(","));
      parsed.searchParams.set("bbox_crs", "CRS:84");
      parsed.searchParams.set("lon", viewport.center[0].toFixed(8));
      parsed.searchParams.set("lat", viewport.center[1].toFixed(8));
      parsed.searchParams.set("radius_m", String(cfg.datasetRadiusMeters));
      parsed.searchParams.set("zoom", Number(viewport.zoom).toFixed(3));
      parsed.searchParams.set("limit", String(cfg.datasetFeatureLimit));
      parsed.searchParams.set("offset", String(clamp(numOr(requestOptions.offset, 0), 0, cfg.datasetFeatureLimit)));
      parsed.searchParams.set("batch_size", String(clamp(numOr(requestOptions.batchSize, DEFAULT_DATASET_BATCH_SIZE), 1, 250)));
      if (/^https?:\/\//i.test(sourceUrl)) {
        return parsed.toString();
      }
      return parsed.pathname + parsed.search + parsed.hash;
    } catch (_) {
      return "";
    }
  }

  function loadDatasetFeatures(dataset, viewport, requestOptions) {
    dataset = ensureObject(dataset);
    requestOptions = requestOptions || {};

    var source = ensureObject(dataset.source);
    var sourceUrl = buildDatasetFetchUrl(dataset, viewport, requestOptions);
    var sourceType = normalizeSourceType(source.type, "placeholder");
    var sourceFormat = asText(source.format, "").trim().toLowerCase();
    var featureLimit = cfg.datasetFeatureLimit;
    var batchOffset = clamp(numOr(requestOptions.offset, 0), 0, featureLimit);
    var batchSize = clamp(numOr(requestOptions.batchSize, DEFAULT_DATASET_BATCH_SIZE), 1, Math.min(250, featureLimit));

    if (!sourceUrl) {
      return Promise.resolve({
        features: [],
        warning: "Datensatz hat keine Quell-URL und wird leer geladen.",
        featureCount: 0,
        featureLimit: featureLimit,
        sourceUrl: "",
        sourceType: sourceType
      });
    }

    var cachedPayload = getCachedFeaturePayload(dataset, sourceUrl);
    if (cachedPayload && isObject(cachedPayload.geojson)) {
      return Promise.resolve({
        features: readGeoJsonFeatures(cachedPayload.geojson),
        warning: asText(cachedPayload.warning, ""),
        featureCount: clamp(numOr(cachedPayload.featureCount, 0), 0, 999999),
        batchOffset: clamp(numOr(cachedPayload.batchOffset, batchOffset), 0, featureLimit),
        batchSize: clamp(numOr(cachedPayload.batchSize, batchSize), 1, 250),
        totalAvailable: clamp(numOr(cachedPayload.totalAvailable, cachedPayload.featureCount), 0, featureLimit),
        hasMore: asBool(cachedPayload.hasMore, false),
        nextOffset: clamp(numOr(cachedPayload.nextOffset, batchOffset + cachedPayload.featureCount), 0, featureLimit),
        featureLimit: featureLimit,
        sourceUrl: sourceUrl,
        sourceType: sourceType,
        cached: true
      });
    }

    return fetchText(sourceUrl, {
      method: "GET",
      headers: {
        "Accept": "application/json, application/geo+json, text/plain;q=0.9, */*;q=0.8"
      },
      credentials: "same-origin",
      signal: requestOptions.signal
    }).then(function (response) {
      if (!response.ok) {
        throw new Error("HTTP " + response.status);
      }

      if (!hasText(response.text)) {
        return {
          features: [],
          warning: "Datensatzquelle ist leer.",
          featureCount: 0,
          featureLimit: featureLimit,
          sourceUrl: sourceUrl,
          sourceType: sourceType
        };
      }

      var jsonPayload = null;
      try {
        jsonPayload = JSON.parse(response.text);
      } catch (_) {
        jsonPayload = null;
      }

      if (jsonPayload && isLikelyGeoJsonPayload(jsonPayload)) {
        var limitedPayload = applyFeatureLimitToGeoJsonPayload(jsonPayload, featureLimit);
        var features = readGeoJsonFeatures(limitedPayload);
        var rawFeatureCount = 0;

        if (limitedPayload && limitedPayload.type === "FeatureCollection" && Array.isArray(limitedPayload.features)) {
          rawFeatureCount = limitedPayload.features.length;
        } else if (limitedPayload && limitedPayload.type === "Feature") {
          rawFeatureCount = 1;
        }

        var warning = "";
        var returnedOffset = clamp(numOr(getResponseHeader(response.headers, "X-OpenLayer-Batch-Offset", batchOffset), batchOffset), 0, featureLimit);
        var returnedBatchSize = clamp(numOr(getResponseHeader(response.headers, "X-OpenLayer-Batch-Size", batchSize), batchSize), 1, 250);
        var totalAvailable = clamp(numOr(getResponseHeader(response.headers, "X-OpenLayer-Total-Available", returnedOffset + rawFeatureCount), returnedOffset + rawFeatureCount), 0, featureLimit);
        var hasMore = asText(getResponseHeader(response.headers, "X-OpenLayer-Has-More", "false"), "false").toLowerCase() === "true";
        var nextOffset = clamp(numOr(getResponseHeader(response.headers, "X-OpenLayer-Next-Offset", returnedOffset + rawFeatureCount), returnedOffset + rawFeatureCount), 0, featureLimit);
        if (!hasMore) { nextOffset = returnedOffset + rawFeatureCount; }

        if (totalAvailable >= featureLimit) {
          warning = "Der " + String(cfg.datasetRadiusMeters) + "-m-Radius wurde auf maximal " + String(featureLimit) + " Features begrenzt.";
        }

        setCachedFeaturePayload(dataset, sourceUrl, {
          geojson: limitedPayload,
          warning: warning,
          featureCount: rawFeatureCount,
          batchOffset: returnedOffset,
          batchSize: returnedBatchSize,
          totalAvailable: totalAvailable,
          hasMore: hasMore,
          nextOffset: nextOffset
        });

        return {
          features: features,
          warning: warning,
          featureCount: rawFeatureCount,
          featureLimit: featureLimit,
          sourceUrl: sourceUrl,
          batchOffset: returnedOffset,
          batchSize: returnedBatchSize,
          totalAvailable: totalAvailable,
          hasMore: hasMore,
          nextOffset: nextOffset,
          sourceType: sourceType
        };
      }

      var shortText = truncateText(response.text, MAX_RESPONSE_PREVIEW_LENGTH);
      var hint = (sourceType === "wfs" || sourceFormat === "wfs")
        ? "WFS-Quelle liefert aktuell kein direkt lesbares JSON/GeoJSON."
        : "Quelle liefert aktuell kein JSON/GeoJSON.";

      return {
        features: [],
        warning: hint + (shortText ? (" Vorschau: " + shortText) : ""),
        featureCount: 0,
        featureLimit: featureLimit,
        sourceUrl: sourceUrl,
        sourceType: sourceType
      };
    }).catch(function (err) {
      if (err && err.name === "AbortError") {
        throw err;
      }
      return {
        features: [],
        warning: "Datensatz konnte nicht geladen werden: " + (err && err.message ? err.message : "unknown_error"),
        featureCount: 0,
        featureLimit: featureLimit,
        sourceUrl: sourceUrl,
        sourceType: sourceType
      };
    });
  }

  function applyDataset(dataset, featuresResult, options) {
    options = options || {};
    dataset = ensureObject(dataset);

    var result = ensureObject(featuresResult);
    var features = Array.isArray(result.features) ? result.features : [];
    var warning = asText(result.warning, "");
    var featureCount = clamp(numOr(result.featureCount, features.length), 0, 999999);
    var replacingCurrent = !!(
      options.viewportReload &&
      state.activeDataset &&
      asText(state.activeDataset.id, "") === asText(dataset.id, "") &&
      state.datasetSource
    );

    var wasEditorActive = !!state.editor.active;
    if (wasEditorActive && !replacingCurrent) {
      deactivateEditor({ silent: true, keepPanel: false });
    }

    if (replacingCurrent) {
      try {
        state.datasetSource.clear(true);
        if (features.length) { state.datasetSource.addFeatures(features); }
      } catch (err) {
        logWarn("[OpenLayer] viewport features replace failed:", err && err.message ? err.message : err);
      }
      state.activeDataset = dataset;
      try { state.datasetLayer.changed(); } catch (_) {}
    } else {
      clearDatasetLayer();
      var created = createDatasetLayer(dataset, features);
      state.datasetLayer = created.layer;
      state.datasetSource = created.source;
      state.activeDataset = dataset;
      try {
        if (state.map) { state.map.addLayer(state.datasetLayer); }
      } catch (e) {
        logError("[OpenLayer] dataset layer add failed:", e && e.message ? e.message : e);
      }
    }

    state.datasets.lastFeatureCount = featureCount;
    upsertDatasetIntoState(dataset);
    markActiveDatasetButton(dataset.id);
    updateEditorButtonState();
    setDatasetZoomVisibility(getCurrentViewportContext());

    if (!options.silent && warning) {
      setToast("danger", "Ausschnitt begrenzt", warning, 4200);
    }

    if (wasEditorActive && !replacingCurrent) {
      activateEditor().catch(noop);
    }
  }


  function reloadActiveDatasetForViewport(options) {
    options = options || {};
    var dataset = state.activeDataset;
    var viewport = getCurrentViewportContext();
    updateViewportIndicators(viewport);

    if (!dataset || !state.datasetSource || !viewport) {
      return Promise.resolve(false);
    }

    if (!setDatasetZoomVisibility(viewport)) { return Promise.resolve(false); }
    if (normalizeSourceType(ensureObject(dataset.source).type, "placeholder") === "wms") {
      state.datasets.lastViewportKey = viewport.key;
      state.datasets.lastFeatureCount = 0;
      updateViewportIndicators(viewport);
      return Promise.resolve(true);
    }

    if (!options.force && state.datasets.lastViewportKey === viewport.key) {
      return Promise.resolve(false);
    }

    if (state.datasets.requestController) {
      try { state.datasets.requestController.abort(); } catch (_) {}
    }
    var requestController = typeof window.AbortController === "function"
      ? new window.AbortController()
      : null;
    var requestSerial = state.datasets.requestSerial + 1;
    state.datasets.requestSerial = requestSerial;
    state.datasets.requestController = requestController;
    state.datasets.loading = true;
    updateViewportIndicators(viewport);

    var loadedFeatureCount = 0;
    var finalWarning = "";
    var batchSize = Math.min(DEFAULT_DATASET_BATCH_SIZE, cfg.datasetFeatureLimit);

    function requestIsCurrent() {
      return (
        requestSerial === state.datasets.requestSerial &&
        state.activeDataset &&
        asText(state.activeDataset.id, "") === asText(dataset.id, "")
      );
    }

    function loadNextBatch(offset) {
      if (!requestIsCurrent() || (requestController && requestController.signal.aborted)) {
        return Promise.resolve(false);
      }

      return loadDatasetFeatures(dataset, viewport, {
        signal: requestController ? requestController.signal : undefined,
        offset: offset,
        batchSize: batchSize
      }).then(function (result) {
        if (!requestIsCurrent()) { return false; }

        var batchFeatures = Array.isArray(result.features) ? result.features : [];
        var isFirstBatch = offset === 0;
        if (isFirstBatch) {
          applyDataset(state.activeDataset, result, {
            viewportReload: true,
            silent: true
          });
        } else if (state.datasetSource && batchFeatures.length) {
          try {
            state.datasetSource.addFeatures(batchFeatures);
          } catch (err) {
            logWarn("[OpenLayer] progressive feature append failed:", err && err.message ? err.message : err);
          }
        }

        loadedFeatureCount += batchFeatures.length;
        finalWarning = asText(result.warning, finalWarning);
        state.datasets.lastFeatureCount = loadedFeatureCount;
        autoSelectCoordinateParcel();
        postParcelCatalog();

        var nextOffset = clamp(numOr(result.nextOffset, offset + batchFeatures.length), 0, cfg.datasetFeatureLimit);
        var hasMore = asBool(result.hasMore, false)
          && nextOffset > offset
          && loadedFeatureCount < cfg.datasetFeatureLimit;

        if (hasMore) {
          updateViewportIndicators(viewport);
          return new Promise(function (resolve) {
            window.setTimeout(resolve, DATASET_BATCH_DELAY_MS);
          }).then(function () {
            return loadNextBatch(nextOffset);
          });
        }

        state.datasets.lastViewportKey = viewport.key;
        autoSelectCoordinateParcel();
        postParcelCatalog();
        updateViewportIndicators(viewport);
        return true;
      });
    }

    return loadNextBatch(0).catch(function (err) {
      if (err && err.name === "AbortError") { return false; }
      logError("[OpenLayer] viewport dataset load failed:", err && err.message ? err.message : err);
      if (requestSerial === state.datasets.requestSerial) {
        setToast("danger", "Standortradius", "Die Daten fuer den " + String(cfg.datasetRadiusMeters) + "-m-Radius konnten nicht geladen werden.", 3800);
      }
      return false;
    }).finally(function () {
      if (requestSerial !== state.datasets.requestSerial) { return; }
      state.datasets.loading = false;
      if (state.datasets.requestController === requestController) {
        state.datasets.requestController = null;
      }
      updateViewportIndicators(viewport);
    });
  }
  function refreshActiveDatasetStyle(options) {
    options = options || {};

    if (!cfg.datasetApiEnabled || !state.activeDataset || !state.datasetLayer || state.datasets.loading) {
      return Promise.resolve(false);
    }
    if (state.style.refreshInflight) {
      return state.style.refreshInflight;
    }

    var viewport = getCurrentViewportContext();
    if (!viewport || viewport.zoom < cfg.datasetMinLoadZoom) {
      return Promise.resolve(false);
    }

    var currentDataset = state.activeDataset;
    var currentKey = asText(ensureObject(currentDataset.style_contract).cacheKey, "");

    state.style.refreshInflight = fetchDatasetDetails(currentDataset, true).then(function (refreshedDataset) {
      if (!refreshedDataset || !hasUsableStyleContract(refreshedDataset)) {
        return false;
      }

      var refreshedKey = asText(ensureObject(refreshedDataset.style_contract).cacheKey, "");
      if (refreshedKey === currentKey) {
        return false;
      }

      state.activeDataset = refreshedDataset;
      upsertDatasetIntoState(refreshedDataset);

      try {
        state.datasetLayer.changed();
      } catch (_) {}

      markActiveDatasetButton(refreshedDataset.id);

      if (options.notify !== false) {
        setToast(
          "success",
          "Style aktualisiert",
          asText(refreshedDataset.title, refreshedDataset.id) + " wird jetzt mit dem gespeicherten Style dargestellt.",
          3000
        );
      }

      return true;
    }).catch(function (err) {
      logWarn("[OpenLayer] style refresh failed:", err && err.message ? err.message : err);
      return false;
    }).finally(function () {
      state.style.refreshInflight = null;
    });

    return state.style.refreshInflight;
  }

  function startActiveStyleRefresh() {
    if (state.style.refreshTimer) { return; }

    state.style.refreshTimer = window.setInterval(function () {
      if (document.visibilityState === "hidden") { return; }
      refreshActiveDatasetStyle({ notify: true }).catch(noop);
    }, DEFAULT_STYLE_REFRESH_INTERVAL_MS);

    window.addEventListener("focus", function () {
      refreshActiveDatasetStyle({ notify: true }).catch(noop);
    });

    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") {
        refreshActiveDatasetStyle({ notify: true }).catch(noop);
      }
    });
  }

  function markActiveDatasetButton(activeId) {
    qa("[data-role='dataset-item-button']", dom.datasetList).forEach(function (btn) {
      try {
        var selected = asText(btn.getAttribute("data-dataset-id"), "") === asText(activeId, "");
        btn.setAttribute("data-selected", selected ? "true" : "false");
        btn.setAttribute("aria-pressed", selected ? "true" : "false");
      } catch (_) {}
    });
  }

  function selectDataset(datasetId, options) {
    options = options || {};

    var item = findDatasetById(datasetId);
    if (!item) {
      setToast("danger", "Datensatz", "Der gewählte Datensatz wurde nicht gefunden.", 3600);
      return;
    }

    if (state.activeDataset && asText(state.activeDataset.id, "") === asText(item.id, "") && !options.forceReload) {
      if (options.closePanel !== false) {
        closeDatasetPanel();
      }
      return;
    }

    fetchDatasetDetails(item, false).then(function (datasetWithDetails) {
      applyDataset(datasetWithDetails, {
        features: [],
        featureCount: 0,
        warning: ""
      }, { silent: true });
      state.datasets.lastViewportKey = "";
      if (options.closePanel !== false) {
        closeDatasetPanel();
      }
      if (normalizeSourceType(ensureObject(datasetWithDetails.source).type, "placeholder") === "wms") {
        return true;
      }
      var viewport = getCurrentViewportContext();
      if (!viewport || viewport.zoom < cfg.datasetMinLoadZoom) {
        return false;
      }
      return reloadActiveDatasetForViewport({ force: true, notify: false, reason: "selection" });
    }).catch(function (err) {
      logError("[OpenLayer] selectDataset failed:", err && err.message ? err.message : err);
      setToast("danger", "Datensatz", "Der Datensatz konnte nicht verarbeitet werden.", 3800);
    });
  }

  // ───────────────────────────────────────────────────────────
  // Editor
  // ───────────────────────────────────────────────────────────

  function isEditorAllowedForActiveDataset() {
    if (!cfg.editorEnabled) { return false; }
    if (!state.activeDataset) { return false; }
    if (!state.datasetSource) { return false; }
    if (!state.activeDataset.editable) { return false; }

    var gt = asText(state.activeDataset.geometry_type, "");
    return isPointGeometry(gt) || isLineGeometry(gt) || isPolygonGeometry(gt);
  }

  function updateEditorButtonState() {
    var enabled = isEditorAllowedForActiveDataset();
    setDisabled(dom.btnEditor, !enabled);
    setPressed(dom.btnEditor, !!state.editor.active);
    setExpanded(dom.btnEditor, !!state.ui.editorPanelOpen);

    if (!enabled && state.editor.active) {
      deactivateEditor({ silent: true, keepPanel: false });
    }
  }

  function cleanupOleDom() {
    var selectors = [
      ".ole-controlbar",
      ".ole-toolbar",
      ".ole-overlay",
      ".ole-dialog",
      ".ole-draw-toolbar"
    ];

    selectors.forEach(function (selector) {
      qa(selector, document).forEach(function (node) {
        try { node.remove(); } catch (_) {}
      });
    });

    try { document.body.classList.remove("ole-editor-active"); } catch (_) {}
  }

  function destroyEditorInstance() {
    var map = state.map;
    var editor = state.editor.instance;
    var controls = Array.isArray(state.editor.controls) ? state.editor.controls.slice() : [];

    controls.forEach(function (control) {
      try { if (typeof control.deactivate === "function") { control.deactivate(); } } catch (_) {}
      try { if (typeof control.setActive === "function") { control.setActive(false); } } catch (_) {}
      try { if (map && typeof map.removeControl === "function") { map.removeControl(control); } } catch (_) {}
    });

    try { if (editor && typeof editor.removeControls === "function") { editor.removeControls(controls); } } catch (_) {}
    try { if (editor && typeof editor.clear === "function") { editor.clear(); } } catch (_) {}
    try { if (editor && typeof editor.destroy === "function") { editor.destroy(); } } catch (_) {}
    try { if (editor && typeof editor.dispose === "function") { editor.dispose(); } } catch (_) {}

    cleanupOleDom();

    state.editor.instance = null;
    state.editor.controls = [];
    state.editor.active = false;
    state.editor.lastDatasetId = "";
  }

  function buildOleControls(source, geometryType) {
    if (!window.ole || !window.ole.control) {
      throw new Error("ole controls unavailable");
    }

    var controls = [];
    var gt = asText(geometryType, "");

    if (window.ole.control.Draw) {
      if (isLineGeometry(gt)) {
        controls.push(new window.ole.control.Draw({
          type: "LineString",
          source: source
        }));
      } else if (isPolygonGeometry(gt)) {
        controls.push(new window.ole.control.Draw({
          type: "Polygon",
          source: source
        }));
      } else {
        controls.push(new window.ole.control.Draw({
          source: source
        }));
      }
    }

    if (window.ole.control.CAD && isLineGeometry(gt)) {
      controls.push(new window.ole.control.CAD({
        source: source
      }));
    }

    if (window.ole.control.Modify) {
      controls.push(new window.ole.control.Modify({
        source: source
      }));
    }

    if (window.ole.control.Rotate && !isPointGeometry(gt)) {
      controls.push(new window.ole.control.Rotate({
        source: source
      }));
    }

    return controls;
  }

  function activateEditor() {
    if (state.editor.loading) {
      return Promise.resolve(false);
    }

    if (!isEditorAllowedForActiveDataset()) {
      setToast("danger", "Editor", "Für den aktuellen Datensatz ist der Editor nicht verfügbar.", 3600);
      return Promise.resolve(false);
    }

    state.editor.loading = true;
    setDisabled(dom.btnEditor, true);

    return ensureOLE().then(function () {
      if (!state.map || !state.datasetSource || !state.activeDataset) {
        throw new Error("map/source/dataset missing");
      }

      destroyEditorInstance();

      var editor = new window.ole.Editor(state.map);
      var controls = buildOleControls(state.datasetSource, state.activeDataset.geometry_type);

      if (!controls.length) {
        throw new Error("no ole controls created");
      }

      editor.addControls(controls);

      state.editor.instance = editor;
      state.editor.controls = controls;
      state.editor.active = true;
      state.editor.lastDatasetId = asText(state.activeDataset.id, "");
      state.editor.libraryReady = true;

      try { document.body.classList.add("ole-editor-active"); } catch (_) {}

      openEditorPanel(true);
      updateEditorButtonState();

      setToast(
        "success",
        "Editor aktiv",
        "Der Editor wurde für " + asText(state.activeDataset.title, "den Datensatz") + " aktiviert.",
        2600
      );

      return true;
    }).catch(function (err) {
      destroyEditorInstance();
      updateEditorButtonState();
      setToast(
        "danger",
        "Editor",
        "OpenLayers Editor konnte nicht aktiviert werden: " + (err && err.message ? err.message : "unknown_error"),
        4600
      );
      return false;
    }).finally(function () {
      state.editor.loading = false;
      updateEditorButtonState();
    });
  }

  function deactivateEditor(options) {
    options = options || {};
    destroyEditorInstance();
    updateEditorButtonState();

    if (!options.keepPanel) {
      openEditorPanel(false);
    }

    if (!options.silent) {
      setToast("success", "Editor deaktiviert", "Der Editor wurde deaktiviert.", 2200);
    }
  }

  function toggleEditor() {
    if (state.editor.active) {
      deactivateEditor({ silent: false, keepPanel: false });
      return;
    }
    activateEditor().catch(noop);
  }

  // ───────────────────────────────────────────────────────────
  // Panels / Toolbar
  // ───────────────────────────────────────────────────────────

  function setDownloadStatus(text, kind) {
    if (!dom.downloadStatus) { return; }
    setText(dom.downloadStatus, text || "");
    if (kind) { dom.downloadStatus.setAttribute("data-kind", kind); }
    else { dom.downloadStatus.removeAttribute("data-kind"); }
    setHidden(dom.downloadStatus, !hasText(text));
  }

  function buildExportRequestUrl(exportFormat) {
    if (!state.activeDataset) { return ""; }
    var viewport = getCurrentViewportContext();
    if (!viewport || viewport.zoom < cfg.datasetMinLoadZoom) { return ""; }
    var baseUrl = buildDatasetExportUrl(state.activeDataset.id);
    if (!baseUrl) { return ""; }

    try {
      var parsed = new URL(baseUrl, window.location.href);
      parsed.searchParams.set("format", exportFormat);
      parsed.searchParams.set("lon", viewport.center[0].toFixed(8));
      parsed.searchParams.set("lat", viewport.center[1].toFixed(8));
      parsed.searchParams.set("radius_m", String(cfg.datasetRadiusMeters));
      parsed.searchParams.set("zoom", Number(viewport.zoom).toFixed(3));
      if (exportFormat !== "pdf") {
        parsed.searchParams.set("bbox", viewport.bbox.map(function (value) {
          return Number(value).toFixed(8);
        }).join(","));
      }
      if (/^https?:\/\//i.test(baseUrl)) { return parsed.toString(); }
      return parsed.pathname + parsed.search + parsed.hash;
    } catch (_) {
      return "";
    }
  }

  function exportFilenameFromResponse(response, fallbackName) {
    try {
      var disposition = response.headers.get("Content-Disposition") || "";
      var match = /filename="?([^";]+)"?/i.exec(disposition);
      if (match && hasText(match[1])) { return match[1].trim(); }
    } catch (_) {}
    return fallbackName;
  }

  function fetchExportArtifact(url, fallbackName) {
    return window.fetch(url, {
      method: "GET",
      headers: { "Accept": "application/octet-stream, application/zip, application/json" },
      credentials: "same-origin"
    }).then(function (response) {
      if (!response.ok) {
        return response.text().then(function (bodyText) {
          var message = "HTTP " + response.status;
          try {
            var payload = JSON.parse(bodyText);
            message = firstText(payload.detail, payload.message, message);
          } catch (_) {}
          throw new Error(message);
        });
      }
      return response.blob().then(function (blob) {
        return {
          blob: blob,
          filename: exportFilenameFromResponse(response, fallbackName)
        };
      });
    });
  }

  function saveExportArtifact(artifact) {
    var objectUrl = URL.createObjectURL(artifact.blob);
    var anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = artifact.filename;
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
    setTimeout(function () {
      try { URL.revokeObjectURL(objectUrl); } catch (_) {}
      try { anchor.remove(); } catch (_) {}
    }, 1500);
  }

  function runDatasetExport(exportFormat) {
    if (state.ui.exportLoading || !state.activeDataset) { return; }
    var viewport = getCurrentViewportContext();
    if (!viewport || viewport.zoom < cfg.datasetMinLoadZoom) {
      setDownloadStatus("Bitte mindestens bis Zoomstufe " + String(cfg.datasetMinLoadZoom) + " hineinzoomen.", "error");
      return;
    }

    var isPdf = exportFormat === "pdf";
    var requests = [{
      url: buildExportRequestUrl(exportFormat),
      fallback: isPdf ? "kartenausschnitt_PDF_A4.zip" : "kartenausschnitt." + exportFormat
    }];

    if (requests.some(function (item) { return !item.url; })) {
      setDownloadStatus("Der Downloadlink konnte nicht erstellt werden.", "error");
      return;
    }

    state.ui.exportLoading = true;
    updateViewportIndicators(viewport);
    setDownloadStatus(
      isPdf ? "Das PDF-ZIP wird erstellt ..." : exportFormat.toUpperCase() + " wird erstellt ...",
      ""
    );

    Promise.all(requests.map(function (item) {
      return fetchExportArtifact(item.url, item.fallback);
    })).then(function (artifacts) {
      artifacts.forEach(saveExportArtifact);
      setDownloadStatus(
        isPdf ? "Das PDF-ZIP wurde heruntergeladen." : exportFormat.toUpperCase() + " wurde heruntergeladen.",
        ""
      );
    }).catch(function (err) {
      var message = err && err.message ? err.message : "unknown_error";
      setDownloadStatus("Download fehlgeschlagen: " + message, "error");
      setToast("danger", "Download", "Die Datei konnte nicht erstellt werden: " + message, 5200);
    }).finally(function () {
      state.ui.exportLoading = false;
      updateViewportIndicators();
    });
  }

  function openDownloadPanel() {
    if (!cfg.datasetExportEnabled || !state.activeDataset) { return; }
    closeDatasetPanel();
    closeEditorPanel();
    closeParcelSelectionPanel();
    state.ui.downloadPanelOpen = true;
    setHidden(dom.downloadPanel, false);
    setExpanded(dom.btnDownload, true);
    setDownloadStatus("", "");
    updateViewportIndicators();
  }

  function closeDownloadPanel() {
    state.ui.downloadPanelOpen = false;
    setHidden(dom.downloadPanel, true);
    setExpanded(dom.btnDownload, false);
  }

  function toggleDownloadPanel() {
    if (state.ui.downloadPanelOpen) { closeDownloadPanel(); }
    else { openDownloadPanel(); }
  }

  function openDatasetPanel() {
    closeDownloadPanel();
    closeEditorPanel();
    closeParcelSelectionPanel();
    state.ui.datasetPanelOpen = true;
    setHidden(dom.datasetPanel, false);
    setExpanded(dom.btnDatasets, true);
    loadDatasetsIntoPanel(false).catch(noop);
  }

  function closeDatasetPanel() {
    state.ui.datasetPanelOpen = false;
    setHidden(dom.datasetPanel, true);
    setExpanded(dom.btnDatasets, false);
  }

  function toggleDatasetPanel() {
    if (state.ui.datasetPanelOpen) { closeDatasetPanel(); }
    else { openDatasetPanel(); }
  }

  function openEditorPanel(openOnly) {
    if (openOnly) {
      closeDatasetPanel();
      closeDownloadPanel();
      closeParcelSelectionPanel();
    }
    state.ui.editorPanelOpen = !!openOnly;
    setHidden(dom.editorPanel, !openOnly);
    setExpanded(dom.btnEditor, !!openOnly);
  }

  function closeEditorPanel() {
    openEditorPanel(false);
  }

  function openParcelSelectionPanel() {
    if (cfg.parcelSelectionReadonly) { return; }
    closeDatasetPanel();
    closeDownloadPanel();
    closeEditorPanel();
    state.parcelSelection.panelOpen = true;
    setHidden(dom.parcelPanel, false);
    updateParcelSelectionUi();
  }

  function closeParcelSelectionPanel() {
    state.parcelSelection.panelOpen = false;
    setHidden(dom.parcelPanel, true);
    updateParcelSelectionUi();
  }

  function toggleParcelSelectionPanel() {
    if (state.parcelSelection.panelOpen) { closeParcelSelectionPanel(); }
    else { openParcelSelectionPanel(); }
  }

  function bindUiEvents() {
    if (dom.btnDatasets) {
      dom.btnDatasets.addEventListener("click", function () {
        toggleDatasetPanel();
      });
    }

    if (dom.btnParcels) {
      dom.btnParcels.addEventListener("click", toggleParcelSelectionPanel);
    }

    if (dom.parcelPanelClose) {
      dom.parcelPanelClose.addEventListener("click", closeParcelSelectionPanel);
    }

    toArray(dom.parcelModeButtons).forEach(function (button) {
      button.addEventListener("click", function () {
        state.parcelSelection.mode = asText(button.getAttribute("data-parcel-mode"), "add") === "remove" ? "remove" : "add";
        updateParcelSelectionUi();
      });
    });

    if (dom.parcelClear) {
      dom.parcelClear.addEventListener("click", function () {
        state.parcelSelection.byId = {};
        postParcelSelection();
      });
    }

    if (dom.datasetPanelClose) {
      dom.datasetPanelClose.addEventListener("click", function () {
        closeDatasetPanel();
      });
    }

    if (dom.btnEditor) {
      dom.btnEditor.addEventListener("click", function () {
        toggleEditor();
      });
    }

    if (dom.editorPanelClose) {
      dom.editorPanelClose.addEventListener("click", function () {
        closeEditorPanel();
      });
    }


    if (dom.btnDownload) {
      dom.btnDownload.addEventListener("click", function () {
        toggleDownloadPanel();
      });
    }

    if (dom.downloadPanelClose) {
      dom.downloadPanelClose.addEventListener("click", function () {
        closeDownloadPanel();
        closeParcelSelectionPanel();
      });
    }

    toArray(dom.downloadActions).forEach(function (button) {
      button.addEventListener("click", function () {
        runDatasetExport(asText(button.getAttribute("data-export-format"), ""));
      });
    });
    if (dom.btnZoomIn) {
      dom.btnZoomIn.addEventListener("click", function () {
        zoomBy(1);
      });
    }

    if (dom.btnZoomOut) {
      dom.btnZoomOut.addEventListener("click", function () {
        zoomBy(-1);
      });
    }

    document.addEventListener("keydown", function (event) {
      if (!event) { return; }
      if (event.key === "Escape") {
        closeDatasetPanel();
        closeEditorPanel();
        closeDownloadPanel();
      }
    });

    document.addEventListener("click", function (event) {
      try {
        var target = event && event.target ? event.target : null;
        if (!target || !dom.toolbarStack) { return; }
        if (dom.toolbarStack.contains(target)) { return; }
        closeDatasetPanel();
        closeEditorPanel();
        closeDownloadPanel();
      } catch (_) {}
    });

    updateEditorButtonState();
    updateViewportIndicators();
    updateParcelSelectionUi();
  }

  function syncToolbarVisibility() {
    try {
      if (!cfg.ui.showToolbar && dom.toolbarStack) {
        setHidden(dom.toolbarStack, true);
      }
      if (!cfg.ui.showDatasetButton && dom.btnDatasets) {
        setHidden(dom.btnDatasets, true);
      }
      if (!cfg.ui.showEditorButton && dom.btnEditor) {
        setHidden(dom.btnEditor, true);
      }
      if (!cfg.ui.showZoomButtons) {
        if (dom.btnZoomIn) { setHidden(dom.btnZoomIn, true); }
        if (dom.btnZoomOut) { setHidden(dom.btnZoomOut, true); }
      }
    } catch (_) {}
  }

  // ───────────────────────────────────────────────────────────
  // Bootstrap
  // ───────────────────────────────────────────────────────────

  function init() {
    bindDom();
    if (!cfg.initialDatasetPanelOpen) {
      closeDatasetPanel();
    }
    syncToolbarVisibility();
    syncInitialBanner();
    bindUiEvents();
    bindParcelSelectionBridge();
    updateDatasetPanelServiceState();

    if (!dom.map) {
      logError("[OpenLayer] #map fehlt im DOM");
      setToast("danger", "Initialisierung", "Der Kartencontainer fehlt im DOM.", 0);
      return;
    }

    logInfo("[OpenLayer] Bootstrap", {
      hasOL: hasOL(),
      hasOLE: hasOLE(),
      lon: cfg.lon,
      lat: cfg.lat,
      zoom: cfg.zoom,
      styleId: cfg.styleId,
      tokenUsable: cfg.tokenUsable,
      disableScroll: cfg.disableScroll,
      datasetApiEnabled: cfg.datasetApiEnabled,
      editorEnabled: cfg.editorEnabled,
      serverError: cfg.serverError,
      serverErrorMsg: cfg.serverErrorMsg || "",
      orchestratorConfigured: cfg.orchestratorConfigured,
      orchestratorClientAvailable: cfg.orchestratorClientAvailable,
      datasetIntegrationDegraded: cfg.datasetIntegrationDegraded,
      initialDatasetId: cfg.initialDatasetId || ""
    });

    if (cfg.serverError) {
      logWarn("[OpenLayer] Serverfehler:", cfg.serverErrorMsg || "(unbekannt)");
    }

    if (cfg.datasetApiEnabled && cfg.datasetIntegrationDegraded) {
      logWarn("[OpenLayer] Dataset-Integration ist degradiert:", cfg.serviceHealth);
    }

    ensureOL().then(function () {
      createMap();
      startActiveStyleRefresh();

      if (cfg.ui.showToolbar) {
        setToast("success", "Karte bereit", "Die Werkzeuge liegen rechts oben über der Kartenfläche.", 2000);
      }

      if (cfg.datasetApiEnabled) {
        // Loading the preferred parcel layer must not depend on whether the
        // catalogue drawer starts open.
        loadDatasetsIntoPanel(false).catch(noop);
        if (cfg.initialDatasetPanelOpen) {
          openDatasetPanel();
        }
      }
    }).catch(function (err) {
      logError("[OpenLayer] OpenLayers konnte nicht geladen werden:", err && err.message ? err.message : err);
      setBanner("danger", "OpenLayers konnte nicht geladen werden.", true);
      setToast("danger", "Initialisierung", "OpenLayers konnte nicht geladen werden.", 0);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
