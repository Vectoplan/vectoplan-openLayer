# services/vectoplan-openLayer/settings.py
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit


# ─────────────────────────────────────────────────────────────
# Pfade
# ─────────────────────────────────────────────────────────────

SERVICE_ROOT = Path(__file__).resolve().parent
ENV_FILE = SERVICE_ROOT / ".env"
TEMPLATES_DIR = SERVICE_ROOT / "templates"
STATIC_DIR = SERVICE_ROOT / "static"
DATA_DIR = SERVICE_ROOT / "data"
MOCK_GEOJSON_DIR = DATA_DIR / "mock_geojson"
VENDOR_OL_DIR = STATIC_DIR / "vendor" / "ol"
VENDOR_OLE_DIR = STATIC_DIR / "vendor" / "openlayers-editor"


# ─────────────────────────────────────────────────────────────
# Defaults
# ─────────────────────────────────────────────────────────────

DEFAULT_SERVICE_NAME = "openlayer"
DEFAULT_SERVICE_VERSION = "0.3.0"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8090
DEFAULT_LOG_LEVEL = "INFO"

# Browser-facing URL. This is the Docker-published host port.
# The browser must not be redirected to localhost:8090.
DEFAULT_OPENLAYER_PUBLIC_URL = "http://localhost:5190"
DEFAULT_OPENLAYER_ROUTE = "/map"

# The parent app that embeds OpenLayer in an iframe.
DEFAULT_VECTOPLAN_APP_PUBLIC_URL = "http://localhost:5103"
DEFAULT_OPENLAYER_FRAME_ANCESTORS = (
    "http://localhost:5103",
    "http://127.0.0.1:5103",
)

DEFAULT_OPENLAYER_EMBED_ENABLED = True
DEFAULT_OPENLAYER_CSP_ENABLED = True
DEFAULT_OPENLAYER_REMOVE_X_FRAME_OPTIONS_ON_EMBED = True
DEFAULT_OPENLAYER_X_FRAME_OPTIONS_DEFAULT = "SAMEORIGIN"

DEFAULT_LON = 11.576124
DEFAULT_LAT = 48.137154
DEFAULT_ZOOM = 14
DEFAULT_MIN_ZOOM = 0
DEFAULT_MAX_ZOOM = 22
DEFAULT_MAPBOX_STYLE = "mapbox/satellite-streets-v12"
DEFAULT_TILE_SIZE = 512

DEFAULT_ALLOWED_ORIGINS = ("*",)

_TRUE_VALUES = frozenset({"1", "true", "t", "yes", "y", "on", "enabled", "ja"})
_FALSE_VALUES = frozenset({"0", "false", "f", "no", "n", "off", "disabled", "nein"})
_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_SPLIT_RE = re.compile(r"[\s,;]+")


