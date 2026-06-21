# /services/vectoplan-openLayer/routes/map.py
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Mapping, Optional
from urllib.parse import urlencode

from flask import Blueprint, Response, current_app, make_response, render_template, request

try:
    from settings import Settings, get_settings
except Exception:  # pragma: no cover
    from ..settings import Settings, get_settings  # type: ignore


bp = Blueprint("map", __name__)

# Nur Styles im Format "<owner>/<style-id>"
_STYLE_RE = re.compile(r"^[a-z0-9\-]+/[a-z0-9\-\.]+$", re.IGNORECASE)

_TRUE_VALUES = frozenset({"1", "true", "t", "yes", "y", "on", "ja"})
_FALSE_VALUES = frozenset({"0", "false", "f", "no", "n", "off", "nein"})

_ORCHESTRATOR_CLIENT_EXTENSION_KEY = "openlayer_orchestrator_client"
_DATASET_CATALOG_SERVICE_EXTENSION_KEY = "openlayer_dataset_catalog_service"
_DATASET_SOURCE_SERVICE_EXTENSION_KEY = "openlayer_dataset_source_service"
_STYLE_ADAPTER_EXTENSION_KEY = "openlayer_style_adapter"

_SERVICE_INIT_SUMMARY_EXTENSION_KEY = "openlayer_service_init_summary"
_SERVICE_FAILURES_EXTENSION_KEY = "openlayer_service_failures"


# ─────────────────────────────────────────────────────────────
# Helper: Settings / Logging / Safe Access
# ─────────────────────────────────────────────────────────────

def _settings() -> Settings:
    """
    Nutzt bevorzugt die bereits in app.py abgelegten Settings.
    Fällt robust auf get_settings() zurück.
    """
    try:
        cached = current_app.extensions.get("openlayer_settings")
        if isinstance(cached, Settings):
            return cached
    except Exception:
        pass
    return get_settings()


def _extensions() -> dict[str, Any]:
    try:
        extensions = getattr(current_app, "extensions", None)
        if isinstance(extensions, dict):
            return extensions
    except Exception:
        pass

    current_app.extensions = {}
    return current_app.extensions


def _log_exception(message: str, exc: Exception | None = None) -> None:
    try:
        if exc is None:
            current_app.logger.exception(message)
        else:
            current_app.logger.exception("%s: %s", message, exc.__class__.__name__)
    except Exception:
        pass


def _log_warning(message: str, *args: Any) -> None:
    try:
        current_app.logger.warning(message, *args)
    except Exception:
        pass


def _log_info(message: str, *args: Any) -> None:
    try:
        current_app.logger.info(message, *args)
    except Exception:
        pass


def _safe_str(value: Any, default: str = "") -> str:
    try:
        if value is None:
            return default
        return str(value)
    except Exception:
        return default


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


def _safe_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    try:
        return {str(k): v for k, v in value.items()}
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────
# Helper: Parsing / Sanitizing
# ─────────────────────────────────────────────────────────────

def _to_float(value: str | None, default: float) -> float:
    try:
        if value is None:
            return float(default)
        return float(str(value).strip())
    except Exception:
        return float(default)


def _to_int(value: str | None, default: int) -> int:
    try:
        if value is None:
            return int(default)
        return int(str(value).strip())
    except Exception:
        return int(default)


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    try:
        return max(minimum, min(maximum, float(value)))
    except Exception:
        return float(minimum)


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except Exception:
        return int(minimum)


def _sanitize_style(style: str | None, fallback: str) -> str:
    try:
        candidate = (style or "").strip()
        if not candidate:
            return fallback
        return candidate if _STYLE_RE.match(candidate) else fallback
    except Exception:
        return fallback


def _parse_boolish(value: str | None) -> bool | None:
    if value is None:
        return None

    try:
        normalized = str(value).strip().lower()
    except Exception:
        return None

    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return None


def _parse_disable_scroll(query_value: str | None, default_disable_scroll: bool) -> tuple[bool, str]:
    """
    Unterstützt weiterhin ?scroll=0|1 und zusätzlich boolische Werte.

    Semantik:
    - scroll=0 / false  -> Scroll/Wheel deaktiviert -> disable_scroll=True
    - scroll=1 / true   -> Scroll/Wheel aktiviert   -> disable_scroll=False
    - fehlt/ungültig    -> Default aus Settings
    """
    if query_value is None:
        return bool(default_disable_scroll), "settings_default"

    parsed = _parse_boolish(query_value)
    if parsed is None:
        return bool(default_disable_scroll), "invalid_query_fallback"

    return (not parsed), "query_override"


