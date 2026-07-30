# /services/openLayer/routes/datasets.py
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from flask import Blueprint, Response, current_app, jsonify, make_response, request, url_for

try:
    from settings import Settings, get_settings
except Exception:  # pragma: no cover
    from ..settings import Settings, get_settings  # type: ignore

try:
    from src.orchestrator.client import (
        GeoServerOrchestratorClient,
        OrchestratorClient,
    )
except Exception:  # pragma: no cover
    try:
        from ..src.orchestrator.client import (  # type: ignore
            GeoServerOrchestratorClient,
            OrchestratorClient,
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "routes.datasets konnte den Orchestrator-Client nicht importieren. "
            "Stelle sicher, dass 'src/orchestrator/client.py' vorhanden ist."
        ) from exc

try:
    from src.datasets.catalog_service import (
        OpenLayerDatasetCatalogError,
        OpenLayerDatasetNotFoundError,
        OpenLayerDatasetCatalogService,
        DatasetCatalogService,
    )
except Exception:  # pragma: no cover
    try:
        from ..src.datasets.catalog_service import (  # type: ignore
            OpenLayerDatasetCatalogError,
            OpenLayerDatasetNotFoundError,
            OpenLayerDatasetCatalogService,
            DatasetCatalogService,
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "routes.datasets konnte den DatasetCatalogService nicht importieren. "
            "Stelle sicher, dass 'src/datasets/catalog_service.py' vorhanden ist."
        ) from exc

try:
    from src.datasets.source_service import (
        OpenLayerDatasetSourceError,
        OpenLayerDatasetSourceUnavailableError,
        OpenLayerDatasetSourceService,
        DatasetSourceService,
    )
except Exception:  # pragma: no cover
    try:
        from ..src.datasets.source_service import (  # type: ignore
            OpenLayerDatasetSourceError,
            OpenLayerDatasetSourceUnavailableError,
            OpenLayerDatasetSourceService,
            DatasetSourceService,
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "routes.datasets konnte den DatasetSourceService nicht importieren. "
            "Stelle sicher, dass 'src/datasets/source_service.py' vorhanden ist."
        ) from exc

try:
    from src.styles.style_adapter import (
        OpenLayerStyleAdapterError,
        OpenLayerStyleAdapter,
        DatasetStyleAdapter,
    )
except Exception:  # pragma: no cover
    try:
        from ..src.styles.style_adapter import (  # type: ignore
            OpenLayerStyleAdapterError,
            OpenLayerStyleAdapter,
            DatasetStyleAdapter,
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "routes.datasets konnte den StyleAdapter nicht importieren. "
            "Stelle sicher, dass 'src/styles/style_adapter.py' vorhanden ist."
        ) from exc

try:
    from src.exports.export_service import (
        ExportUnavailableError,
        build_export_artifact,
        pdf_bbox_for_scale,
    )
except Exception:  # pragma: no cover
    try:
        from ..src.exports.export_service import (  # type: ignore
            ExportUnavailableError,
            build_export_artifact,
            pdf_bbox_for_scale,
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "routes.datasets could not import the export service."
        ) from exc


bp = Blueprint("datasets", __name__)

_TRUE_VALUES = frozenset({"1", "true", "t", "yes", "y", "on", "ja"})
_EARTH_RADIUS_METERS = 6_378_137.0
_MAX_DATASET_RADIUS_METERS = 400
_DEFAULT_DATASET_BATCH_SIZE = 100
_MAX_DATASET_BATCH_SIZE = 250
_FALSE_VALUES = frozenset({"0", "false", "f", "no", "n", "off", "nein"})

_GEOMETRY_MAP = {
    "point": "Point",
    "multipoint": "MultiPoint",
    "line": "LineString",
    "linestring": "LineString",
    "multiline": "MultiLineString",
    "multilinestring": "MultiLineString",
    "polygon": "Polygon",
    "multipolygon": "MultiPolygon",
    "geometry": "Geometry",
    "geometrycollection": "GeometryCollection",
}

_ORCHESTRATOR_CLIENT_EXTENSION_KEY = "openlayer_orchestrator_client"
_DATASET_CATALOG_SERVICE_EXTENSION_KEY = "openlayer_dataset_catalog_service"
_DATASET_SOURCE_SERVICE_EXTENSION_KEY = "openlayer_dataset_source_service"
_STYLE_ADAPTER_EXTENSION_KEY = "openlayer_style_adapter"

_SERVICE_INIT_SUMMARY_EXTENSION_KEY = "openlayer_service_init_summary"
_SERVICE_FAILURES_EXTENSION_KEY = "openlayer_service_failures"


# ─────────────────────────────────────────────────────────────
# Helper: Logging / Response / Settings
# ─────────────────────────────────────────────────────────────

def _settings() -> Settings:
    try:
        cached = current_app.extensions.get("openlayer_settings")
        if isinstance(cached, Settings):
            return cached
    except Exception:
        pass
    return get_settings()


def _ensure_extensions_dict() -> dict[str, Any]:
    try:
        extensions = getattr(current_app, "extensions", None)
        if isinstance(extensions, dict):
            return extensions
    except Exception:
        pass

    current_app.extensions = {}
    return current_app.extensions


def _log_info(message: str, *args: Any) -> None:
    try:
        current_app.logger.info(message, *args)
    except Exception:
        pass


def _log_warning(message: str, *args: Any) -> None:
    try:
        current_app.logger.warning(message, *args)
    except Exception:
        pass


def _log_exception(message: str, exc: Exception | None = None) -> None:
    try:
        if exc is None:
            current_app.logger.exception(message)
        else:
            current_app.logger.exception("%s: %s", message, exc.__class__.__name__)
    except Exception:
        pass


def _json(payload: Mapping[str, Any], code: int = 200) -> Response:
    response = make_response(jsonify(dict(payload)), int(code))
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers["Cache-Control"] = "no-store"
    return response