# ─────────────────────────────────────────────────────────────
# Datamodel
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Settings:
    """
    Zentrale, normalisierte Konfiguration für den OpenLayer-Service.

    Designziele:
    - nur eine Konfigurationsquelle im Code
    - .env wird tolerant gelesen, Prozess-ENV hat Vorrang
    - robuste Fallbacks bei Parse-Fehlern
    - per Cache nur einmal aufgebaut
    - klare Trennung zwischen internem Service-Port und Browser-/iframe-URL
    """

    service_root: Path
    env_file: Path
    templates_dir: Path
    static_dir: Path
    data_dir: Path
    mock_geojson_dir: Path
    vendor_ol_dir: Path
    vendor_ole_dir: Path

    service_name: str
    service_version: str
    host: str
    port: int
    log_level: str
    flask_debug: bool

    allowed_origins: tuple[str, ...]
    mapbox_token: str

    # Public / iframe integration
    openlayer_public_url: str
    openlayer_route: str
    openlayer_embed_enabled: bool
    openlayer_csp_enabled: bool
    openlayer_frame_ancestors: tuple[str, ...]
    openlayer_frame_ancestors_csp: str
    openlayer_remove_x_frame_options_on_embed: bool
    openlayer_x_frame_options_default: str
    vectoplan_app_public_url: str

    map_default_lon: float
    map_default_lat: float
    map_default_zoom: int
    map_min_zoom: int
    map_max_zoom: int
    map_default_style: str
    map_tile_size: int
    map_disable_scroll: bool
    map_enable_wheel_zoom: bool

    dataset_api_enabled: bool
    editor_enabled: bool
    dataset_catalog_path: Path
    geoserver_orchestrator_url: str

    required_files: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_mapbox_token(self) -> bool:
        try:
            return len(self.mapbox_token.strip()) >= 10
        except Exception:
            return False

    @property
    def is_development(self) -> bool:
        return bool(self.flask_debug)

    @property
    def map_default_center(self) -> tuple[float, float]:
        return (self.map_default_lon, self.map_default_lat)

    @property
    def openlayer_public_base_url(self) -> str:
        return self.openlayer_public_url

    @property
    def public_map_url(self) -> str:
        return _join_public_url(self.openlayer_public_url, self.openlayer_route)

    def resolve_required_files(self) -> dict[str, Path]:
        result: dict[str, Path] = {}
        try:
            for rel in self.required_files:
                result[rel] = self.service_root / rel
        except Exception:
            return {}
        return result

    def required_files_state(self) -> dict[str, bool]:
        state: dict[str, bool] = {}
        try:
            for rel, path in self.resolve_required_files().items():
                state[rel] = path.exists()
        except Exception:
            return {}
        return state

    def origin_is_allowed(self, origin: str | None) -> bool:
        try:
            if "*" in self.allowed_origins:
                return True
            if not origin:
                return False
            normalized = _normalize_origin(origin)
            return bool(normalized and normalized in self.allowed_origins)
        except Exception:
            return False

    def frame_origin_is_allowed(self, origin: str | None) -> bool:
        try:
            if not origin:
                return False
            normalized = _normalize_origin(origin)
            return bool(normalized and normalized in self.openlayer_frame_ancestors)
        except Exception:
            return False

    def to_flask_config(self) -> dict[str, Any]:
        """
        Normalisierte Werte für app.config.
        """
        return {
            "SERVICE_NAME": self.service_name,
            "SERVICE_VERSION": self.service_version,
            "HOST": self.host,
            "OPENLAYER_PORT": self.port,
            "PORT": self.port,
            "LOG_LEVEL": self.log_level,
            "FLASK_DEBUG": self.flask_debug,
            "ALLOWED_ORIGINS": list(self.allowed_origins),
            "MAPBOX_TOKEN": self.mapbox_token,

            # Public / iframe integration
            "OPENLAYER_PUBLIC_URL": self.openlayer_public_url,
            "OPENLAYER_PUBLIC_BASE_URL": self.openlayer_public_base_url,
            "OPENLAYER_ROUTE": self.openlayer_route,
            "OPENLAYER_PUBLIC_MAP_URL": self.public_map_url,
            "OPENLAYER_EMBED_ENABLED": self.openlayer_embed_enabled,
            "OPENLAYER_CSP_ENABLED": self.openlayer_csp_enabled,
            "OPENLAYER_FRAME_ANCESTORS": list(self.openlayer_frame_ancestors),
            "OPENLAYER_ALLOWED_FRAME_PARENTS": list(self.openlayer_frame_ancestors),
            "OPENLAYER_FRAME_ANCESTORS_CSP": self.openlayer_frame_ancestors_csp,
            "OPENLAYER_REMOVE_X_FRAME_OPTIONS_ON_EMBED": self.openlayer_remove_x_frame_options_on_embed,
            "OPENLAYER_X_FRAME_OPTIONS_DEFAULT": self.openlayer_x_frame_options_default,
            "VECTOPLAN_APP_PUBLIC_URL": self.vectoplan_app_public_url,

            "DEFAULT_LON": self.map_default_lon,
            "DEFAULT_LAT": self.map_default_lat,
            "DEFAULT_ZOOM": self.map_default_zoom,
            "MAP_DEFAULT_LON": self.map_default_lon,
            "MAP_DEFAULT_LAT": self.map_default_lat,
            "MAP_DEFAULT_ZOOM": self.map_default_zoom,
            "MAP_DEFAULT_CENTER": [self.map_default_lon, self.map_default_lat],
            "MAP_MIN_ZOOM": self.map_min_zoom,
            "MAP_MAX_ZOOM": self.map_max_zoom,
            "MAPBOX_DEFAULT_STYLE": self.map_default_style,
            "MAP_STYLE_ID": self.map_default_style,
            "MAP_TILE_SIZE": self.map_tile_size,
            "DISABLE_SCROLL": self.map_disable_scroll,
            "MAP_DISABLE_SCROLL": self.map_disable_scroll,
            "ENABLE_WHEEL_ZOOM": self.map_enable_wheel_zoom,
            "MAP_ENABLE_WHEEL_ZOOM": self.map_enable_wheel_zoom,
            "DATASET_API_ENABLED": self.dataset_api_enabled,
            "EDITOR_ENABLED": self.editor_enabled,
            "DATASET_CATALOG_PATH": str(self.dataset_catalog_path),
            "GEOSERVER_ORCHESTRATOR_URL": self.geoserver_orchestrator_url,
            "SERVICE_ROOT": str(self.service_root),
            "ENV_FILE": str(self.env_file),
            "TEMPLATES_DIR": str(self.templates_dir),
            "STATIC_DIR": str(self.static_dir),
            "DATA_DIR": str(self.data_dir),
            "MOCK_GEOJSON_DIR": str(self.mock_geojson_dir),
            "VENDOR_OL_DIR": str(self.vendor_ol_dir),
            "VENDOR_OLE_DIR": str(self.vendor_ole_dir),
            "REQUIRED_FILES": list(self.required_files),
            "SETTINGS_NOTES": list(self.notes),
        }

    def to_public_dict(self) -> dict[str, Any]:
        """
        Für Debug-/Health-Ausgaben ohne Secrets.
        """
        return {
            "service": self.service_name,
            "version": self.service_version,
            "host": self.host,
            "port": self.port,
            "log_level": self.log_level,
            "flask_debug": self.flask_debug,
            "allowed_origins": list(self.allowed_origins),
            "has_mapbox_token": self.has_mapbox_token,
            "public": {
                "openlayer_public_url": self.openlayer_public_url,
                "openlayer_route": self.openlayer_route,
                "public_map_url": self.public_map_url,
                "vectoplan_app_public_url": self.vectoplan_app_public_url,
            },
            "embed": {
                "enabled": self.openlayer_embed_enabled,
                "csp_enabled": self.openlayer_csp_enabled,
                "frame_ancestors": list(self.openlayer_frame_ancestors),
                "frame_ancestors_csp": self.openlayer_frame_ancestors_csp,
                "remove_x_frame_options_on_embed": self.openlayer_remove_x_frame_options_on_embed,
                "x_frame_options_default": self.openlayer_x_frame_options_default,
            },
            "map": {
                "lon": self.map_default_lon,
                "lat": self.map_default_lat,
                "zoom": self.map_default_zoom,
                "min_zoom": self.map_min_zoom,
                "max_zoom": self.map_max_zoom,
                "style": self.map_default_style,
                "tile_size": self.map_tile_size,
                "disable_scroll": self.map_disable_scroll,
                "enable_wheel_zoom": self.map_enable_wheel_zoom,
            },
            "features": {
                "dataset_api_enabled": self.dataset_api_enabled,
                "editor_enabled": self.editor_enabled,
            },
            "paths": {
                "service_root": str(self.service_root),
                "env_file": str(self.env_file),
                "templates_dir": str(self.templates_dir),
                "static_dir": str(self.static_dir),
                "data_dir": str(self.data_dir),
                "mock_geojson_dir": str(self.mock_geojson_dir),
                "dataset_catalog_path": str(self.dataset_catalog_path),
                "vendor_ol_dir": str(self.vendor_ol_dir),
                "vendor_ole_dir": str(self.vendor_ole_dir),
            },
            "required_files": self.required_files_state(),
            "notes": list(self.notes),
        }