def _style_requires_mapbox_token(style_id: str) -> bool:
    try:
        return str(style_id).strip().lower().startswith("mapbox/")
    except Exception:
        return False


def _safe_url_for(endpoint: str, fallback: str) -> str:
    try:
        from flask import url_for
        return str(url_for(endpoint))
    except Exception:
        return fallback


def _append_query_params(url: str, params: Mapping[str, Any] | None = None) -> str:
    base = _safe_str(url, "").strip()
    if not base:
        return ""

    if not isinstance(params, Mapping) or not params:
        return base

    try:
        normalized: dict[str, str] = {}
        for key, value in params.items():
            key_text = _safe_str(key, "").strip()
            if not key_text:
                continue
            if value is None:
                continue
            normalized[key_text] = _safe_str(value, "").strip()

        if not normalized:
            return base

        separator = "&" if "?" in base else "?"
        return f"{base}{separator}{urlencode(normalized)}"
    except Exception:
        return base


# ─────────────────────────────────────────────────────────────
# Helper: Runtime Service / Diagnostics
# ─────────────────────────────────────────────────────────────

def _get_service_init_summary() -> dict[str, Any]:
    try:
        value = _extensions().get(_SERVICE_INIT_SUMMARY_EXTENSION_KEY, {})
        if isinstance(value, dict):
            return dict(value)
    except Exception:
        pass
    return {}


def _get_service_failures() -> dict[str, Any]:
    try:
        value = _extensions().get(_SERVICE_FAILURES_EXTENSION_KEY, {})
        if isinstance(value, dict):
            return dict(value)
    except Exception:
        pass
    return {}


def _service_available(extension_key: str, expected_method: str | None = None) -> bool:
    try:
        service = _extensions().get(extension_key)
        if service is None:
            return False
        if expected_method is None:
            return True
        return callable(getattr(service, expected_method, None))
    except Exception:
        return False


def _safe_service_summary(extension_key: str, summary_method: str = "get_service_summary") -> dict[str, Any]:
    try:
        service = _extensions().get(extension_key)
        if service is None:
            return {}
        summary_fn = getattr(service, summary_method, None)
        if callable(summary_fn):
            summary = summary_fn()
            if isinstance(summary, dict):
                return dict(summary)
    except Exception:
        pass
    return {}


def _safe_dataset_catalog_preview(settings: Settings) -> dict[str, Any]:
    """
    Best-effort-Vorschau auf den aktuellen Datensatzbestand.
    Diese Vorschau darf niemals die Map-Route blockieren.
    """
    preview: dict[str, Any] = {
        "available": False,
        "dataset_count": 0,
        "active_count": 0,
        "editable_count": 0,
        "first_dataset_id": "",
        "first_dataset_title": "",
        "warning": "",
    }

    try:
        if not _safe_bool(getattr(settings, "dataset_api_enabled", False), False):
            preview["warning"] = "dataset_api_disabled"
            return preview

        service = _extensions().get(_DATASET_CATALOG_SERVICE_EXTENSION_KEY)
        if service is None:
            preview["warning"] = "dataset_catalog_service_missing"
            return preview

        list_fn = getattr(service, "list_dataset_dicts", None)
        if not callable(list_fn):
            preview["warning"] = "dataset_catalog_service_invalid"
            return preview

        items = list_fn(
            include_inactive=True,
            include_invalid=True,
            include_style_details=False,
            enrich_with_db=False,
            include_internal=False,
            include_style_payload=False,
            use_cache=True,
        )
        if not isinstance(items, list):
            preview["warning"] = "dataset_catalog_payload_invalid"
            return preview

        preview["available"] = True
        preview["dataset_count"] = len(items)
        preview["active_count"] = len([item for item in items if _safe_bool(_safe_mapping(item).get("active"), False)])
        preview["editable_count"] = len([item for item in items if _safe_bool(_safe_mapping(item).get("editable"), False)])

        if items:
            first = _safe_mapping(items[0])
            preview["first_dataset_id"] = _safe_str(first.get("dataset_id") or first.get("id"), "").strip()
            preview["first_dataset_title"] = _safe_str(first.get("title"), "").strip()

        return preview

    except Exception as exc:
        preview["warning"] = exc.__class__.__name__
        return preview


