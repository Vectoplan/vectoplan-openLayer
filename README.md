# vectoplan-openLayer

`vectoplan-openLayer` ist die Karten- und Geodatenoberfläche des
Projekt-Workspaces. Neben dem viewportbegrenzten Laden verwaltet sie die
interaktive Flurstücksauswahl und die Projektkoordinate. Der serviceübergreifende
Vertrag ist unter
[`../vectoplan-editor/docs/PARCEL_GRID_AND_WORLDEDIT.md`](../vectoplan-editor/docs/PARCEL_GRID_AND_WORLDEDIT.md)
dokumentiert.

## Flurstücksauswahl und Projektkoordinate

- Ist `flurstuecke` vorhanden, wird dieser Datensatz beim Öffnen bevorzugt.
- Das Polygon an der Projektkoordinate wird nach dem Laden automatisch
  ausgewählt und kräftiger blau dargestellt.
- Ein Klick auf ein Flurstück schaltet seine Auswahl ein oder aus.
- Die Auswahl hat keinen eigenen Menüpunkt. Sie wird auf einer separaten,
  synchronisierten Kartenebene angezeigt und bleibt beim Wechsel von
  Kartendesign oder Geodatensatz sichtbar.
- Im bearbeitbaren Projektmodus kann der Marker gezogen werden. Die neue
  Koordinate löst einen Datensatz-Reload und eine erneute Koordinatenauswahl aus.
- Auswahl und Katalog werden mit monotoner Revision an den Workspace-Bridge
  veröffentlicht; Map und WorldEdit-Flurstückswerkzeug bearbeiten denselben
  Zustand.
- Im Readonly-/öffentlichen Modus bleibt der Marker sichtbar, aber nicht
  verschiebbar.
- Routinemeldungen wie „Datensatz wird geladen“ oder „flurstuecke wird geladen“
  werden nicht als Toast oder Panel eingeblendet.

Browserverträge:

```text
vectoplan-map:parcel-catalog-changed
vectoplan-map:parcel-selection-changed
vectoplan-map:parcel-selection-request
vectoplan-map:project-coordinate-changed
```

## Basiskarte

Mapbox (`mapbox/light-v11` bzw. `mapbox/dark-v11`) bleibt der bevorzugte Anbieter. Ohne gültigen Token,
bei Kachelfehlern oder nach 12 Sekunden ohne Ladefortschritt wird automatisch
OpenFreeMap mit dem passenden Stil **Positron** bzw. **Dark** geladen. Falls dessen Renderer,
Stil oder Kacheln nicht erreichbar sind, bleibt OSM als letzter Fallback.
Die Umschaltung und der Kartenstart erzeugen keine Banner, Toasts oder
Bestätigungen; technische Fehler stehen nur in der Browserkonsole.

