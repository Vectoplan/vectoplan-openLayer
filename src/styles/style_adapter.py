# services/openLayer/src/styles/style_adapter.py
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import re
from threading import RLock
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

try:
    from flask import current_app, has_app_context
except Exception:  # pragma: no cover
    current_app = None  # type: ignore

    def has_app_context() -> bool:  # type: ignore
        return False


try:
    from settings import Settings, get_settings
except Exception:  # pragma: no cover
    try:
        from ...settings import Settings, get_settings  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "src.styles.style_adapter konnte settings.py nicht importieren. "
            "Stelle sicher, dass Settings/get_settings verfügbar sind."
        ) from exc

try:
    from src.datasets.catalog_service import (
        OpenLayerDatasetCatalogError,
        OpenLayerDatasetEntry,
        OpenLayerDatasetNotFoundError,
        OpenLayerDatasetCatalogService,
        DatasetCatalogService,
    )
except Exception:  # pragma: no cover
    try:
        from ..datasets.catalog_service import (  # type: ignore
            OpenLayerDatasetCatalogError,
            OpenLayerDatasetEntry,
            OpenLayerDatasetNotFoundError,
            OpenLayerDatasetCatalogService,
            DatasetCatalogService,
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "src.styles.style_adapter konnte catalog_service.py nicht importieren. "
            "Stelle sicher, dass 'src/datasets/catalog_service.py' vorhanden ist."
        ) from exc

try:
    from src.orchestrator.client import (
        GeoServerOrchestratorClient,
        OrchestratorClient,
        OrchestratorClientError,
    )
except Exception:  # pragma: no cover
    try:
        from ..orchestrator.client import (  # type: ignore
            GeoServerOrchestratorClient,
            OrchestratorClient,
            OrchestratorClientError,
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "src.styles.style_adapter konnte den Orchestrator-Client nicht importieren. "
            "Stelle sicher, dass 'src/orchestrator/client.py' vorhanden ist."
        ) from exc


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

_DEFAULT_CACHE_TTL_SECONDS = 25
_DEFAULT_ALLOW_STALE_ON_ERROR = True
_DEFAULT_UNKNOWN_GEOMETRY = "Unknown"
_DEFAULT_STYLE_SOURCE = "geometry_fallback"
_DEFAULT_STYLE_MODE = "single_symbol"
_DEFAULT_RULE_MODE = "rule_based"

_HEX_COLOR_RE = re.compile(r"^#(?P<hex>[0-9a-fA-F]{3,8})$")
_RGBA_RE = re.compile(
    r"^rgba?\(\s*(?P<r>\d{1,3})\s*,\s*(?P<g>\d{1,3})\s*,\s*(?P<b>\d{1,3})(?:\s*,\s*(?P<a>[0-9.]+))?\s*\)$",
    re.IGNORECASE,
)

_POINT_DEFAULT_STYLE = {
    "kind": "point",
    "radius": 6,
    "fill_color": "rgba(255,210,0,0.98)",
    "stroke_color": "rgba(20,20,20,0.95)",
    "stroke_width": 2,
    "opacity": 1.0,
    "icon_url": None,
    "icon_scale": 1.0,
    "rotation": 0.0,
    "z_index": 0,
}

_LINE_DEFAULT_STYLE = {
    "kind": "line",
    "stroke_color": "rgba(0,229,255,0.95)",
    "stroke_width": 4,
    "line_dash": [],
    "line_cap": "round",
    "line_join": "round",
    "opacity": 1.0,
    "z_index": 0,
}

_POLYGON_DEFAULT_STYLE = {
    "kind": "polygon",
    "fill_color": "rgba(0,229,255,0.18)",
    "fill_opacity": 0.18,
    "stroke_color": "rgba(0,229,255,0.95)",
    "stroke_width": 2,
    "line_dash": [],
    "line_cap": "round",
    "line_join": "round",
    "opacity": 1.0,
    "z_index": 0,
}

_GENERIC_DEFAULT_STYLE = {
    "kind": "generic",
    "stroke_color": "rgba(0,229,255,0.95)",
    "stroke_width": 2,
    "fill_color": "rgba(0,229,255,0.18)",
    "fill_opacity": 0.18,
    "opacity": 1.0,
    "z_index": 0,
}


# ---------------------------------------------------------------------------
# Kleine Hilfsfunktionen
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    try:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _safe_str(value: Any, default: Optional[str] = None) -> Optional[str]:
    try:
        if value is None:
            return default
        text_value = str(value).strip()
        return text_value or default
    except Exception:
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
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
    try:
        return bool(value)
    except Exception:
        return bool(default)


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return default
        return int(str(value).strip())
    except Exception:
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return default
        return float(str(value).strip())
    except Exception:
        return default


def _deepcopy_or_value(value: Any) -> Any:
    try:
        return deepcopy(value)
    except Exception:
        return value


def _normalize_mapping(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    try:
        return {str(key): _deepcopy_or_value(item) for key, item in value.items()}
    except Exception:
        return {}


def _normalize_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_deepcopy_or_value(item) for item in value]
    if isinstance(value, tuple):
        return [_deepcopy_or_value(item) for item in list(value)]
    if isinstance(value, set):
        return [_deepcopy_or_value(item) for item in list(value)]
    try:
        return [_deepcopy_or_value(item) for item in list(value)]
    except Exception:
        return [_deepcopy_or_value(value)]


def _unique_texts(values: Sequence[Any]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()

    for item in values:
        normalized = _safe_str(item)
        if normalized is None:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)

    return result


def _get_nested(mapping: Any, *path: str, default: Any = None) -> Any:
    current = mapping
    try:
        for key in path:
            if not isinstance(current, Mapping):
                return default
            if key not in current:
                return default
            current = current.get(key)
        return current
    except Exception:
        return default


def _truncate_text(value: Optional[str], max_length: int = 600) -> Optional[str]:
    text_value = _safe_str(value)
    if text_value is None:
        return None
    if len(text_value) <= max_length:
        return text_value
    return text_value[:max_length] + "...<truncated>"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class OpenLayerStyleAdapterError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[BaseException] = None,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.details = deepcopy(details) if isinstance(details, dict) else {}
        self.original_exception = original_exception
        self.status_code = status_code

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "message": str(self),
            "details": deepcopy(self.details),
            "status_code": self.status_code,
            "error_type": self.__class__.__name__,
        }
        if self.original_exception is not None:
            payload["original_exception_type"] = self.original_exception.__class__.__name__
            payload["original_exception_message"] = str(self.original_exception)
        return payload


class OpenLayerStyleNotFoundError(OpenLayerStyleAdapterError):
    pass


