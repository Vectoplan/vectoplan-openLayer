# /services/openLayer/routes/health.py
from __future__ import annotations

import os
import socket
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, make_response, request

try:
    from settings import Settings, get_settings
except Exception:  # pragma: no cover
    from ..settings import Settings, get_settings  # type: ignore


bp = Blueprint("system", __name__)

_PROCESS_STARTED_AT = int(time.time())
_PROCESS_PID = os.getpid()


# ─────────────────────────────────────────────────────────────
# Helper: Basis
# ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown-host"


def _uptime_seconds() -> int:
    try:
        return max(0, int(time.time()) - _PROCESS_STARTED_AT)
    except Exception:
        return 0


def _json(payload: dict[str, Any], code: int = 200) -> Response:
    response = make_response(jsonify(payload), int(code))
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers["Cache-Control"] = "no-store"
    return response


def _settings() -> Settings:
    """
    Holt bevorzugt die bereits in app.py abgelegten Settings.
    Fällt robust auf get_settings() zurück.
    """
    try:
        cached = current_app.extensions.get("openlayer_settings")
        if isinstance(cached, Settings):
            return cached
    except Exception:
        pass

    return get_settings()


def _safe_bool(value: Any, default: bool = False) -> bool:
    try:
        return bool(value)
    except Exception:
        return default


def _safe_str(value: Any, default: str = "") -> str:
    try:
        return str(value)
    except Exception:
        return default


def _style_requires_mapbox(style_id: str | None) -> bool:
    try:
        if not style_id:
            return False
        return str(style_id).strip().lower().startswith("mapbox/")
    except Exception:
        return False


def _path_exists(path: Path | str | None) -> bool:
    try:
        if path is None:
            return False
        return Path(path).exists()
    except Exception:
        return False


def _is_dir(path: Path | str | None) -> bool:
    try:
        if path is None:
            return False
        return Path(path).is_dir()
    except Exception:
        return False


def _has_route(rule_path: str) -> bool:
    try:
        for rule in current_app.url_map.iter_rules():
            try:
                if rule.rule == rule_path:
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
# Helper: Struktur / Runtime
# ─────────────────────────────────────────────────────────────

def _collect_required_files_state(settings: Settings) -> dict[str, bool]:
    """
    Nutzt die zentrale required_files-Liste aus settings.py.
    Damit wachsen Health/Ready automatisch mit, sobald später
    weitere kritische Assets dort ergänzt werden.
    """
    try:
        return settings.required_files_state()
    except Exception:
        state: dict[str, bool] = {}
        try:
            for rel in settings.required_files:
                state[str(rel)] = _path_exists(settings.service_root / rel)
        except Exception:
            pass
        return state


def _collect_path_state(settings: Settings) -> dict[str, Any]:
    state: dict[str, Any] = {
        "service_root_exists": _path_exists(settings.service_root),
        "templates_dir_exists": _is_dir(settings.templates_dir),
        "static_dir_exists": _is_dir(settings.static_dir),
        "data_dir_exists": _is_dir(settings.data_dir),
        "mock_geojson_dir_exists": _is_dir(settings.mock_geojson_dir),
        "vendor_ol_dir_exists": _is_dir(settings.vendor_ol_dir),
        "vendor_ole_dir_exists": _is_dir(settings.vendor_ole_dir),
        "dataset_catalog_exists": _path_exists(settings.dataset_catalog_path),
        "env_file_exists": _path_exists(settings.env_file),
    }

    try:
        state["dataset_catalog_path"] = str(settings.dataset_catalog_path)
    except Exception:
        state["dataset_catalog_path"] = ""

    return state


def _collect_routes_state() -> dict[str, bool]:
    return {
        "root": _has_route("/"),
        "map": _has_route("/map"),
        "health": _has_route("/health"),
        "health_live": _has_route("/health/live"),
        "ready": _has_route("/ready"),
        "health_ready": _has_route("/health/ready"),
        "config": _has_route("/config"),
        "ping": _has_route("/ping"),
        "datasets": _has_route("/api/datasets"),
    }