Der Renderer `ol-mapbox-style@12.4.0` wird erst im Fallback-Fall geladen und
ist mit dem vorhandenen OpenLayers 10.6.1 kompatibel. Stil, Sprites und Kacheln
kommen direkt von `https://tiles.openfreemap.org/styles/positron`; es ist kein
API-Schlüssel und kein eigenes Hosting der Kartendaten erforderlich.
[OpenFreeMap](https://openfreemap.org/) erlaubt kostenlose kommerzielle Nutzung
ohne Anfragekontingent, bietet aber keine Verfügbarkeitsgarantie. Die nötigen
Quellenangaben für OpenFreeMap/OpenMapTiles/OpenStreetMap stehen in der Karte.
Die vorhandenen Geometrie-Exporte enthalten keine Hintergrundkarte; wird diese
später mitgedruckt, müssen die Quellenangaben auch im Export erscheinen.

Fallback-Verhalten testen: `node --test tests/base_layers.test.cjs`.

## Kartendesign und Navigationsgrenzen

Der Menüpunkt **Kartendesign** bietet genau zwei rechteckige, textfreie
Vorschaubilder: **Hell** und **Dunkel**. Mapbox, OpenFreeMap und OSM sind
automatische Anbieter/Fallbacks und haben keine eigenen Menüeinträge.
Die Quellenangaben der Vorschauen und der Karte stehen gemeinsam einmal
unten an der Karte. Frühere Designpräferenzen werden Hell bzw. Dunkel zugeordnet.
Die Schaltflächen haben zugängliche Namen und eine sichtbare
Auswahlmarkierung. Die Wahl wird im Browser gespeichert. Beim Wechsel bleiben
Kamera, Projektkoordinate und Grundstücksauswahl erhalten; veraltete
Ladevorgänge können ein inzwischen gewähltes Design nicht überschreiben.

Die OpenLayers-View begrenzt den **gesamten sichtbaren Kartenausschnitt** auf
ein Rechteck von ±400 m um die Projektkoordinate (bei kleiner konfiguriertem
Radius entsprechend weniger). Der kleinste erlaubte Zoom ergibt sich aus
Rechteck, Fenstergröße und Drehung. Die Grenzen gelten auch während Gesten und
Animationen sowie für URL-Zoomwerte, `fit()`, Größenänderungen und Designwechsel.
Eine Änderung der Projektkoordinate erstellt die View mit den neuen Grenzen;
Zoom und Drehung werden soweit innerhalb der Grenzen möglich übernommen.
Die Geodaten- und Exportgrenze bleibt der bisherige Kreis mit 400 m Radius.

Browserprüfung mit einer isolierten Oberfläche ohne Projektzugriffe:

```sh
docker run --rm -p 127.0.0.1:5191:8090 -e PYTHONPATH=/service \
  --entrypoint python vectoplan-server-openlayer /service/tests/browser_preview.py
# In einem zweiten Terminal, mit installiertem Playwright/Chromium:
node tests/browser_map_controls.cjs
```

`MAP_TEST_URL`, `MAP_TEST_OUTPUT` und `PLAYWRIGHT_CHANNEL` können Testadresse,
Screenshot-Verzeichnis und Browserkanal überschreiben. Die Prüfung umfasst
Designwechsel, gespeicherte Auswahl, Navigationsgrenzen, Kartenklicks und
Editor-Synchronisation. Die Vorschau ist nur für lokale Tests vorgesehen.

## Gemeinsame Kartendarstellung im 3D-Editor

`static/js/basemap.js` stellt dieselbe Hell-/Dunkel-Auswahl und Fallback-Reihenfolge
für `/map` und `/map/terrain` bereit. Der Editor bindet die zweite Route als
unsichtbaren Renderer ein. Sie nutzt die vorhandene Browser-Präferenz und übernimmt
Änderungen aus der 2D-Auswahl sofort. Bei einem Anbieterwechsel werden alte
Kartentexturen verworfen; verspätete Antworten werden ignoriert.

Der Renderer zeichnet OpenFreeMap mit OpenLayers und ol-mapbox-style, wie in der
[OpenFreeMap-Anleitung](https://openfreemap.org/quick_start/) beschrieben. Er liefert
nur gerenderte Pixel an den Editor, lädt keine Projekt-/Flurstücksdaten und speichert
keine Kacheln auf dem Server. `OPENLAYER_PUBLIC_URL` muss bei App und Editor dieselbe
öffentliche Service-Adresse verwenden. Der Ursprung und das absendende Fenster
werden bei jeder Nachricht geprüft; Anfragen sind begrenzt und haben Zeitlimits.

Die Ende-zu-Ende-Prüfung liegt im Editor unter `tests/browser_terrain_map.cjs` und
verwendet diese lokale `tests/browser_preview.py`-Oberfläche.

## Viewport loading and downloads

Only the currently selected dataset is requested. Geometry requests always contain the
WGS84 bounding box for a fixed 400 m radius around the project coordinate and are capped
at 1,000 features. The API also removes geometry outside the actual circle.
Large results are transferred to the browser and rendered progressively in batches of
100 features, while the overall hard limit remains 1,000 features.

The project coordinate is the reference for navigation and downloads. In an
editable project it can be moved with the map marker:

- A visible, draggable map pin marks the current project coordinate.
- The full map viewport is constrained to a rectangle extending 400 m from
  the project coordinate in each direction.
- DXF and DWG contain the selected dataset inside the 400 m radius.
- PDF creates two separate A4 downloads at 1:100 and 1:1000.
- DWG files are generated by GNU LibreDWG `dxf2dwg`; the Docker image builds and
  installs the converter.

Relevant environment variables:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `DATASET_MIN_LOAD_ZOOM` | `14` | First zoom level at which geometry is loaded |
| `DATASET_WFS_FEATURE_LIMIT` | `1000` | Feature limit, hard-capped at 1000 |
| `DATASET_EXPORT_ENABLED` | `true` | Enables the download panel and export API |
| `DATASET_RADIUS_METERS` | `400` | Project radius, hard-capped at 400 m |
| `OPENLAYER_DWG_CONVERTER` | `dxf2dwg` | Path or command used for real DWG conversion |

Run the checks in the production-like container:

```sh
docker build -t vectoplan-openlayer .
docker run --rm --entrypoint python vectoplan-openlayer -m unittest discover -s tests -v
```