def _build_map_runtime_summary(settings: Settings) -> dict[str, Any]:
    summary = {
        "orchestrator_client_available": _service_available(
            _ORCHESTRATOR_CLIENT_EXTENSION_KEY,
            expected_method="get_client_summary",
        ),
        "dataset_catalog_service_available": _service_available(
            _DATASET_CATALOG_SERVICE_EXTENSION_KEY,
            expected_method="list_dataset_dicts",
        ),
        "dataset_source_service_available": _service_available(
            _DATASET_SOURCE_SERVICE_EXTENSION_KEY,
            expected_method="get_dataset_source",
        ),
        "style_adapter_available": _service_available(
            _STYLE_ADAPTER_EXTENSION_KEY,
            expected_method="get_dataset_style_dict",
        ),
        "service_init_summary": _get_service_init_summary(),
        "service_failures": _get_service_failures(),
        "dataset_catalog_preview": _safe_dataset_catalog_preview(settings),
        "orchestrator_client_summary": _safe_service_summary(
            _ORCHESTRATOR_CLIENT_EXTENSION_KEY,
            summary_method="get_client_summary",
        ),
        "dataset_catalog_service_summary": _safe_service_summary(
            _DATASET_CATALOG_SERVICE_EXTENSION_KEY,
            summary_method="get_service_summary",
        ),
        "dataset_source_service_summary": _safe_service_summary(
            _DATASET_SOURCE_SERVICE_EXTENSION_KEY,
            summary_method="get_service_summary",
        ),
        "style_adapter_summary": _safe_service_summary(
            _STYLE_ADAPTER_EXTENSION_KEY,
            summary_method="get_service_summary",
        ),
    }

    return summary


# ─────────────────────────────────────────────────────────────
# Helper: URL / API Context
# ─────────────────────────────────────────────────────────────

def _build_datasets_api_url(settings: Settings) -> str:
    """
    Die Toolbar soll die aktuelle Orchestrator-Sicht bekommen.
    Deshalb hängen wir direkt Style-Details an, ohne das Frontend zu zwingen,
    weitere Requests für Basisinformationen zu machen.
    """
    base_url = _safe_url_for("datasets.list_datasets", "/api/datasets")
    return _append_query_params(
        base_url,
        {
            "include_style_details": "1",
            "include_invalid": "0",
        },
    )


def _build_datasets_api_style_contract_url(settings: Settings) -> str:
    """
    Optionaler vollerer Datensatzvertrag für spätere UI-Ausbaustufen.
    """
    base_url = _safe_url_for("datasets.list_datasets", "/api/datasets")
    return _append_query_params(
        base_url,
        {
            "include_style_details": "1",
            "include_style_contract": "1",
            "include_invalid": "0",
        },
    )


def _build_dataset_changes_url_template() -> str:
    return "/api/datasets/{dataset_id}/changes"


def _build_dataset_source_url_template() -> str:
    return "/api/datasets/{dataset_id}/source"


def _build_dataset_style_url_template() -> str:
    """
    Noch keine eigene OpenLayer-Style-Route.
    Wir hinterlegen die Information trotzdem für spätere JS-Ausbaustufen.
    """
    return "/api/datasets/{dataset_id}?include_style_contract=1"


