(function () {
  "use strict";
  var identity = window.OPENLAYER_CONFIG?.projectPublicId;
  var node = document.getElementById("map-cache-status");
  if (!identity || !node) return;
  var stopped = false, timer;
  async function update() {
    if (stopped) return;
    var complete = false;
    try {
      var response = await fetch("/api/map/projects/" + encodeURIComponent(identity) + "/status");
      if (!response.ok) throw new Error("status unavailable");
      var status = await response.json();
      node.hidden = false;
      node.dataset.state = status.state;
      complete = status.state === "ready";
      node.textContent = complete ? "Projektkarte gespeichert · alle Zoomstufen verfügbar"
        : status.failed ? "Projektkarte: " + status.ready + "/" + status.total + " gespeichert · fehlende Daten werden erneut geladen"
        : status.total ? "Projektkarte wird gespeichert · " + status.ready + "/" + status.total
        : "Projektkarte wird vorbereitet …";
    } catch (_) {
      node.hidden = false; node.textContent = "Kartenspeicher momentan nicht erreichbar";
    }
    if (!stopped && !complete) timer = setTimeout(update, 5000);
  }
  window.addEventListener("pagehide", function () { stopped = true; clearTimeout(timer); });
  update();
})();
