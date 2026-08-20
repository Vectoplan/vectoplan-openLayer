from pathlib import Path


ROOT = Path(__file__).parents[1]
MAIN_JS = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
MAP_HTML = (ROOT / "templates" / "map.html").read_text(encoding="utf-8")


def test_parcel_dataset_is_preferred_and_coordinate_parcel_is_auto_selected() -> None:
    assert "function datasetLooksLikeParcels" in MAIN_JS
    assert "var parcelDataset = list.find" in MAIN_JS
    assert "function autoSelectCoordinateParcel" in MAIN_JS
    assert "geometry.intersectsCoordinate(coordinate)" in MAIN_JS
    assert "geometry.getClosestPoint(coordinate)" in MAIN_JS
    assert "nearestTolerance" in MAIN_JS
    assert "loadDatasetsIntoPanel(false).catch(noop)" in MAIN_JS
    assert 'fill: new ol.style.Fill({ color: "rgba(15, 98, 254, 0.44)" })' in MAIN_JS


def test_parcels_toggle_and_sync_between_map_and_editor_bridge() -> None:
    assert "function handleParcelMapClick" in MAIN_JS
    assert "delete state.parcelSelection.byId[parcel.parcelId]" in MAIN_JS
    assert "directCandidates" in MAIN_JS
    assert "incomingRevision < state.parcelSelection.revision" in MAIN_JS
    assert 'type: "vectoplan-map:parcel-selection-changed"' in MAIN_JS
    assert 'type: "vectoplan-map:parcel-catalog-changed"' in MAIN_JS


def test_project_marker_is_draggable_and_publishes_new_coordinates() -> None:
    assert "function bindProjectLocationMarkerDrag" in MAIN_JS
    assert 'marker.addEventListener("pointerdown"' in MAIN_JS
    assert 'type: "vectoplan-map:project-coordinate-changed"' in MAIN_JS
    assert "projectCoordinateManualOverride: state.location.manualOverride" in MAIN_JS
    assert "{ manualOverride: true, localChange: true }" in MAIN_JS
    assert "pendingLocalCoordinate" in MAIN_JS
    assert "scheduleActiveDatasetReload({ immediate: true, force: true" in MAIN_JS


def test_parent_sync_restores_persisted_project_coordinate() -> None:
    assert "selection.projectCoordinate || selection.project_coordinate" in MAIN_JS
    assert "Number.isFinite(incomingLongitude) && Number.isFinite(incomingLatitude)" in MAIN_JS
    assert "notifyParent: false" in MAIN_JS
    assert "autoSelect: false" in MAIN_JS


def test_parent_sync_cannot_reset_an_active_or_unconfirmed_local_drag() -> None:
    assert "state.location.markerDragging" in MAIN_JS
    assert "pendingLocalCoordinateUntil" in MAIN_JS
    assert "coordinateSyncBlocked" in MAIN_JS
    assert "pendingMatchesIncoming" in MAIN_JS


def test_routine_dataset_loading_copy_is_not_rendered() -> None:
    assert "flurstuecke wird geladen" not in MAP_HTML.lower()
    assert "datensatz wird geladen" not in MAP_HTML.lower()
    assert "dataset-panel-loading" not in MAP_HTML
    assert '"Datensatz aktiv"' not in MAIN_JS