def _collect_runtime_state(settings: Settings) -> dict[str, Any]:
    registered_blueprints: list[str] = []
    blueprint_failures: dict[str, str] = {}

    try:
        raw_registered = current_app.extensions.get("registered_blueprints", [])
        if isinstance(raw_registered, list):
            registered_blueprints = [str(item) for item in raw_registered]
    except Exception:
        pass

    try:
        raw_failures = current_app.extensions.get("blueprint_failures", {})
        if isinstance(raw_failures, dict):
            blueprint_failures = {str(k): _safe_str(v) for k, v in raw_failures.items()}
    except Exception:
        pass

    return {
        "hostname": _get_hostname(),
        "pid": _PROCESS_PID,
        "process_started_at": _PROCESS_STARTED_AT,
        "uptime_seconds": _uptime_seconds(),
        "debug": _safe_bool(current_app.config.get("FLASK_DEBUG", settings.flask_debug), settings.flask_debug),
        "registered_blueprints": registered_blueprints,
        "blueprint_failures": blueprint_failures,
    }


def _collect_config_state(settings: Settings) -> dict[str, Any]:
    style_id = ""
    try:
        style_id = _safe_str(current_app.config.get("MAPBOX_DEFAULT_STYLE", settings.map_default_style))
    except Exception:
        style_id = settings.map_default_style

    return {
        "service_name": settings.service_name,
        "service_version": settings.service_version,
        "host": settings.host,
        "port": settings.port,
        "log_level": settings.log_level,
        "allowed_origins": list(settings.allowed_origins),
        "map": {
            "default_lon": settings.map_default_lon,
            "default_lat": settings.map_default_lat,
            "default_zoom": settings.map_default_zoom,
            "min_zoom": settings.map_min_zoom,
            "max_zoom": settings.map_max_zoom,
            "default_style": style_id,
            "tile_size": settings.map_tile_size,
            "disable_scroll": settings.map_disable_scroll,
            "enable_wheel_zoom": settings.map_enable_wheel_zoom,
            "mapbox_token_present": settings.has_mapbox_token,
            "mapbox_style_requires_token": _style_requires_mapbox(style_id),
        },
        "features": {
            "dataset_api_enabled": settings.dataset_api_enabled,
            "editor_enabled": settings.editor_enabled,
        },
        "geoserver_orchestrator_url_present": bool(settings.geoserver_orchestrator_url.strip()),
    }


# ─────────────────────────────────────────────────────────────
# Helper: Readiness
# ─────────────────────────────────────────────────────────────

