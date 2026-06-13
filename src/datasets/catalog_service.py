# services/openLayer/src/datasets/catalog_service.py
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Type

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
            "src.datasets.catalog_service konnte settings.py nicht importieren. "
            "Stelle sicher, dass Settings/get_settings verfügbar sind."
        ) from exc

try:
    from src.orchestrator.client import (
        GeoServerOrchestratorClient,
        OrchestratorClient,
        OrchestratorClientError,
        OrchestratorPayloadError,
        OrchestratorHttpError,
    )
except Exception:  # pragma: no cover
    try:
        from ..orchestrator.client import (  # type: ignore
            GeoServerOrchestratorClient,
            OrchestratorClient,
            OrchestratorClientError,
            OrchestratorPayloadError,
            OrchestratorHttpError,
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "src.datasets.catalog_service konnte den Orchestrator-Client nicht importieren. "
            "Stelle sicher, dass 'src/orchestrator/client.py' vorhanden ist."
        ) from exc


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

_DEFAULT_CACHE_TTL_SECONDS = 20
_DEFAULT_DETAIL_CACHE_TTL_SECONDS = 25
_DEFAULT_ALLOW_STALE_ON_ERROR = True
_DEFAULT_DATASETS_API_PREFIX = "/api/datasets"
_DEFAULT_SOURCE_PROVIDER = "geoserver_orchestrator"
_DEFAULT_SOURCE_TYPE = "wfs"
_DEFAULT_SOURCE_FORMAT = "geojson"
_DEFAULT_UNKNOWN_GEOMETRY = "Unknown"
_DEFAULT_ACTIVE_STATUS = "active"
_DEFAULT_INACTIVE_STATUS = "inactive"


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


def _unique_texts(values: Sequence[Any]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = _safe_str(value)
        if normalized is None:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)

    return result


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


def _truncate_text(value: Optional[str], max_length: int = 500) -> Optional[str]:
    text_value = _safe_str(value)
    if text_value is None:
        return None
    if len(text_value) <= max_length:
        return text_value
    return text_value[:max_length] + "...<truncated>"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class OpenLayerDatasetCatalogError(RuntimeError):
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


