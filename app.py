# /services/openLayer/app.py
from __future__ import annotations

import importlib
import importlib.util
import logging
import socket
import time
from functools import lru_cache
from pathlib import Path
from threading import RLock
from types import ModuleType
from typing import Any, Callable, Mapping, Optional

from flask import Flask, Response, jsonify, make_response, redirect, request, url_for

try:
    from settings import SERVICE_ROOT, Settings, get_settings
except Exception:  # pragma: no cover
    from .settings import SERVICE_ROOT, Settings, get_settings  # type: ignore


_PROCESS_STARTED_AT = int(time.time())
_PROCESS_PID = None
try:
    import os
    _PROCESS_PID = os.getpid()
except Exception:
    _PROCESS_PID = None


# ─────────────────────────────────────────────────────────────
# Modulweite Konstanten / Caches
# ─────────────────────────────────────────────────────────────

_IMPORT_LOCK = RLock()
_IMPORT_CACHE: dict[str, ModuleType] = {}

_SETTINGS_EXTENSION_KEY = "openlayer_settings"
_REGISTERED_BLUEPRINTS_KEY = "registered_blueprints"
_BLUEPRINT_FAILURES_KEY = "blueprint_failures"

_ORCHESTRATOR_CLIENT_EXTENSION_KEY = "openlayer_orchestrator_client"
_DATASET_CATALOG_SERVICE_EXTENSION_KEY = "openlayer_dataset_catalog_service"
_DATASET_SOURCE_SERVICE_EXTENSION_KEY = "openlayer_dataset_source_service"
_STYLE_ADAPTER_EXTENSION_KEY = "openlayer_style_adapter"

_SERVICE_INIT_SUMMARY_EXTENSION_KEY = "openlayer_service_init_summary"
_SERVICE_FAILURES_EXTENSION_KEY = "openlayer_service_failures"

_DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"


# ─────────────────────────────────────────────────────────────
# Helper: Runtime / Logging / Safe Conversions
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
            if normalized in {"1", "true", "t", "yes", "y", "on", "ja"}:
                return True
            if normalized in {"0", "false", "f", "no", "n", "off", "nein"}:
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
        return {str(k): v for k, v in dict(value).items()}
    except Exception:
        return {}


def _safe_exception_name(exc: Exception | BaseException | None) -> str:
    try:
        if exc is None:
            return "unknown"
        return exc.__class__.__name__
    except Exception:
        return "unknown"