# ─────────────────────────────────────────────────────────────
# Fallback Context
# ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _fallback_context() -> dict[str, Any]:
    """
    Letztes Sicherheitsnetz, falls sogar Settings-Aufbau oder Request-Parsing scheitern.
    """
    return {
        "mapbox_token": "",
        "lon": 11.576124,
        "lat": 48.137154,
        "zoom": 14,
        "min_zoom": 0,
        "max_zoom": 22,
        "style_id": "mapbox/satellite-streets-v12",
        "disable_scroll": False,
        "enable_wheel_zoom": True,
        "scroll_source": "fallback_default",
        "tile_size": 512,
        "dataset_api_enabled": False,
        "editor_enabled": False,
        "datasets_api_url": "/api/datasets?include_style_details=1&include_invalid=0",
        "datasets_api_url_base": "/api/datasets",
        "datasets_api_style_contract_url": "/api/datasets?include_style_details=1&include_style_contract=1&include_invalid=0",
        "dataset_source_url_template": "/api/datasets/{dataset_id}/source",
        "dataset_style_url_template": "/api/datasets/{dataset_id}?include_style_contract=1",
        "dataset_changes_url_template": "/api/datasets/{dataset_id}/changes",
        "geoserver_orchestrator_url": "",
        "orchestrator_configured": False,
        "orchestrator_client_available": False,
        "server_error": True,
        "server_error_msg": "fallback_context_used",
        "server_error_detail": "settings_or_request_failed",
        "mapbox_token_present": False,
        "style_requires_mapbox_token": True,
        "style_token_mismatch": True,
        "dataset_catalog_preview": {
            "available": False,
            "dataset_count": 0,
            "active_count": 0,
            "editable_count": 0,
            "first_dataset_id": "",
            "first_dataset_title": "",
            "warning": "fallback_context",
        },
        "service_init_summary": {},
        "service_failures": {},
        "service_health": {
            "orchestrator_client_available": False,
            "dataset_catalog_service_available": False,
            "dataset_source_service_available": False,
            "style_adapter_available": False,
        },
        "ui": {
            "show_toolbar": True,
            "show_dataset_button": True,
            "show_editor_button": False,
            "show_zoom_buttons": True,
        },
    }


# ─────────────────────────────────────────────────────────────
# Helper: Context Builder
# ─────────────────────────────────────────────────────────────