def _json_geojson(
    payload: Any,
    code: int = 200,
    *,
    extra_headers: Optional[Mapping[str, Any]] = None,
) -> Response:
    response = make_response(jsonify(payload), int(code))
    response.headers["Content-Type"] = "application/geo+json; charset=utf-8"
    response.headers["Cache-Control"] = "no-store"

    if isinstance(extra_headers, Mapping):
        for key, value in extra_headers.items():
            key_text = _safe_str(key, "").strip()
            value_text = _safe_str(value, "").strip()
            if not key_text or not value_text:
                continue
            response.headers[key_text] = value_text

    return response


def _json_error(
    code: int,
    message: str,
    *,
    detail: Any | None = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Response:
    payload: dict[str, Any] = {
        "status": "error",
        "message": str(message),
        "code": int(code),
    }

    if detail is not None:
        payload["detail"] = detail

    if isinstance(extra, Mapping):
        try:
            payload.update(dict(extra))
        except Exception:
            payload["extra_error"] = "extra_payload_invalid"

    return _json(payload, code)


# ─────────────────────────────────────────────────────────────
# Helper: Runtime-Service-Resolver
# ─────────────────────────────────────────────────────────────

def _service_init_diagnostics() -> dict[str, Any]:
    extensions = _ensure_extensions_dict()
    return {
        "service_init_summary": deepcopy(
            extensions.get(_SERVICE_INIT_SUMMARY_EXTENSION_KEY, {})
        ) if isinstance(extensions.get(_SERVICE_INIT_SUMMARY_EXTENSION_KEY), dict) else {},
        "service_failures": deepcopy(
            extensions.get(_SERVICE_FAILURES_EXTENSION_KEY, {})
        ) if isinstance(extensions.get(_SERVICE_FAILURES_EXTENSION_KEY), dict) else {},
    }


def _get_orchestrator_client() -> GeoServerOrchestratorClient:
    extensions = _ensure_extensions_dict()
    cached = extensions.get(_ORCHESTRATOR_CLIENT_EXTENSION_KEY)
    if isinstance(cached, GeoServerOrchestratorClient):
        return cached

    settings = _settings()
    client = OrchestratorClient(settings=settings)
    extensions[_ORCHESTRATOR_CLIENT_EXTENSION_KEY] = client
    return client


def _get_dataset_catalog_service() -> OpenLayerDatasetCatalogService:
    extensions = _ensure_extensions_dict()
    cached = extensions.get(_DATASET_CATALOG_SERVICE_EXTENSION_KEY)
    if isinstance(cached, OpenLayerDatasetCatalogService):
        return cached

    settings = _settings()
    orchestrator_client = _get_orchestrator_client()
    service = DatasetCatalogService(
        settings=settings,
        orchestrator_client=orchestrator_client,
    )
    extensions[_DATASET_CATALOG_SERVICE_EXTENSION_KEY] = service
    return service


def _get_dataset_source_service() -> OpenLayerDatasetSourceService:
    extensions = _ensure_extensions_dict()
    cached = extensions.get(_DATASET_SOURCE_SERVICE_EXTENSION_KEY)
    if isinstance(cached, OpenLayerDatasetSourceService):
        return cached

    settings = _settings()
    orchestrator_client = _get_orchestrator_client()
    catalog_service = _get_dataset_catalog_service()

    service = DatasetSourceService(
        settings=settings,
        orchestrator_client=orchestrator_client,
        catalog_service=catalog_service,
    )
    extensions[_DATASET_SOURCE_SERVICE_EXTENSION_KEY] = service
    return service


def _get_style_adapter() -> OpenLayerStyleAdapter:
    extensions = _ensure_extensions_dict()
    cached = extensions.get(_STYLE_ADAPTER_EXTENSION_KEY)
    if isinstance(cached, OpenLayerStyleAdapter):
        return cached

    settings = _settings()
    orchestrator_client = _get_orchestrator_client()
    catalog_service = _get_dataset_catalog_service()

    service = DatasetStyleAdapter(
        settings=settings,
        orchestrator_client=orchestrator_client,
        catalog_service=catalog_service,
    )
    extensions[_STYLE_ADAPTER_EXTENSION_KEY] = service
    return service


# ─────────────────────────────────────────────────────────────
# Helper: Parsing / Sanitizing
# ─────────────────────────────────────────────────────────────

def _safe_bool(value: Any, default: bool = False) -> bool:
    try:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value != 0
        if isinstance(value, float):
            return value != 0.0
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in _TRUE_VALUES:
                return True
            if normalized in _FALSE_VALUES:
                return False
        return bool(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return int(default)
        if isinstance(value, bool):
            return int(default)
        return int(str(value).strip())
    except Exception:
        return int(default)


def _safe_str(value: Any, default: str = "") -> str:
    try:
        if value is None:
            return default
        return str(value)
    except Exception:
        return default


def _parse_boolish(value: Any, default: bool | None = None) -> bool | None:
    if value is None:
        return default

    try:
        normalized = str(value).strip().lower()
    except Exception:
        return default

    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


def _query_bool(name: str, default: bool) -> bool:
    try:
        parsed = _parse_boolish(request.args.get(name), default)
        return default if parsed is None else parsed
    except Exception:
        return default


def _query_text(name: str, default: str = "") -> str:
    try:
        return _safe_str(request.args.get(name), default).strip()
    except Exception:
        return default


def _query_int(name: str, default: int) -> int:
    try:
        return _safe_int(request.args.get(name), default)
    except Exception:
        return default



def _query_float(name: str, default: float) -> float:
    try:
        value = float(request.args.get(name, default))
        return value if math.isfinite(value) else float(default)
    except Exception:
        return float(default)


def _query_bbox(*, required: bool = False) -> Optional[Tuple[float, float, float, float]]:
    raw_value = _query_text("bbox", "")
    if not raw_value:
        if required:
            raise ValueError("bbox query parameter is required")
        return None

    parts = [part.strip() for part in raw_value.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must contain minLon,minLat,maxLon,maxLat")
    try:
        values = tuple(float(part) for part in parts)
    except (TypeError, ValueError) as exc:
        raise ValueError("bbox contains invalid coordinates") from exc

    if not all(math.isfinite(value) for value in values):
        raise ValueError("bbox contains non-finite coordinates")
    if values[0] >= values[2] or values[1] >= values[3]:
        raise ValueError("bbox must contain minLon,minLat,maxLon,maxLat")
    if values[0] < -180 or values[2] > 180 or values[1] < -90 or values[3] > 90:
        raise ValueError("bbox must be inside EPSG:4326 bounds")
    return values
def _get_request_json_object(optional: bool = True) -> dict[str, Any]:
    try:
        data = request.get_json(silent=True)
    except Exception:
        data = None

    if data is None:
        if optional:
            return {}
        raise ValueError("request body must be a JSON object")

    if not isinstance(data, dict):
        raise ValueError("request body must be a JSON object")

    return data


def _normalize_geometry_type(value: Any, default: str = "Point") -> str:
    raw = _safe_str(value, "").strip()
    if not raw:
        return default

    normalized = raw.replace(" ", "").replace("-", "").lower()
    return _GEOMETRY_MAP.get(normalized, raw if raw else default)


# ─────────────────────────────────────────────────────────────
# Helper: Filtering / Payload Shaping
# ─────────────────────────────────────────────────────────────

def _matches_query(item: Mapping[str, Any], query: str) -> bool:
    if not query:
        return True

    try:
        haystack = " ".join(
            [
                _safe_str(item.get("id"), ""),
                _safe_str(item.get("title"), ""),
                _safe_str(item.get("description"), ""),
                _safe_str(item.get("geometry_type"), ""),
                _safe_str(_safe_mapping(item.get("source")).get("type"), ""),
                _safe_str(_safe_mapping(item.get("source")).get("format"), ""),
            ]
        ).lower()
        return query.lower() in haystack
    except Exception:
        return False


def _safe_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    try:
        return {str(k): v for k, v in value.items()}
    except Exception:
        return {}

def _configured_dataset_feature_limit() -> int:
    settings = _settings()
    return min(
        1000,
        max(1, _safe_int(getattr(settings, "dataset_feature_limit", 1000), 1000)),
    )



def _configured_dataset_radius_meters() -> int:
    settings = _settings()
    return min(
        _MAX_DATASET_RADIUS_METERS,
        max(1, _safe_int(getattr(settings, "dataset_radius_meters", 400), 400)),
    )


def _location_center(
    requested_bbox: Optional[Tuple[float, float, float, float]],
) -> Tuple[float, float]:
    raw_lon = _query_text("lon", "")
    raw_lat = _query_text("lat", "")
    if bool(raw_lon) != bool(raw_lat):
        raise ValueError("lon and lat query parameters must be provided together")

    if raw_lon and raw_lat:
        center_lon = float(raw_lon)
        center_lat = float(raw_lat)
    elif requested_bbox is not None:
        center_lon = (requested_bbox[0] + requested_bbox[2]) / 2.0
        center_lat = (requested_bbox[1] + requested_bbox[3]) / 2.0
    else:
        raise ValueError("lon and lat query parameters are required")

    if not math.isfinite(center_lon) or not math.isfinite(center_lat):
        raise ValueError("lon and lat must be finite")
    if center_lon < -180 or center_lon > 180 or center_lat < -90 or center_lat > 90:
        raise ValueError("lon and lat must be inside EPSG:4326 bounds")
    return center_lon, center_lat


def _bbox_for_location_radius(
    center: Tuple[float, float],
    radius_meters: int,
) -> Tuple[float, float, float, float]:
    center_lon, center_lat = center
    safe_radius = min(_MAX_DATASET_RADIUS_METERS, max(1, int(radius_meters)))
    latitude_delta = math.degrees(safe_radius / _EARTH_RADIUS_METERS)
    longitude_scale = max(0.000001, abs(math.cos(math.radians(center_lat))))
    longitude_delta = math.degrees(safe_radius / (_EARTH_RADIUS_METERS * longitude_scale))
    return (
        max(-180.0, center_lon - longitude_delta),
        max(-90.0, center_lat - latitude_delta),
        min(180.0, center_lon + longitude_delta),
        min(90.0, center_lat + latitude_delta),
    )


def _paginate_feature_collection(
    payload: Mapping[str, Any],
    *,
    offset: int,
    batch_size: int,
    feature_limit: int,
) -> Tuple[dict[str, Any], dict[str, Any]]:
    raw_features = payload.get("features")
    features = raw_features if isinstance(raw_features, list) else []
    safe_limit = min(1000, max(1, int(feature_limit)))
    safe_batch_size = min(
        _MAX_DATASET_BATCH_SIZE,
        max(1, int(batch_size)),
    )
    capped_features = features[:safe_limit]
    total_available = len(capped_features)
    safe_offset = min(safe_limit, max(0, int(offset)))
    page_end = min(total_available, safe_offset + safe_batch_size)
    page_features = deepcopy(capped_features[safe_offset:page_end])
    has_more = page_end < total_available

    page_payload = dict(payload)
    page_payload["type"] = "FeatureCollection"
    page_payload["features"] = page_features
    page_payload["numberReturned"] = len(page_features)

    return page_payload, {
        "offset": safe_offset,
        "batch_size": safe_batch_size,
        "returned": len(page_features),
        "total_available": total_available,
        "has_more": has_more,
        "next_offset": page_end if has_more else None,
    }



def _normalize_public_dataset_item(
    item: Mapping[str, Any],
    *,
    include_internal: bool,
) -> dict[str, Any]:
    raw = deepcopy(dict(item))

    dataset_id = _safe_str(raw.get("dataset_id"), "").strip() or _safe_str(raw.get("id"), "").strip()
    source = _safe_mapping(raw.get("source"))
    capabilities = _safe_mapping(raw.get("capabilities"))
    links = _safe_mapping(raw.get("links"))
    style = _safe_mapping(raw.get("style"))
    orchestrator = _safe_mapping(raw.get("orchestrator"))

    public_item: dict[str, Any] = {
        "id": dataset_id,
        "dataset_id": dataset_id,
        "title": _safe_str(raw.get("title"), "").strip(),
        "description": _safe_str(raw.get("description"), "").strip(),
        "active": _safe_bool(raw.get("active"), False),
        "status": _safe_str(raw.get("status"), "inactive").strip() or "inactive",
        "editable": _safe_bool(raw.get("editable"), False),
        "geometry_type": _normalize_geometry_type(raw.get("geometry_type"), default="Unknown"),
        "source": {
            "type": _safe_str(source.get("type"), "").strip(),
            "format": _safe_str(source.get("format"), "").strip(),
            "url": _safe_str(source.get("url"), "").strip(),
            "available": _safe_bool(source.get("available"), False),
            "max_features": _configured_dataset_feature_limit(),
        },
        "capabilities": {
            "read": _safe_bool(capabilities.get("read"), True),
            "create": _safe_bool(capabilities.get("create"), False),
            "update": _safe_bool(capabilities.get("update"), False),
            "delete": _safe_bool(capabilities.get("delete"), False),
        },
        "changes_url": _safe_str(links.get("changes"), "").strip()
        or _safe_url_for("datasets.dataset_changes", f"/api/datasets/{dataset_id}/changes", dataset_id=dataset_id),
        "links": {
            "self": _safe_str(links.get("self"), "").strip()
            or f"/api/datasets/{dataset_id}",
            "source": _safe_str(links.get("source"), "").strip()
            or _safe_url_for("datasets.dataset_source", f"/api/datasets/{dataset_id}/source", dataset_id=dataset_id),
            "changes": _safe_str(links.get("changes"), "").strip()
            or _safe_url_for("datasets.dataset_changes", f"/api/datasets/{dataset_id}/changes", dataset_id=dataset_id),
        },
        "style": {
            "available": _safe_bool(style.get("available"), False),
            "loaded": _safe_bool(style.get("loaded"), False),
            "valid": _safe_bool(style.get("valid"), False),
            "rule_count": _safe_int(style.get("rule_count"), 0),
            "geometry": _safe_str(style.get("geometry"), "").strip(),
            "orchestrator_url": _safe_str(style.get("orchestrator_url"), "").strip(),
            "warnings": list(style.get("warnings", [])) if isinstance(style.get("warnings"), list) else [],
            "errors": list(style.get("errors", [])) if isinstance(style.get("errors"), list) else [],
        },
        "warnings": list(raw.get("warnings", [])) if isinstance(raw.get("warnings"), list) else [],
        "errors": list(raw.get("errors", [])) if isinstance(raw.get("errors"), list) else [],
        "notes": list(raw.get("notes", [])) if isinstance(raw.get("notes"), list) else [],
        "published_known": _safe_bool(raw.get("published_known"), False),
        "sync_log_known": _safe_bool(raw.get("sync_log_known"), False),
        "overall_valid": _safe_bool(raw.get("overall_valid"), False),
        "catalog_source": _safe_str(raw.get("catalog_source"), "geoserver_orchestrator").strip()
        or "geoserver_orchestrator",
        "built_at": _safe_str(raw.get("built_at"), "").strip(),
    }

    if include_internal:
        public_item["orchestrator"] = deepcopy(orchestrator)
        public_item["source"]["direct_url"] = _safe_str(source.get("direct_url"), "").strip()
        public_item["source"]["orchestrator_wfs_url"] = _safe_str(source.get("orchestrator_wfs_url"), "").strip()
        public_item["source"]["orchestrator_capabilities_url"] = _safe_str(
            source.get("orchestrator_capabilities_url"), ""
        ).strip()
        public_item["source"]["orchestrator_describe_feature_type_url"] = _safe_str(
            source.get("orchestrator_describe_feature_type_url"), ""
        ).strip()
        if "payload" in style:
            public_item["style"]["payload"] = deepcopy(style.get("payload"))

    if "style_contract" in raw:
        public_item["style_contract"] = deepcopy(raw.get("style_contract"))

    return public_item


def _filter_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    include_inactive = _query_bool("include_inactive", False)
    editable_only = _query_bool("editable_only", False)
    geometry_type_filter_raw = _query_text("geometry_type", "")
    geometry_type_filter = (
        _normalize_geometry_type(geometry_type_filter_raw, default="")
        if geometry_type_filter_raw
        else ""
    )
    query = _query_text("q", "")

    result: list[dict[str, Any]] = []

    for item in items:
        try:
            if not include_inactive and not _safe_bool(item.get("active"), False):
                continue
            if editable_only and not _safe_bool(item.get("editable"), False):
                continue
            if geometry_type_filter and _safe_str(item.get("geometry_type"), "") != geometry_type_filter:
                continue
            if not _matches_query(item, query):
                continue
            result.append(item)
        except Exception:
            continue

    filters = {
        "include_inactive": include_inactive,
        "editable_only": editable_only,
        "geometry_type": geometry_type_filter,
        "q": query,
    }

    return result, filters


# ─────────────────────────────────────────────────────────────
# Helper: Change Payload (Platzhalter)
# ─────────────────────────────────────────────────────────────

def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _extract_change_summary(payload: dict[str, Any]) -> dict[str, Any]:
    created = _ensure_list(payload.get("created", payload.get("insert")))
    updated = _ensure_list(payload.get("updated", payload.get("update")))
    deleted = _ensure_list(payload.get("deleted", payload.get("delete")))

    feature_count = 0
    try:
        feature_count = len(created) + len(updated) + len(deleted)
    except Exception:
        feature_count = 0

    return {
        "created_count": len(created),
        "updated_count": len(updated),
        "deleted_count": len(deleted),
        "total_operations": feature_count,
    }


def _safe_url_for(endpoint: str, fallback: str, **values: Any) -> str:
    try:
        return str(url_for(endpoint, **values))
    except Exception:
        return fallback


# ─────────────────────────────────────────────────────────────
# Cache-Clear Helper
# ─────────────────────────────────────────────────────────────

def clear_dataset_catalog_cache() -> None:
    try:
        if _ensure_extensions_dict().get(_DATASET_CATALOG_SERVICE_EXTENSION_KEY):
            service = _get_dataset_catalog_service()
            clear_fn = getattr(service, "clear_caches", None)
            if callable(clear_fn):
                clear_fn()
    except Exception:
        pass


def clear_geojson_source_cache() -> None:
    try:
        if _ensure_extensions_dict().get(_DATASET_SOURCE_SERVICE_EXTENSION_KEY):
            service = _get_dataset_source_service()
            clear_fn = getattr(service, "clear_caches", None)
            if callable(clear_fn):
                clear_fn()
    except Exception:
        pass


def clear_style_adapter_cache() -> None:
    try:
        if _ensure_extensions_dict().get(_STYLE_ADAPTER_EXTENSION_KEY):
            service = _get_style_adapter()
            clear_fn = getattr(service, "clear_caches", None)
            if callable(clear_fn):
                clear_fn()
    except Exception:
        pass


def clear_datasets_route_caches() -> None:
    clear_dataset_catalog_cache()
    clear_geojson_source_cache()
    clear_style_adapter_cache()


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@bp.route("/api/datasets", methods=["GET", "HEAD"])
def list_datasets() -> Response:
    """
    Liefert die Datensatzliste für die Toolbar.

    Query-Parameter:
    - include_inactive=1|0
    - editable_only=1|0
    - geometry_type=Point|LineString|...
    - q=<freitext>
    - include_invalid=1|0
    - include_style_details=1|0
    - include_style_contract=1|0
    - include_style_payload=1|0
    - include_internal=1|0
    - enrich_with_db=1|0
    - refresh=1|0
    """
    try:
        settings = _settings()

        if not _safe_bool(getattr(settings, "dataset_api_enabled", False), False):
            payload = {
                "status": "not_available",
                "placeholder": True,
                "message": "dataset api disabled",
                "items": [],
                "count": 0,
                "diagnostics": _service_init_diagnostics(),
            }
            if request.method == "HEAD":
                return _json({"status": payload["status"]}, 503)
            return _json(payload, 503)

        include_invalid = _query_bool("include_invalid", False)
        include_style_details = _query_bool("include_style_details", False)
        include_style_contract = _query_bool("include_style_contract", False)
        include_style_payload = _query_bool("include_style_payload", False)
        include_internal = _query_bool("include_internal", False)
        enrich_with_db = _query_bool("enrich_with_db", False)
        refresh = _query_bool("refresh", False)

        use_cache = not refresh

        catalog_service = _get_dataset_catalog_service()
        raw_items = catalog_service.list_dataset_dicts(
            include_inactive=True,
            include_invalid=include_invalid,
            include_style_details=(include_style_details or include_style_contract or include_style_payload),
            enrich_with_db=enrich_with_db,
            include_internal=include_internal,
            include_style_payload=include_style_payload,
            use_cache=use_cache,
        )

        normalized_items = [
            _normalize_public_dataset_item(item, include_internal=include_internal)
            for item in raw_items
            if isinstance(item, Mapping)
        ]

        if include_style_contract:
            style_adapter = _get_style_adapter()
            for item in normalized_items:
                dataset_id = _safe_str(item.get("dataset_id"), "").strip()
                if not dataset_id:
                    continue

                try:
                    item["style_contract"] = style_adapter.get_dataset_style_dict(
                        dataset_id,
                        use_cache=use_cache,
                        include_rules=True,
                        include_raw_style=include_style_payload,
                        enrich_with_db=enrich_with_db,
                    )
                except OpenLayerStyleAdapterError as exc:
                    item.setdefault("warnings", [])
                    if isinstance(item["warnings"], list):
                        item["warnings"].append(
                            f"style_contract_not_available: {exc.__class__.__name__}"
                        )

        filtered_items, filters = _filter_items(normalized_items)

        payload = {
            "status": "ok",
            "placeholder": False,
            "catalog_source": "geoserver_orchestrator",
            "count": len(filtered_items),
            "total_count": len(normalized_items),
            "filters": filters,
            "include_invalid": include_invalid,
            "include_style_details": include_style_details,
            "include_style_contract": include_style_contract,
            "include_style_payload": include_style_payload,
            "include_internal": include_internal,
            "enrich_with_db": enrich_with_db,
            "refresh": refresh,
            "items": filtered_items,
            "notes": [],
        }

        try:
            summary_fn = getattr(catalog_service, "get_service_summary", None)
            if include_internal and callable(summary_fn):
                payload["service_summary"] = summary_fn()
        except Exception:
            pass

        if request.method == "HEAD":
            return _json(
                {
                    "status": payload["status"],
                    "count": payload["count"],
                    "total_count": payload["total_count"],
                },
                200,
            )

        return _json(payload, 200)

    except Exception as exc:
        _log_exception("list_datasets failed", exc)
        return _json(
            {
                "status": "error",
                "message": "datasets route failed",
                "detail": exc.__class__.__name__,
                "items": [],
                "count": 0,
                "diagnostics": _service_init_diagnostics(),
            },
            500,
        )


@bp.route("/api/datasets/<string:dataset_id>", methods=["GET", "HEAD"])
def dataset_detail(dataset_id: str) -> Response:
    """Liefert einen einzelnen Datensatz samt aktuellem OpenLayers-Style."""
    try:
        settings = _settings()
        if not _safe_bool(getattr(settings, "dataset_api_enabled", False), False):
            return _json_error(503, "dataset api disabled")

        include_style_contract = _query_bool("include_style_contract", True)
        include_style_payload = _query_bool("include_style_payload", False)
        include_internal = _query_bool("include_internal", False)
        enrich_with_db = _query_bool("enrich_with_db", False)
        refresh = _query_bool("refresh", False)
        use_cache = not refresh

        catalog_service = _get_dataset_catalog_service()
        raw_item = catalog_service.get_dataset_dict(
            dataset_id,
            include_style_details=True,
            enrich_with_db=enrich_with_db,
            include_internal=include_internal,
            include_style_payload=include_style_payload,
            use_cache=use_cache,
        )
        item = _normalize_public_dataset_item(raw_item, include_internal=include_internal)

        if include_style_contract:
            item["style_contract"] = _get_style_adapter().get_dataset_style_dict(
                dataset_id,
                use_cache=use_cache,
                include_rules=True,
                include_raw_style=include_style_payload,
                enrich_with_db=enrich_with_db,
            )

        item["refresh"] = refresh
        if request.method == "HEAD":
            return _json(
                {
                    "status": "ok",
                    "dataset_id": item.get("dataset_id", dataset_id),
                    "style_available": bool(item.get("style_contract")),
                },
                200,
            )
        return _json(item, 200)

    except OpenLayerDatasetNotFoundError:
        return _json_error(404, "dataset not found", extra={"dataset_id": dataset_id})
    except OpenLayerDatasetCatalogError as exc:
        status_code = int(getattr(exc, "status_code", 502) or 502)
        return _json_error(
            status_code,
            "dataset detail unavailable",
            detail=exc.__class__.__name__,
            extra={"dataset_id": dataset_id},
        )
    except OpenLayerStyleAdapterError as exc:
        status_code = int(getattr(exc, "status_code", 502) or 502)
        return _json_error(
            status_code,
            "dataset style unavailable",
            detail=exc.__class__.__name__,
            extra={"dataset_id": dataset_id},
        )
    except Exception as exc:
        _log_exception("dataset_detail failed", exc)
        return _json_error(
            500,
            "dataset detail route failed",
            detail=exc.__class__.__name__,
            extra={"dataset_id": dataset_id},
        )


@bp.route("/api/datasets/<string:dataset_id>/source", methods=["GET", "HEAD"])
def dataset_source(dataset_id: str) -> Response:
    """
    Liefert die Geometrie eines Datasets als serverseitig proxied GeoJSON.

    Wichtig:
    - OpenLayer lädt same-origin über diese API
    - die interne direkte WFS-URL bleibt im Backend
    - WFS-Antworten sind serverseitig auf ein sicheres Limit begrenzt
    """
    try:
        settings = _settings()

        if not _safe_bool(getattr(settings, "dataset_api_enabled", False), False):
            return _json(
                {
                    "status": "not_available",
                    "message": "dataset api disabled",
                    "dataset_id": dataset_id,
                },
                503,
            )

        refresh = _query_bool("refresh", False)
        use_cache = not refresh
        requested_bbox = _query_bbox(required=False)
        center = _location_center(requested_bbox)
        radius_meters = _configured_dataset_radius_meters()
        bbox = _bbox_for_location_radius(center, radius_meters)
        bbox_crs = "CRS:84"
        min_load_zoom = max(0, _safe_int(getattr(settings, "dataset_min_load_zoom", 14), 14))
        requested_zoom = _query_float("zoom", float(min_load_zoom))
        feature_limit = _configured_dataset_feature_limit()
        batch_size = min(
            _MAX_DATASET_BATCH_SIZE,
            max(1, _query_int("batch_size", _DEFAULT_DATASET_BATCH_SIZE)),
        )
        batch_offset = min(
            feature_limit, max(0, _query_int("offset", 0))
        )

        if requested_zoom < min_load_zoom:
            empty_payload = {
                "type": "FeatureCollection",
                "features": [],
                "numberReturned": 0,
            }
            if request.method == "HEAD":
                return _json(
                    {
                        "status": "zoom_too_low",
                        "dataset_id": dataset_id,
                        "feature_count": 0,
                        "feature_limit": feature_limit,
                        "min_load_zoom": min_load_zoom,
                        "batch_size": batch_size,
                        "offset": batch_offset,
                        "has_more": False,
                    },
                    200,
                )
            return _json_geojson(
                empty_payload,
                200,
                extra_headers={
                    "X-OpenLayer-Dataset-Id": dataset_id,
                    "X-OpenLayer-Feature-Count": "0",
                    "X-OpenLayer-Feature-Limit": str(feature_limit),
                    "X-OpenLayer-Center": ",".join(format(value, ".9g") for value in center),
                    "X-OpenLayer-Radius-Meters": str(radius_meters),
                    "X-OpenLayer-Bbox": ",".join(format(value, ".9g") for value in bbox),
                    "X-OpenLayer-Min-Load-Zoom": str(min_load_zoom),
                    "X-OpenLayer-Zoom-Too-Low": "true",
                    "X-OpenLayer-Batch-Offset": str(batch_offset),
                    "X-OpenLayer-Batch-Size": str(batch_size),
                    "X-OpenLayer-Total-Available": "0",
                    "X-OpenLayer-Has-More": "false",
                    "X-OpenLayer-Next-Offset": "",
                    "X-OpenLayer-Progressive": "true",
                },
            )

        source_service = _get_dataset_source_service()
        result = source_service.get_dataset_source(
            dataset_id,
            use_cache=use_cache,
            bbox=bbox,
            bbox_crs=bbox_crs,
            circle_center=center,
            circle_radius_m=radius_meters,
            feature_limit=feature_limit,
        )

        if not isinstance(result.payload, Mapping):
            return _json(
                {
                    "status": "error",
                    "message": "dataset source payload missing",
                    "dataset_id": result.dataset_id,
                    "detail": "payload_not_mapping",
                },
                500,
            )

        page_payload, paging = _paginate_feature_collection(
            result.payload,
            offset=batch_offset,
            batch_size=batch_size,
            feature_limit=feature_limit,
        )

        extra_headers = {
            "X-OpenLayer-Dataset-Id": result.dataset_id,
            "X-OpenLayer-Source-Provider": result.provider,
            "X-OpenLayer-Feature-Count": str(paging["returned"]),
            "X-OpenLayer-Feature-Limit": str(result.feature_limit or feature_limit),
            "X-OpenLayer-Trimmed": "true" if result.trimmed else "false",
            "X-OpenLayer-From-Cache": "true" if result.from_cache else "false",
            "X-OpenLayer-Stale-Cache": "true" if result.stale_cache_used else "false",
            "X-OpenLayer-Min-Load-Zoom": str(min_load_zoom),
            "X-OpenLayer-Zoom-Too-Low": "false",
            "X-OpenLayer-Center": ",".join(format(value, ".9g") for value in center),
            "X-OpenLayer-Radius-Meters": str(radius_meters),
            "X-OpenLayer-Bbox": ",".join(format(value, ".9g") for value in bbox or ()),
            "X-OpenLayer-Batch-Offset": str(paging["offset"]),
            "X-OpenLayer-Batch-Size": str(paging["batch_size"]),
            "X-OpenLayer-Total-Available": str(paging["total_available"]),
            "X-OpenLayer-Has-More": "true" if paging["has_more"] else "false",
            "X-OpenLayer-Next-Offset": "" if paging["next_offset"] is None else str(paging["next_offset"]),
            "X-OpenLayer-Progressive": "true",
        }

        if request.method == "HEAD":
            return _json(
                {
                    "status": "ok",
                    "dataset_id": result.dataset_id,
                    "feature_count": paging["returned"],
                    "total_available": paging["total_available"],
                    "feature_limit": result.feature_limit,
                    "batch_size": paging["batch_size"],
                    "offset": paging["offset"],
                    "next_offset": paging["next_offset"],
                    "has_more": paging["has_more"],
                    "center": center,
                    "radius_meters": radius_meters,
                    "trimmed": result.trimmed,
                },
                200,
            )

        return _json_geojson(
            page_payload,
            200,
            extra_headers=extra_headers,
        )

    except ValueError as exc:
        return _json_error(
            400,
            "invalid dataset source request",
            detail=str(exc),
            extra={"dataset_id": dataset_id},
        )

    except OpenLayerDatasetNotFoundError as exc:
        return _json(
            {
                "status": "error",
                "message": "dataset not found",
                "dataset_id": dataset_id,
                "detail": exc.__class__.__name__,
            },
            404,
        )

    except OpenLayerDatasetSourceUnavailableError as exc:
        return _json(
            {
                "status": "error",
                "message": "dataset source unavailable",
                "dataset_id": dataset_id,
                "detail": exc.__class__.__name__,
                "error": str(exc),
            },
            404,
        )

    except OpenLayerDatasetSourceError as exc:
        _log_exception("dataset_source failed with service error", exc)
        return _json(
            {
                "status": "error",
                "message": "dataset source route failed",
                "detail": exc.__class__.__name__,
                "dataset_id": dataset_id,
                "error": str(exc),
            },
            exc.status_code if isinstance(exc.status_code, int) and exc.status_code > 0 else 500,
        )

    except Exception as exc:
        _log_exception("dataset_source failed", exc)
        return _json(
            {
                "status": "error",
                "message": "dataset source route failed",
                "detail": exc.__class__.__name__,
                "dataset_id": dataset_id,
            },
            500,
        )



@bp.route("/api/datasets/<string:dataset_id>/export", methods=["GET"])
def dataset_export(dataset_id: str) -> Response:
    """Exports the selected dataset for the current map coordinate/viewport."""
    try:
        settings = _settings()
        if not _safe_bool(getattr(settings, "dataset_api_enabled", False), False):
            return _json_error(503, "dataset api disabled", extra={"dataset_id": dataset_id})
        if not _safe_bool(getattr(settings, "dataset_export_enabled", True), True):
            return _json_error(503, "dataset export disabled", extra={"dataset_id": dataset_id})

        export_format = _query_text("format", "").lower()
        if export_format not in {"dxf", "dwg", "pdf"}:
            raise ValueError("format must be dxf, dwg or pdf")

        min_load_zoom = max(0, _safe_int(getattr(settings, "dataset_min_load_zoom", 14), 14))
        requested_zoom = _query_float("zoom", float(min_load_zoom))
        if requested_zoom < min_load_zoom:
            raise ValueError(f"downloads require zoom level {min_load_zoom} or higher")

        center = _location_center(None)
        radius_meters = _configured_dataset_radius_meters()

        scale: Optional[int] = None
        if export_format == "pdf":
            scale = _query_int("scale", 0)
            if scale not in {100, 1000}:
                raise ValueError("PDF scale must be 100 or 1000")
            bbox = pdf_bbox_for_scale(center, scale)
        else:
            bbox = _bbox_for_location_radius(center, radius_meters)

        feature_limit = _configured_dataset_feature_limit()
        source_result = _get_dataset_source_service().get_dataset_source(
            dataset_id,
            use_cache=True,
            bbox=bbox,
            bbox_crs="CRS:84",
            circle_center=center,
            circle_radius_m=radius_meters,
            feature_limit=feature_limit,
        )
        if not isinstance(source_result.payload, Mapping):
            return _json_error(
                500,
                "dataset export source payload missing",
                extra={"dataset_id": dataset_id},
            )

        dataset = _get_dataset_catalog_service().get_dataset_dict(
            dataset_id,
            include_style_details=False,
            include_style_payload=False,
            include_internal=False,
            use_cache=True,
        )
        dataset_title = _safe_str(dataset.get("title"), "").strip() or dataset_id
        artifact = build_export_artifact(
            export_format=export_format,
            dataset_id=dataset_id,
            dataset_title=dataset_title,
            payload=source_result.payload,
            center=center,
            scale=scale,
            dwg_converter_command=_safe_str(
                getattr(settings, "dwg_converter_command", "dxf2dwg"),
                "dxf2dwg",
            ),
        )

        response = make_response(artifact.content, 200)
        response.headers["Content-Type"] = artifact.content_type
        response.headers["Content-Disposition"] = f'attachment; filename="{artifact.filename}"'
        response.headers["Content-Length"] = str(len(artifact.content))
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-OpenLayer-Dataset-Id"] = source_result.dataset_id
        response.headers["X-OpenLayer-Feature-Count"] = str(source_result.feature_count)
        response.headers["X-OpenLayer-Feature-Limit"] = str(source_result.feature_limit or feature_limit)
        response.headers["X-OpenLayer-Export-Format"] = export_format
        response.headers["X-OpenLayer-Center"] = ",".join(format(value, ".9g") for value in center)
        response.headers["X-OpenLayer-Radius-Meters"] = str(radius_meters)
        response.headers["X-OpenLayer-Bbox"] = ",".join(format(value, ".9g") for value in bbox or ())
        if scale is not None:
            response.headers["X-OpenLayer-Pdf-Scale"] = str(scale)
        return response

    except ValueError as exc:
        return _json_error(
            400,
            "invalid dataset export request",
            detail=str(exc),
            extra={"dataset_id": dataset_id},
        )
    except ExportUnavailableError as exc:
        return _json_error(
            503,
            "dataset export backend unavailable",
            detail=str(exc),
            extra={"dataset_id": dataset_id},
        )
    except OpenLayerDatasetNotFoundError:
        return _json_error(404, "dataset not found", extra={"dataset_id": dataset_id})
    except OpenLayerDatasetSourceUnavailableError as exc:
        return _json_error(
            404,
            "dataset source unavailable",
            detail=str(exc),
            extra={"dataset_id": dataset_id},
        )
    except OpenLayerDatasetSourceError as exc:
        status_code = exc.status_code if isinstance(exc.status_code, int) and exc.status_code > 0 else 500
        return _json_error(
            status_code,
            "dataset export source failed",
            detail=str(exc),
            extra={"dataset_id": dataset_id},
        )
    except Exception as exc:
        _log_exception("dataset_export failed", exc)
        return _json_error(
            500,
            "dataset export failed",
            detail=exc.__class__.__name__,
            extra={"dataset_id": dataset_id},
        )
@bp.route("/api/datasets/<string:dataset_id>/changes", methods=["POST"])
def dataset_changes(dataset_id: str) -> Response:
    """
    Platzhalter-Endpunkt für spätere Schreibvorgänge in Richtung
    GeoServer-Orchestrator.

    Aktueller Stand:
    - validiert minimal
    - prüft Dataset-Existenz über die neue Service-Schicht
    - fasst Operationen zusammen
    - persistiert nichts
    - antwortet mit 202 Accepted
    """
    try:
        settings = _settings()

        if not _safe_bool(getattr(settings, "dataset_api_enabled", False), False):
            return _json(
                {
                    "status": "not_available",
                    "message": "dataset api disabled",
                    "placeholder": True,
                    "dataset_id": dataset_id,
                },
                503,
            )

        catalog_service = _get_dataset_catalog_service()
        orchestrator_client = _get_orchestrator_client()

        dataset = catalog_service.get_dataset_dict(
            dataset_id,
            include_style_details=False,
            include_style_payload=False,
            include_internal=False,
            use_cache=True,
        )

        try:
            payload = _get_request_json_object(optional=True)
        except ValueError as exc:
            return _json(
                {
                    "status": "error",
                    "message": str(exc),
                    "dataset_id": dataset_id,
                },
                400,
            )

        summary = _extract_change_summary(payload)

        orchestrator_summary = {}
        try:
            orchestrator_summary = orchestrator_client.get_client_summary()
        except Exception:
            orchestrator_summary = {}

        response_payload = {
            "status": "accepted",
            "placeholder": True,
            "persisted": False,
            "dataset_id": _safe_str(dataset.get("dataset_id"), "").strip(),
            "dataset_title": _safe_str(dataset.get("title"), "").strip(),
            "editable": _safe_bool(dataset.get("editable"), False),
            "geometry_type": _safe_str(dataset.get("geometry_type"), "").strip(),
            "summary": summary,
            "orchestrator": {
                "configured": _safe_bool(orchestrator_summary.get("configured"), False),
                "base_url": _safe_str(orchestrator_summary.get("base_url"), "").strip(),
                "catalog_url": _safe_str(_safe_mapping(dataset.get("orchestrator")).get("catalog_url"), "").strip(),
                "style_url": _safe_str(_safe_mapping(dataset.get("orchestrator")).get("style_url"), "").strip(),
                "sync_url": _safe_str(_safe_mapping(dataset.get("orchestrator")).get("sync_url"), "").strip(),
            },
            "message": (
                "Änderungen wurden entgegengenommen, aber noch nicht persistiert. "
                "Die Weiterleitung an den GeoServer-Orchestrator folgt später."
            ),
        }

        _log_info(
            "dataset changes placeholder accepted for dataset_id=%s created=%s updated=%s deleted=%s",
            dataset_id,
            summary.get("created_count"),
            summary.get("updated_count"),
            summary.get("deleted_count"),
        )

        return _json(response_payload, 202)

    except OpenLayerDatasetNotFoundError:
        return _json(
            {
                "status": "error",
                "message": "dataset not found",
                "dataset_id": dataset_id,
            },
            404,
        )

    except OpenLayerDatasetCatalogError as exc:
        _log_exception("dataset_changes failed with catalog service error", exc)
        return _json(
            {
                "status": "error",
                "message": "dataset lookup failed",
                "dataset_id": dataset_id,
                "detail": exc.__class__.__name__,
                "error": str(exc),
            },
            exc.status_code if isinstance(exc.status_code, int) and exc.status_code > 0 else 500,
        )

    except Exception as exc:
        _log_exception("dataset_changes failed", exc)
        return _json(
            {
                "status": "error",
                "message": "dataset changes route failed",
                "detail": exc.__class__.__name__,
                "dataset_id": dataset_id,
            },
            500,
        )


__all__ = [
    "bp",
    "clear_dataset_catalog_cache",
    "clear_geojson_source_cache",
    "clear_style_adapter_cache",
    "clear_datasets_route_caches",
]