# ─────────────────────────────────────────────────────────────
# Cache / Reload
# ─────────────────────────────────────────────────────────────

def clear_settings_cache() -> None:
    try:
        get_settings.cache_clear()
    except Exception:
        pass


def reload_settings() -> Settings:
    clear_settings_cache()
    return get_settings()


# ─────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────

def _clean_env_value(value: str) -> str:
    try:
        v = value.strip()
        if v.startswith("export "):
            v = v[7:].strip()
        if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
            v = v[1:-1]
        return v.strip()
    except Exception:
        return value


def _read_env_file(path: Path) -> tuple[dict[str, str], list[str]]:
    data: dict[str, str] = {}
    notes: list[str] = []

    try:
        if not path.exists():
            notes.append(".env nicht gefunden")
            return data, notes
    except Exception as exc:
        notes.append(f".env Existenzprüfung fehlgeschlagen: {exc.__class__.__name__}")
        return data, notes

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        notes.append(f".env Lesen fehlgeschlagen: {exc.__class__.__name__}")
        return data, notes

    for lineno, raw in enumerate(content.splitlines(), start=1):
        try:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = _clean_env_value(value)

            if not key:
                notes.append(f".env Zeile {lineno}: leerer Schlüssel ignoriert")
                continue

            data[key] = value
        except Exception as exc:
            notes.append(f".env Zeile {lineno}: {exc.__class__.__name__}")

    return data, notes