def _build_context(settings: Settings) -> dict[str, Any]:
    server_error = False
    server_error_msg = ""
    server_error_detail = ""

    try:
        map_default_lon = float(getattr(settings, "map_default_lon", 11.576124))
        map_default_lat = float(getattr(settings, "map_default_lat", 48.137154))
        map_default_zoom = int(getattr(settings, "map_default_zoom", 14))
        map_min_zoom = int(getattr(settings, "map_min_zoom", 0))
        map_max_zoom = int(getattr(settings, "map_max_zoom", 22))
        map_tile_size = int(getattr(settings, "map_tile_size", 512))
        map_default_style = _safe_str(getattr(settings, "map_default_style", None), "mapbox/satellite-streets-v12")
        map_disable_scroll = _safe_bool(getattr(settings, "map_disable_scroll", False), False)
        map_enable_wheel_zoom = _safe_bool(getattr(settings, "map_enable_wheel_zoom", not map_disable_scroll), True)

        lon = _clamp_float(
            _to_float(request.args.get("lon"), map_default_lon),
            -180.0,
            180.0,
        )
        lat = _clamp_float(
            _to_float(request.args.get("lat"), map_default_lat),
            -90.0,
            90.0,
        )
        zoom = _clamp_int(
            _to_int(request.args.get("zoom"), map_default_zoom),
            map_min_zoom,
            map_max_zoom,
        )

        style_id = _sanitize_style(
            request.args.get("style"),
            map_default_style,
        )
        if style_id != (request.args.get("style") or "").strip() and request.args.get("style"):
            _log_warning("invalid map style query param ignored: %r", request.args.get("style"))

        disable_scroll, scroll_source = _parse_disable_scroll(
            request.args.get("scroll"),
            map_disable_scroll,
        )
        enable_wheel_zoom = (not disable_scroll) and bool(map_enable_wheel_zoom)

        mapbox_token = _safe_str(getattr(settings, "mapbox_token", None), "")
        token_present = _safe_bool(getattr(settings, "has_mapbox_token", bool(mapbox_token.strip())), bool(mapbox_token.strip()))
        style_requires_token = _style_requires_mapbox_token(style_id)
        style_token_mismatch = bool(style_requires_token and not token_present)

        dataset_api_enabled = _safe_bool(getattr(settings, "dataset_api_enabled", False), False)
        editor_enabled = _safe_bool(getattr(settings, "editor_enabled", False), False)
        geoserver_orchestrator_url = _safe_str(getattr(settings, "geoserver_orchestrator_url", None), "").strip()

        datasets_api_url = _build_datasets_api_url(settings)
        datasets_api_style_contract_url = _build_datasets_api_style_contract_url(settings)
        dataset_changes_url_template = _build_dataset_changes_url_template()
        dataset_source_url_template = _build_dataset_source_url_template()
        dataset_style_url_template = _build_dataset_style_url_template()

        runtime_summary = _build_map_runtime_summary(settings)
        dataset_catalog_preview = _safe_mapping(runtime_summary.get("dataset_catalog_preview"))
        service_init_summary = _safe_mapping(runtime_summary.get("service_init_summary"))
        service_failures = _safe_mapping(runtime_summary.get("service_failures"))

        service_health = {
            "orchestrator_client_available": _safe_bool(runtime_summary.get("orchestrator_client_available"), False),
            "dataset_catalog_service_available": _safe_bool(runtime_summary.get("dataset_catalog_service_available"), False),
            "dataset_source_service_available": _safe_bool(runtime_summary.get("dataset_source_service_available"), False),
            "style_adapter_available": _safe_bool(runtime_summary.get("style_adapter_available"), False),
        }

        requested_dataset_id = _safe_str(request.args.get("dataset_id"), "").strip()
        initial_dataset_id = requested_dataset_id or _safe_str(dataset_catalog_preview.get("first_dataset_id"), "").strip()
        initial_dataset_title = _safe_str(dataset_catalog_preview.get("first_dataset_title"), "").strip()

        context: dict[str, Any] = {
            # Kartenkonfiguration
            "mapbox_token": mapbox_token,
            "mapbox_token_present": token_present,
            "lon": lon,
            "lat": lat,
            "zoom": zoom,
            "min_zoom": map_min_zoom,
            "max_zoom": map_max_zoom,
            "style_id": style_id,
            "tile_size": map_tile_size,
            "disable_scroll": disable_scroll,
            "enable_wheel_zoom": enable_wheel_zoom,
            "scroll_source": scroll_source,
            "style_requires_mapbox_token": style_requires_token,
            "style_token_mismatch": style_token_mismatch,

            # API / Services
            "dataset_api_enabled": dataset_api_enabled,
            "editor_enabled": editor_enabled,
            "datasets_api_url": datasets_api_url,
            "datasets_api_url_base": _safe_url_for("datasets.list_datasets", "/api/datasets"),
            "datasets_api_style_contract_url": datasets_api_style_contract_url,
            "dataset_changes_url_template": dataset_changes_url_template,
            "dataset_source_url_template": dataset_source_url_template,
            "dataset_style_url_template": dataset_style_url_template,
            "geoserver_orchestrator_url": geoserver_orchestrator_url,
            "orchestrator_configured": bool(geoserver_orchestrator_url),
            "orchestrator_client_available": service_health["orchestrator_client_available"],

            # Dataset / Preview / Initialzustand
            "dataset_catalog_preview": dataset_catalog_preview,
            "initial_dataset_id": initial_dataset_id,
            "initial_dataset_title": initial_dataset_title,

            # Service-Diagnostik für spätere JS-Ausbaustufen
            "service_health": service_health,
            "service_init_summary": service_init_summary,
            "service_failures": service_failures,
            "runtime_summary": runtime_summary,

            # UI-Hinweise für Toolbar/Template
            "ui": {
                "show_toolbar": True,
                "show_dataset_button": True,
                "show_editor_button": bool(editor_enabled),
                "show_zoom_buttons": True,
            },

            # Debug-/Fehlerflags für JS
            "server_error": server_error,
            "server_error_msg": server_error_msg,
            "server_error_detail": server_error_detail,
        }

        return context

    except Exception as exc:
        _log_exception("map context build failed", exc)

        server_error = True
        server_error_msg = exc.__class__.__name__
        server_error_detail = "context_build_failed"

        fallback = dict(_fallback_context())
        fallback.update(
            {
                "server_error": server_error,
                "server_error_msg": server_error_msg,
                "server_error_detail": server_error_detail,
            }
        )

        # Versuche Settings-basierte Defaults trotzdem noch zu übernehmen
        try:
            map_default_style = _safe_str(getattr(settings, "map_default_style", None), "mapbox/satellite-streets-v12")
            mapbox_token = _safe_str(getattr(settings, "mapbox_token", None), "")
            token_present = _safe_bool(getattr(settings, "has_mapbox_token", bool(mapbox_token.strip())), bool(mapbox_token.strip()))

            fallback["mapbox_token"] = mapbox_token
            fallback["mapbox_token_present"] = token_present
            fallback["lon"] = float(getattr(settings, "map_default_lon", fallback["lon"]))
            fallback["lat"] = float(getattr(settings, "map_default_lat", fallback["lat"]))
            fallback["zoom"] = int(getattr(settings, "map_default_zoom", fallback["zoom"]))
            fallback["min_zoom"] = int(getattr(settings, "map_min_zoom", fallback["min_zoom"]))
            fallback["max_zoom"] = int(getattr(settings, "map_max_zoom", fallback["max_zoom"]))
            fallback["style_id"] = map_default_style
            fallback["tile_size"] = int(getattr(settings, "map_tile_size", fallback["tile_size"]))
            fallback["disable_scroll"] = _safe_bool(getattr(settings, "map_disable_scroll", fallback["disable_scroll"]), False)
            fallback["enable_wheel_zoom"] = _safe_bool(getattr(settings, "map_enable_wheel_zoom", fallback["enable_wheel_zoom"]), True)
            fallback["dataset_api_enabled"] = _safe_bool(getattr(settings, "dataset_api_enabled", fallback["dataset_api_enabled"]), False)
            fallback["editor_enabled"] = _safe_bool(getattr(settings, "editor_enabled", fallback["editor_enabled"]), False)
            fallback["datasets_api_url"] = _build_datasets_api_url(settings)
            fallback["datasets_api_url_base"] = _safe_url_for("datasets.list_datasets", "/api/datasets")
            fallback["datasets_api_style_contract_url"] = _build_datasets_api_style_contract_url(settings)
            fallback["dataset_source_url_template"] = _build_dataset_source_url_template()
            fallback["dataset_style_url_template"] = _build_dataset_style_url_template()
            fallback["dataset_changes_url_template"] = _build_dataset_changes_url_template()
            fallback["geoserver_orchestrator_url"] = _safe_str(getattr(settings, "geoserver_orchestrator_url", None), "")
            fallback["orchestrator_configured"] = bool(fallback["geoserver_orchestrator_url"])
            fallback["style_requires_mapbox_token"] = _style_requires_mapbox_token(map_default_style)
            fallback["style_token_mismatch"] = bool(
                _style_requires_mapbox_token(map_default_style) and not token_present
            )

            runtime_summary = _build_map_runtime_summary(settings)
            fallback["runtime_summary"] = runtime_summary
            fallback["dataset_catalog_preview"] = _safe_mapping(runtime_summary.get("dataset_catalog_preview"))
            fallback["service_init_summary"] = _safe_mapping(runtime_summary.get("service_init_summary"))
            fallback["service_failures"] = _safe_mapping(runtime_summary.get("service_failures"))
            fallback["service_health"] = {
                "orchestrator_client_available": _safe_bool(runtime_summary.get("orchestrator_client_available"), False),
                "dataset_catalog_service_available": _safe_bool(runtime_summary.get("dataset_catalog_service_available"), False),
                "dataset_source_service_available": _safe_bool(runtime_summary.get("dataset_source_service_available"), False),
                "style_adapter_available": _safe_bool(runtime_summary.get("style_adapter_available"), False),
            }
            fallback["orchestrator_client_available"] = fallback["service_health"]["orchestrator_client_available"]
            fallback["initial_dataset_id"] = _safe_str(
                _safe_mapping(fallback["dataset_catalog_preview"]).get("first_dataset_id"),
                "",
            )
            fallback["initial_dataset_title"] = _safe_str(
                _safe_mapping(fallback["dataset_catalog_preview"]).get("first_dataset_title"),
                "",
            )

            fallback["ui"] = {
                "show_toolbar": True,
                "show_dataset_button": True,
                "show_editor_button": bool(fallback["editor_enabled"]),
                "show_zoom_buttons": True,
            }
        except Exception:
            pass

        return fallback