class OpenLayerStylePayloadError(OpenLayerStyleAdapterError):
    pass


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class _ServiceCacheEntry:
    value: Any
    cached_at: datetime
    expires_at: Optional[datetime] = None

    @property
    def is_fresh(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at >= _utc_now()


@dataclass
class OpenLayerRuleStyle:
    rule_id: str
    title: str
    geometry_type: str
    filter_expression: Optional[str]
    min_scale: Optional[float]
    max_scale: Optional[float]
    style: Dict[str, Any] = field(default_factory=dict)
    label: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def add_warning(self, message: str) -> None:
        normalized = _safe_str(message)
        if normalized and normalized not in self.warnings:
            self.warnings.append(normalized)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "geometry_type": self.geometry_type,
            "filter_expression": self.filter_expression,
            "min_scale": self.min_scale,
            "max_scale": self.max_scale,
            "style": deepcopy(self.style),
            "label": deepcopy(self.label),
            "metadata": deepcopy(self.metadata),
            "warnings": list(self.warnings),
        }


@dataclass
class OpenLayerDatasetStyleContract:
    dataset_id: str
    available: bool
    valid: bool
    fallback: bool
    source: str
    mode: str
    geometry_type: str
    style_id: Optional[str] = None
    style_url: Optional[str] = None
    style_path: Optional[str] = None
    rule_count: int = 0
    default_style: Dict[str, Any] = field(default_factory=dict)
    rules: List[OpenLayerRuleStyle] = field(default_factory=list)
    label: Optional[Dict[str, Any]] = None
    legend: Dict[str, Any] = field(default_factory=dict)
    validation: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    raw_style: Optional[Dict[str, Any]] = None
    built_at: datetime = field(default_factory=_utc_now)

    def add_warning(self, message: str) -> None:
        normalized = _safe_str(message)
        if normalized and normalized not in self.warnings:
            self.warnings.append(normalized)

    def add_error(self, message: str) -> None:
        normalized = _safe_str(message)
        if normalized and normalized not in self.errors:
            self.errors.append(normalized)

    def add_note(self, message: str) -> None:
        normalized = _safe_str(message)
        if normalized and normalized not in self.notes:
            self.notes.append(normalized)

    def to_dict(
        self,
        *,
        include_rules: bool = True,
        include_raw_style: bool = False,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "dataset_id": self.dataset_id,
            "available": self.available,
            "valid": self.valid,
            "fallback": self.fallback,
            "source": self.source,
            "mode": self.mode,
            "geometry_type": self.geometry_type,
            "style_id": self.style_id,
            "style_url": self.style_url,
            "style_path": self.style_path,
            "rule_count": self.rule_count,
            "default_style": deepcopy(self.default_style),
            "label": deepcopy(self.label),
            "legend": deepcopy(self.legend),
            "validation": deepcopy(self.validation),
            "metadata": deepcopy(self.metadata),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "notes": list(self.notes),
            "built_at": _dt_to_iso(self.built_at),
        }

        if include_rules:
            payload["rules"] = [item.to_dict() for item in self.rules]

        if include_raw_style:
            payload["raw_style"] = deepcopy(self.raw_style)

        return payload


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class OpenLayerStyleAdapter:
    """
    Adapter zwischen Orchestrator-Style-Payloads und einem stabilen
    OpenLayer-Stylevertrag.

    Ziele:
    - OpenLayer-Frontend kennt keine rohen Orchestrator-Style-Interna
    - robuste Fallback-Styles pro Geometrietyp
    - kleine TTL-Caches + stale fallback
    - tolerante Normalisierung vieler möglicher Style-Strukturen
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        catalog_service: Optional[OpenLayerDatasetCatalogService] = None,
        orchestrator_client: Optional[GeoServerOrchestratorClient] = None,
        enable_cache: bool = True,
        cache_ttl_seconds: Optional[int] = None,
        allow_stale_on_error: bool = _DEFAULT_ALLOW_STALE_ON_ERROR,
    ) -> None:
        self.settings = settings or self._settings()
        self.enable_cache = _safe_bool(enable_cache, True)
        self.allow_stale_on_error = _safe_bool(allow_stale_on_error, _DEFAULT_ALLOW_STALE_ON_ERROR)

        self.catalog_service = catalog_service or DatasetCatalogService(settings=self.settings)
        self.orchestrator_client = (
            orchestrator_client
            or getattr(self.catalog_service, "orchestrator_client", None)
            or OrchestratorClient(settings=self.settings)
        )

        self.cache_ttl_seconds = self._resolve_cache_ttl_seconds(
            cache_ttl_seconds,
            self.settings,
            fallback=_DEFAULT_CACHE_TTL_SECONDS,
            attr_candidates=(
                "style_adapter_cache_ttl_seconds",
                "openlayer_style_adapter_cache_ttl_seconds",
                "openlayer_dataset_style_cache_ttl_seconds",
            ),
        )

        self._cache_lock = RLock()
        self._style_cache: Dict[str, _ServiceCacheEntry] = {}
        self._summary_cache: Dict[str, Dict[str, Any]] = {}

    # ---------------------------------------------------------------------
    # Öffentliche Diagnose / Cache
    # ---------------------------------------------------------------------

    def clear_caches(self) -> None:
        with self._cache_lock:
            self._style_cache.clear()
            self._summary_cache.clear()

    def get_service_summary(self) -> Dict[str, Any]:
        cache_key = "service_summary"

        with self._cache_lock:
            cached = self._summary_cache.get(cache_key)
            if isinstance(cached, dict):
                return deepcopy(cached)

        summary = {
            "service_type": type(self).__name__,
            "enable_cache": self.enable_cache,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "allow_stale_on_error": self.allow_stale_on_error,
            "cache_size": self._get_cache_size(),
            "catalog_service_summary": self._safe_catalog_service_summary(),
            "orchestrator_client_summary": self._safe_orchestrator_client_summary(),
        }

        with self._cache_lock:
            self._summary_cache[cache_key] = deepcopy(summary)

        return summary

    # ---------------------------------------------------------------------
    # Öffentliche API
    # ---------------------------------------------------------------------

    def get_dataset_style(
        self,
        dataset_id: str,
        *,
        use_cache: bool = True,
        include_rules: bool = True,
        include_raw_style: bool = False,
        enrich_with_db: bool = False,
    ) -> OpenLayerDatasetStyleContract:
        normalized_dataset_id = self._sanitize_dataset_id(dataset_id)
        if not normalized_dataset_id:
            raise OpenLayerStyleAdapterError(
                "dataset_id darf nicht leer sein.",
                details={"dataset_id": dataset_id},
            )

        cache_key = self._build_style_cache_key(
            dataset_id=normalized_dataset_id,
            include_rules=include_rules,
            include_raw_style=include_raw_style,
            enrich_with_db=enrich_with_db,
        )

        if self.enable_cache and use_cache:
            cached = self._get_style_cache_entry(cache_key, require_fresh=True)
            if isinstance(cached, OpenLayerDatasetStyleContract):
                return _deepcopy_or_value(cached)

        stale = None
        if self.enable_cache and self.allow_stale_on_error:
            stale = self._get_style_cache_entry(cache_key, require_fresh=False)

        try:
            dataset_entry = self.catalog_service.get_dataset(
                normalized_dataset_id,
                include_style_details=True,
                enrich_with_db=enrich_with_db,
                use_cache=use_cache,
            )

            contract = self.adapt_from_dataset_entry(
                dataset_entry,
                include_rules=include_rules,
                include_raw_style=include_raw_style,
                use_cache=use_cache,
            )

            if self.enable_cache and use_cache:
                self._set_style_cache_entry(cache_key, contract, self.cache_ttl_seconds)

            return _deepcopy_or_value(contract)

        except OpenLayerDatasetNotFoundError as exc:
            raise OpenLayerStyleNotFoundError(
                f"Dataset '{normalized_dataset_id}' wurde nicht gefunden.",
                details={"dataset_id": normalized_dataset_id},
                original_exception=exc,
                status_code=404,
            ) from exc

        except Exception as exc:
            if isinstance(stale, OpenLayerDatasetStyleContract):
                stale.add_warning(
                    f"Es wird ein stale Style-Cache verwendet, weil der Live-Abruf fehlgeschlagen ist: {exc}"
                )
                self._log_warning(
                    "Nutze stale Style-Cache für Dataset '%s' nach Fehler: %s",
                    normalized_dataset_id,
                    exc,
                )
                return stale

            raise OpenLayerStyleAdapterError(
                f"Der Style für Dataset '{normalized_dataset_id}' konnte nicht aufgebaut werden: {exc}",
                details={
                    "dataset_id": normalized_dataset_id,
                    "include_rules": include_rules,
                    "include_raw_style": include_raw_style,
                },
                original_exception=exc,
                status_code=getattr(exc, "status_code", None),
            ) from exc

    def get_dataset_style_dict(self, dataset_id: str, **kwargs: Any) -> Dict[str, Any]:
        include_rules = _safe_bool(kwargs.pop("include_rules", True), True)
        include_raw_style = _safe_bool(kwargs.pop("include_raw_style", False), False)

        contract = self.get_dataset_style(
            dataset_id,
            include_rules=include_rules,
            include_raw_style=include_raw_style,
            **kwargs,
        )
        return contract.to_dict(
            include_rules=include_rules,
            include_raw_style=include_raw_style,
        )

    def adapt_from_dataset_entry(
        self,
        dataset_entry: OpenLayerDatasetEntry,
        *,
        include_rules: bool = True,
        include_raw_style: bool = False,
        use_cache: bool = True,
    ) -> OpenLayerDatasetStyleContract:
        if not isinstance(dataset_entry, OpenLayerDatasetEntry):
            raise OpenLayerStyleAdapterError(
                "dataset_entry muss vom Typ OpenLayerDatasetEntry sein.",
                details={"actual_type": type(dataset_entry).__name__},
            )

        style_block = _normalize_mapping(getattr(dataset_entry, "style", {}))
        raw_style_payload = _normalize_mapping(style_block.get("payload"))
        style_url = _safe_str(style_block.get("orchestrator_url"))
        style_path = _safe_str(style_block.get("path"))
        geometry_type = self._normalize_geometry_type(
            _safe_str(style_block.get("geometry")) or _safe_str(getattr(dataset_entry, "geometry_type", None))
        )

        if raw_style_payload:
            contract = self._adapt_style_payload(
                dataset_id=dataset_entry.dataset_id,
                raw_style_payload=raw_style_payload,
                dataset_entry=dataset_entry,
                style_url=style_url,
                style_path=style_path,
                geometry_type=geometry_type,
                include_rules=include_rules,
                include_raw_style=include_raw_style,
                source="catalog_embedded_style_payload",
                valid=_safe_bool(style_block.get("valid"), True),
            )
            contract.add_note("Style aus dem eingebetteten Dataset-Style-Payload abgeleitet.")
            return contract

        style_available = _safe_bool(style_block.get("available"), False)
        if style_available:
            try:
                style_envelope = self.orchestrator_client.get_style_envelope(
                    dataset_entry.dataset_id,
                    strict_validation=False,
                    include_validation_report=True,
                    include_catalog=False,
                    enrich_with_db=False,
                    include_issues=True,
                    include_rules=True,
                    include_raw_payload=False,
                    use_cache=use_cache,
                    allow_stale_on_error=self.allow_stale_on_error,
                )
                contract = self.adapt_from_style_envelope(
                    dataset_id=dataset_entry.dataset_id,
                    style_envelope=style_envelope,
                    dataset_entry=dataset_entry,
                    include_rules=include_rules,
                    include_raw_style=include_raw_style,
                )
                contract.add_note("Style aus dem Orchestrator-Style-Envelope abgeleitet.")
                return contract
            except OrchestratorClientError as exc:
                self._log_warning(
                    "Style-Envelope für Dataset '%s' konnte nicht geladen werden: %s",
                    dataset_entry.dataset_id,
                    exc,
                )

        contract = self._build_fallback_contract(
            dataset_id=dataset_entry.dataset_id,
            geometry_type=geometry_type,
            style_url=style_url,
            style_path=style_path,
            available=style_available,
            valid=_safe_bool(style_block.get("valid"), False),
            warnings=list(getattr(dataset_entry, "warnings", []) or []),
            errors=list(getattr(dataset_entry, "errors", []) or []),
            notes=[
                "Fallback-Style wird verwendet, weil kein nutzbares Style-Payload verfügbar ist."
            ],
            include_raw_style=include_raw_style,
        )
        return contract

    def adapt_from_style_envelope(
        self,
        *,
        dataset_id: str,
        style_envelope: Mapping[str, Any],
        dataset_entry: Optional[OpenLayerDatasetEntry] = None,
        include_rules: bool = True,
        include_raw_style: bool = False,
    ) -> OpenLayerDatasetStyleContract:
        normalized_dataset_id = self._sanitize_dataset_id(dataset_id)
        if not normalized_dataset_id:
            raise OpenLayerStyleAdapterError(
                "dataset_id darf nicht leer sein.",
                details={"dataset_id": dataset_id},
            )

        envelope = _normalize_mapping(style_envelope)
        if not envelope:
            raise OpenLayerStylePayloadError(
                f"Das Style-Envelope für Dataset '{normalized_dataset_id}' ist leer oder ungültig.",
                details={"dataset_id": normalized_dataset_id},
            )

        raw_style_payload = _normalize_mapping(envelope.get("style"))
        if not raw_style_payload:
            raise OpenLayerStylePayloadError(
                f"Das Style-Envelope für Dataset '{normalized_dataset_id}' enthält kein gültiges 'style'-Objekt.",
                details={
                    "dataset_id": normalized_dataset_id,
                    "keys": sorted(list(envelope.keys())),
                },
            )

        geometry_type = self._normalize_geometry_type(
            _safe_str(envelope.get("geometry"))
            or _safe_str(_get_nested(envelope, "style", "geometry"))
            or _safe_str(getattr(dataset_entry, "geometry_type", None))
        )

        style_url = _safe_str(envelope.get("style_url"))
        if not style_url and dataset_entry is not None:
            try:
                style_url = _safe_str(getattr(dataset_entry, "style", {}).get("orchestrator_url"))  # type: ignore[union-attr]
            except Exception:
                style_url = None

        style_path = _safe_str(envelope.get("style_path"))

        validation_report = _normalize_mapping(envelope.get("validation_report"))
        valid = _safe_bool(validation_report.get("is_valid"), None) if validation_report else True
        if valid is None:
            valid = True

        contract = self._adapt_style_payload(
            dataset_id=normalized_dataset_id,
            raw_style_payload=raw_style_payload,
            dataset_entry=dataset_entry,
            style_url=style_url,
            style_path=style_path,
            geometry_type=geometry_type,
            include_rules=include_rules,
            include_raw_style=include_raw_style,
            source="orchestrator_style_envelope",
            valid=valid,
        )

        if validation_report:
            contract.validation = self._build_validation_payload(validation_report)
            for item in _normalize_list(validation_report.get("warnings")):
                contract.add_warning(_safe_str(item) or str(item))
            for item in _normalize_list(validation_report.get("errors")):
                contract.add_error(_safe_str(item) or str(item))

        for item in _normalize_list(envelope.get("warnings")):
            contract.add_warning(_safe_str(item) or str(item))

        for item in _normalize_list(envelope.get("errors")):
            contract.add_error(_safe_str(item) or str(item))

        contract.style_id = _safe_str(envelope.get("style_id")) or contract.style_id
        contract.rule_count = _safe_int(envelope.get("rule_count"), contract.rule_count) or contract.rule_count

        return contract

    # ---------------------------------------------------------------------
    # Interne Style-Adaption
    # ---------------------------------------------------------------------

    def _adapt_style_payload(
        self,
        *,
        dataset_id: str,
        raw_style_payload: Mapping[str, Any],
        dataset_entry: Optional[OpenLayerDatasetEntry],
        style_url: Optional[str],
        style_path: Optional[str],
        geometry_type: str,
        include_rules: bool,
        include_raw_style: bool,
        source: str,
        valid: bool,
    ) -> OpenLayerDatasetStyleContract:
        style_payload = _normalize_mapping(raw_style_payload)
        effective_geometry_type = self._normalize_geometry_type(
            _safe_str(style_payload.get("geometry"))
            or _safe_str(style_payload.get("geometry_type"))
            or _safe_str(dataset_entry.geometry_type) if dataset_entry is not None else geometry_type
        )
        if effective_geometry_type == _DEFAULT_UNKNOWN_GEOMETRY:
            effective_geometry_type = geometry_type

        rules_payload = _normalize_list(style_payload.get("rules"))
        adapted_rules: List[OpenLayerRuleStyle] = []

        if include_rules:
            for index, raw_rule in enumerate(rules_payload):
                if not isinstance(raw_rule, Mapping):
                    continue
                try:
                    rule_contract = self._adapt_rule_payload(
                        dataset_id=dataset_id,
                        raw_rule=_normalize_mapping(raw_rule),
                        rule_index=index,
                        fallback_geometry_type=effective_geometry_type,
                    )
                    adapted_rules.append(rule_contract)
                except Exception as exc:
                    fallback_rule = OpenLayerRuleStyle(
                        rule_id=f"rule-{index + 1}",
                        title=f"Regel {index + 1}",
                        geometry_type=effective_geometry_type,
                        filter_expression=None,
                        min_scale=None,
                        max_scale=None,
                        style=self._build_fallback_symbolizer(effective_geometry_type),
                        label=None,
                        metadata={"adaptation_error": str(exc)},
                        warnings=[f"Regel {index + 1} konnte nicht vollständig adaptiert werden: {exc}"],
                    )
                    adapted_rules.append(fallback_rule)

        default_style = self._adapt_default_symbolizer(
            raw_style_payload=style_payload,
            geometry_type=effective_geometry_type,
            fallback_rules=adapted_rules,
        )

        label_payload = self._adapt_label_payload(
            raw_style_payload=style_payload,
            geometry_type=effective_geometry_type,
        )

        contract = OpenLayerDatasetStyleContract(
            dataset_id=dataset_id,
            available=True,
            valid=bool(valid),
            fallback=False,
            source=source,
            mode=_DEFAULT_RULE_MODE if adapted_rules else _DEFAULT_STYLE_MODE,
            geometry_type=effective_geometry_type,
            style_id=_safe_str(style_payload.get("style_id")) or _safe_str(style_payload.get("id")),
            style_url=style_url,
            style_path=style_path,
            rule_count=len(adapted_rules) if adapted_rules else len(rules_payload),
            default_style=default_style,
            rules=adapted_rules if include_rules else [],
            label=label_payload,
            legend=self._build_legend_payload(style_payload),
            validation={},
            metadata=self._build_metadata_payload(
                style_payload=style_payload,
                dataset_entry=dataset_entry,
                effective_geometry_type=effective_geometry_type,
            ),
            warnings=[],
            errors=[],
            notes=[],
            raw_style=deepcopy(style_payload) if include_raw_style else None,
            built_at=_utc_now(),
        )

        for item in _normalize_list(style_payload.get("warnings")):
            contract.add_warning(_safe_str(item) or str(item))

        for item in _normalize_list(style_payload.get("errors")):
            contract.add_error(_safe_str(item) or str(item))

        if contract.geometry_type == _DEFAULT_UNKNOWN_GEOMETRY:
            contract.add_warning("Geometrietyp konnte aus dem Style nicht sicher abgeleitet werden.")

        if not adapted_rules and len(rules_payload) > 0:
            contract.add_warning("Style-Regeln waren vorhanden, wurden aber nicht in einzelne Rule-Styles überführt.")

        if include_raw_style:
            contract.add_note("Rohes Style-Payload wurde in den Vertrag übernommen.")

        return contract

    def _adapt_rule_payload(
        self,
        *,
        dataset_id: str,
        raw_rule: Mapping[str, Any],
        rule_index: int,
        fallback_geometry_type: str,
    ) -> OpenLayerRuleStyle:
        geometry_type = self._normalize_geometry_type(
            _safe_str(raw_rule.get("geometry"))
            or _safe_str(raw_rule.get("geometry_type"))
            or fallback_geometry_type
        )

        title = (
            _safe_str(raw_rule.get("title"))
            or _safe_str(raw_rule.get("name"))
            or f"Regel {rule_index + 1}"
        )
        rule_id = _safe_str(raw_rule.get("id")) or f"rule-{rule_index + 1}"
        filter_expression = (
            _safe_str(raw_rule.get("filter"))
            or _safe_str(raw_rule.get("expression"))
            or _safe_str(raw_rule.get("where"))
        )

        min_scale = (
            _safe_float(raw_rule.get("min_scale"), None)
            or _safe_float(raw_rule.get("minScale"), None)
        )
        max_scale = (
            _safe_float(raw_rule.get("max_scale"), None)
            or _safe_float(raw_rule.get("maxScale"), None)
        )

        style = self._build_symbolizer_from_mapping(
            mapping=raw_rule,
            geometry_type=geometry_type,
            parent_mapping=raw_rule,
        )
        label = self._adapt_label_payload(raw_rule, geometry_type=geometry_type)

        metadata = {
            "dataset_id": dataset_id,
            "rule_index": rule_index,
            "raw_keys": sorted(list(raw_rule.keys())),
        }

        result = OpenLayerRuleStyle(
            rule_id=rule_id,
            title=title,
            geometry_type=geometry_type,
            filter_expression=filter_expression,
            min_scale=min_scale,
            max_scale=max_scale,
            style=style,
            label=label,
            metadata=metadata,
            warnings=[],
        )

        if filter_expression is None:
            result.add_warning("Regel enthält keinen expliziten Filterausdruck.")

        return result

    def _adapt_default_symbolizer(
        self,
        *,
        raw_style_payload: Mapping[str, Any],
        geometry_type: str,
        fallback_rules: Sequence[OpenLayerRuleStyle],
    ) -> Dict[str, Any]:
        if fallback_rules:
            first_rule = fallback_rules[0]
            if isinstance(first_rule.style, dict) and first_rule.style:
                return deepcopy(first_rule.style)

        return self._build_symbolizer_from_mapping(
            mapping=raw_style_payload,
            geometry_type=geometry_type,
            parent_mapping=raw_style_payload,
        )

    def _adapt_label_payload(
        self,
        raw_style_payload: Mapping[str, Any],
        *,
        geometry_type: str,
    ) -> Optional[Dict[str, Any]]:
        label_candidates = [
            _normalize_mapping(raw_style_payload.get("label")),
            _normalize_mapping(raw_style_payload.get("labels")),
            _normalize_mapping(raw_style_payload.get("text")),
            _normalize_mapping(raw_style_payload.get("annotation")),
        ]

        merged: Dict[str, Any] = {}
        for candidate in label_candidates:
            if candidate:
                merged.update(candidate)

        field_name = (
            _safe_str(merged.get("field"))
            or _safe_str(merged.get("attribute"))
            or _safe_str(merged.get("property"))
            or _safe_str(merged.get("text_field"))
            or _safe_str(raw_style_payload.get("label_field"))
            or _safe_str(raw_style_payload.get("text_field"))
        )

        if not field_name:
            return None

        color = self._normalize_css_color(
            merged.get("color"),
            fallback="rgba(20,20,20,0.95)",
        )
        halo_color = self._normalize_css_color(
            merged.get("halo_color") or merged.get("outline_color"),
            fallback="rgba(255,255,255,0.92)",
        )

        label = {
            "enabled": True,
            "field": field_name,
            "color": color,
            "font_size": max(8, _safe_int(merged.get("font_size"), 12) or 12),
            "font_family": _safe_str(merged.get("font_family"), "sans-serif") or "sans-serif",
            "font_weight": _safe_str(merged.get("font_weight"), "normal") or "normal",
            "halo_color": halo_color,
            "halo_width": max(0, _safe_float(merged.get("halo_width"), 2.0) or 2.0),
            "offset_x": _safe_float(merged.get("offset_x"), 0.0) or 0.0,
            "offset_y": _safe_float(merged.get("offset_y"), 0.0) or 0.0,
            "geometry_type": geometry_type,
        }

        return label

    def _build_symbolizer_from_mapping(
        self,
        *,
        mapping: Mapping[str, Any],
        geometry_type: str,
        parent_mapping: Mapping[str, Any],
    ) -> Dict[str, Any]:
        effective_geometry_type = self._normalize_geometry_type(geometry_type)
        base = self._build_fallback_symbolizer(effective_geometry_type)

        candidate_blocks = self._collect_symbolizer_candidates(
            mapping=mapping,
            parent_mapping=parent_mapping,
            geometry_type=effective_geometry_type,
        )

        result = deepcopy(base)
        for block in candidate_blocks:
            result = self._merge_symbolizer_from_block(
                base_symbolizer=result,
                block=block,
                geometry_type=effective_geometry_type,
            )

        result["kind"] = self._style_kind_for_geometry(effective_geometry_type)
        return result

    def _collect_symbolizer_candidates(
        self,
        *,
        mapping: Mapping[str, Any],
        parent_mapping: Mapping[str, Any],
        geometry_type: str,
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []

        blocks_to_try = [
            _normalize_mapping(mapping),
            _normalize_mapping(mapping.get("style")),
            _normalize_mapping(mapping.get("symbolizer")),
            _normalize_mapping(mapping.get("paint")),
            _normalize_mapping(mapping.get("render")),
            _normalize_mapping(mapping.get("renderer")),
            _normalize_mapping(mapping.get("default")),
            _normalize_mapping(mapping.get("default_style")),
        ]

        geometry_lookup = geometry_type.lower()
        if geometry_lookup in {"point", "multipoint"}:
            blocks_to_try.extend(
                [
                    _normalize_mapping(mapping.get("point")),
                    _normalize_mapping(mapping.get("marker")),
                    _normalize_mapping(mapping.get("circle")),
                ]
            )
        elif geometry_lookup in {"linestring", "multilinestring"}:
            blocks_to_try.extend(
                [
                    _normalize_mapping(mapping.get("line")),
                    _normalize_mapping(mapping.get("stroke")),
                ]
            )
        elif geometry_lookup in {"polygon", "multipolygon"}:
            blocks_to_try.extend(
                [
                    _normalize_mapping(mapping.get("polygon")),
                    _normalize_mapping(mapping.get("fill")),
                    _normalize_mapping(mapping.get("area")),
                ]
            )

        if parent_mapping is not mapping:
            blocks_to_try.extend(
                [
                    _normalize_mapping(parent_mapping.get("style")),
                    _normalize_mapping(parent_mapping.get("symbolizer")),
                    _normalize_mapping(parent_mapping.get("paint")),
                ]
            )

        seen_keys: set[str] = set()
        for block in blocks_to_try:
            if not block:
                continue
            key = self._serialize_mapping_key(block)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            candidates.append(block)

        return candidates

    def _merge_symbolizer_from_block(
        self,
        *,
        base_symbolizer: Dict[str, Any],
        block: Mapping[str, Any],
        geometry_type: str,
    ) -> Dict[str, Any]:
        result = deepcopy(base_symbolizer)
        kind = self._style_kind_for_geometry(geometry_type)

        color_value = (
            block.get("color")
            or block.get("fill_color")
            or block.get("fillColor")
            or block.get("stroke_color")
            or block.get("strokeColor")
        )

        opacity = self._normalize_opacity(
            block.get("opacity")
            or block.get("fill_opacity")
            or block.get("fillOpacity")
            or 1.0,
            fallback=1.0,
        )

        if kind == "point":
            radius = max(
                1,
                _safe_int(
                    block.get("radius")
                    or block.get("size")
                    or block.get("circle_radius")
                    or block.get("point_radius"),
                    result.get("radius", 6),
                ) or 6,
            )
            result["radius"] = radius
            result["fill_color"] = self._normalize_css_color(
                block.get("fill_color")
                or block.get("fillColor")
                or block.get("fill")
                or block.get("color")
                or color_value,
                opacity=opacity,
                fallback=result.get("fill_color"),
            )
            result["stroke_color"] = self._normalize_css_color(
                block.get("stroke_color")
                or block.get("strokeColor")
                or block.get("stroke")
                or block.get("outline_color")
                or block.get("outlineColor"),
                opacity=1.0,
                fallback=result.get("stroke_color"),
            )
            result["stroke_width"] = max(
                0,
                _safe_float(
                    block.get("stroke_width")
                    or block.get("strokeWidth")
                    or block.get("outline_width")
                    or block.get("outlineWidth"),
                    result.get("stroke_width", 2),
                ) or 2.0,
            )
            result["opacity"] = opacity
            result["icon_url"] = _safe_str(block.get("icon_url") or block.get("iconUrl")) or result.get("icon_url")
            result["icon_scale"] = max(
                0.01,
                _safe_float(block.get("icon_scale") or block.get("iconScale"), result.get("icon_scale", 1.0)) or 1.0,
            )
            result["rotation"] = _safe_float(block.get("rotation"), result.get("rotation", 0.0)) or 0.0

        elif kind == "line":
            result["stroke_color"] = self._normalize_css_color(
                block.get("stroke_color")
                or block.get("strokeColor")
                or block.get("stroke")
                or block.get("line_color")
                or block.get("lineColor")
                or block.get("color")
                or color_value,
                opacity=opacity,
                fallback=result.get("stroke_color"),
            )
            result["stroke_width"] = max(
                0,
                _safe_float(
                    block.get("stroke_width")
                    or block.get("strokeWidth")
                    or block.get("width")
                    or block.get("line_width")
                    or block.get("lineWidth"),
                    result.get("stroke_width", 4),
                ) or 4.0,
            )
            result["line_dash"] = self._normalize_line_dash(
                block.get("line_dash")
                or block.get("lineDash")
                or block.get("dasharray")
                or block.get("stroke_dasharray"),
                fallback=result.get("line_dash", []),
            )
            result["line_cap"] = _safe_str(block.get("line_cap") or block.get("lineCap"), result.get("line_cap")) or result.get("line_cap")
            result["line_join"] = _safe_str(block.get("line_join") or block.get("lineJoin"), result.get("line_join")) or result.get("line_join")
            result["opacity"] = opacity

        elif kind == "polygon":
            fill_opacity = self._normalize_opacity(
                block.get("fill_opacity")
                or block.get("fillOpacity")
                or block.get("opacity")
                or result.get("fill_opacity", 0.18),
                fallback=result.get("fill_opacity", 0.18),
            )
            result["fill_opacity"] = fill_opacity
            result["fill_color"] = self._normalize_css_color(
                block.get("fill_color")
                or block.get("fillColor")
                or block.get("fill")
                or block.get("color")
                or color_value,
                opacity=fill_opacity,
                fallback=result.get("fill_color"),
            )
            result["stroke_color"] = self._normalize_css_color(
                block.get("stroke_color")
                or block.get("strokeColor")
                or block.get("stroke")
                or block.get("outline_color")
                or block.get("outlineColor"),
                opacity=1.0,
                fallback=result.get("stroke_color"),
            )
            result["stroke_width"] = max(
                0,
                _safe_float(
                    block.get("stroke_width")
                    or block.get("strokeWidth")
                    or block.get("outline_width")
                    or block.get("outlineWidth")
                    or block.get("width"),
                    result.get("stroke_width", 2),
                ) or 2.0,
            )
            result["line_dash"] = self._normalize_line_dash(
                block.get("line_dash")
                or block.get("lineDash")
                or block.get("dasharray")
                or block.get("stroke_dasharray"),
                fallback=result.get("line_dash", []),
            )
            result["line_cap"] = _safe_str(block.get("line_cap") or block.get("lineCap"), result.get("line_cap")) or result.get("line_cap")
            result["line_join"] = _safe_str(block.get("line_join") or block.get("lineJoin"), result.get("line_join")) or result.get("line_join")
            result["opacity"] = opacity

        else:
            result["stroke_color"] = self._normalize_css_color(
                block.get("stroke_color")
                or block.get("strokeColor")
                or block.get("stroke")
                or block.get("color")
                or color_value,
                opacity=opacity,
                fallback=result.get("stroke_color"),
            )
            result["fill_color"] = self._normalize_css_color(
                block.get("fill_color")
                or block.get("fillColor")
                or block.get("fill")
                or block.get("color"),
                opacity=self._normalize_opacity(block.get("fill_opacity"), fallback=result.get("fill_opacity", 0.18)),
                fallback=result.get("fill_color"),
            )
            result["fill_opacity"] = self._normalize_opacity(
                block.get("fill_opacity"),
                fallback=result.get("fill_opacity", 0.18),
            )
            result["stroke_width"] = max(
                0,
                _safe_float(block.get("stroke_width") or block.get("width"), result.get("stroke_width", 2)) or 2.0,
            )
            result["opacity"] = opacity

        result["z_index"] = _safe_int(block.get("z_index") or block.get("zIndex"), result.get("z_index", 0)) or 0
        return result

    def _build_fallback_contract(
        self,
        *,
        dataset_id: str,
        geometry_type: str,
        style_url: Optional[str],
        style_path: Optional[str],
        available: bool,
        valid: bool,
        warnings: Sequence[Any],
        errors: Sequence[Any],
        notes: Sequence[Any],
        include_raw_style: bool,
    ) -> OpenLayerDatasetStyleContract:
        effective_geometry_type = self._normalize_geometry_type(geometry_type)
        default_style = self._build_fallback_symbolizer(effective_geometry_type)

        contract = OpenLayerDatasetStyleContract(
            dataset_id=dataset_id,
            available=available,
            valid=valid,
            fallback=True,
            source=_DEFAULT_STYLE_SOURCE,
            mode=_DEFAULT_STYLE_MODE,
            geometry_type=effective_geometry_type,
            style_id=None,
            style_url=style_url,
            style_path=style_path,
            rule_count=0,
            default_style=default_style,
            rules=[],
            label=None,
            legend={},
            validation={},
            metadata={
                "style_kind": self._style_kind_for_geometry(effective_geometry_type),
                "fallback_reason": "no_usable_style_payload",
            },
            warnings=[],
            errors=[],
            notes=[],
            raw_style={} if include_raw_style else None,
            built_at=_utc_now(),
        )

        for item in warnings:
            contract.add_warning(_safe_str(item) or str(item))
        for item in errors:
            contract.add_error(_safe_str(item) or str(item))
        for item in notes:
            contract.add_note(_safe_str(item) or str(item))

        contract.add_note("Geometrie-basierter Fallback-Style wurde erzeugt.")
        return contract

    def _build_fallback_symbolizer(self, geometry_type: str) -> Dict[str, Any]:
        kind = self._style_kind_for_geometry(geometry_type)
        if kind == "point":
            return deepcopy(_POINT_DEFAULT_STYLE)
        if kind == "line":
            return deepcopy(_LINE_DEFAULT_STYLE)
        if kind == "polygon":
            return deepcopy(_POLYGON_DEFAULT_STYLE)
        return deepcopy(_GENERIC_DEFAULT_STYLE)

    def _style_kind_for_geometry(self, geometry_type: str) -> str:
        normalized = self._normalize_geometry_type(geometry_type).lower()
        if normalized in {"point", "multipoint"}:
            return "point"
        if normalized in {"linestring", "multilinestring"}:
            return "line"
        if normalized in {"polygon", "multipolygon"}:
            return "polygon"
        return "generic"

    def _build_validation_payload(self, validation_report: Mapping[str, Any]) -> Dict[str, Any]:
        warnings = _normalize_list(validation_report.get("warnings"))
        errors = _normalize_list(validation_report.get("errors"))
        issues = _normalize_list(validation_report.get("issues"))

        return {
            "is_valid": _safe_bool(validation_report.get("is_valid"), True),
            "warning_count": len(warnings),
            "error_count": len(errors),
            "issue_count": len(issues),
        }

    def _build_legend_payload(self, style_payload: Mapping[str, Any]) -> Dict[str, Any]:
        legend = _normalize_mapping(style_payload.get("legend"))
        if legend:
            return legend

        legend_url = _safe_str(style_payload.get("legend_url"))
        if legend_url:
            return {"url": legend_url}

        return {}

    def _build_metadata_payload(
        self,
        *,
        style_payload: Mapping[str, Any],
        dataset_entry: Optional[OpenLayerDatasetEntry],
        effective_geometry_type: str,
    ) -> Dict[str, Any]:
        metadata = {
            "style_kind": self._style_kind_for_geometry(effective_geometry_type),
            "style_keys": sorted(list(style_payload.keys())),
            "geometry_type": effective_geometry_type,
        }

        if dataset_entry is not None:
            metadata["dataset_title"] = dataset_entry.title
            metadata["dataset_status"] = dataset_entry.status
            metadata["dataset_editable"] = dataset_entry.editable

        return metadata

    # ---------------------------------------------------------------------
    # Interne Farb-/Opacity-/Dash-Normalisierung
    # ---------------------------------------------------------------------

    def _normalize_opacity(self, value: Any, *, fallback: float) -> float:
        parsed = _safe_float(value, fallback)
        if parsed is None:
            return fallback
        if parsed < 0:
            return 0.0
        if parsed > 1:
            return 1.0
        return float(parsed)

    def _normalize_line_dash(self, value: Any, *, fallback: Sequence[Any]) -> List[int]:
        if value is None:
            return [int(item) for item in list(fallback or []) if _safe_int(item, None) is not None]

        if isinstance(value, str):
            parts = [part.strip() for part in value.replace(";", ",").split(",")]
            result: List[int] = []
            for part in parts:
                parsed = _safe_int(part, None)
                if parsed is None or parsed < 0:
                    continue
                result.append(parsed)
            return result

        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            result = []
            for item in value:
                parsed = _safe_int(item, None)
                if parsed is None or parsed < 0:
                    continue
                result.append(parsed)
            return result

        parsed_single = _safe_int(value, None)
        if parsed_single is not None and parsed_single >= 0:
            return [parsed_single]

        return [int(item) for item in list(fallback or []) if _safe_int(item, None) is not None]

    def _normalize_css_color(
        self,
        value: Any,
        *,
        opacity: Optional[float] = None,
        fallback: Optional[str] = None,
    ) -> str:
        if isinstance(value, Mapping):
            r = _safe_int(value.get("r"), None)
            g = _safe_int(value.get("g"), None)
            b = _safe_int(value.get("b"), None)
            a = _safe_float(value.get("a"), opacity if opacity is not None else 1.0)

            if r is not None and g is not None and b is not None:
                return self._rgba_string(r, g, b, a if a is not None else 1.0)

        text_value = _safe_str(value)
        if text_value is None:
            return fallback or "rgba(0,0,0,1.0)"

        hex_match = _HEX_COLOR_RE.match(text_value)
        if hex_match:
            return self._normalize_hex_color(
                hex_match.group("hex"),
                opacity=opacity,
                fallback=fallback,
            )

        rgba_match = _RGBA_RE.match(text_value)
        if rgba_match:
            r = max(0, min(255, _safe_int(rgba_match.group("r"), 0) or 0))
            g = max(0, min(255, _safe_int(rgba_match.group("g"), 0) or 0))
            b = max(0, min(255, _safe_int(rgba_match.group("b"), 0) or 0))
            parsed_alpha = _safe_float(rgba_match.group("a"), 1.0) or 1.0
            alpha = self._normalize_opacity(opacity, fallback=parsed_alpha) if opacity is not None else self._normalize_opacity(parsed_alpha, fallback=1.0)
            return self._rgba_string(r, g, b, alpha)

        lowered = text_value.lower()
        if lowered in {
            "black", "white", "red", "green", "blue", "yellow", "orange",
            "purple", "magenta", "cyan", "gray", "grey", "transparent",
        }:
            if lowered == "transparent":
                return "rgba(0,0,0,0.0)"
            return text_value

        return fallback or text_value

    def _normalize_hex_color(
        self,
        hex_value: str,
        *,
        opacity: Optional[float],
        fallback: Optional[str],
    ) -> str:
        raw = _safe_str(hex_value, "") or ""
        raw = raw.strip().lstrip("#")

        try:
            if len(raw) == 3:
                r = int(raw[0] * 2, 16)
                g = int(raw[1] * 2, 16)
                b = int(raw[2] * 2, 16)
                a = self._normalize_opacity(opacity, fallback=1.0) if opacity is not None else 1.0
                return self._rgba_string(r, g, b, a)

            if len(raw) == 4:
                r = int(raw[0] * 2, 16)
                g = int(raw[1] * 2, 16)
                b = int(raw[2] * 2, 16)
                parsed_alpha = int(raw[3] * 2, 16) / 255.0
                a = self._normalize_opacity(opacity, fallback=parsed_alpha) if opacity is not None else parsed_alpha
                return self._rgba_string(r, g, b, a)

            if len(raw) == 6:
                r = int(raw[0:2], 16)
                g = int(raw[2:4], 16)
                b = int(raw[4:6], 16)
                a = self._normalize_opacity(opacity, fallback=1.0) if opacity is not None else 1.0
                return self._rgba_string(r, g, b, a)

            if len(raw) == 8:
                r = int(raw[0:2], 16)
                g = int(raw[2:4], 16)
                b = int(raw[4:6], 16)
                parsed_alpha = int(raw[6:8], 16) / 255.0
                a = self._normalize_opacity(opacity, fallback=parsed_alpha) if opacity is not None else parsed_alpha
                return self._rgba_string(r, g, b, a)
        except Exception:
            return fallback or "rgba(0,0,0,1.0)"

        return fallback or "rgba(0,0,0,1.0)"

    def _rgba_string(self, r: int, g: int, b: int, a: float) -> str:
        rr = max(0, min(255, int(r)))
        gg = max(0, min(255, int(g)))
        bb = max(0, min(255, int(b)))
        aa = self._normalize_opacity(a, fallback=1.0)
        return f"rgba({rr},{gg},{bb},{aa:.3f})"

    # ---------------------------------------------------------------------
    # Interne Cache-Logik
    # ---------------------------------------------------------------------

    def _build_style_cache_key(
        self,
        *,
        dataset_id: str,
        include_rules: bool,
        include_raw_style: bool,
        enrich_with_db: bool,
    ) -> str:
        payload = {
            "dataset_id": dataset_id,
            "include_rules": include_rules,
            "include_raw_style": include_raw_style,
            "enrich_with_db": enrich_with_db,
        }
        return f"style::{self._safe_serialize_key(payload)}"

    def _get_style_cache_entry(
        self,
        cache_key: str,
        *,
        require_fresh: bool,
    ) -> Optional[OpenLayerDatasetStyleContract]:
        with self._cache_lock:
            cached = self._style_cache.get(cache_key)
            if not isinstance(cached, _ServiceCacheEntry):
                return None
            if require_fresh and not cached.is_fresh:
                return None
            value = cached.value

        if not isinstance(value, OpenLayerDatasetStyleContract):
            return None

        return _deepcopy_or_value(value)

    def _set_style_cache_entry(
        self,
        cache_key: str,
        value: OpenLayerDatasetStyleContract,
        ttl_seconds: int,
    ) -> None:
        cached_at = _utc_now()
        expires_at = cached_at + timedelta(seconds=max(0, ttl_seconds))

        entry = _ServiceCacheEntry(
            value=_deepcopy_or_value(value),
            cached_at=cached_at,
            expires_at=expires_at,
        )

        with self._cache_lock:
            self._style_cache[cache_key] = entry

    def _get_cache_size(self) -> int:
        with self._cache_lock:
            return len(self._style_cache)

    def _serialize_mapping_key(self, value: Mapping[str, Any]) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            return repr(value)

    def _safe_serialize_key(self, value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            return repr(value)

    # ---------------------------------------------------------------------
    # Interne Settings / Logging
    # ---------------------------------------------------------------------

    def _settings(self) -> Settings:
        try:
            if has_app_context():
                cached = getattr(current_app, "extensions", {}).get("openlayer_settings")  # type: ignore[arg-type]
                if isinstance(cached, Settings):
                    return cached
        except Exception:
            pass

        return get_settings()

    def _resolve_cache_ttl_seconds(
        self,
        explicit_value: Optional[int],
        settings: Settings,
        *,
        fallback: int,
        attr_candidates: Sequence[str],
    ) -> int:
        if explicit_value is not None:
            return max(0, _safe_int(explicit_value, fallback) or fallback)

        for attr_name in attr_candidates:
            try:
                value = getattr(settings, attr_name, None)
                if value is not None:
                    return max(0, _safe_int(value, fallback) or fallback)
            except Exception:
                continue

        try:
            if has_app_context():
                app_config = getattr(current_app, "config", {})  # type: ignore[arg-type]
                for key in (
                    "OPENLAYER_STYLE_ADAPTER_CACHE_TTL_SECONDS",
                    "OPENLAYER_DATASET_STYLE_CACHE_TTL_SECONDS",
                ):
                    if key in app_config:
                        return max(0, _safe_int(app_config.get(key), fallback) or fallback)
        except Exception:
            pass

        return fallback

    def _sanitize_dataset_id(self, dataset_id: Any) -> Optional[str]:
        normalized = _safe_str(dataset_id)
        if normalized is None:
            return None

        sanitizer = getattr(self.settings, "sanitize_dataset_id", None)
        if callable(sanitizer):
            try:
                return sanitizer(normalized)
            except Exception:
                return normalized

        return normalized

    def _normalize_geometry_type(self, value: Optional[str]) -> str:
        text_value = _safe_str(value)
        if text_value is None:
            return _DEFAULT_UNKNOWN_GEOMETRY

        lookup = text_value.strip().replace("-", "").replace(" ", "").lower()
        mapping = {
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
        return mapping.get(lookup, text_value)

    def _safe_catalog_service_summary(self) -> Dict[str, Any]:
        try:
            summary_fn = getattr(self.catalog_service, "get_service_summary", None)
            if callable(summary_fn):
                result = summary_fn()
                if isinstance(result, dict):
                    return deepcopy(result)
        except Exception:
            pass
        return {"service_type": type(self.catalog_service).__name__}

    def _safe_orchestrator_client_summary(self) -> Dict[str, Any]:
        try:
            summary_fn = getattr(self.orchestrator_client, "get_client_summary", None)
            if callable(summary_fn):
                result = summary_fn()
                if isinstance(result, dict):
                    return deepcopy(result)
        except Exception:
            pass
        return {"client_type": type(self.orchestrator_client).__name__}

    def _log_warning(self, message: str, *args: Any) -> None:
        try:
            if has_app_context():
                current_app.logger.warning(message, *args)  # type: ignore[arg-type]
        except Exception:
            pass


# Komfort-Aliase
DatasetStyleAdapter = OpenLayerStyleAdapter
DatasetStyleContract = OpenLayerDatasetStyleContract
DatasetRuleStyle = OpenLayerRuleStyle

__all__ = [
    "OpenLayerStyleAdapterError",
    "OpenLayerStyleNotFoundError",
    "OpenLayerStylePayloadError",
    "OpenLayerRuleStyle",
    "OpenLayerDatasetStyleContract",
    "OpenLayerStyleAdapter",
    "DatasetStyleAdapter",
    "DatasetStyleContract",
    "DatasetRuleStyle",
]