def _merge_env(file_env: Mapping[str, str]) -> dict[str, str]:
    """
    Prozess-ENV hat Vorrang vor .env.
    """
    merged: dict[str, str] = {}

    try:
        merged.update({k: str(v) for k, v in file_env.items()})
    except Exception:
        pass

    try:
        merged.update({k: str(v) for k, v in os.environ.items() if v is not None})
    except Exception:
        pass

    return merged


def _first_non_blank(env: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        try:
            value = env.get(name)
        except Exception:
            value = None
        if value is None:
            continue
        try:
            cleaned = str(value).strip()
        except Exception:
            continue
        if cleaned != "":
            return cleaned
    return None


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    try:
        return max(minimum, min(maximum, float(value)))
    except Exception:
        return minimum


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except Exception:
        return minimum


def _parse_bool(
    env: Mapping[str, str],
    names: Iterable[str],
    default: bool,
    notes: list[str],
) -> bool:
    names_tuple = tuple(names)
    raw = _first_non_blank(env, *names_tuple)
    if raw is None:
        return default

    lowered = raw.strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False

    try:
        joined = ",".join(names_tuple)
    except Exception:
        joined = "unknown"
    notes.append(f"Bool-Parse fehlgeschlagen für {joined!r}: {raw!r}")
    return default


def _parse_int(
    env: Mapping[str, str],
    names: Iterable[str],
    default: int,
    notes: list[str],
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    names_tuple = tuple(names)
    raw = _first_non_blank(env, *names_tuple)
    if raw is None:
        value = default
    else:
        try:
            value = int(str(raw).strip())
        except Exception:
            try:
                joined = ",".join(names_tuple)
            except Exception:
                joined = "unknown"
            notes.append(f"Int-Parse fehlgeschlagen für {joined!r}: {raw!r}")
            value = default

    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _parse_float(
    env: Mapping[str, str],
    names: Iterable[str],
    default: float,
    notes: list[str],
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    names_tuple = tuple(names)
    raw = _first_non_blank(env, *names_tuple)
    if raw is None:
        value = default
    else:
        try:
            value = float(str(raw).strip())
        except Exception:
            try:
                joined = ",".join(names_tuple)
            except Exception:
                joined = "unknown"
            notes.append(f"Float-Parse fehlgeschlagen für {joined!r}: {raw!r}")
            value = default

    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _parse_string_list(raw: str | None) -> list[str]:
    if raw is None:
        return []

    text = str(raw).strip()
    if text == "":
        return []

    try:
        loaded = json.loads(text)
        if isinstance(loaded, list):
            items: list[str] = []
            for item in loaded:
                try:
                    s = str(item).strip()
                except Exception:
                    continue
                if s:
                    items.append(s)
            return items
    except Exception:
        pass

    try:
        return [item.strip() for item in _SPLIT_RE.split(text) if item.strip()]
    except Exception:
        return []


def _unique_tuple(items: Iterable[str], fallback: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []

    try:
        for item in items:
            value = str(item).strip()
            if not value:
                continue
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
    except Exception:
        return fallback

    return tuple(result) if result else fallback


def _normalize_origin(origin: str | None, default: str = "") -> str:
    """
    Normalize an origin for CORS/CSP.

    - '*' is returned only where callers explicitly keep it.
    - http(s) URLs are reduced to scheme://host[:port].
    - invalid values return default.
    """
    if origin is None:
        return default

    try:
        raw = str(origin).strip()
    except Exception:
        return default

    if not raw:
        return default

    if raw in {"self", "'self'"}:
        return "'self'"

    if raw == "*":
        return "*"

    if not (raw.startswith("http://") or raw.startswith("https://")):
        return default

    try:
        parsed = urlsplit(raw)
        if not parsed.scheme or not parsed.netloc:
            return default
        return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return default


def _normalize_url(raw: str | None, default: str) -> str:
    if raw is None:
        return default.rstrip("/")

    try:
        text = str(raw).strip().rstrip("/")
        if not text:
            return default.rstrip("/")
        if not (text.startswith("http://") or text.startswith("https://")):
            return default.rstrip("/")
        return text
    except Exception:
        return default.rstrip("/")


def _normalize_route(raw: str | None, default: str) -> str:
    if raw is None:
        return default

    try:
        text = str(raw).strip()
        if not text:
            return default
        if not text.startswith("/"):
            text = "/" + text
        while "//" in text:
            text = text.replace("//", "/")
        if len(text) > 1:
            text = text.rstrip("/")
        return text
    except Exception:
        return default


def _join_public_url(base_url: str, route: str) -> str:
    try:
        base = _normalize_url(base_url, DEFAULT_OPENLAYER_PUBLIC_URL)
        path = _normalize_route(route, DEFAULT_OPENLAYER_ROUTE)

        if base.endswith(path):
            return base

        if path == "/":
            return base

        return f"{base}{path}"
    except Exception:
        return f"{DEFAULT_OPENLAYER_PUBLIC_URL}{DEFAULT_OPENLAYER_ROUTE}"


def _parse_allowed_origins(env: Mapping[str, str], notes: list[str]) -> tuple[str, ...]:
    raw = _first_non_blank(env, "ALLOWED_ORIGINS", "CORS_ALLOWED_ORIGINS")
    if raw is None:
        return DEFAULT_ALLOWED_ORIGINS

    items = _parse_string_list(raw)
    if not items:
        notes.append("ALLOWED_ORIGINS leer oder ungültig → '*'")
        return DEFAULT_ALLOWED_ORIGINS

    normalized: list[str] = []
    wildcard = False

    for item in items:
        origin = _normalize_origin(item)
        if origin == "*":
            wildcard = True
            continue
        if origin and origin not in normalized:
            normalized.append(origin)

    if wildcard:
        return DEFAULT_ALLOWED_ORIGINS

    return _unique_tuple(normalized, DEFAULT_ALLOWED_ORIGINS)


def _parse_frame_ancestors(env: Mapping[str, str], notes: list[str], app_public_url: str) -> tuple[str, ...]:
    raw = _first_non_blank(
        env,
        "OPENLAYER_FRAME_ANCESTORS",
        "OPENLAYER_ALLOWED_FRAME_PARENTS",
        "VECTOPLAN_ALLOWED_FRAME_PARENTS",
        "FRAME_ANCESTORS",
    )

    if raw is None:
        items = list(DEFAULT_OPENLAYER_FRAME_ANCESTORS)
    else:
        items = _parse_string_list(raw)
        if not items:
            notes.append("OPENLAYER_FRAME_ANCESTORS leer oder ungültig → lokale App-Origins")
            items = list(DEFAULT_OPENLAYER_FRAME_ANCESTORS)

    app_origin = _normalize_origin(app_public_url)
    normalized: list[str] = []

    if app_origin:
        normalized.append(app_origin)

    for item in items:
        origin = _normalize_origin(item)
        if not origin or origin == "*":
            if str(item).strip() == "*":
                notes.append("Wildcard '*' in OPENLAYER_FRAME_ANCESTORS ignoriert")
            continue
        if origin not in normalized:
            normalized.append(origin)

    return tuple(normalized) if normalized else DEFAULT_OPENLAYER_FRAME_ANCESTORS


def _frame_ancestors_csp(ancestors: tuple[str, ...], include_self: bool = True) -> str:
    result: list[str] = []

    if include_self:
        result.append("'self'")

    for ancestor in ancestors:
        origin = _normalize_origin(ancestor)
        if not origin or origin == "*":
            continue
        if origin not in result:
            result.append(origin)

    return " ".join(result) if result else "'self'"


def _normalize_x_frame_options(raw: str | None, default: str = DEFAULT_OPENLAYER_X_FRAME_OPTIONS_DEFAULT) -> str:
    try:
        value = str(raw or default).strip().upper()
    except Exception:
        value = default

    if value in {"DENY", "SAMEORIGIN"}:
        return value

    return default


def _normalize_log_level(raw: str | None, notes: list[str]) -> str:
    if raw is None:
        return DEFAULT_LOG_LEVEL

    try:
        value = str(raw).strip().upper()
    except Exception:
        return DEFAULT_LOG_LEVEL

    if value in _VALID_LOG_LEVELS:
        return value

    notes.append(f"Ungültiges LOG_LEVEL {raw!r} → {DEFAULT_LOG_LEVEL}")
    return DEFAULT_LOG_LEVEL


def _parse_center_from_single_value(raw: str | None, notes: list[str]) -> tuple[float, float] | None:
    if raw is None:
        return None

    text = str(raw).strip()
    if text == "":
        return None

    try:
        loaded = json.loads(text)
        if isinstance(loaded, (list, tuple)) and len(loaded) >= 2:
            lon = float(loaded[0])
            lat = float(loaded[1])
            return (
                _clamp_float(lon, -180.0, 180.0),
                _clamp_float(lat, -90.0, 90.0),
            )
    except Exception:
        pass

    try:
        parts = [part.strip() for part in text.split(",")]
        if len(parts) >= 2:
            lon = float(parts[0])
            lat = float(parts[1])
            return (
                _clamp_float(lon, -180.0, 180.0),
                _clamp_float(lat, -90.0, 90.0),
            )
    except Exception:
        notes.append(f"MAP_DEFAULT_CENTER ungültig: {raw!r}")

    return None


def _normalize_path(raw: str | None, default: Path) -> Path:
    if raw is None:
        return default

    try:
        candidate = Path(str(raw).strip()).expanduser()
        if not candidate.is_absolute():
            candidate = SERVICE_ROOT / candidate
        return candidate
    except Exception:
        return default


def _required_files_default() -> tuple[str, ...]:
    return (
        "templates/map.html",
        "static/css/style.css",
        "static/js/main.js",
    )


# ─────────────────────────────────────────────────────────────
# Settings Loader
# ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    notes: list[str] = []

    file_env, env_notes = _read_env_file(ENV_FILE)
    notes.extend(env_notes)

    env = _merge_env(file_env)

    service_name = _first_non_blank(env, "SERVICE_NAME") or DEFAULT_SERVICE_NAME
    service_version = _first_non_blank(env, "SERVICE_VERSION") or DEFAULT_SERVICE_VERSION
    host = _first_non_blank(env, "HOST") or DEFAULT_HOST

    port = _parse_int(
        env,
        ("OPENLAYER_PORT", "PORT"),
        DEFAULT_PORT,
        notes,
        minimum=1,
        maximum=65535,
    )

    log_level = _normalize_log_level(_first_non_blank(env, "LOG_LEVEL"), notes)

    flask_debug = _parse_bool(
        env,
        ("FLASK_DEBUG", "DEBUG"),
        False,
        notes,
    )

    allowed_origins = _parse_allowed_origins(env, notes)

    mapbox_token = _first_non_blank(
        env,
        "MAPBOX_TOKEN",
        "MAPBOX_ACCESS_TOKEN",
    ) or ""

    openlayer_public_url = _normalize_url(
        _first_non_blank(
            env,
            "OPENLAYER_PUBLIC_URL",
            "OPENLAYER_PUBLIC_BASE_URL",
            "VECTOPLAN_OPENLAYER_PUBLIC_URL",
        ),
        DEFAULT_OPENLAYER_PUBLIC_URL,
    )

    openlayer_route = _normalize_route(
        _first_non_blank(
            env,
            "OPENLAYER_ROUTE",
            "VECTOPLAN_OPENLAYER_ROUTE",
            "MAP_ROUTE",
        ),
        DEFAULT_OPENLAYER_ROUTE,
    )

    vectoplan_app_public_url = _normalize_url(
        _first_non_blank(
            env,
            "VECTOPLAN_APP_PUBLIC_URL",
            "VECTOPLAN_APP_PUBLIC_BASE_URL",
            "APP_PUBLIC_URL",
        ),
        DEFAULT_VECTOPLAN_APP_PUBLIC_URL,
    )

    openlayer_embed_enabled = _parse_bool(
        env,
        (
            "OPENLAYER_EMBED_ENABLED",
            "VECTOPLAN_OPENLAYER_EMBED_ENABLED",
            "MAP_EMBED_ENABLED",
        ),
        DEFAULT_OPENLAYER_EMBED_ENABLED,
        notes,
    )

    openlayer_csp_enabled = _parse_bool(
        env,
        (
            "OPENLAYER_CSP_ENABLED",
            "VECTOPLAN_OPENLAYER_CSP_ENABLED",
            "MAP_CSP_ENABLED",
        ),
        DEFAULT_OPENLAYER_CSP_ENABLED,
        notes,
    )

    openlayer_remove_x_frame_options_on_embed = _parse_bool(
        env,
        (
            "OPENLAYER_REMOVE_X_FRAME_OPTIONS_ON_EMBED",
            "VECTOPLAN_OPENLAYER_REMOVE_X_FRAME_OPTIONS_ON_EMBED",
            "MAP_REMOVE_X_FRAME_OPTIONS_ON_EMBED",
        ),
        DEFAULT_OPENLAYER_REMOVE_X_FRAME_OPTIONS_ON_EMBED,
        notes,
    )

    openlayer_x_frame_options_default = _normalize_x_frame_options(
        _first_non_blank(
            env,
            "OPENLAYER_X_FRAME_OPTIONS_DEFAULT",
            "VECTOPLAN_OPENLAYER_X_FRAME_OPTIONS_DEFAULT",
            "MAP_X_FRAME_OPTIONS_DEFAULT",
        ),
        DEFAULT_OPENLAYER_X_FRAME_OPTIONS_DEFAULT,
    )

    openlayer_frame_ancestors = _parse_frame_ancestors(
        env,
        notes,
        vectoplan_app_public_url,
    )

    openlayer_frame_ancestors_csp = _frame_ancestors_csp(
        openlayer_frame_ancestors,
        include_self=True,
    )

    # Zentrum: zuerst MAP_DEFAULT_CENTER, dann Einzelwerte
    center = _parse_center_from_single_value(_first_non_blank(env, "MAP_DEFAULT_CENTER"), notes)
    if center is not None:
        map_default_lon, map_default_lat = center
    else:
        map_default_lon = _parse_float(
            env,
            ("DEFAULT_LON", "MAP_DEFAULT_LON"),
            DEFAULT_LON,
            notes,
            minimum=-180.0,
            maximum=180.0,
        )
        map_default_lat = _parse_float(
            env,
            ("DEFAULT_LAT", "MAP_DEFAULT_LAT"),
            DEFAULT_LAT,
            notes,
            minimum=-90.0,
            maximum=90.0,
        )

    map_default_zoom = _parse_int(
        env,
        ("DEFAULT_ZOOM", "MAP_DEFAULT_ZOOM"),
        DEFAULT_ZOOM,
        notes,
        minimum=0,
        maximum=22,
    )

    map_min_zoom = _parse_int(
        env,
        ("MAP_MIN_ZOOM",),
        DEFAULT_MIN_ZOOM,
        notes,
        minimum=0,
        maximum=22,
    )

    map_max_zoom = _parse_int(
        env,
        ("MAP_MAX_ZOOM",),
        DEFAULT_MAX_ZOOM,
        notes,
        minimum=0,
        maximum=22,
    )

    if map_max_zoom < map_min_zoom:
        notes.append(
            f"MAP_MAX_ZOOM ({map_max_zoom}) < MAP_MIN_ZOOM ({map_min_zoom}) → Werte korrigiert"
        )
        map_max_zoom = map_min_zoom

    if map_default_zoom < map_min_zoom:
        notes.append(
            f"MAP_DEFAULT_ZOOM ({map_default_zoom}) < MAP_MIN_ZOOM ({map_min_zoom}) → Wert korrigiert"
        )
        map_default_zoom = map_min_zoom

    if map_default_zoom > map_max_zoom:
        notes.append(
            f"MAP_DEFAULT_ZOOM ({map_default_zoom}) > MAP_MAX_ZOOM ({map_max_zoom}) → Wert korrigiert"
        )
        map_default_zoom = map_max_zoom

    map_default_style = (
        _first_non_blank(env, "MAPBOX_DEFAULT_STYLE", "MAP_STYLE_ID", "MAPBOX_STYLE_ID")
        or DEFAULT_MAPBOX_STYLE
    )

    map_tile_size = _parse_int(
        env,
        ("MAP_TILE_SIZE",),
        DEFAULT_TILE_SIZE,
        notes,
        minimum=128,
        maximum=1024,
    )

    # Neue Flag-Logik mit sauberer Priorität:
    # 1) explizites ENABLE_WHEEL_ZOOM / MAP_ENABLE_WHEEL_ZOOM
    # 2) Fallback auf DISABLE_SCROLL / MAP_DISABLE_SCROLL
    wheel_zoom_explicit = _first_non_blank(env, "ENABLE_WHEEL_ZOOM", "MAP_ENABLE_WHEEL_ZOOM")
    if wheel_zoom_explicit is not None:
        map_enable_wheel_zoom = _parse_bool(
            env,
            ("ENABLE_WHEEL_ZOOM", "MAP_ENABLE_WHEEL_ZOOM"),
            False,
            notes,
        )
        map_disable_scroll = not map_enable_wheel_zoom
    else:
        map_disable_scroll = _parse_bool(
            env,
            ("DISABLE_SCROLL", "MAP_DISABLE_SCROLL"),
            True,
            notes,
        )
        map_enable_wheel_zoom = not map_disable_scroll

    dataset_api_enabled = _parse_bool(
        env,
        ("DATASET_API_ENABLED", "ENABLE_DATASET_API"),
        True,
        notes,
    )

    editor_enabled = _parse_bool(
        env,
        ("EDITOR_ENABLED", "OPENLAYER_EDITOR_ENABLED", "ENABLE_EDITOR"),
        True,
        notes,
    )

    dataset_catalog_default = DATA_DIR / "datasets_catalog.json"
    dataset_catalog_path = _normalize_path(
        _first_non_blank(env, "DATASET_CATALOG_PATH"),
        dataset_catalog_default,
    )

    geoserver_orchestrator_url = _first_non_blank(
        env,
        "GEOSERVER_ORCHESTRATOR_URL",
        "GEOSERVER_ORCHESTRATOR_BASE_URL",
    ) or ""

    required_files = _required_files_default()

    return Settings(
        service_root=SERVICE_ROOT,
        env_file=ENV_FILE,
        templates_dir=TEMPLATES_DIR,
        static_dir=STATIC_DIR,
        data_dir=DATA_DIR,
        mock_geojson_dir=MOCK_GEOJSON_DIR,
        vendor_ol_dir=VENDOR_OL_DIR,
        vendor_ole_dir=VENDOR_OLE_DIR,
        service_name=service_name,
        service_version=service_version,
        host=host,
        port=port,
        log_level=log_level,
        flask_debug=flask_debug,
        allowed_origins=allowed_origins,
        mapbox_token=mapbox_token,
        openlayer_public_url=openlayer_public_url,
        openlayer_route=openlayer_route,
        openlayer_embed_enabled=openlayer_embed_enabled,
        openlayer_csp_enabled=openlayer_csp_enabled,
        openlayer_frame_ancestors=openlayer_frame_ancestors,
        openlayer_frame_ancestors_csp=openlayer_frame_ancestors_csp,
        openlayer_remove_x_frame_options_on_embed=openlayer_remove_x_frame_options_on_embed,
        openlayer_x_frame_options_default=openlayer_x_frame_options_default,
        vectoplan_app_public_url=vectoplan_app_public_url,
        map_default_lon=map_default_lon,
        map_default_lat=map_default_lat,
        map_default_zoom=map_default_zoom,
        map_min_zoom=map_min_zoom,
        map_max_zoom=map_max_zoom,
        map_default_style=map_default_style,
        map_tile_size=map_tile_size,
        map_disable_scroll=map_disable_scroll,
        map_enable_wheel_zoom=map_enable_wheel_zoom,
        dataset_api_enabled=dataset_api_enabled,
        editor_enabled=editor_enabled,
        dataset_catalog_path=dataset_catalog_path,
        geoserver_orchestrator_url=geoserver_orchestrator_url,
        required_files=required_files,
        notes=tuple(notes),
    )


__all__ = [
    "Settings",
    "SERVICE_ROOT",
    "ENV_FILE",
    "TEMPLATES_DIR",
    "STATIC_DIR",
    "DATA_DIR",
    "MOCK_GEOJSON_DIR",
    "VENDOR_OL_DIR",
    "VENDOR_OLE_DIR",
    "get_settings",
    "reload_settings",
    "clear_settings_cache",
]