def _collect_readiness(settings: Settings) -> dict[str, Any]:
    notes: list[str] = []
    required_files = _collect_required_files_state(settings)
    path_state = _collect_path_state(settings)
    route_state = _collect_routes_state()
    config_state = _collect_config_state(settings)

    templates_dir_ok = _safe_bool(path_state.get("templates_dir_exists"))
    static_dir_ok = _safe_bool(path_state.get("static_dir_exists"))
    map_route_ok = _safe_bool(route_state.get("map"))
    health_route_ok = _safe_bool(route_state.get("health"))
    ready_route_ok = _safe_bool(route_state.get("ready"))
    required_files_ok = all(required_files.values()) if required_files else True

    style_requires_token = _safe_bool(
        config_state.get("map", {}).get("mapbox_style_requires_token"),
        False,
    )
    token_present = _safe_bool(
        config_state.get("map", {}).get("mapbox_token_present"),
        False,
    )

    mapbox_ready = True
    if style_requires_token and not token_present:
        mapbox_ready = False
        notes.append("Mapbox-Style konfiguriert, aber MAPBOX_TOKEN fehlt")

    dataset_advisory: dict[str, Any] = {
        "enabled": settings.dataset_api_enabled,
        "route_present": _safe_bool(route_state.get("datasets")),
        "catalog_exists": _safe_bool(path_state.get("dataset_catalog_exists")),
        "blocking": False,
    }

    # Noch kein Blocker, weil der Datensatzkatalog in den nächsten Schritten folgt.
    if settings.dataset_api_enabled and not dataset_advisory["route_present"]:
        notes.append("Datasets-API noch nicht registriert oder als Fallback aktiv")

    if settings.dataset_api_enabled and not dataset_advisory["catalog_exists"]:
        notes.append("Datasets-Katalogdatei fehlt noch oder wurde noch nicht angelegt")

    vendor_advisory: dict[str, Any] = {
        "ol_vendor_dir_exists": _safe_bool(path_state.get("vendor_ol_dir_exists")),
        "openlayers_editor_vendor_dir_exists": _safe_bool(path_state.get("vendor_ole_dir_exists")),
        "blocking": False,
    }

    # Solange lokale Vendor-Assets noch nicht eingebaut sind, nur Hinweis, kein Blocker.
    if not vendor_advisory["ol_vendor_dir_exists"]:
        notes.append("Lokale OpenLayers-Vendor-Assets fehlen noch oder werden noch nicht verwendet")
    if not vendor_advisory["openlayers_editor_vendor_dir_exists"]:
        notes.append("Lokale openlayers-editor-Vendor-Assets fehlen noch oder werden noch nicht verwendet")

    required: dict[str, bool] = {
        "templates_dir_exists": templates_dir_ok,
        "static_dir_exists": static_dir_ok,
        "required_files_exist": required_files_ok,
        "map_route_present": map_route_ok,
        "health_route_present": health_route_ok,
        "ready_route_present": ready_route_ok,
        "mapbox_ready": mapbox_ready,
    }

    ok = all(required.values())

    return {
        "ok": ok,
        "required": required,
        "required_files": required_files,
        "advisory": {
            "dataset_api": dataset_advisory,
            "vendor_assets": vendor_advisory,
        },
        "notes": notes,
    }


def _collect_health_payload() -> dict[str, Any]:
    settings = _settings()
    payload: dict[str, Any] = {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.service_version,
        "runtime": _collect_runtime_state(settings),
        "routes": _collect_routes_state(),
        "paths": _collect_path_state(settings),
        "config": _collect_config_state(settings),
        "notes": list(settings.notes),
    }

    try:
        payload["structure"] = {
            "required_files": _collect_required_files_state(settings),
        }
    except Exception:
        payload["structure"] = {"required_files": {}}

    return payload


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@bp.route("/health", methods=["GET", "HEAD"])
@bp.route("/health/live", methods=["GET", "HEAD"])
def health() -> Response:
    """
    Liveness:
    - Prozess lebt
    - Flask antwortet
    - liefert optional Diagnoseinformationen
    """
    try:
        payload = _collect_health_payload()

        if request.method == "HEAD":
            return _json({"status": payload.get("status", "ok")}, 200)

        return _json(payload, 200)
    except Exception as exc:
        error_payload = {
            "status": "error",
            "error": f"health:{exc.__class__.__name__}",
        }
        return _json(error_payload, 500)


@bp.route("/ready", methods=["GET", "HEAD"])
@bp.route("/health/ready", methods=["GET", "HEAD"])
def ready() -> Response:
    """
    Readiness:
    - kritische Dateien/Verzeichnisse vorhanden
    - Kernrouten registriert
    - falls ein Mapbox-Style konfiguriert ist: Token vorhanden
    - zukünftige Bestandteile wie Datasets/Vendor-Assets werden vorerst
      advisory gemeldet und blockieren noch nicht
    """
    try:
        settings = _settings()
        health_payload = _collect_health_payload()
        readiness = _collect_readiness(settings)
        ok = _safe_bool(readiness.get("ok"), False)

        health_payload["readiness"] = readiness
        health_payload["status"] = "ok" if ok else "not_ready"

        if request.method == "HEAD":
            return _json({"status": health_payload["status"]}, 200 if ok else 503)

        return _json(health_payload, 200 if ok else 503)
    except Exception as exc:
        error_payload = {
            "status": "error",
            "error": f"ready:{exc.__class__.__name__}",
        }
        return _json(error_payload, 500)