def _render_map_template(context: dict[str, Any]) -> Response:
    response = make_response(render_template("map.html", **context), 200)
    try:
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    except Exception:
        pass
    return response


def _render_last_resort_html(context: dict[str, Any], exc: Exception) -> Response:
    """
    Letztes Sicherheitsnetz, falls selbst map.html nicht gerendert werden kann.
    """
    try:
        preview = _safe_mapping(context.get("dataset_catalog_preview"))
        dataset_count = _safe_str(preview.get("dataset_count"), "0")
        first_dataset_id = _safe_str(preview.get("first_dataset_id"), "")
        first_dataset_title = _safe_str(preview.get("first_dataset_title"), "")
        service_health = _safe_mapping(context.get("service_health"))

        html = f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>OpenLayer Map Fallback</title>
  <style>
    html, body {{
      margin: 0;
      padding: 0;
      font: 14px/1.5 system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      background: #111;
      color: #f5f5f5;
    }}
    .wrap {{
      padding: 16px;
    }}
    .box {{
      background: #1d1d1d;
      border: 1px solid #333;
      border-radius: 12px;
      padding: 16px;
      max-width: 920px;
    }}
    code {{
      background: #2a2a2a;
      padding: 2px 6px;
      border-radius: 6px;
    }}
    ul {{
      padding-left: 18px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="box">
      <h1>OpenLayer UI Fallback</h1>
      <p>Das eigentliche Template konnte nicht gerendert werden.</p>
      <p><strong>Fehler:</strong> <code>{exc.__class__.__name__}</code></p>
      <p><strong>Style:</strong> <code>{context.get("style_id", "")}</code></p>
      <p><strong>Zentrum:</strong> <code>{context.get("lon", "")}, {context.get("lat", "")}</code></p>
      <p><strong>Zoom:</strong> <code>{context.get("zoom", "")}</code></p>
      <p><strong>Editor aktiviert:</strong> <code>{bool(context.get("editor_enabled", False))}</code></p>
      <p><strong>Datasets API aktiviert:</strong> <code>{bool(context.get("dataset_api_enabled", False))}</code></p>
      <p><strong>Datasets API URL:</strong> <code>{context.get("datasets_api_url", "")}</code></p>
      <p><strong>Orchestrator URL:</strong> <code>{context.get("geoserver_orchestrator_url", "")}</code></p>
      <p><strong>Dataset-Vorschau:</strong> <code>{dataset_count}</code> Datensätze</p>
      <p><strong>Erster Datensatz:</strong> <code>{first_dataset_id}</code> {first_dataset_title}</p>
      <h2>Service-Zustand</h2>
      <ul>
        <li>Orchestrator Client: <code>{bool(service_health.get("orchestrator_client_available", False))}</code></li>
        <li>Dataset Catalog Service: <code>{bool(service_health.get("dataset_catalog_service_available", False))}</code></li>
        <li>Dataset Source Service: <code>{bool(service_health.get("dataset_source_service_available", False))}</code></li>
        <li>Style Adapter: <code>{bool(service_health.get("style_adapter_available", False))}</code></li>
      </ul>
    </div>
  </div>
</body>
</html>"""
        response = make_response(html, 200)
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response
    except Exception:
        response = make_response("OpenLayer fallback unavailable", 500)
        response.headers["Content-Type"] = "text/plain; charset=utf-8"
        return response


# ─────────────────────────────────────────────────────────────
# Route
# ─────────────────────────────────────────────────────────────

@bp.get("/map")
def map_view() -> Response:
    """
    Einzige UI-Route für die Karte.

    Verhalten:
    - rendert die Kartenansicht best-effort
    - Request-Parameter überschreiben sichere Defaults aus settings.py
    - Template erhält Flags und URLs für die neue Orchestrator-/Dataset-Integration
    - bei Fehlern wird weiterhin versucht, die UI mit Fallback-Kontext zu rendern
    """
    try:
        settings = _settings()
    except Exception as exc:
        _log_exception("settings lookup failed in map_view", exc)
        settings = get_settings()

    try:
        context = _build_context(settings)
        _log_info(
            "map_view context built dataset_api_enabled=%s editor_enabled=%s orchestrator_configured=%s",
            context.get("dataset_api_enabled"),
            context.get("editor_enabled"),
            context.get("orchestrator_configured"),
        )
    except Exception as exc:
        _log_exception("map_view build context hard failure", exc)
        context = dict(_fallback_context())
        context["server_error"] = True
        context["server_error_msg"] = exc.__class__.__name__
        context["server_error_detail"] = "hard_context_failure"

    try:
        return _render_map_template(context)
    except Exception as exc:
        _log_exception("map template render failed", exc)
        return _render_last_resort_html(context, exc)