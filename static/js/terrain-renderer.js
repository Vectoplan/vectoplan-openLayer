/* Browser texture bridge: the same OpenLayers basemap as /map, no world writes. */
(async function () {
  "use strict";
  var contract = "vectoplan-terrain-map.v1";
  var parentOrigin;
  try { parentOrigin = new URL(document.referrer).origin; } catch (_) { return; }
  if (window.parent === window || !/^https?:/.test(parentOrigin)) { return; }
  function send(payload, transfers) {
    window.parent.postMessage(Object.assign({ contract: contract }, payload), parentOrigin, transfers || []);
  }
  async function loadLibrary(name, version, file, ready) {
    if (ready()) { return; }
    for (var host of ["https://cdn.jsdelivr.net/npm/", "https://unpkg.com/"]) {
      try {
        await new Promise(function (resolve, reject) {
          var script = document.createElement("script");
          var timeout = setTimeout(function () { script.remove(); reject(new Error("library timeout")); }, 5000);
          script.src = host + name + "@" + version + "/" + file;
          script.onload = function () { clearTimeout(timeout); ready() ? resolve() : reject(new Error("library missing")); };
          script.onerror = function () { clearTimeout(timeout); script.remove(); reject(new Error("library unavailable")); };
          document.head.appendChild(script);
        });
        return;
      } catch (_) {}
    }
    throw new Error("Map renderer unavailable");
  }
  try {
    await loadLibrary("ol", "10.6.1", "dist/ol.js", function () { return !!window.ol; });
    var basemap = window.VectoplanBasemap;
    var map = new ol.Map({ target: "map", controls: [], interactions: [], pixelRatio: 1,
      layers: [], view: new ol.View({ center: [0, 0], zoom: 19, maxZoom: 22 }) });
    map.setSize([768, 768]);
    var layers, revision = 0, queue = [], active = null, disposed = false;
    // A 2x2 metatile has a 128px label gutter on the existing 768px renderer.
    // Neighbouring CAD/3D requests share one render, including source decoding.
    var tiles = new Map();
    function tileKey(job) { return job.z + '/' + job.x + '/' + job.y; }
    function sendTile(job, pixels) {
      var copy=pixels.slice(0); // postMessage transfers ownership, retain cache.
      send(Object.assign({type:'tile',id:job.id,width:256,height:256,pixels:copy},status()),[copy]);
    }
    function status() { return { designId: layers.designId, provider: layers.provider, revision: revision }; }
    function cancel() {
      if (active) { active.finish("stale"); }
      queue.splice(0).forEach(function (job) { send({ type: "tile-error", id: job.id }); });
    }
    function announce() {
      if (disposed) { return; }
      revision++;
      tiles.clear();
      cancel();
      send(Object.assign({ type: "state" }, status()));
    }
    function applyDesign() {
      var design = basemap.readPreference();
      if (layers && layers.designId === design) { return; }
      if (layers) { layers.dispose(); }
      layers = basemap.create(window.TERRAIN_BASEMAP_CONFIG, design, function () {
        // create() announces synchronously, before its return value is assigned.
        queueMicrotask(announce);
      }, function () {
        return loadLibrary("ol-mapbox-style", "12.4.0", "dist/olms.js", function () { return !!window.olms; });
      });
      map.setLayers([layers.mapbox, layers.openfreemap, layers.osm].filter(Boolean));
    }
    function renderTiles(job) {
      var canvas = document.createElement("canvas"); canvas.width = canvas.height = 768;
      var ctx = canvas.getContext("2d");
      ctx.fillStyle = layers.designId === "dark" ? "#101010" : "#ffffff";
      ctx.fillRect(0, 0, 768, 768);
      map.getViewport().querySelectorAll(".ol-layer canvas").forEach(function (source) {
        if (!source.width || !source.height) { return; }
        ctx.save();
        var opacity = source.parentNode.style.opacity || source.style.opacity;
        ctx.globalAlpha = opacity === "" ? 1 : Number(opacity);
        var transform = source.style.transform;
        if (transform) {
          var matrix = transform.match(/^matrix\(([^)]+)\)$/);
          if (matrix) { ctx.transform.apply(ctx, matrix[1].split(",").map(Number)); }
        }
        var background = source.parentNode.style.backgroundColor;
        if (background) { ctx.fillStyle = background; ctx.fillRect(0, 0, source.width, source.height); }
        ctx.drawImage(source, 0, 0); ctx.restore();
      });
      var span=Math.min(2,Math.pow(2,job.z)),left=Math.floor(job.x/2)*2,top=Math.floor(job.y/2)*2;
      var gutter=(768-span*256)/2;
      for(var x=0;x<span;x++) for(var y=0;y<span;y++) {
        var key=tileKey({z:job.z,x:left+x,y:top+y});
        tiles.delete(key);
        tiles.set(key,ctx.getImageData(gutter+x*256,gutter+y*256,256,256).data.buffer);
      }
      while(tiles.size>128) tiles.delete(tiles.keys().next().value);
    }
    function pump() {
      if (disposed || active || !queue.length) { return; }
      var job = queue.shift(), currentRevision = revision, done = false;
      var cached=tiles.get(tileKey(job));
      if(cached) { tiles.delete(tileKey(job));tiles.set(tileKey(job),cached);sendTile(job,cached);queueMicrotask(pump);return; }
      var timeout, tick;
      function finish(error) {
        if (done) { return; } done = true;
        clearTimeout(timeout); clearInterval(tick); map.un("rendercomplete", complete);
        active = null;
        if (error) { send({ type: "tile-error", id: job.id }); }
        queueMicrotask(pump);
      }
      function complete() {
        if (layers.styleLoading || revision !== currentRevision || done) { return; }
        try {
          renderTiles(job);
          sendTile(job,tiles.get(tileKey(job)));
          finish();
        } catch (_) { finish("render-failed"); }
      }
      active = { id: job.id, finish: finish };
      var n = Math.pow(2, job.z);
      var span=Math.min(2,n);
      var lon = (Math.floor(job.x/2)*2 + span/2) / n * 360 - 180;
      var lat = Math.atan(Math.sinh(Math.PI * (1 - 2 * (Math.floor(job.y/2)*2 + span/2) / n))) * 180 / Math.PI;
      map.getView().setCenter(ol.proj.fromLonLat([lon, lat]));
      map.getView().setZoom(job.z);
      map.on("rendercomplete", complete);
      timeout = setTimeout(function () { finish("timeout"); }, 35000);
      // Hidden cross-origin frames may throttle requestAnimationFrame. Drive
      // only an active export explicitly; idle maps consume no render loop.
      tick = setInterval(function () { map.renderSync(); }, 50);
      map.renderSync();
    }
    window.addEventListener("message", function (event) {
      if (event.source !== window.parent || event.origin !== parentOrigin || event.data?.contract !== contract) { return; }
      var data = event.data;
      if (data.type === "state-request") { send(Object.assign({ type: "state" }, status())); return; }
      if (data.type === "tile-cancel" && Number.isSafeInteger(data.id)) {
        queue = queue.filter(function (job) { return job.id !== data.id; });
        if (active && active.id === data.id) { active.finish("cancelled"); }
        return;
      }
      if (data.type !== "tile" || !Number.isSafeInteger(data.id) || !Number.isInteger(data.z)
        || data.z < 0 || data.z > 19 || !Number.isInteger(data.x) || !Number.isInteger(data.y)
        || data.x < 0 || data.y < 0 || data.x >= Math.pow(2, data.z) || data.y >= Math.pow(2, data.z)) { return; }
      if (queue.length >= 8 || data.revision !== revision) { send({ type: "tile-error", id: data.id }); return; }
      queue.push(data); pump();
    });
    window.addEventListener("storage", function (event) { if (event.key === basemap.storageKey || event.key === null) { applyDesign(); } });
    window.addEventListener("pagehide", function () { disposed = true; cancel(); layers.dispose(); map.dispose(); });
    applyDesign();
  } catch (_) { send({ type: "unavailable" }); }
})();