def _configure_logging(app: Flask, settings: Settings) -> None:
    """
    Robuste Logging-Konfiguration.

    Verhalten:
    - Gunicorn-Handler übernehmen, falls vorhanden
    - sonst basicConfig als Fallback
    - App-Logger-Level aus Settings
    """
    try:
        level_name = _safe_str(getattr(settings, "log_level", None), "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
    except Exception:
        level = logging.INFO

    try:
        gunicorn_error_logger = logging.getLogger("gunicorn.error")
        if gunicorn_error_logger.handlers:
            app.logger.handlers = gunicorn_error_logger.handlers
            app.logger.propagate = False
    except Exception:
        pass

    try:
        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=level,
                format=_DEFAULT_LOG_FORMAT,
            )
    except Exception:
        pass

    try:
        app.logger.setLevel(level)
    except Exception:
        try:
            app.logger.setLevel(logging.INFO)
        except Exception:
            pass

    try:
        logging.getLogger("werkzeug").setLevel(
            level if _safe_bool(getattr(settings, "flask_debug", False), False) else logging.INFO
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# Helper: JSON Responses
# ─────────────────────────────────────────────────────────────

def _json_response(payload: Mapping[str, Any], status: int = 200) -> Response:
    response = make_response(jsonify(dict(payload)), int(status))
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers["Cache-Control"] = "no-store"
    return response


def _json_error(
    status: int,
    message: str,
    *,
    detail: Any | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Response:
    payload: dict[str, Any] = {
        "status": "error",
        "code": int(status),
        "message": str(message),
    }

    if detail is not None:
        payload["detail"] = detail

    if extra:
        try:
            payload.update(dict(extra))
        except Exception:
            payload["extra_error"] = "extra_payload_invalid"

    return _json_response(payload, status=status)


# ─────────────────────────────────────────────────────────────
# Helper: App Extensions / Settings Resolution
# ─────────────────────────────────────────────────────────────

def _ensure_extensions_dict(app: Flask) -> dict[str, Any]:
    try:
        extensions = getattr(app, "extensions", None)
        if isinstance(extensions, dict):
            return extensions
    except Exception:
        pass

    app.extensions = {}
    return app.extensions


def _set_extension_if_missing(app: Flask, key: str, value: Any) -> None:
    try:
        extensions = _ensure_extensions_dict(app)
        if key not in extensions:
            extensions[key] = value
    except Exception:
        pass


def _resolve_settings(test_config: Mapping[str, Any] | None = None) -> Settings:
    """
    Erlaubt in Tests optional ein injiziertes Settings-Objekt oder eine Factory.
    """
    if isinstance(test_config, Mapping):
        try:
            injected_settings = test_config.get("OPENLAYER_SETTINGS")
            if isinstance(injected_settings, Settings):
                return injected_settings
        except Exception:
            pass

        try:
            settings_factory = test_config.get("OPENLAYER_SETTINGS_FACTORY")
            if callable(settings_factory):
                built = settings_factory()
                if isinstance(built, Settings):
                    return built
        except Exception:
            pass

    return get_settings()


# ─────────────────────────────────────────────────────────────
# Helper: Dynamic Import für Blueprints und Services
# ─────────────────────────────────────────────────────────────

def _load_module_from_file(module_name: str, file_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"spec creation failed for {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def _import_module_cached(import_name: str, file_path: Path | None = None) -> ModuleType:
    cache_key = f"{import_name}::{str(file_path) if file_path else ''}"

    with _IMPORT_LOCK:
        cached = _IMPORT_CACHE.get(cache_key)
        if isinstance(cached, ModuleType):
            return cached

    last_error: Exception | None = None

    try:
        module = importlib.import_module(import_name)
        with _IMPORT_LOCK:
            _IMPORT_CACHE[cache_key] = module
        return module
    except Exception as exc:
        last_error = exc

    if file_path is not None and file_path.exists():
        unique_name = f"openlayer_dynamic_{file_path.stem}_{abs(hash(str(file_path)))}"
        try:
            module = _load_module_from_file(unique_name, file_path)
            with _IMPORT_LOCK:
                _IMPORT_CACHE[cache_key] = module
            return module
        except Exception as exc:
            last_error = exc

    raise ImportError(
        f"module import failed for {import_name} ({file_path})"
    ) from last_error


def _import_blueprint_module(import_name: str, file_path: Path) -> ModuleType:
    return _import_module_cached(import_name, file_path)


def _find_blueprint_in_module(module: ModuleType, label: str) -> Any:
    candidates = [
        getattr(module, "bp", None),
        getattr(module, "blueprint", None),
        getattr(module, f"{label}_blueprint", None),
    ]

    for candidate in candidates:
        if candidate is not None:
            return candidate

    raise AttributeError(f"{label} module missing blueprint export ('bp')")


def _load_class_from_module(
    *,
    import_name: str,
    file_path: Path,
    class_name: str,
) -> type[Any]:
    module = _import_module_cached(import_name, file_path)
    candidate = getattr(module, class_name, None)
    if candidate is None or not isinstance(candidate, type):
        raise AttributeError(f"{class_name} missing in {import_name}")
    return candidate


def _register_blueprint(
    app: Flask,
    *,
    import_name: str,
    file_path: Path,
    label: str,
    required: bool,
    on_failure: Callable[[Flask, Exception], None] | None = None,
) -> bool:
    """
    Registriert ein Blueprint robust. Falls Import/Registrierung scheitert:
    - required=True: Fallback-Route(s) via on_failure
    - required=False: nur Log-Hinweis + optionaler Fallback
    """
    try:
        module = _import_blueprint_module(import_name, file_path)
        blueprint = _find_blueprint_in_module(module, label)

        extensions = _ensure_extensions_dict(app)
        registered_blueprints = extensions.setdefault(_REGISTERED_BLUEPRINTS_KEY, [])
        if isinstance(registered_blueprints, list) and label in registered_blueprints:
            return True

        app.register_blueprint(blueprint)

        if isinstance(registered_blueprints, list):
            registered_blueprints.append(label)

        return True

    except Exception as exc:
        try:
            app.logger.exception("register blueprint failed: %s", label, exc_info=exc)
        except Exception:
            pass

        try:
            failures = _ensure_extensions_dict(app).setdefault(_BLUEPRINT_FAILURES_KEY, {})
            if isinstance(failures, dict):
                failures[label] = {
                    "error_type": _safe_exception_name(exc),
                    "message": _safe_str(exc, "unknown_error"),
                    "required": bool(required),
                }
        except Exception:
            pass

        if on_failure is not None:
            try:
                on_failure(app, exc)
            except Exception:
                pass

        return False


# ─────────────────────────────────────────────────────────────
# Helper: Runtime Services Initialisierung
# ─────────────────────────────────────────────────────────────

def _service_summary_or_placeholder(service: Any, fallback_name: str) -> dict[str, Any]:
    try:
        summary_fn = getattr(service, "get_service_summary", None)
        if callable(summary_fn):
            summary = summary_fn()
            if isinstance(summary, dict):
                return dict(summary)
    except Exception:
        pass

    return {"service_type": fallback_name}


def _store_runtime_service(app: Flask, extension_key: str, service: Any) -> None:
    try:
        _ensure_extensions_dict(app)[extension_key] = service
    except Exception:
        pass


def _initialize_runtime_services(app: Flask, settings: Settings) -> None:
    """
    Initialisiert die neuen Service-Objekte robust und legt sie in current_app.extensions ab.

    Verhalten:
    - best effort: App startet auch dann, wenn einzelne Services nicht gebaut werden können
    - Fehler werden in app.extensions dokumentiert
    - spätere Routen können die Services aus extensions lesen
    """
    extensions = _ensure_extensions_dict(app)
    service_summary: dict[str, Any] = {
        "initialized_at": int(time.time()),
        "dataset_api_enabled": _safe_bool(getattr(settings, "dataset_api_enabled", False), False),
        "editor_enabled": _safe_bool(getattr(settings, "editor_enabled", False), False),
        "services": {},
    }
    service_failures: dict[str, Any] = {}

    src_root = SERVICE_ROOT / "src"

    runtime_classes: dict[str, tuple[str, Path, str]] = {
        "orchestrator_client": (
            "src.orchestrator.client",
            src_root / "orchestrator" / "client.py",
            "GeoServerOrchestratorClient",
        ),
        "dataset_catalog_service": (
            "src.datasets.catalog_service",
            src_root / "datasets" / "catalog_service.py",
            "OpenLayerDatasetCatalogService",
        ),
        "dataset_source_service": (
            "src.datasets.source_service",
            src_root / "datasets" / "source_service.py",
            "OpenLayerDatasetSourceService",
        ),
        "style_adapter": (
            "src.styles.style_adapter",
            src_root / "styles" / "style_adapter.py",
            "OpenLayerStyleAdapter",
        ),
    }

    resolved_classes: dict[str, type[Any]] = {}

    for logical_name, (import_name, file_path, class_name) in runtime_classes.items():
        try:
            resolved_classes[logical_name] = _load_class_from_module(
                import_name=import_name,
                file_path=file_path,
                class_name=class_name,
            )
            service_summary["services"][logical_name] = {
                "imported": True,
                "class_name": class_name,
                "module": import_name,
                "file": str(file_path),
            }
        except Exception as exc:
            service_failures[logical_name] = {
                "stage": "import",
                "error_type": _safe_exception_name(exc),
                "message": _safe_str(exc, "import_failed"),
                "module": import_name,
                "file": str(file_path),
                "class_name": class_name,
            }
            service_summary["services"][logical_name] = {
                "imported": False,
                "class_name": class_name,
                "module": import_name,
                "file": str(file_path),
                "error_type": _safe_exception_name(exc),
                "message": _safe_str(exc, "import_failed"),
            }

    orchestrator_client = None
    dataset_catalog_service = None
    dataset_source_service = None
    style_adapter = None

    # Orchestrator Client
    if "orchestrator_client" in resolved_classes:
        try:
            orchestrator_client_cls = resolved_classes["orchestrator_client"]
            orchestrator_client = orchestrator_client_cls(settings=settings)
            _store_runtime_service(app, _ORCHESTRATOR_CLIENT_EXTENSION_KEY, orchestrator_client)

            service_summary["services"]["orchestrator_client"].update(
                {
                    "initialized": True,
                    "summary": _service_summary_or_placeholder(
                        orchestrator_client,
                        "GeoServerOrchestratorClient",
                    ),
                }
            )
        except Exception as exc:
            service_failures["orchestrator_client"] = {
                "stage": "initialize",
                "error_type": _safe_exception_name(exc),
                "message": _safe_str(exc, "initialization_failed"),
            }
            service_summary["services"]["orchestrator_client"].update(
                {
                    "initialized": False,
                    "error_type": _safe_exception_name(exc),
                    "message": _safe_str(exc, "initialization_failed"),
                }
            )

    # Dataset Catalog Service
    if "dataset_catalog_service" in resolved_classes:
        try:
            dataset_catalog_service_cls = resolved_classes["dataset_catalog_service"]
            init_kwargs = {"settings": settings}
            if orchestrator_client is not None:
                init_kwargs["orchestrator_client"] = orchestrator_client

            dataset_catalog_service = dataset_catalog_service_cls(**init_kwargs)
            _store_runtime_service(app, _DATASET_CATALOG_SERVICE_EXTENSION_KEY, dataset_catalog_service)

            service_summary["services"]["dataset_catalog_service"].update(
                {
                    "initialized": True,
                    "summary": _service_summary_or_placeholder(
                        dataset_catalog_service,
                        "OpenLayerDatasetCatalogService",
                    ),
                }
            )
        except Exception as exc:
            service_failures["dataset_catalog_service"] = {
                "stage": "initialize",
                "error_type": _safe_exception_name(exc),
                "message": _safe_str(exc, "initialization_failed"),
            }
            service_summary["services"]["dataset_catalog_service"].update(
                {
                    "initialized": False,
                    "error_type": _safe_exception_name(exc),
                    "message": _safe_str(exc, "initialization_failed"),
                }
            )

    # Dataset Source Service
    if "dataset_source_service" in resolved_classes:
        try:
            dataset_source_service_cls = resolved_classes["dataset_source_service"]
            init_kwargs = {"settings": settings}
            if dataset_catalog_service is not None:
                init_kwargs["catalog_service"] = dataset_catalog_service
            if orchestrator_client is not None:
                init_kwargs["orchestrator_client"] = orchestrator_client

            dataset_source_service = dataset_source_service_cls(**init_kwargs)
            _store_runtime_service(app, _DATASET_SOURCE_SERVICE_EXTENSION_KEY, dataset_source_service)

            service_summary["services"]["dataset_source_service"].update(
                {
                    "initialized": True,
                    "summary": _service_summary_or_placeholder(
                        dataset_source_service,
                        "OpenLayerDatasetSourceService",
                    ),
                }
            )
        except Exception as exc:
            service_failures["dataset_source_service"] = {
                "stage": "initialize",
                "error_type": _safe_exception_name(exc),
                "message": _safe_str(exc, "initialization_failed"),
            }
            service_summary["services"]["dataset_source_service"].update(
                {
                    "initialized": False,
                    "error_type": _safe_exception_name(exc),
                    "message": _safe_str(exc, "initialization_failed"),
                }
            )

    # Style Adapter
    if "style_adapter" in resolved_classes:
        try:
            style_adapter_cls = resolved_classes["style_adapter"]
            init_kwargs = {"settings": settings}
            if dataset_catalog_service is not None:
                init_kwargs["catalog_service"] = dataset_catalog_service
            if orchestrator_client is not None:
                init_kwargs["orchestrator_client"] = orchestrator_client

            style_adapter = style_adapter_cls(**init_kwargs)
            _store_runtime_service(app, _STYLE_ADAPTER_EXTENSION_KEY, style_adapter)

            service_summary["services"]["style_adapter"].update(
                {
                    "initialized": True,
                    "summary": _service_summary_or_placeholder(
                        style_adapter,
                        "OpenLayerStyleAdapter",
                    ),
                }
            )
        except Exception as exc:
            service_failures["style_adapter"] = {
                "stage": "initialize",
                "error_type": _safe_exception_name(exc),
                "message": _safe_str(exc, "initialization_failed"),
            }
            service_summary["services"]["style_adapter"].update(
                {
                    "initialized": False,
                    "error_type": _safe_exception_name(exc),
                    "message": _safe_str(exc, "initialization_failed"),
                }
            )

    extensions[_SERVICE_INIT_SUMMARY_EXTENSION_KEY] = service_summary
    extensions[_SERVICE_FAILURES_EXTENSION_KEY] = service_failures

    try:
        app.logger.info(
            "runtime services initialized",
            extra={
                "services_initialized": {
                    key: value.get("initialized", False)
                    for key, value in service_summary.get("services", {}).items()
                    if isinstance(value, dict)
                }
            },
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# Helper: App Configuration / Headers
# ─────────────────────────────────────────────────────────────

def _apply_settings_to_app(app: Flask, settings: Settings) -> None:
    try:
        flask_config = settings.to_flask_config()
        if isinstance(flask_config, Mapping):
            app.config.update(dict(flask_config))
    except Exception:
        pass

    try:
        app.config["JSON_AS_ASCII"] = False
    except Exception:
        pass

    try:
        app.config["JSON_SORT_KEYS"] = False
    except Exception:
        pass

    try:
        app.config["TEMPLATES_AUTO_RELOAD"] = _safe_bool(getattr(settings, "flask_debug", False), False)
    except Exception:
        pass

    try:
        if _safe_bool(getattr(settings, "flask_debug", False), False):
            app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    except Exception:
        pass

    try:
        app.extensions[_SETTINGS_EXTENSION_KEY] = settings
    except Exception:
        pass


def _install_request_hooks(app: Flask, settings: Settings) -> None:
    @app.before_request
    def _handle_preflight() -> Response | None:
        try:
            if request.method == "OPTIONS":
                response = make_response("", 204)
                response.headers["Content-Length"] = "0"
                return response
        except Exception:
            return make_response("", 204)
        return None

    @app.after_request
    def _headers(response: Response) -> Response:
        try:
            origin = request.headers.get("Origin")
            allowed_origins = tuple(app.config.get("ALLOWED_ORIGINS", ["*"]))

            vary_values: list[str] = []
            existing_vary = response.headers.get("Vary", "")
            if existing_vary.strip():
                vary_values.extend([item.strip() for item in existing_vary.split(",") if item.strip()])

            if "Origin" not in vary_values:
                vary_values.append("Origin")
            response.headers["Vary"] = ", ".join(vary_values)

            if "*" in allowed_origins:
                response.headers["Access-Control-Allow-Origin"] = "*"
            elif origin:
                try:
                    checker = getattr(settings, "origin_is_allowed", None)
                    if callable(checker) and checker(origin):
                        response.headers["Access-Control-Allow-Origin"] = origin
                except Exception:
                    pass

            response.headers["Access-Control-Allow-Methods"] = "GET,HEAD,POST,OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
            response.headers["Access-Control-Max-Age"] = "86400"

            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

            # Absichtlich kein X-Frame-Options: DENY/SAMEORIGIN würde Iframe-Embedding stören.
        except Exception:
            pass

        return response


# ─────────────────────────────────────────────────────────────
# Helper: Builtin Routes / Runtime Payload
# ─────────────────────────────────────────────────────────────

def _runtime_payload(app: Flask, settings: Settings) -> dict[str, Any]:
    extensions = _ensure_extensions_dict(app)

    registered = extensions.get(_REGISTERED_BLUEPRINTS_KEY, [])
    failures = extensions.get(_BLUEPRINT_FAILURES_KEY, {})
    service_init_summary = extensions.get(_SERVICE_INIT_SUMMARY_EXTENSION_KEY, {})
    service_failures = extensions.get(_SERVICE_FAILURES_EXTENSION_KEY, {})

    try:
        payload = settings.to_public_dict()
    except Exception:
        payload = {}

    payload.update(
        {
            "hostname": _get_hostname(),
            "pid": _PROCESS_PID,
            "process_started_at": _PROCESS_STARTED_AT,
            "uptime_seconds": _uptime_seconds(),
            "registered_blueprints": list(registered) if isinstance(registered, list) else [],
            "blueprint_failures": dict(failures) if isinstance(failures, dict) else {},
            "service_init_summary": dict(service_init_summary) if isinstance(service_init_summary, dict) else {},
            "service_failures": dict(service_failures) if isinstance(service_failures, dict) else {},
        }
    )

    # Kurzzusammenfassungen der Services zusätzlich direkt anhängen
    try:
        orchestrator_client = extensions.get(_ORCHESTRATOR_CLIENT_EXTENSION_KEY)
        if orchestrator_client is not None:
            summary_fn = getattr(orchestrator_client, "get_client_summary", None)
            if callable(summary_fn):
                payload["orchestrator_client"] = summary_fn()
    except Exception:
        payload["orchestrator_client"] = {"error": "summary_failed"}

    try:
        dataset_catalog_service = extensions.get(_DATASET_CATALOG_SERVICE_EXTENSION_KEY)
        if dataset_catalog_service is not None:
            summary_fn = getattr(dataset_catalog_service, "get_service_summary", None)
            if callable(summary_fn):
                payload["dataset_catalog_service"] = summary_fn()
    except Exception:
        payload["dataset_catalog_service"] = {"error": "summary_failed"}

    try:
        dataset_source_service = extensions.get(_DATASET_SOURCE_SERVICE_EXTENSION_KEY)
        if dataset_source_service is not None:
            summary_fn = getattr(dataset_source_service, "get_service_summary", None)
            if callable(summary_fn):
                payload["dataset_source_service"] = summary_fn()
    except Exception:
        payload["dataset_source_service"] = {"error": "summary_failed"}

    try:
        style_adapter = extensions.get(_STYLE_ADAPTER_EXTENSION_KEY)
        if style_adapter is not None:
            summary_fn = getattr(style_adapter, "get_service_summary", None)
            if callable(summary_fn):
                payload["style_adapter"] = summary_fn()
    except Exception:
        payload["style_adapter"] = {"error": "summary_failed"}

    return payload


def _install_builtin_routes(app: Flask, settings: Settings) -> None:
    @app.route("/", methods=["GET"])
    def index() -> Response:
        try:
            return redirect(url_for("map.map_view"), code=302)
        except Exception:
            try:
                return redirect("/map", code=302)
            except Exception as exc:
                return _json_error(500, "redirect failed", detail=_safe_exception_name(exc))

    @app.route("/favicon.ico", methods=["GET"])
    def favicon() -> Response:
        try:
            return make_response("", 204)
        except Exception:
            return make_response("", 204)

    @app.route("/ping", methods=["GET", "HEAD"])
    def ping() -> Response:
        try:
            if request.method == "HEAD":
                return make_response("", 200)

            return _json_response(
                {
                    "status": "ok",
                    "pong": True,
                    "service": _safe_str(getattr(settings, "service_name", None), "openlayer"),
                    "version": _safe_str(getattr(settings, "service_version", None), ""),
                },
                status=200,
            )
        except Exception:
            return make_response("", 200)

    @app.route("/config", methods=["GET"])
    def config_dump() -> Response:
        try:
            return _json_response(_runtime_payload(app, settings), status=200)
        except Exception as exc:
            return _json_error(500, "config failed", detail=_safe_exception_name(exc))


# ─────────────────────────────────────────────────────────────
# Helper: Fallback Routes bei fehlenden Blueprints
# ─────────────────────────────────────────────────────────────

def _install_health_fallback(app: Flask, exc: Exception) -> None:
    @app.route("/health", methods=["GET", "HEAD"])
    def _health_fallback() -> Response:
        try:
            payload = {
                "status": "ok",
                "fallback": True,
                "warning": "health blueprint missing",
                "detail": _safe_exception_name(exc),
            }
            if request.method == "HEAD":
                return _json_response({"status": payload["status"]}, status=200)
            return _json_response(payload, status=200)
        except Exception:
            return make_response("", 200)

    @app.route("/ready", methods=["GET", "HEAD"])
    def _ready_fallback() -> Response:
        try:
            payload = {
                "status": "not_ready",
                "fallback": True,
                "warning": "ready blueprint missing",
                "detail": _safe_exception_name(exc),
            }
            if request.method == "HEAD":
                return _json_response({"status": payload["status"]}, status=503)
            return _json_response(payload, status=503)
        except Exception:
            return make_response("", 503)


def _install_map_fallback(app: Flask, exc: Exception) -> None:
    @app.route("/map", methods=["GET"])
    def _map_fallback() -> Response:
        return _json_error(
            500,
            "map route missing",
            detail=_safe_exception_name(exc),
            extra={"hint": "create routes/map.py with bp"},
        )


def _install_datasets_fallback(app: Flask, exc: Exception) -> None:
    @app.route("/api/datasets", methods=["GET"])
    def _datasets_fallback() -> Response:
        return _json_error(
            501,
            "datasets api not ready",
            detail=_safe_exception_name(exc),
            extra={
                "placeholder": True,
                "items": [],
                "hint": "create or fix routes/datasets.py with bp",
            },
        )

    @app.route("/api/datasets/<string:dataset_id>/changes", methods=["POST"])
    def _dataset_changes_fallback(dataset_id: str) -> Response:
        return _json_error(
            501,
            "dataset changes api not ready",
            detail=_safe_exception_name(exc),
            extra={
                "placeholder": True,
                "dataset_id": dataset_id,
                "hint": "later handled by datasets/changes route",
            },
        )


# ─────────────────────────────────────────────────────────────
# Helper: Error Handlers
# ─────────────────────────────────────────────────────────────

def _install_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def _e404(_e: Any) -> Response:
        return _json_error(404, "not found")

    @app.errorhandler(405)
    def _e405(_e: Any) -> Response:
        return _json_error(405, "method not allowed")

    @app.errorhandler(500)
    def _e500(_e: Any) -> Response:
        return _json_error(500, "internal server error")


# ─────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────

def create_app(test_config: Mapping[str, Any] | None = None) -> Flask:
    settings = _resolve_settings(test_config)

    app = Flask(
        __name__,
        static_folder=str(getattr(settings, "static_dir", SERVICE_ROOT / "static")),
        template_folder=str(getattr(settings, "templates_dir", SERVICE_ROOT / "templates")),
    )

    extensions = _ensure_extensions_dict(app)
    extensions[_REGISTERED_BLUEPRINTS_KEY] = []
    extensions[_BLUEPRINT_FAILURES_KEY] = {}
    extensions[_SERVICE_INIT_SUMMARY_EXTENSION_KEY] = {}
    extensions[_SERVICE_FAILURES_EXTENSION_KEY] = {}

    _apply_settings_to_app(app, settings)

    if test_config:
        try:
            app.config.update(dict(test_config))
        except Exception:
            pass

    _configure_logging(app, settings)
    _install_request_hooks(app, settings)
    _install_builtin_routes(app, settings)

    # Neue Runtime-Services früh initialisieren, damit Blueprints direkt darauf zugreifen können
    _initialize_runtime_services(app, settings)

    routes_dir = SERVICE_ROOT / "routes"

    # Pflicht-Blueprints
    _register_blueprint(
        app,
        import_name="routes.health",
        file_path=routes_dir / "health.py",
        label="health",
        required=True,
        on_failure=_install_health_fallback,
    )

    _register_blueprint(
        app,
        import_name="routes.map",
        file_path=routes_dir / "map.py",
        label="map",
        required=True,
        on_failure=_install_map_fallback,
    )

    # Optionaler Blueprint für Datensatzliste / Source / Changes
    if _safe_bool(getattr(settings, "dataset_api_enabled", False), False):
        _register_blueprint(
            app,
            import_name="routes.datasets",
            file_path=routes_dir / "datasets.py",
            label="datasets",
            required=False,
            on_failure=_install_datasets_fallback,
        )

    _install_error_handlers(app)

    try:
        app.logger.info(
            "OpenLayer app initialized",
            extra={
                "service": _safe_str(getattr(settings, "service_name", None), "openlayer"),
                "version": _safe_str(getattr(settings, "service_version", None), ""),
                "port": _safe_int(getattr(settings, "port", None), 0),
                "debug": _safe_bool(getattr(settings, "flask_debug", False), False),
                "dataset_api_enabled": _safe_bool(getattr(settings, "dataset_api_enabled", False), False),
                "editor_enabled": _safe_bool(getattr(settings, "editor_enabled", False), False),
            },
        )
    except Exception:
        pass

    return app


app = create_app()


if __name__ == "__main__":
    runtime_settings = get_settings()

    try:
        host = str(app.config.get("HOST", getattr(runtime_settings, "host", "0.0.0.0")))
    except Exception:
        host = _safe_str(getattr(runtime_settings, "host", None), "0.0.0.0") or "0.0.0.0"

    try:
        port = int(app.config.get("OPENLAYER_PORT", getattr(runtime_settings, "port", 8090)))
    except Exception:
        port = _safe_int(getattr(runtime_settings, "port", None), 8090)

    try:
        debug = bool(app.config.get("FLASK_DEBUG", getattr(runtime_settings, "flask_debug", False)))
    except Exception:
        debug = _safe_bool(getattr(runtime_settings, "flask_debug", False), False)

    app.run(host=host, port=port, debug=debug)