class OpenLayerDatasetNotFoundError(OpenLayerDatasetCatalogError):
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
class OpenLayerDatasetEntry:
    dataset_id: str
    title: str
    description: str
    active: bool
    status: str
    editable: bool
    geometry_type: str
    source: Dict[str, Any] = field(default_factory=dict)
    capabilities: Dict[str, bool] = field(default_factory=dict)
    style: Dict[str, Any] = field(default_factory=dict)
    links: Dict[str, Any] = field(default_factory=dict)
    orchestrator: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    catalog_source: str = _DEFAULT_SOURCE_PROVIDER
    overall_valid: bool = False
    published_known: bool = False
    sync_log_known: bool = False
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
        include_internal: bool = False,
        include_style_payload: bool = False,
    ) -> Dict[str, Any]:
        source = deepcopy(self.source)
        style = deepcopy(self.style)
        links = deepcopy(self.links)
        orchestrator = deepcopy(self.orchestrator)

        if not include_internal:
            source.pop("direct_url", None)
            source.pop("orchestrator_wfs_url", None)
            source.pop("orchestrator_capabilities_url", None)
            source.pop("orchestrator_describe_feature_type_url", None)
            source.pop("orchestrator_catalog_url", None)
            source.pop("orchestrator_style_url", None)
            source.pop("orchestrator_sync_url", None)
            style.pop("payload", None)

        if not include_style_payload:
            style.pop("payload", None)

        return {
            "id": self.dataset_id,
            "dataset_id": self.dataset_id,
            "title": self.title,
            "description": self.description,
            "active": self.active,
            "status": self.status,
            "editable": self.editable,
            "geometry_type": self.geometry_type,
            "source": source,
            "capabilities": deepcopy(self.capabilities),
            "style": style,
            "links": links,
            "orchestrator": orchestrator if include_internal else {
                "catalog_url": orchestrator.get("catalog_url"),
                "style_url": orchestrator.get("style_url"),
                "sync_url": orchestrator.get("sync_url"),
                "published_known": orchestrator.get("published_known"),
                "sync_log_known": orchestrator.get("sync_log_known"),
                "entry_count_hint": orchestrator.get("entry_count_hint"),
            },
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "notes": list(self.notes),
            "catalog_source": self.catalog_source,
            "overall_valid": self.overall_valid,
            "published_known": self.published_known,
            "sync_log_known": self.sync_log_known,
            "built_at": _dt_to_iso(self.built_at),
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class OpenLayerDatasetCatalogService:
    """
    Adapter-Schicht zwischen OpenLayer und GeoServer-Orchestrator.

    Aufgaben:
    - liest `/catalog` und optional `/styles/<dataset_id>` aus dem Orchestrator
    - normalisiert das Ergebnis in einen stabilen OpenLayer-Datensatzvertrag
    - hält kleine Service-Caches für Listen- und Detailansichten
    - nutzt serverseitig lokale Source-URLs (`/api/datasets/<id>/source`)
    - propagiert direkte Orchestrator-/GeoServer-Links nur als interne Metadaten
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        orchestrator_client: Optional[GeoServerOrchestratorClient] = None,
        enable_cache: bool = True,
        cache_ttl_seconds: Optional[int] = None,
        detail_cache_ttl_seconds: Optional[int] = None,
        allow_stale_on_error: bool = _DEFAULT_ALLOW_STALE_ON_ERROR,
    ) -> None:
        self.settings = settings or self._settings()
        self.enable_cache = _safe_bool(enable_cache, True)
        self.allow_stale_on_error = _safe_bool(allow_stale_on_error, _DEFAULT_ALLOW_STALE_ON_ERROR)

        self.cache_ttl_seconds = self._resolve_cache_ttl_seconds(
            cache_ttl_seconds,
            self.settings,
            attr_candidates=(
                "dataset_catalog_service_cache_ttl_seconds",
                "openlayer_dataset_catalog_cache_ttl_seconds",
                "geoserver_orchestrator_catalog_cache_ttl_seconds",
            ),
            fallback=_DEFAULT_CACHE_TTL_SECONDS,
        )
        self.detail_cache_ttl_seconds = self._resolve_cache_ttl_seconds(
            detail_cache_ttl_seconds,
            self.settings,
            attr_candidates=(
                "dataset_catalog_detail_cache_ttl_seconds",
                "openlayer_dataset_detail_cache_ttl_seconds",
                "geoserver_orchestrator_style_cache_ttl_seconds",
            ),
            fallback=_DEFAULT_DETAIL_CACHE_TTL_SECONDS,
        )

        self.datasets_api_prefix = self._resolve_datasets_api_prefix(self.settings)
        self.orchestrator_client = orchestrator_client or self._build_orchestrator_client(self.settings)

        self._cache_lock = RLock()
        self._list_cache: Dict[str, _ServiceCacheEntry] = {}
        self._detail_cache: Dict[str, _ServiceCacheEntry] = {}
        self._summary_cache: Dict[str, Dict[str, Any]] = {}

    # ---------------------------------------------------------------------
    # Öffentliche Diagnose / Cache
    # ---------------------------------------------------------------------

    def clear_caches(self) -> None:
        with self._cache_lock:
            self._list_cache.clear()
            self._detail_cache.clear()
            self._summary_cache.clear()

        try:
            self.orchestrator_client.clear_caches()
        except Exception:
            pass

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
            "detail_cache_ttl_seconds": self.detail_cache_ttl_seconds,
            "allow_stale_on_error": self.allow_stale_on_error,
            "datasets_api_prefix": self.datasets_api_prefix,
            "orchestrator_client": self.orchestrator_client.get_client_summary(),
            "list_cache_size": self._get_list_cache_size(),
            "detail_cache_size": self._get_detail_cache_size(),
        }

        with self._cache_lock:
            self._summary_cache[cache_key] = deepcopy(summary)

        return summary

    # ---------------------------------------------------------------------
    # Öffentliche API
    # ---------------------------------------------------------------------

    def list_datasets(
        self,
        *,
        include_inactive: bool = False,
        include_invalid: bool = False,
        include_style_details: bool = False,
        enrich_with_db: bool = False,
        use_cache: bool = True,
    ) -> List[OpenLayerDatasetEntry]:
        cache_key = self._build_list_cache_key(
            include_inactive=include_inactive,
            include_invalid=include_invalid,
            include_style_details=include_style_details,
            enrich_with_db=enrich_with_db,
        )

        if self.enable_cache and use_cache:
            cached = self._get_list_cache_entry(cache_key, require_fresh=True)
            if isinstance(cached, list):
                return [_deepcopy_or_value(item) for item in cached]

        stale = None
        if self.enable_cache and self.allow_stale_on_error:
            stale = self._get_list_cache_entry(cache_key, require_fresh=False)

        try:
            payload = self.orchestrator_client.get_catalog_index_payload(
                include_invalid=True,
                include_source_files=False,
                include_validation_reports=True,
                include_state_payloads=True,
                enrich_with_db=enrich_with_db,
                use_cache=use_cache,
                allow_stale_on_error=self.allow_stale_on_error,
            )

            raw_entries = payload.get("entries")
            if not isinstance(raw_entries, list):
                raise OrchestratorPayloadError(
                    "Der Orchestrator-Katalog enthält kein gültiges 'entries'-Array.",
                    details={
                        "payload_type": type(payload).__name__,
                        "entries_type": type(raw_entries).__name__,
                    },
                )

            normalized_entries: List[OpenLayerDatasetEntry] = []
            for raw_entry in raw_entries:
                if not isinstance(raw_entry, Mapping):
                    continue

                entry = self._build_dataset_entry_from_catalog_entry(
                    catalog_entry=raw_entry,
                    style_envelope=None,
                    include_style_payload=False,
                    entry_count_hint=len(raw_entries),
                )

                if include_style_details and entry.style.get("available"):
                    try:
                        style_envelope = self.orchestrator_client.get_style_envelope(
                            entry.dataset_id,
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
                        entry = self._build_dataset_entry_from_catalog_entry(
                            catalog_entry=raw_entry,
                            style_envelope=style_envelope,
                            include_style_payload=True,
                            entry_count_hint=len(raw_entries),
                        )
                    except Exception as exc:
                        entry.add_warning(
                            f"Style-Details für Dataset '{entry.dataset_id}' konnten nicht geladen werden: {exc}"
                        )

                if not include_invalid and not entry.overall_valid:
                    continue

                if not include_inactive and not entry.active:
                    continue

                normalized_entries.append(entry)

            if self.enable_cache and use_cache:
                self._set_list_cache_entry(cache_key, normalized_entries, self.cache_ttl_seconds)

            return [_deepcopy_or_value(item) for item in normalized_entries]

        except Exception as exc:
            if isinstance(stale, list):
                self._log_warning(
                    "Nutze stale Dataset-Liste aus Service-Cache nach Fehler: %s",
                    exc,
                )
                return [_deepcopy_or_value(item) for item in stale]

            raise OpenLayerDatasetCatalogError(
                f"Die Datensatzliste konnte nicht aus dem GeoServer-Orchestrator aufgebaut werden: {exc}",
                details={
                    "include_inactive": include_inactive,
                    "include_invalid": include_invalid,
                    "include_style_details": include_style_details,
                    "enrich_with_db": enrich_with_db,
                    "service_summary": self.get_service_summary(),
                },
                original_exception=exc,
                status_code=getattr(exc, "status_code", None),
            ) from exc

    def list_dataset_dicts(self, **kwargs: Any) -> List[Dict[str, Any]]:
        include_internal = _safe_bool(kwargs.pop("include_internal", False), False)
        include_style_payload = _safe_bool(kwargs.pop("include_style_payload", False), False)

        items = self.list_datasets(**kwargs)
        return [
            item.to_dict(
                include_internal=include_internal,
                include_style_payload=include_style_payload,
            )
            for item in items
        ]

    def get_dataset(
        self,
        dataset_id: str,
        *,
        include_style_details: bool = True,
        enrich_with_db: bool = False,
        use_cache: bool = True,
    ) -> OpenLayerDatasetEntry:
        normalized_dataset_id = self._sanitize_dataset_id(dataset_id)
        if not normalized_dataset_id:
            raise OpenLayerDatasetCatalogError(
                "dataset_id darf nicht leer sein.",
                details={"dataset_id": dataset_id},
            )

        cache_key = self._build_detail_cache_key(
            dataset_id=normalized_dataset_id,
            include_style_details=include_style_details,
            enrich_with_db=enrich_with_db,
        )

        if self.enable_cache and use_cache:
            cached = self._get_detail_cache_entry(cache_key, require_fresh=True)
            if isinstance(cached, OpenLayerDatasetEntry):
                return _deepcopy_or_value(cached)

        stale = None
        if self.enable_cache and self.allow_stale_on_error:
            stale = self._get_detail_cache_entry(cache_key, require_fresh=False)

        try:
            catalog_entry = self.orchestrator_client.get_catalog_entry_payload(
                normalized_dataset_id,
                include_source_files=False,
                include_validation_reports=True,
                include_state_payloads=True,
                enrich_with_db=enrich_with_db,
                use_cache=use_cache,
                allow_stale_on_error=self.allow_stale_on_error,
            )

            style_envelope = None
            include_style_payload = False

            if include_style_details:
                style_available = _safe_bool(catalog_entry.get("style_exists"), False) or _safe_bool(
                    catalog_entry.get("style_loaded"), False
                )
                if style_available:
                    try:
                        style_envelope = self.orchestrator_client.get_style_envelope(
                            normalized_dataset_id,
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
                        include_style_payload = True
                    except OrchestratorHttpError as exc:
                        self._log_warning(
                            "Style-Envelope für Dataset '%s' konnte nicht geladen werden (HTTP): %s",
                            normalized_dataset_id,
                            exc,
                        )
                    except Exception as exc:
                        self._log_warning(
                            "Style-Envelope für Dataset '%s' konnte nicht geladen werden: %s",
                            normalized_dataset_id,
                            exc,
                        )

            entry = self._build_dataset_entry_from_catalog_entry(
                catalog_entry=catalog_entry,
                style_envelope=style_envelope,
                include_style_payload=include_style_payload,
                entry_count_hint=1,
            )

            if self.enable_cache and use_cache:
                self._set_detail_cache_entry(cache_key, entry, self.detail_cache_ttl_seconds)

            return _deepcopy_or_value(entry)

        except OrchestratorHttpError as exc:
            if exc.status_code == 404:
                raise OpenLayerDatasetNotFoundError(
                    f"Dataset '{normalized_dataset_id}' wurde im GeoServer-Orchestrator nicht gefunden.",
                    details={
                        "dataset_id": normalized_dataset_id,
                        "service_summary": self.get_service_summary(),
                    },
                    original_exception=exc,
                    status_code=404,
                ) from exc

            if isinstance(stale, OpenLayerDatasetEntry):
                self._log_warning(
                    "Nutze stale Dataset-Detail aus Service-Cache nach HTTP-Fehler: %s",
                    exc,
                )
                return _deepcopy_or_value(stale)

            raise OpenLayerDatasetCatalogError(
                f"Dataset '{normalized_dataset_id}' konnte nicht geladen werden: {exc}",
                details={"dataset_id": normalized_dataset_id},
                original_exception=exc,
                status_code=exc.status_code,
            ) from exc

        except Exception as exc:
            if isinstance(stale, OpenLayerDatasetEntry):
                self._log_warning(
                    "Nutze stale Dataset-Detail aus Service-Cache nach Fehler: %s",
                    exc,
                )
                return _deepcopy_or_value(stale)

            raise OpenLayerDatasetCatalogError(
                f"Dataset '{normalized_dataset_id}' konnte nicht aus dem GeoServer-Orchestrator aufgebaut werden: {exc}",
                details={
                    "dataset_id": normalized_dataset_id,
                    "include_style_details": include_style_details,
                    "enrich_with_db": enrich_with_db,
                },
                original_exception=exc,
                status_code=getattr(exc, "status_code", None),
            ) from exc

    def get_dataset_dict(self, dataset_id: str, **kwargs: Any) -> Dict[str, Any]:
        include_internal = _safe_bool(kwargs.pop("include_internal", False), False)
        include_style_payload = _safe_bool(kwargs.pop("include_style_payload", False), False)

        item = self.get_dataset(dataset_id, **kwargs)
        return item.to_dict(
            include_internal=include_internal,
            include_style_payload=include_style_payload,
        )

    def dataset_exists(
        self,
        dataset_id: str,
        *,
        use_cache: bool = True,
    ) -> bool:
        normalized_dataset_id = self._sanitize_dataset_id(dataset_id)
        if not normalized_dataset_id:
            return False

        try:
            self.get_dataset(
                normalized_dataset_id,
                include_style_details=False,
                enrich_with_db=False,
                use_cache=use_cache,
            )
            return True
        except OpenLayerDatasetNotFoundError:
            return False
        except Exception:
            return False

    # ---------------------------------------------------------------------
    # Interne Normalisierung
    # ---------------------------------------------------------------------

    def _build_dataset_entry_from_catalog_entry(
        self,
        *,
        catalog_entry: Mapping[str, Any],
        style_envelope: Optional[Mapping[str, Any]],
        include_style_payload: bool,
        entry_count_hint: int,
    ) -> OpenLayerDatasetEntry:
        raw_entry = _normalize_mapping(catalog_entry)
        raw_style_envelope = _normalize_mapping(style_envelope)

        dataset_id = self._sanitize_dataset_id(
            _safe_str(raw_entry.get("dataset_id")) or _safe_str(raw_style_envelope.get("dataset_id"))
        )
        if not dataset_id:
            raise OpenLayerDatasetCatalogError(
                "Der Orchestrator-Katalogeintrag enthält keine gültige dataset_id.",
                details={"catalog_entry": _truncate_text(_safe_str(raw_entry))},
            )

        manifest_summary = _normalize_mapping(raw_entry.get("manifest_summary"))
        style_summary = _normalize_mapping(raw_entry.get("style_summary"))
        urls = _normalize_mapping(raw_entry.get("urls"))
        published_state_summary = _normalize_mapping(raw_entry.get("published_state_summary"))

        title = self._resolve_title(
            dataset_id=dataset_id,
            catalog_entry=raw_entry,
            manifest_summary=manifest_summary,
        )
        description = self._resolve_description(
            catalog_entry=raw_entry,
            manifest_summary=manifest_summary,
            style_envelope=raw_style_envelope,
        )
        geometry_type = self._resolve_geometry_type(
            catalog_entry=raw_entry,
            manifest_summary=manifest_summary,
            style_summary=style_summary,
            style_envelope=raw_style_envelope,
        )
        editable = _safe_bool(raw_entry.get("editable"), False)
        overall_valid = _safe_bool(raw_entry.get("overall_valid"), False)

        source_available = self._resolve_source_available(
            urls=urls,
            published_state_summary=published_state_summary,
            catalog_entry=raw_entry,
        )
        active = bool(overall_valid and source_available)
        status = self._resolve_status(
            active=active,
            overall_valid=overall_valid,
            catalog_entry=raw_entry,
        )

        source = self._build_source_payload(
            dataset_id=dataset_id,
            urls=urls,
            published_state_summary=published_state_summary,
            catalog_entry=raw_entry,
            source_available=source_available,
        )
        capabilities = self._build_capabilities_payload(
            editable=editable,
            source_available=source_available,
        )
        style = self._build_style_payload(
            dataset_id=dataset_id,
            catalog_entry=raw_entry,
            style_summary=style_summary,
            style_envelope=raw_style_envelope,
            include_style_payload=include_style_payload,
        )
        links = self._build_local_links_payload(dataset_id=dataset_id)
        orchestrator = self._build_orchestrator_payload(
            urls=urls,
            published_state_summary=published_state_summary,
            catalog_entry=raw_entry,
            entry_count_hint=entry_count_hint,
        )

        entry = OpenLayerDatasetEntry(
            dataset_id=dataset_id,
            title=title,
            description=description,
            active=active,
            status=status,
            editable=editable,
            geometry_type=geometry_type,
            source=source,
            capabilities=capabilities,
            style=style,
            links=links,
            orchestrator=orchestrator,
            warnings=[],
            errors=[],
            notes=[],
            catalog_source=_DEFAULT_SOURCE_PROVIDER,
            overall_valid=overall_valid,
            published_known=_safe_bool(raw_entry.get("published_known"), False),
            sync_log_known=_safe_bool(raw_entry.get("sync_log_known"), False),
            built_at=_utc_now(),
        )

        for item in _normalize_list(raw_entry.get("warnings")):
            entry.add_warning(_safe_str(item) or str(item))

        for item in _normalize_list(raw_entry.get("errors")):
            entry.add_error(_safe_str(item) or str(item))

        for item in _normalize_list(raw_style_envelope.get("warnings")):
            entry.add_warning(_safe_str(item) or str(item))

        for item in _normalize_list(raw_style_envelope.get("errors")):
            entry.add_error(_safe_str(item) or str(item))

        if not overall_valid:
            entry.add_note("Dataset ist im Orchestrator nicht vollständig valide.")

        if not source_available:
            entry.add_note("Für dieses Dataset ist aktuell keine nutzbare WFS-Quelle bekannt.")

        if not style.get("available", False):
            entry.add_note("Für dieses Dataset ist aktuell kein nutzbarer Style bekannt.")

        if source.get("max_features") is not None:
            entry.add_note(
                f"WFS-Anfragen werden serverseitig auf maximal {source.get('max_features')} Features begrenzt."
            )

        return entry

    def _resolve_title(
        self,
        *,
        dataset_id: str,
        catalog_entry: Mapping[str, Any],
        manifest_summary: Mapping[str, Any],
    ) -> str:
        candidates = [
            _safe_str(catalog_entry.get("title")),
            _safe_str(catalog_entry.get("name")),
            _safe_str(manifest_summary.get("title")),
            _safe_str(manifest_summary.get("name")),
            _safe_str(_get_nested(manifest_summary, "manifest", "title")),
            _safe_str(_get_nested(manifest_summary, "manifest", "name")),
            dataset_id,
        ]
        for candidate in candidates:
            if candidate:
                return candidate
        return dataset_id

    def _resolve_description(
        self,
        *,
        catalog_entry: Mapping[str, Any],
        manifest_summary: Mapping[str, Any],
        style_envelope: Mapping[str, Any],
    ) -> str:
        candidates = [
            _safe_str(catalog_entry.get("description")),
            _safe_str(catalog_entry.get("abstract")),
            _safe_str(manifest_summary.get("description")),
            _safe_str(manifest_summary.get("abstract")),
            _safe_str(_get_nested(manifest_summary, "manifest", "description")),
            _safe_str(_get_nested(style_envelope, "style", "description")),
        ]
        for candidate in candidates:
            if candidate:
                return candidate
        return ""

    def _resolve_geometry_type(
        self,
        *,
        catalog_entry: Mapping[str, Any],
        manifest_summary: Mapping[str, Any],
        style_summary: Mapping[str, Any],
        style_envelope: Mapping[str, Any],
    ) -> str:
        candidates = [
            _safe_str(catalog_entry.get("geometry_type")),
            _safe_str(catalog_entry.get("geometry")),
            _safe_str(style_summary.get("geometry")),
            _safe_str(style_envelope.get("geometry")),
            _safe_str(_get_nested(style_envelope, "style", "geometry")),
            _safe_str(_get_nested(manifest_summary, "target", "geometry_type")),
            _safe_str(_get_nested(manifest_summary, "target", "geom_type")),
            _safe_str(_get_nested(manifest_summary, "manifest", "geometry_type")),
            _safe_str(_get_nested(manifest_summary, "manifest", "geom_type")),
        ]
        for candidate in candidates:
            normalized = self._normalize_geometry_type(candidate)
            if normalized != _DEFAULT_UNKNOWN_GEOMETRY:
                return normalized
        return _DEFAULT_UNKNOWN_GEOMETRY

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

    def _resolve_source_available(
        self,
        *,
        urls: Mapping[str, Any],
        published_state_summary: Mapping[str, Any],
        catalog_entry: Mapping[str, Any],
    ) -> bool:
        wfs_url = (
            _safe_str(urls.get("wfs_url"))
            or _safe_str(published_state_summary.get("wfs_url"))
            or _safe_str(catalog_entry.get("wfs_url"))
        )

        return bool(
            _safe_bool(catalog_entry.get("published_known"), False)
            and wfs_url
        )

    def _resolve_status(
        self,
        *,
        active: bool,
        overall_valid: bool,
        catalog_entry: Mapping[str, Any],
    ) -> str:
        if active:
            return _DEFAULT_ACTIVE_STATUS

        if not overall_valid:
            return "invalid"

        if not _safe_bool(catalog_entry.get("published_known"), False):
            return "unpublished"

        return _DEFAULT_INACTIVE_STATUS

    def _build_source_payload(
        self,
        *,
        dataset_id: str,
        urls: Mapping[str, Any],
        published_state_summary: Mapping[str, Any],
        catalog_entry: Mapping[str, Any],
        source_available: bool,
    ) -> Dict[str, Any]:
        direct_wfs_url = (
            _safe_str(urls.get("wfs_url"))
            or _safe_str(published_state_summary.get("wfs_url"))
            or _safe_str(catalog_entry.get("wfs_url"))
        )

        max_features = (
            _safe_int(urls.get("wfs_feature_limit"))
            or _safe_int(published_state_summary.get("wfs_feature_limit"))
            or self.orchestrator_client.wfs_feature_limit
        )

        return {
            "type": _DEFAULT_SOURCE_TYPE,
            "format": _DEFAULT_SOURCE_FORMAT,
            "provider": _DEFAULT_SOURCE_PROVIDER,
            "available": source_available,
            "url": self._build_local_source_url(dataset_id),
            "max_features": max_features,
            "direct_url": direct_wfs_url,
            "orchestrator_wfs_url": direct_wfs_url,
            "orchestrator_capabilities_url": (
                _safe_str(urls.get("capabilities_url"))
                or _safe_str(published_state_summary.get("capabilities_url"))
            ),
            "orchestrator_describe_feature_type_url": (
                _safe_str(urls.get("describe_feature_type_url"))
                or _safe_str(published_state_summary.get("describe_feature_type_url"))
            ),
            "orchestrator_catalog_url": (
                _safe_str(urls.get("catalog_url"))
                or self._build_orchestrator_catalog_url(dataset_id)
            ),
            "orchestrator_style_url": (
                _safe_str(urls.get("style_url"))
                or _safe_str(published_state_summary.get("style_url"))
            ),
            "orchestrator_sync_url": (
                _safe_str(urls.get("sync_url"))
                or _safe_str(published_state_summary.get("sync_url"))
            ),
        }

    def _build_capabilities_payload(
        self,
        *,
        editable: bool,
        source_available: bool,
    ) -> Dict[str, bool]:
        return {
            "read": bool(source_available),
            "create": bool(editable),
            "update": bool(editable),
            "delete": bool(editable),
        }

    def _build_style_payload(
        self,
        *,
        dataset_id: str,
        catalog_entry: Mapping[str, Any],
        style_summary: Mapping[str, Any],
        style_envelope: Mapping[str, Any],
        include_style_payload: bool,
    ) -> Dict[str, Any]:
        available = bool(
            _safe_bool(catalog_entry.get("style_exists"), False)
            or _safe_bool(catalog_entry.get("style_loaded"), False)
            or bool(style_envelope)
        )

        rule_count = (
            _safe_int(style_envelope.get("rule_count"))
            or _safe_int(catalog_entry.get("style_rule_count"))
            or _safe_int(style_summary.get("rule_count"))
            or 0
        )

        payload: Dict[str, Any] = {
            "available": available,
            "loaded": _safe_bool(catalog_entry.get("style_loaded"), False) or bool(style_envelope),
            "valid": _safe_bool(catalog_entry.get("style_valid"), False)
                     if "style_valid" in catalog_entry
                     else _safe_bool(_get_nested(style_envelope, "validation_report", "is_valid"), False),
            "rule_count": rule_count,
            "geometry": self._normalize_geometry_type(
                _safe_str(style_envelope.get("geometry"))
                or _safe_str(style_summary.get("geometry"))
                or _safe_str(catalog_entry.get("geometry_type"))
            ),
            "orchestrator_url": self._resolve_style_url(
                dataset_id=dataset_id,
                catalog_entry=catalog_entry,
            ),
            "path": (
                _safe_str(style_envelope.get("style_path"))
                or _safe_str(catalog_entry.get("style_path"))
            ),
            "warnings": _unique_texts(
                list(_normalize_list(style_envelope.get("warnings")))
                + list(_normalize_list(catalog_entry.get("warnings")))
            ),
            "errors": _unique_texts(
                list(_normalize_list(style_envelope.get("errors")))
                + list(_normalize_list(catalog_entry.get("errors")))
            ),
        }

        if include_style_payload:
            raw_style_payload = _normalize_mapping(style_envelope.get("style"))
            if raw_style_payload:
                payload["payload"] = raw_style_payload

        return payload

    def _build_local_links_payload(self, *, dataset_id: str) -> Dict[str, str]:
        normalized_id = self._sanitize_dataset_id(dataset_id) or dataset_id
        base = self.datasets_api_prefix.rstrip("/")

        return {
            "self": f"{base}/{normalized_id}",
            "source": f"{base}/{normalized_id}/source",
            "changes": f"{base}/{normalized_id}/changes",
        }

    def _build_orchestrator_payload(
        self,
        *,
        urls: Mapping[str, Any],
        published_state_summary: Mapping[str, Any],
        catalog_entry: Mapping[str, Any],
        entry_count_hint: int,
    ) -> Dict[str, Any]:
        return {
            "catalog_url": (
                _safe_str(urls.get("catalog_url"))
                or self._build_orchestrator_catalog_url(_safe_str(catalog_entry.get("dataset_id")) or "")
            ),
            "style_url": (
                _safe_str(urls.get("style_url"))
                or _safe_str(published_state_summary.get("style_url"))
            ),
            "sync_url": (
                _safe_str(urls.get("sync_url"))
                or _safe_str(published_state_summary.get("sync_url"))
            ),
            "wfs_url": (
                _safe_str(urls.get("wfs_url"))
                or _safe_str(published_state_summary.get("wfs_url"))
                or _safe_str(catalog_entry.get("wfs_url"))
            ),
            "capabilities_url": (
                _safe_str(urls.get("capabilities_url"))
                or _safe_str(published_state_summary.get("capabilities_url"))
            ),
            "describe_feature_type_url": (
                _safe_str(urls.get("describe_feature_type_url"))
                or _safe_str(published_state_summary.get("describe_feature_type_url"))
            ),
            "published_known": _safe_bool(catalog_entry.get("published_known"), False),
            "sync_log_known": _safe_bool(catalog_entry.get("sync_log_known"), False),
            "entry_count_hint": entry_count_hint,
        }

    def _resolve_style_url(
        self,
        *,
        dataset_id: str,
        catalog_entry: Mapping[str, Any],
    ) -> Optional[str]:
        urls = _normalize_mapping(catalog_entry.get("urls"))
        published_state_summary = _normalize_mapping(catalog_entry.get("published_state_summary"))

        return (
            _safe_str(urls.get("style_url"))
            or _safe_str(published_state_summary.get("style_url"))
            or self._build_orchestrator_style_url(dataset_id)
        )

    # ---------------------------------------------------------------------
    # Interne Cache-Logik
    # ---------------------------------------------------------------------

    def _build_list_cache_key(
        self,
        *,
        include_inactive: bool,
        include_invalid: bool,
        include_style_details: bool,
        enrich_with_db: bool,
    ) -> str:
        payload = {
            "include_inactive": include_inactive,
            "include_invalid": include_invalid,
            "include_style_details": include_style_details,
            "enrich_with_db": enrich_with_db,
        }
        return f"list::{self._safe_serialize_key(payload)}"

    def _build_detail_cache_key(
        self,
        *,
        dataset_id: str,
        include_style_details: bool,
        enrich_with_db: bool,
    ) -> str:
        payload = {
            "dataset_id": dataset_id,
            "include_style_details": include_style_details,
            "enrich_with_db": enrich_with_db,
        }
        return f"detail::{self._safe_serialize_key(payload)}"

    def _get_list_cache_entry(self, cache_key: str, *, require_fresh: bool) -> Optional[List[OpenLayerDatasetEntry]]:
        with self._cache_lock:
            cached = self._list_cache.get(cache_key)
            if not isinstance(cached, _ServiceCacheEntry):
                return None
            if require_fresh and not cached.is_fresh:
                return None
            value = cached.value

        if not isinstance(value, list):
            return None

        return [_deepcopy_or_value(item) for item in value]

    def _set_list_cache_entry(
        self,
        cache_key: str,
        value: List[OpenLayerDatasetEntry],
        ttl_seconds: int,
    ) -> None:
        cached_at = _utc_now()
        expires_at = cached_at + timedelta(seconds=max(0, ttl_seconds))

        entry = _ServiceCacheEntry(
            value=[_deepcopy_or_value(item) for item in value],
            cached_at=cached_at,
            expires_at=expires_at,
        )

        with self._cache_lock:
            self._list_cache[cache_key] = entry

    def _get_detail_cache_entry(
        self,
        cache_key: str,
        *,
        require_fresh: bool,
    ) -> Optional[OpenLayerDatasetEntry]:
        with self._cache_lock:
            cached = self._detail_cache.get(cache_key)
            if not isinstance(cached, _ServiceCacheEntry):
                return None
            if require_fresh and not cached.is_fresh:
                return None
            value = cached.value

        if not isinstance(value, OpenLayerDatasetEntry):
            return None

        return _deepcopy_or_value(value)

    def _set_detail_cache_entry(
        self,
        cache_key: str,
        value: OpenLayerDatasetEntry,
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
            self._detail_cache[cache_key] = entry

    def _get_list_cache_size(self) -> int:
        with self._cache_lock:
            return len(self._list_cache)

    def _get_detail_cache_size(self) -> int:
        with self._cache_lock:
            return len(self._detail_cache)

    def _safe_serialize_key(self, value: Any) -> str:
        try:
            import json
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            return repr(value)

    # ---------------------------------------------------------------------
    # Interne Settings / Defaults / Logging
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

    def _build_orchestrator_client(self, settings: Settings) -> GeoServerOrchestratorClient:
        return OrchestratorClient(settings=settings)

    def _resolve_cache_ttl_seconds(
        self,
        explicit_value: Optional[int],
        settings: Settings,
        *,
        attr_candidates: Sequence[str],
        fallback: int,
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
                for attr_name in (
                    attr_candidates[0].upper(),
                    "OPENLAYER_DATASET_CATALOG_CACHE_TTL_SECONDS",
                    "GEOSERVER_ORCHESTRATOR_CACHE_TTL_SECONDS",
                ):
                    app_config = getattr(current_app, "config", {})  # type: ignore[arg-type]
                    if attr_name in app_config:
                        return max(0, _safe_int(app_config.get(attr_name), fallback) or fallback)
        except Exception:
            pass

        return fallback

    def _resolve_datasets_api_prefix(self, settings: Settings) -> str:
        for attr_name in (
            "datasets_api_prefix",
            "dataset_api_prefix",
            "api_datasets_prefix",
        ):
            try:
                value = getattr(settings, attr_name, None)
                normalized = _safe_str(value)
                if normalized:
                    return normalized.rstrip("/")
            except Exception:
                continue

        try:
            if has_app_context():
                app_config = getattr(current_app, "config", {})  # type: ignore[arg-type]
                for key in ("DATASETS_API_PREFIX", "DATASET_API_PREFIX"):
                    if key in app_config:
                        normalized = _safe_str(app_config.get(key))
                        if normalized:
                            return normalized.rstrip("/")
        except Exception:
            pass

        return _DEFAULT_DATASETS_API_PREFIX

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

    def _build_local_source_url(self, dataset_id: str) -> str:
        normalized_id = self._sanitize_dataset_id(dataset_id) or dataset_id
        return f"{self.datasets_api_prefix.rstrip('/')}/{normalized_id}/source"

    def _build_orchestrator_catalog_url(self, dataset_id: str) -> Optional[str]:
        normalized_id = self._sanitize_dataset_id(dataset_id)
        base_url = _safe_str(getattr(self.orchestrator_client, "base_url", None))
        if not base_url:
            return None
        if not normalized_id:
            return f"{base_url.rstrip('/')}/catalog"
        return f"{base_url.rstrip('/')}/catalog/{normalized_id}"

    def _build_orchestrator_style_url(self, dataset_id: str) -> Optional[str]:
        normalized_id = self._sanitize_dataset_id(dataset_id)
        base_url = _safe_str(getattr(self.orchestrator_client, "base_url", None))
        if not base_url or not normalized_id:
            return None
        return f"{base_url.rstrip('/')}/styles/{normalized_id}"

    def _log_warning(self, message: str, *args: Any) -> None:
        try:
            if has_app_context():
                current_app.logger.warning(message, *args)  # type: ignore[arg-type]
        except Exception:
            pass


# Komfort-Aliase
DatasetCatalogService = OpenLayerDatasetCatalogService
DatasetCatalogEntry = OpenLayerDatasetEntry

__all__ = [
    "OpenLayerDatasetCatalogError",
    "OpenLayerDatasetNotFoundError",
    "OpenLayerDatasetEntry",
    "OpenLayerDatasetCatalogService",
    "DatasetCatalogService",
    "DatasetCatalogEntry",
]