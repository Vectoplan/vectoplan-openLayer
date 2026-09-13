/* Shared 2D/3D basemap policy. No parcel or world state lives here. */
(function () {
  "use strict";
  var MAP_DESIGNS = ["light", "dark"];
  var OPENFREEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
  var BASEMAP_TIMEOUT_MS = 12000;
  function logWarn() { console.warn.apply(console, arguments); }
  function logError() { console.error.apply(console, arguments); }
  async function loadStyle(url) {
    if (!url.startsWith("/api/map/projects/")) return url;
    for (var attempt = 0; attempt < 5; attempt++) {
      var response = await fetch(url);
      if (response.ok) {
        var style = await response.json();
        function absolute(value) { return value && value.startsWith("/") ? window.location.origin + value : value; }
        style.sprite = absolute(style.sprite); style.glyphs = absolute(style.glyphs);
        Object.values(style.sources).forEach(function (source) {
          if (source.url) source.url = absolute(source.url);
          if (source.tiles) source.tiles = source.tiles.map(absolute);
        });
        return style;
      }
      if (response.status !== 503 || attempt === 4) throw new Error("Project map storage unavailable");
      await new Promise(function (resolve) { setTimeout(resolve, 3000); });
    }
  }
  var OPENFREEMAP_ATTRIBUTION = '<a href="https://openfreemap.org/" target="_blank" rel="noopener">OpenFreeMap</a> '
    + '<a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">© OpenMapTiles</a> '
    + 'Data from <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>';
  var MAP_DESIGN_STORAGE_KEY = "vectoplan-openlayer:map-design";
  function createBaseLayers(cfg, designId, onDesignChange, ensureMapStyleRenderer) {
    designId = MAP_DESIGNS.indexOf(designId) !== -1 ? designId : "light";
    var baseLayers = { mapbox: null, openfreemap: null, osm: null, provider: null };
    baseLayers.designId = designId;
    baseLayers.styleLoading = false;
    var loadTimer = null;
    var fallbackStarted = false;
    var pendingLoads = 0;

    function clearLoadTimer() {
      if (loadTimer !== null) { clearTimeout(loadTimer); }
      loadTimer = null;
    }

    function activate(provider) {
      clearLoadTimer();
      baseLayers.provider = provider;
      pendingLoads = 0;
      baseLayers.styleLoading = provider === "openfreemap";
      baseLayers.designId = designId;
      ["mapbox", "openfreemap", "osm"].forEach(function (name) {
        if (baseLayers[name]) { baseLayers[name].setVisible(name === provider); }
      });
      if (typeof onDesignChange === "function") { onDesignChange(baseLayers.designId); }
    }

    function useOsm() {
      if (baseLayers.provider !== "openfreemap") { return; }
      logWarn("[OpenLayer] OpenFreeMap unavailable; using OSM");
      activate("osm");
    }

    function watchLoadTimeout(provider, onFailure) {
      if (loadTimer !== null || baseLayers.provider !== provider) { return; }
      loadTimer = setTimeout(function () {
        loadTimer = null;
        if (baseLayers.provider === provider) { onFailure(); }
      }, cfg.projectPublicId && baseLayers.styleLoading ? 60000 : BASEMAP_TIMEOUT_MS);
    }

    function watchSource(source, provider, onFailure) {
      source.on("tileloadstart", function () {
        if (baseLayers.provider !== provider) { return; }
        pendingLoads++;
        watchLoadTimeout(provider, onFailure);
      });
      source.on("tileloadend", function () {
        if (baseLayers.provider !== provider) { return; }
        pendingLoads = Math.max(0, pendingLoads - 1);
        clearLoadTimer();
        // A completed neighbour must not mask another request that is stuck.
        if (pendingLoads) { watchLoadTimeout(provider, onFailure); }
      });
      source.on("tileloaderror", function () {
        if (baseLayers.provider === provider) { onFailure(); }
      });
    }

    function useOpenFreeMap() {
      if (fallbackStarted) { return; }
      fallbackStarted = true;
      activate("openfreemap");
      watchLoadTimeout("openfreemap", useOsm);
      // OpenFreeMap is the design provider, regardless of legacy Mapbox tokens.
      Promise.resolve().then(function () {
        return ensureMapStyleRenderer();
      }).then(function () {
        if (baseLayers.provider !== "openfreemap") { return; }
        var group = new ol.layer.Group({ visible: false });
        group.set("layerRole", "base-openfreemap");
        baseLayers.openfreemap.getLayers().push(group);
        var styleUrl = designId === "light" ? OPENFREEMAP_STYLE_URL : "https://tiles.openfreemap.org/styles/" + designId;
        var projectId = cfg.projectPublicId;
        if (projectId && /^[A-Za-z0-9_-]{1,160}$/.test(projectId)) {
          styleUrl = "/api/map/projects/" + encodeURIComponent(projectId) + "/style/" + designId;
        }
        return loadStyle(styleUrl).then(function (style) {
          return window.olms.apply(group, style);
        }).then(function () {
          if (baseLayers.provider !== "openfreemap") { return; }
          var sources = [];
          group.getLayers().forEach(function (layer) {
            var source = typeof layer.getSource === "function" ? layer.getSource() : null;
            if (!source || sources.indexOf(source) !== -1) { return; }
            sources.push(source);
            source.setAttributions(OPENFREEMAP_ATTRIBUTION);
            watchSource(source, "openfreemap", useOsm);
          });
          baseLayers.styleLoading = false;
          group.setVisible(true);
        });
      }).catch(function (err) {
        logWarn("[OpenLayer] OpenFreeMap init failed:", err && err.message ? err.message : err);
        useOsm();
      });
    }

    try {
      baseLayers.osm = new ol.layer.Tile({
        source: new ol.source.OSM({ attributions: OPENFREEMAP_ATTRIBUTION }),
        visible: false
      });
      baseLayers.osm.set("layerRole", "base-osm");
    } catch (e1) {
      logError("[OpenLayer] OSM layer create failed:", e1 && e1.message ? e1.message : e1);
    }
    baseLayers.openfreemap = new ol.layer.Group({ visible: false });
    baseLayers.openfreemap.set("layerRole", "base-openfreemap");

    useOpenFreeMap();

    baseLayers.dispose = function () {
      clearLoadTimer();
      baseLayers.provider = null;
      fallbackStarted = true;
    };
    return baseLayers;
  }

  function readPreference() {
    var saved;
    try { saved = window.localStorage.getItem(MAP_DESIGN_STORAGE_KEY); } catch (_) {}
    return saved === "dark" || saved === "fiord" ? "dark" : "light";
  }
  window.VectoplanBasemap = { create: createBaseLayers, readPreference: readPreference,
    storageKey: MAP_DESIGN_STORAGE_KEY, designs: MAP_DESIGNS, attribution: OPENFREEMAP_ATTRIBUTION };
})();
