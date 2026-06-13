from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

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
            "src.datasets.source_service konnte settings.py nicht importieren. "
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
        from .catalog_service import (  # type: ignore
            OpenLayerDatasetCatalogError,
            OpenLayerDatasetEntry,
            OpenLayerDatasetNotFoundError,
            OpenLayerDatasetCatalogService,
            DatasetCatalogService,
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "src.datasets.source_service konnte catalog_service.py nicht importieren. "
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
            "src.datasets.source_service konnte den Orchestrator-Client nicht importieren. "
            "Stelle sicher, dass 'src/orchestrator/client.py' vorhanden ist."
        ) from exc


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

_DEFAULT_CACHE_TTL_SECONDS = 20
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 15
_DEFAULT_MAX_PAYLOAD_BYTES = 12 * 1024 * 1024  # 12 MB
_DEFAULT_ALLOW_STALE_ON_ERROR = True
_DEFAULT_ACCEPT_HEADER = "application/geo+json, application/json, text/json;q=0.9, */*;q=0.8"
_DEFAULT_USER_AGENT = "openlayer-dataset-source-service/1.0"

_DEFAULT_GEOSERVER_INTERNAL_BASE_URL = "http://geoserver:8080/geoserver"
_DEFAULT_GEOSERVER_PUBLIC_BASE_URL = "http://localhost:8082/geoserver"

_GEOJSON_FEATURE_COLLECTION = "FeatureCollection"
_GEOJSON_FEATURE = "Feature"

_LOCALHOST_NAMES = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "[::1]",
    "host.docker.internal",
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
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        return int(str(value).strip())
    except Exception:
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            return float(value)
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


def _truncate_text(value: Optional[str], max_length: int = 800) -> Optional[str]:
    text_value = _safe_str(value)
    if text_value is None:
        return None
    if len(text_value) <= max_length:
        return text_value
    return text_value[:max_length] + "...<truncated>"


def _safe_headers_to_dict(headers: Any) -> Dict[str, str]:
    result: Dict[str, str] = {}
    try:
        if headers is None:
            return result
        if hasattr(headers, "items"):
            for key, value in headers.items():
                normalized_key = _safe_str(key)
                normalized_value = _safe_str(value)
                if normalized_key is None or normalized_value is None:
                    continue
                result[normalized_key] = normalized_value
    except Exception:
        return result
    return result


def _safe_json_loads(text: str) -> Tuple[Any, Optional[str]]:
    try:
        return json.loads(text), None
    except Exception as exc:
        return None, f"{exc.__class__.__name__}: {exc}"


def _build_url_with_query(base_url: str, query_params: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(query_params, Mapping) or not query_params:
        return base_url

    try:
        normalized_pairs: List[Tuple[str, str]] = []
        for key, value in query_params.items():
            normalized_key = _safe_str(key)
            normalized_value = _safe_str(value)
            if normalized_key is None or normalized_value is None:
                continue
            normalized_pairs.append((normalized_key, normalized_value))

        split_result = urlsplit(base_url)
        existing_pairs = parse_qsl(split_result.query, keep_blank_values=True)

        filtered_existing_pairs = []
        normalized_keys = {key for key, _value in normalized_pairs}
        for key, value in existing_pairs:
            if str(key) in normalized_keys:
                continue
            filtered_existing_pairs.append((str(key), str(value)))

        final_query = urlencode(filtered_existing_pairs + normalized_pairs, doseq=True)
        return urlunsplit(
            (
                split_result.scheme,
                split_result.netloc,
                split_result.path,
                final_query,
                split_result.fragment,
            )
        )
    except Exception:
        return base_url


def _normalize_base_url(value: Any) -> Optional[str]:
    normalized = _safe_str(value)
    if normalized is None:
        return None

    try:
        split_result = urlsplit(normalized)
        scheme = _safe_str(split_result.scheme, "").lower() or ""
        netloc = _safe_str(split_result.netloc, "") or ""
        path = _safe_str(split_result.path, "") or ""

        if not scheme or not netloc:
            return None

        normalized_path = path.rstrip("/")
        return urlunsplit((scheme, netloc, normalized_path, "", ""))
    except Exception:
        try:
            return str(normalized).rstrip("/")
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class OpenLayerDatasetSourceError(RuntimeError):
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


class OpenLayerDatasetSourceUnavailableError(OpenLayerDatasetSourceError):
    pass


class OpenLayerDatasetSourcePayloadError(OpenLayerDatasetSourceError):
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
class OpenLayerDatasetSourceResult:
    dataset_id: str
    provider: str
    source_type: str
    source_format: str
    available: bool
    public_url: Optional[str]
    direct_url: Optional[str]
    effective_url: Optional[str]
    payload: Optional[Dict[str, Any]] = None
    payload_type: str = _GEOJSON_FEATURE_COLLECTION
    feature_limit: Optional[int] = None
    feature_count_before_trim: int = 0
    feature_count_after_trim: int = 0
    trimmed: bool = False
    status_code: int = 200
    headers: Dict[str, str] = field(default_factory=dict)
    from_cache: bool = False
    stale_cache_used: bool = False
    cached_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    elapsed_ms: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def feature_count(self) -> int:
        return int(self.feature_count_after_trim)

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
        include_payload: bool = False,
        include_headers: bool = False,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "dataset_id": self.dataset_id,
            "provider": self.provider,
            "source_type": self.source_type,
            "source_format": self.source_format,
            "available": self.available,
            "public_url": self.public_url,
            "direct_url": self.direct_url,
            "effective_url": self.effective_url,
            "payload_type": self.payload_type,
            "feature_limit": self.feature_limit,
            "feature_count_before_trim": self.feature_count_before_trim,
            "feature_count_after_trim": self.feature_count_after_trim,
            "feature_count": self.feature_count,
            "trimmed": self.trimmed,
            "status_code": self.status_code,
            "from_cache": self.from_cache,
            "stale_cache_used": self.stale_cache_used,
            "cached_at": _dt_to_iso(self.cached_at),
            "expires_at": _dt_to_iso(self.expires_at),
            "fetched_at": _dt_to_iso(self.fetched_at),
            "elapsed_ms": self.elapsed_ms,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "notes": list(self.notes),
        }

        if include_payload:
            payload["payload"] = _deepcopy_or_value(self.payload)

        if include_headers:
            payload["headers"] = deepcopy(self.headers)

        return payload


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class OpenLayerDatasetSourceService:
    """
    Serverseitiger Source-Proxy für Dataset-Geometrien.

    Ziele:
    - Browser lädt Geodaten nur same-origin über `/api/datasets/<id>/source`
    - interne direkte WFS-URL bleibt im Backend
    - zusätzliche Sicherheitsstufe gegen zu große WFS-Responses
    - TTL-Caches + stale-cache fallback bei temporären Fehlern
    - Rückgabe immer als valides GeoJSON FeatureCollection
    - öffentliche GeoServer-URLs werden serverseitig auf interne Container-URLs umgeschrieben
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        catalog_service: Optional[OpenLayerDatasetCatalogService] = None,
        orchestrator_client: Optional[GeoServerOrchestratorClient] = None,
        enable_cache: bool = True,
        cache_ttl_seconds: Optional[int] = None,
        request_timeout_seconds: Optional[int] = None,
        max_payload_bytes: Optional[int] = None,
        feature_limit: Optional[int] = None,
        allow_stale_on_error: bool = _DEFAULT_ALLOW_STALE_ON_ERROR,
        user_agent: Optional[str] = None,
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
                "dataset_source_service_cache_ttl_seconds",
                "openlayer_dataset_source_cache_ttl_seconds",
                "geoserver_orchestrator_source_cache_ttl_seconds",
            ),
        )
        self.request_timeout_seconds = self._resolve_request_timeout_seconds(
            request_timeout_seconds,
            self.settings,
        )
        self.max_payload_bytes = self._resolve_max_payload_bytes(
            max_payload_bytes,
            self.settings,
        )
        self.feature_limit = self._resolve_feature_limit(
            feature_limit,
            self.settings,
        )
        self.user_agent = _safe_str(user_agent) or self._resolve_user_agent(self.settings)

        self._cache_lock = RLock()
        self._source_cache: Dict[str, _ServiceCacheEntry] = {}
        self._summary_cache: Dict[str, Dict[str, Any]] = {}
        self._url_rewrite_cache: Dict[str, str] = {}
        self._url_rewrite_notes_cache: Dict[str, List[str]] = {}

    # ---------------------------------------------------------------------
    # Öffentliche Diagnose / Cache
    # ---------------------------------------------------------------------

    def clear_caches(self) -> None:
        with self._cache_lock:
            self._source_cache.clear()
            self._summary_cache.clear()
            self._url_rewrite_cache.clear()
            self._url_rewrite_notes_cache.clear()

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
            "request_timeout_seconds": self.request_timeout_seconds,
            "max_payload_bytes": self.max_payload_bytes,
            "feature_limit": self.feature_limit,
            "allow_stale_on_error": self.allow_stale_on_error,
            "user_agent": self.user_agent,
            "cache_size": self._get_cache_size(),
            "url_rewrite_cache_size": self._get_url_rewrite_cache_size(),
            "geoserver_public_base_urls": self._resolve_geoserver_public_base_urls(),
            "geoserver_internal_base_urls": self._resolve_geoserver_internal_base_urls(),
            "catalog_service_summary": self._safe_catalog_service_summary(),
            "orchestrator_client_summary": self._safe_orchestrator_client_summary(),
        }

        with self._cache_lock:
            self._summary_cache[cache_key] = deepcopy(summary)

        return summary

    # ---------------------------------------------------------------------
    # Öffentliche API
    # ---------------------------------------------------------------------

    def get_dataset_source(
        self,
        dataset_id: str,
        *,
        use_cache: bool = True,
    ) -> OpenLayerDatasetSourceResult:
        normalized_dataset_id = self._sanitize_dataset_id(dataset_id)
        if not normalized_dataset_id:
            raise OpenLayerDatasetSourceError(
                "dataset_id darf nicht leer sein.",
                details={"dataset_id": dataset_id},
            )

        dataset_entry = self._get_dataset_entry(normalized_dataset_id, use_cache=use_cache)
        source_descriptor = self._resolve_source_descriptor(dataset_entry)

        cache_key = self._build_source_cache_key(
            dataset_id=normalized_dataset_id,
            source_descriptor=source_descriptor,
        )

        if self.enable_cache and use_cache:
            cached = self._get_source_cache_entry(cache_key, require_fresh=True)
            if isinstance(cached, OpenLayerDatasetSourceResult):
                cached.from_cache = True
                cached.add_note("fresh_cache_hit")
                return cached

        stale = None
        if self.enable_cache and self.allow_stale_on_error:
            stale = self._get_source_cache_entry(cache_key, require_fresh=False)

        try:
            url_resolution = self._build_effective_source_url(
                dataset_id=normalized_dataset_id,
                source_descriptor=source_descriptor,
            )
            effective_url = _safe_str(url_resolution.get("effective_url"))
            resolved_direct_url = _safe_str(url_resolution.get("direct_url"))
            url_resolution_notes = _normalize_list(url_resolution.get("notes"))

            if not effective_url:
                raise OpenLayerDatasetSourceUnavailableError(
                    f"Für Dataset '{normalized_dataset_id}' konnte keine effektive Quell-URL ermittelt werden.",
                    details={
                        "dataset_id": normalized_dataset_id,
                        "source_descriptor": deepcopy(dict(source_descriptor)),
                        "url_resolution": deepcopy(dict(url_resolution)),
                    },
                )

            http_result = self._fetch_json_source(
                dataset_id=normalized_dataset_id,
                effective_url=effective_url,
            )
            normalized_payload, payload_meta = self._normalize_geojson_payload(
                dataset_id=normalized_dataset_id,
                payload=http_result["payload"],
                feature_limit=source_descriptor["feature_limit"],
            )

            result = OpenLayerDatasetSourceResult(
                dataset_id=normalized_dataset_id,
                provider=source_descriptor["provider"],
                source_type=source_descriptor["source_type"],
                source_format=source_descriptor["source_format"],
                available=True,
                public_url=source_descriptor["public_url"],
                direct_url=resolved_direct_url or source_descriptor["direct_url"],
                effective_url=effective_url,
                payload=normalized_payload,
                payload_type=_safe_str(normalized_payload.get("type"), _GEOJSON_FEATURE_COLLECTION) or _GEOJSON_FEATURE_COLLECTION,
                feature_limit=source_descriptor["feature_limit"],
                feature_count_before_trim=_safe_int(payload_meta.get("feature_count_before_trim"), 0) or 0,
                feature_count_after_trim=_safe_int(payload_meta.get("feature_count_after_trim"), 0) or 0,
                trimmed=_safe_bool(payload_meta.get("trimmed"), False),
                status_code=_safe_int(http_result.get("status_code"), 200) or 200,
                headers=_normalize_mapping(http_result.get("headers")),
                from_cache=False,
                stale_cache_used=False,
                cached_at=_utc_now(),
                expires_at=_utc_now() + timedelta(seconds=self.cache_ttl_seconds),
                fetched_at=http_result.get("fetched_at"),
                elapsed_ms=_safe_float(http_result.get("elapsed_ms"), None),
                warnings=[],
                errors=[],
                notes=[],
            )

            for note in url_resolution_notes:
                result.add_note(_safe_str(note) or str(note))

            for note in _normalize_list(http_result.get("notes")):
                result.add_note(_safe_str(note) or str(note))

            for note in _normalize_list(payload_meta.get("notes")):
                result.add_note(_safe_str(note) or str(note))

            if result.trimmed:
                result.add_warning(
                    (
                        f"Die Antwort für Dataset '{normalized_dataset_id}' wurde auf "
                        f"{result.feature_count_after_trim} Features begrenzt."
                    )
                )

            if self.enable_cache and use_cache:
                self._set_source_cache_entry(cache_key, result, self.cache_ttl_seconds)

            return _deepcopy_or_value(result)

        except Exception as exc:
            if isinstance(stale, OpenLayerDatasetSourceResult):
                stale.from_cache = True
                stale.stale_cache_used = True
                stale.add_warning(
                    f"Es wird ein stale Cache-Eintrag verwendet, weil die Live-Quelle fehlgeschlagen ist: {exc}"
                )
                self._log_warning(
                    "Nutze stale Dataset-Source aus Cache für '%s' nach Fehler: %s",
                    normalized_dataset_id,
                    exc,
                )
                return stale

            if isinstance(exc, OpenLayerDatasetSourceError):
                raise

            raise OpenLayerDatasetSourceError(
                f"Die Quelle für Dataset '{normalized_dataset_id}' konnte nicht geladen werden: {exc}",
                details={
                    "dataset_id": normalized_dataset_id,
                    "source_descriptor": deepcopy(source_descriptor),
                },
                original_exception=exc,
                status_code=getattr(exc, "status_code", None),
            ) from exc

    def get_dataset_source_payload(
        self,
        dataset_id: str,
        *,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        result = self.get_dataset_source(dataset_id, use_cache=use_cache)
        payload = result.payload

        if not isinstance(payload, Mapping):
            raise OpenLayerDatasetSourcePayloadError(
                f"Für Dataset '{dataset_id}' liegt kein gültiges GeoJSON-Payload vor.",
                details={"result": result.to_dict(include_payload=False, include_headers=False)},
            )

        return {str(key): _deepcopy_or_value(value) for key, value in payload.items()}

    def get_dataset_source_summary(
        self,
        dataset_id: str,
        *,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        result = self.get_dataset_source(dataset_id, use_cache=use_cache)
        return result.to_dict(include_payload=False, include_headers=False)

    # ---------------------------------------------------------------------
    # Interne Dataset-/Source-Auflösung
    # ---------------------------------------------------------------------

    def _get_dataset_entry(
        self,
        dataset_id: str,
        *,
        use_cache: bool,
    ) -> OpenLayerDatasetEntry:
        try:
            return self.catalog_service.get_dataset(
                dataset_id,
                include_style_details=False,
                enrich_with_db=False,
                use_cache=use_cache,
            )
        except OpenLayerDatasetNotFoundError:
            raise
        except OpenLayerDatasetCatalogError as exc:
            raise OpenLayerDatasetSourceError(
                f"Dataset-Metadaten für '{dataset_id}' konnten nicht geladen werden: {exc}",
                details={"dataset_id": dataset_id},
                original_exception=exc,
                status_code=exc.status_code,
            ) from exc
        except Exception as exc:
            raise OpenLayerDatasetSourceError(
                f"Dataset-Metadaten für '{dataset_id}' konnten nicht geladen werden: {exc}",
                details={"dataset_id": dataset_id},
                original_exception=exc,
            ) from exc

    def _resolve_source_descriptor(
        self,
        dataset_entry: OpenLayerDatasetEntry,
    ) -> Dict[str, Any]:
        source = _normalize_mapping(getattr(dataset_entry, "source", {}))

        provider = _safe_str(source.get("provider"), "unknown") or "unknown"
        source_type = _safe_str(source.get("type"), "unknown") or "unknown"
        source_format = _safe_str(source.get("format"), "unknown") or "unknown"

        public_url = _safe_str(source.get("url"))
        direct_url = (
            _safe_str(source.get("direct_url"))
            or _safe_str(source.get("orchestrator_wfs_url"))
            or _safe_str(source.get("orchestrator_geojson_url"))
        )

        feature_limit = (
            _safe_int(source.get("max_features"), None)
            or _safe_int(getattr(self.orchestrator_client, "wfs_feature_limit", None), None)
            or self.feature_limit
        )

        available = _safe_bool(source.get("available"), False)

        if not available:
            raise OpenLayerDatasetSourceUnavailableError(
                f"Dataset '{dataset_entry.dataset_id}' besitzt aktuell keine verfügbare Quelle.",
                details={
                    "dataset_id": dataset_entry.dataset_id,
                    "source": deepcopy(source),
                },
            )

        return {
            "dataset_id": dataset_entry.dataset_id,
            "provider": provider,
            "source_type": source_type,
            "source_format": source_format,
            "public_url": public_url,
            "direct_url": direct_url,
            "feature_limit": feature_limit,
            "available": available,
        }

    def _build_effective_source_url(
        self,
        *,
        dataset_id: str,
        source_descriptor: Mapping[str, Any],
    ) -> Dict[str, Any]:
        direct_url = _safe_str(source_descriptor.get("direct_url"))
        public_url = _safe_str(source_descriptor.get("public_url"))
        source_type = _safe_str(source_descriptor.get("source_type"), "unknown") or "unknown"
        feature_limit = _safe_int(source_descriptor.get("feature_limit"), self.feature_limit) or self.feature_limit

        candidate_url = direct_url or public_url
        if not candidate_url:
            raise OpenLayerDatasetSourceUnavailableError(
                f"Für Dataset '{dataset_id}' ist keine direkte Quelle bekannt.",
                details={
                    "dataset_id": dataset_id,
                    "source_descriptor": deepcopy(dict(source_descriptor)),
                },
            )

        split_result = urlsplit(candidate_url)
        scheme = _safe_str(split_result.scheme, "").lower() or ""

        if scheme not in {"http", "https"}:
            raise OpenLayerDatasetSourceUnavailableError(
                (
                    f"Für Dataset '{dataset_id}' ist keine serverseitig nutzbare Quell-URL verfügbar. "
                    "Es werden nur absolute http/https-URLs unterstützt."
                ),
                details={
                    "dataset_id": dataset_id,
                    "candidate_url": candidate_url,
                    "source_type": source_type,
                },
            )

        rewritten_candidate_url, rewrite_notes = self._rewrite_source_url_for_backend(candidate_url)
        effective_direct_url = direct_url or rewritten_candidate_url

        effective_url = rewritten_candidate_url

        notes: List[str] = []
        for note in rewrite_notes:
            normalized_note = _safe_str(note)
            if normalized_note:
                notes.append(normalized_note)

        if source_type.lower() == "wfs":
            limited_url = self._apply_feature_limit_to_wfs_url(
                raw_url=effective_url,
                feature_limit=feature_limit,
            )
            if limited_url != effective_url:
                notes.append(f"wfs_feature_limit_applied:{feature_limit}")
            effective_url = limited_url

        return {
            "dataset_id": dataset_id,
            "public_url": public_url,
            "direct_url": effective_direct_url,
            "effective_url": effective_url,
            "notes": notes,
        }

    # ---------------------------------------------------------------------
    # Interne URL-Rewrite-Logik
    # ---------------------------------------------------------------------

    def _rewrite_source_url_for_backend(
        self,
        raw_url: str,
    ) -> Tuple[str, List[str]]:
        normalized_raw_url = _safe_str(raw_url)
        if normalized_raw_url is None:
            return raw_url, []

        with self._cache_lock:
            cached_url = self._url_rewrite_cache.get(normalized_raw_url)
            cached_notes = self._url_rewrite_notes_cache.get(normalized_raw_url)
            if isinstance(cached_url, str) and isinstance(cached_notes, list):
                return cached_url, list(cached_notes)

        rewritten_url = normalized_raw_url
        notes: List[str] = []

        internal_bases = self._resolve_geoserver_internal_base_urls()
        public_bases = self._resolve_geoserver_public_base_urls()

        if internal_bases:
            matched = False

            for public_base in public_bases:
                for internal_base in internal_bases:
                    candidate = self._replace_url_base(
                        raw_url=normalized_raw_url,
                        source_base=public_base,
                        target_base=internal_base,
                    )
                    if candidate and candidate != normalized_raw_url:
                        rewritten_url = candidate
                        notes.append("public_geoserver_url_rewritten_to_internal")
                        matched = True
                        break
                if matched:
                    break

            if not matched:
                localhost_rewrite = self._rewrite_localhost_geoserver_url_to_internal(
                    raw_url=normalized_raw_url,
                    internal_bases=internal_bases,
                )
                if localhost_rewrite and localhost_rewrite != normalized_raw_url:
                    rewritten_url = localhost_rewrite
                    notes.append("localhost_geoserver_url_rewritten_to_internal")

        with self._cache_lock:
            self._url_rewrite_cache[normalized_raw_url] = rewritten_url
            self._url_rewrite_notes_cache[normalized_raw_url] = list(notes)

        return rewritten_url, notes

    def _replace_url_base(
        self,
        *,
        raw_url: str,
        source_base: str,
        target_base: str,
    ) -> Optional[str]:
        normalized_raw_url = _safe_str(raw_url)
        normalized_source_base = _normalize_base_url(source_base)
        normalized_target_base = _normalize_base_url(target_base)

        if not normalized_raw_url or not normalized_source_base or not normalized_target_base:
            return None

        if not normalized_raw_url.startswith(normalized_source_base):
            return None

        suffix = normalized_raw_url[len(normalized_source_base):]
        if suffix and not suffix.startswith(("/", "?", "#")):
            return None

        return f"{normalized_target_base}{suffix}"

    def _rewrite_localhost_geoserver_url_to_internal(
        self,
        *,
        raw_url: str,
        internal_bases: Sequence[str],
    ) -> Optional[str]:
        normalized_raw_url = _safe_str(raw_url)
        if normalized_raw_url is None:
            return None

        try:
            raw_parts = urlsplit(normalized_raw_url)
        except Exception:
            return None

        raw_host = _safe_str(getattr(raw_parts, "hostname", None), "").lower() or ""
        if raw_host not in _LOCALHOST_NAMES:
            return None

        raw_path = _safe_str(raw_parts.path, "") or ""
        if "/geoserver" not in raw_path:
            return None

        for internal_base in internal_bases:
            normalized_internal_base = _normalize_base_url(internal_base)
            if normalized_internal_base is None:
                continue

            try:
                internal_parts = urlsplit(normalized_internal_base)
                internal_context_path = (_safe_str(internal_parts.path, "") or "").rstrip("/")
                if not internal_context_path:
                    internal_context_path = "/geoserver"

                geoserver_anchor = "/geoserver"
                if raw_path.startswith(internal_context_path):
                    target_path = raw_path
                elif geoserver_anchor in raw_path:
                    suffix = raw_path.split(geoserver_anchor, 1)[1]
                    target_path = f"{internal_context_path}{suffix}"
                else:
                    continue

                return urlunsplit(
                    (
                        _safe_str(internal_parts.scheme, raw_parts.scheme) or raw_parts.scheme,
                        _safe_str(internal_parts.netloc, raw_parts.netloc) or raw_parts.netloc,
                        target_path,
                        raw_parts.query,
                        raw_parts.fragment,
                    )
                )
            except Exception:
                continue

        return None

    def _resolve_geoserver_public_base_urls(self) -> List[str]:
        candidates: List[Any] = [
            getattr(self.settings, "geoserver_public_base_url", None),
            getattr(self.settings, "geoserver_public_url", None),
            getattr(self.settings, "geoserver_browser_base_url", None),
            self._get_app_config_value("GEOSERVER_PUBLIC_BASE_URL"),
            self._get_app_config_value("GEOSERVER_PUBLIC_URL"),
            os.getenv("GEOSERVER_PUBLIC_BASE_URL"),
            os.getenv("GEOSERVER_PUBLIC_URL"),
            _DEFAULT_GEOSERVER_PUBLIC_BASE_URL,
        ]

        normalized: List[str] = []
        for candidate in candidates:
            base = _normalize_base_url(candidate)
            if base is not None:
                normalized.append(base)

        return _unique_texts(normalized)

    def _resolve_geoserver_internal_base_urls(self) -> List[str]:
        candidates: List[Any] = [
            getattr(self.settings, "geoserver_internal_base_url", None),
            getattr(self.settings, "geoserver_internal_url", None),
            getattr(self.settings, "geoserver_base_url", None),
            getattr(self.settings, "geoserver_url", None),
            self._get_app_config_value("GEOSERVER_INTERNAL_BASE_URL"),
            self._get_app_config_value("GEOSERVER_INTERNAL_URL"),
            self._get_app_config_value("GEOSERVER_URL"),
            os.getenv("GEOSERVER_INTERNAL_BASE_URL"),
            os.getenv("GEOSERVER_INTERNAL_URL"),
            os.getenv("GEOSERVER_URL"),
            _DEFAULT_GEOSERVER_INTERNAL_BASE_URL,
        ]

        normalized: List[str] = []
        for candidate in candidates:
            base = _normalize_base_url(candidate)
            if base is not None:
                normalized.append(base)

        return _unique_texts(normalized)

    def _get_app_config_value(self, key: str) -> Optional[str]:
        try:
            if has_app_context():
                app_config = getattr(current_app, "config", {})  # type: ignore[arg-type]
                if isinstance(app_config, Mapping) and key in app_config:
                    return _safe_str(app_config.get(key))
        except Exception:
            pass
        return None

    # ---------------------------------------------------------------------
    # Interne HTTP-Fetch-Logik
    # ---------------------------------------------------------------------

    def _fetch_json_source(
        self,
        *,
        dataset_id: str,
        effective_url: str,
    ) -> Dict[str, Any]:
        request_headers = {
            "Accept": _DEFAULT_ACCEPT_HEADER,
            "User-Agent": self.user_agent,
        }

        request_obj = Request(
            effective_url,
            method="GET",
            headers=request_headers,
        )

        started_at = _utc_now()

        try:
            self._log_info(
                "Dataset-Source-Request GET %s für dataset_id=%s",
                effective_url,
                dataset_id,
            )

            with urlopen(request_obj, timeout=self.request_timeout_seconds) as raw_response:
                status_code = int(getattr(raw_response, "status", raw_response.getcode()))
                headers = _safe_headers_to_dict(getattr(raw_response, "headers", None))
                raw_bytes = self._read_response_bytes_limited(
                    raw_response,
                    max_bytes=self.max_payload_bytes,
                )
                text = self._decode_response_bytes(raw_bytes, raw_response)
                payload, payload_error = _safe_json_loads(text)

                if payload is None:
                    raise OpenLayerDatasetSourcePayloadError(
                        (
                            f"Die Quelle für Dataset '{dataset_id}' liefert kein gültiges JSON/GeoJSON "
                            f"(HTTP {status_code})."
                        ),
                        details={
                            "dataset_id": dataset_id,
                            "effective_url": effective_url,
                            "status_code": status_code,
                            "headers": headers,
                            "payload_error": payload_error,
                            "text_excerpt": _truncate_text(text),
                        },
                        status_code=status_code,
                    )

                elapsed_ms = round((_utc_now() - started_at).total_seconds() * 1000.0, 3)

                result = {
                    "status_code": status_code,
                    "headers": headers,
                    "payload": payload,
                    "text": text,
                    "payload_error": payload_error,
                    "elapsed_ms": elapsed_ms,
                    "fetched_at": _utc_now(),
                    "notes": [],
                }

                if payload_error:
                    result["notes"].append(f"json_decode_warning:{payload_error}")

                return result

        except HTTPError as exc:
            headers = _safe_headers_to_dict(getattr(exc, "headers", None))
            body_text = None
            try:
                body_bytes = self._read_response_bytes_limited(exc, max_bytes=self.max_payload_bytes)
                body_text = self._decode_response_bytes(body_bytes, exc)
            except Exception:
                body_text = _safe_str(exc.reason)

            raise OpenLayerDatasetSourceError(
                f"Die Quelle für Dataset '{dataset_id}' antwortete mit HTTP {getattr(exc, 'code', 500)}.",
                details={
                    "dataset_id": dataset_id,
                    "effective_url": effective_url,
                    "status_code": getattr(exc, "code", 500),
                    "headers": headers,
                    "body_excerpt": _truncate_text(body_text),
                },
                original_exception=exc,
                status_code=getattr(exc, "code", None),
            ) from exc

        except URLError as exc:
            raise OpenLayerDatasetSourceError(
                f"Die Quelle für Dataset '{dataset_id}' ist nicht erreichbar: {exc}",
                details={
                    "dataset_id": dataset_id,
                    "effective_url": effective_url,
                },
                original_exception=exc,
            ) from exc

    def _read_response_bytes_limited(self, response_obj: Any, *, max_bytes: int) -> bytes:
        safe_limit = max(1024, _safe_int(max_bytes, _DEFAULT_MAX_PAYLOAD_BYTES) or _DEFAULT_MAX_PAYLOAD_BYTES)

        try:
            raw = response_obj.read(safe_limit + 1)
        except Exception as exc:
            raise OpenLayerDatasetSourceError(
                f"Die Quellantwort konnte nicht gelesen werden: {exc}",
                original_exception=exc,
            ) from exc

        if isinstance(raw, bytearray):
            raw = bytes(raw)

        if not isinstance(raw, bytes):
            raise OpenLayerDatasetSourceError(
                "Die Quellantwort ist kein Byte-Stream."
            )

        if len(raw) > safe_limit:
            raise OpenLayerDatasetSourceError(
                (
                    f"Die Quellantwort überschreitet das erlaubte Maximum von "
                    f"{safe_limit} Bytes."
                ),
                details={"max_payload_bytes": safe_limit},
            )

        return raw

    def _decode_response_bytes(self, raw_bytes: bytes, response_obj: Any) -> str:
        if not isinstance(raw_bytes, (bytes, bytearray)):
            return _safe_str(raw_bytes, "") or ""

        charset = None
        try:
            headers = getattr(response_obj, "headers", None)
            if headers is not None and hasattr(headers, "get_content_charset"):
                charset = headers.get_content_charset()
        except Exception:
            charset = None

        encoding = _safe_str(charset, "utf-8") or "utf-8"

        try:
            return raw_bytes.decode(encoding, errors="replace")
        except Exception:
            try:
                return raw_bytes.decode("utf-8", errors="replace")
            except Exception:
                return ""

    # ---------------------------------------------------------------------
    # Interne GeoJSON-Normalisierung
    # ---------------------------------------------------------------------

    def _normalize_geojson_payload(
        self,
        *,
        dataset_id: str,
        payload: Any,
        feature_limit: int,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        limit = max(1, _safe_int(feature_limit, self.feature_limit) or self.feature_limit)
        notes: List[str] = []

        if isinstance(payload, list):
            normalized_payload = {
                "type": _GEOJSON_FEATURE_COLLECTION,
                "features": [_deepcopy_or_value(item) for item in payload],
            }
            notes.append("array_wrapped_as_feature_collection")
            return self._trim_feature_collection_payload(
                dataset_id=dataset_id,
                payload=normalized_payload,
                feature_limit=limit,
                notes=notes,
            )

        if not isinstance(payload, Mapping):
            raise OpenLayerDatasetSourcePayloadError(
                f"Die Quelle für Dataset '{dataset_id}' liefert kein GeoJSON-Objekt.",
                details={
                    "dataset_id": dataset_id,
                    "actual_type": type(payload).__name__,
                },
            )

        raw_payload = _normalize_mapping(payload)
        payload_type = _safe_str(raw_payload.get("type"))

        if payload_type == _GEOJSON_FEATURE_COLLECTION:
            return self._trim_feature_collection_payload(
                dataset_id=dataset_id,
                payload=raw_payload,
                feature_limit=limit,
                notes=notes,
            )

        if payload_type == _GEOJSON_FEATURE:
            normalized_payload = {
                "type": _GEOJSON_FEATURE_COLLECTION,
                "features": [raw_payload],
            }
            notes.append("single_feature_wrapped_as_feature_collection")
            return self._trim_feature_collection_payload(
                dataset_id=dataset_id,
                payload=normalized_payload,
                feature_limit=limit,
                notes=notes,
            )

        if isinstance(raw_payload.get("features"), list):
            normalized_payload = deepcopy(raw_payload)
            normalized_payload["type"] = _GEOJSON_FEATURE_COLLECTION
            notes.append("implicit_feature_collection_type_fixed")
            return self._trim_feature_collection_payload(
                dataset_id=dataset_id,
                payload=normalized_payload,
                feature_limit=limit,
                notes=notes,
            )

        raise OpenLayerDatasetSourcePayloadError(
            f"Die Quelle für Dataset '{dataset_id}' liefert kein unterstütztes GeoJSON.",
            details={
                "dataset_id": dataset_id,
                "payload_type": payload_type,
                "keys": sorted(list(raw_payload.keys())),
            },
        )

    def _trim_feature_collection_payload(
        self,
        *,
        dataset_id: str,
        payload: MutableMapping[str, Any],
        feature_limit: int,
        notes: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        normalized_notes = list(notes or [])

        features = payload.get("features")
        if not isinstance(features, list):
            raise OpenLayerDatasetSourcePayloadError(
                f"Die FeatureCollection von Dataset '{dataset_id}' enthält kein gültiges Feature-Array.",
                details={
                    "dataset_id": dataset_id,
                    "features_type": type(features).__name__,
                },
            )

        feature_count_before_trim = len(features)
        trimmed = feature_count_before_trim > feature_limit

        trimmed_features = [_deepcopy_or_value(item) for item in features[:feature_limit]]
        normalized_payload = deepcopy(payload)
        normalized_payload["type"] = _GEOJSON_FEATURE_COLLECTION
        normalized_payload["features"] = trimmed_features

        if "numberReturned" in normalized_payload:
            normalized_payload["numberReturned"] = len(trimmed_features)

        if trimmed:
            normalized_notes.append(
                f"feature_collection_trimmed_to_{feature_limit}"
            )

        meta = {
            "feature_count_before_trim": feature_count_before_trim,
            "feature_count_after_trim": len(trimmed_features),
            "trimmed": trimmed,
            "notes": normalized_notes,
        }

        return normalized_payload, meta

    # ---------------------------------------------------------------------
    # Interne WFS-Schutzlogik
    # ---------------------------------------------------------------------

    def _apply_feature_limit_to_wfs_url(
        self,
        *,
        raw_url: str,
        feature_limit: int,
    ) -> str:
        normalized_raw_url = _safe_str(raw_url)
        if normalized_raw_url is None:
            raise OpenLayerDatasetSourceUnavailableError(
                "Die WFS-URL ist leer."
            )

        safe_limit = max(1, _safe_int(feature_limit, self.feature_limit) or self.feature_limit)

        try:
            split_result = urlsplit(normalized_raw_url)
            query_pairs = parse_qsl(split_result.query, keep_blank_values=True)

            lowered_map: Dict[str, str] = {}
            for key, value in query_pairs:
                lowered_map[str(key).lower()] = str(value)

            request_value = _safe_str(lowered_map.get("request"), "")
            has_typenames = "typenames" in lowered_map or "typename" in lowered_map

            is_get_feature_like = False
            if request_value:
                is_get_feature_like = request_value.lower() == "getfeature"
            elif has_typenames:
                is_get_feature_like = True

            if not is_get_feature_like:
                return normalized_raw_url

            existing_limit = None
            for key_name in ("count", "maxfeatures"):
                raw_value = lowered_map.get(key_name)
                if raw_value is None:
                    continue
                parsed = _safe_int(raw_value, None)
                if parsed is not None and parsed > 0:
                    existing_limit = parsed
                    break

            effective_limit = safe_limit
            if existing_limit is not None:
                effective_limit = min(existing_limit, safe_limit)

            filtered_pairs: List[Tuple[str, str]] = []
            for key, value in query_pairs:
                if str(key).lower() in {"count", "maxfeatures"}:
                    continue
                filtered_pairs.append((str(key), str(value)))

            filtered_pairs.append(("count", str(effective_limit)))
            filtered_pairs.append(("maxFeatures", str(effective_limit)))

            normalized_query = urlencode(filtered_pairs, doseq=True)
            return urlunsplit(
                (
                    split_result.scheme,
                    split_result.netloc,
                    split_result.path,
                    normalized_query,
                    split_result.fragment,
                )
            )
        except Exception as exc:
            raise OpenLayerDatasetSourceError(
                f"Die WFS-URL konnte nicht sicher begrenzt werden: {exc}",
                details={"raw_url": normalized_raw_url, "feature_limit": safe_limit},
                original_exception=exc,
            ) from exc

    # ---------------------------------------------------------------------
    # Interne Cache-Logik
    # ---------------------------------------------------------------------

    def _build_source_cache_key(
        self,
        *,
        dataset_id: str,
        source_descriptor: Mapping[str, Any],
    ) -> str:
        payload = {
            "dataset_id": dataset_id,
            "provider": _safe_str(source_descriptor.get("provider")),
            "source_type": _safe_str(source_descriptor.get("source_type")),
            "source_format": _safe_str(source_descriptor.get("source_format")),
            "direct_url": _safe_str(source_descriptor.get("direct_url")),
            "public_url": _safe_str(source_descriptor.get("public_url")),
            "feature_limit": _safe_int(source_descriptor.get("feature_limit"), None),
        }
        return f"source::{self._safe_serialize_key(payload)}"

    def _get_source_cache_entry(
        self,
        cache_key: str,
        *,
        require_fresh: bool,
    ) -> Optional[OpenLayerDatasetSourceResult]:
        with self._cache_lock:
            cached = self._source_cache.get(cache_key)
            if not isinstance(cached, _ServiceCacheEntry):
                return None
            if require_fresh and not cached.is_fresh:
                return None
            value = cached.value

        if not isinstance(value, OpenLayerDatasetSourceResult):
            return None

        return _deepcopy_or_value(value)

    def _set_source_cache_entry(
        self,
        cache_key: str,
        value: OpenLayerDatasetSourceResult,
        ttl_seconds: int,
    ) -> None:
        cached_at = _utc_now()
        expires_at = cached_at + timedelta(seconds=max(0, ttl_seconds))

        cached_value = _deepcopy_or_value(value)
        cached_value.cached_at = cached_at
        cached_value.expires_at = expires_at

        entry = _ServiceCacheEntry(
            value=cached_value,
            cached_at=cached_at,
            expires_at=expires_at,
        )

        with self._cache_lock:
            self._source_cache[cache_key] = entry

    def _get_cache_size(self) -> int:
        with self._cache_lock:
            return len(self._source_cache)

    def _get_url_rewrite_cache_size(self) -> int:
        with self._cache_lock:
            return len(self._url_rewrite_cache)

    def _safe_serialize_key(self, value: Any) -> str:
        try:
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
                    "OPENLAYER_DATASET_SOURCE_CACHE_TTL_SECONDS",
                    "GEOSERVER_ORCHESTRATOR_SOURCE_CACHE_TTL_SECONDS",
                ):
                    if key in app_config:
                        return max(0, _safe_int(app_config.get(key), fallback) or fallback)
        except Exception:
            pass

        return fallback

    def _resolve_request_timeout_seconds(
        self,
        explicit_value: Optional[int],
        settings: Settings,
    ) -> int:
        if explicit_value is not None:
            return max(1, _safe_int(explicit_value, _DEFAULT_REQUEST_TIMEOUT_SECONDS) or _DEFAULT_REQUEST_TIMEOUT_SECONDS)

        for attr_name in (
            "dataset_source_request_timeout_seconds",
            "openlayer_dataset_source_timeout_seconds",
            "geoserver_orchestrator_timeout_seconds",
            "orchestrator_timeout_seconds",
        ):
            try:
                value = getattr(settings, attr_name, None)
                if value is not None:
                    return max(1, _safe_int(value, _DEFAULT_REQUEST_TIMEOUT_SECONDS) or _DEFAULT_REQUEST_TIMEOUT_SECONDS)
            except Exception:
                continue

        try:
            if has_app_context():
                app_config = getattr(current_app, "config", {})  # type: ignore[arg-type]
                for key in (
                    "OPENLAYER_DATASET_SOURCE_TIMEOUT_SECONDS",
                    "GEOSERVER_ORCHESTRATOR_TIMEOUT_SECONDS",
                ):
                    if key in app_config:
                        return max(1, _safe_int(app_config.get(key), _DEFAULT_REQUEST_TIMEOUT_SECONDS) or _DEFAULT_REQUEST_TIMEOUT_SECONDS)
        except Exception:
            pass

        return _DEFAULT_REQUEST_TIMEOUT_SECONDS

    def _resolve_max_payload_bytes(
        self,
        explicit_value: Optional[int],
        settings: Settings,
    ) -> int:
        if explicit_value is not None:
            return max(1024, _safe_int(explicit_value, _DEFAULT_MAX_PAYLOAD_BYTES) or _DEFAULT_MAX_PAYLOAD_BYTES)

        for attr_name in (
            "dataset_source_max_payload_bytes",
            "openlayer_dataset_source_max_payload_bytes",
            "geoserver_orchestrator_source_max_payload_bytes",
        ):
            try:
                value = getattr(settings, attr_name, None)
                if value is not None:
                    return max(1024, _safe_int(value, _DEFAULT_MAX_PAYLOAD_BYTES) or _DEFAULT_MAX_PAYLOAD_BYTES)
            except Exception:
                continue

        try:
            if has_app_context():
                app_config = getattr(current_app, "config", {})  # type: ignore[arg-type]
                for key in (
                    "OPENLAYER_DATASET_SOURCE_MAX_PAYLOAD_BYTES",
                    "GEOSERVER_ORCHESTRATOR_SOURCE_MAX_PAYLOAD_BYTES",
                ):
                    if key in app_config:
                        return max(1024, _safe_int(app_config.get(key), _DEFAULT_MAX_PAYLOAD_BYTES) or _DEFAULT_MAX_PAYLOAD_BYTES)
        except Exception:
            pass

        return _DEFAULT_MAX_PAYLOAD_BYTES

    def _resolve_feature_limit(
        self,
        explicit_value: Optional[int],
        settings: Settings,
    ) -> int:
        if explicit_value is not None:
            return max(1, _safe_int(explicit_value, getattr(self.orchestrator_client, "wfs_feature_limit", 100)) or 100)

        try:
            client_limit = _safe_int(getattr(self.orchestrator_client, "wfs_feature_limit", None), None)
            if client_limit is not None and client_limit > 0:
                return client_limit
        except Exception:
            pass

        for attr_name in (
            "dataset_wfs_feature_limit",
            "geoserver_orchestrator_wfs_feature_limit",
            "orchestrator_wfs_feature_limit",
        ):
            try:
                value = getattr(settings, attr_name, None)
                if value is not None:
                    return max(1, _safe_int(value, 100) or 100)
            except Exception:
                continue

        return 100

    def _resolve_user_agent(self, settings: Settings) -> str:
        for candidate in (
            getattr(settings, "service_name", None),
            _safe_str(getattr(self.catalog_service, "__class__", type(self.catalog_service)).__name__),
        ):
            normalized = _safe_str(candidate)
            if normalized:
                return f"{normalized}-dataset-source-service/1.0"
        return _DEFAULT_USER_AGENT

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

    def _log_info(self, message: str, *args: Any) -> None:
        try:
            if has_app_context():
                current_app.logger.info(message, *args)  # type: ignore[arg-type]
        except Exception:
            pass

    def _log_warning(self, message: str, *args: Any) -> None:
        try:
            if has_app_context():
                current_app.logger.warning(message, *args)  # type: ignore[arg-type]
        except Exception:
            pass


# Komfort-Aliase
DatasetSourceService = OpenLayerDatasetSourceService
DatasetSourceResult = OpenLayerDatasetSourceResult

__all__ = [
    "OpenLayerDatasetSourceError",
    "OpenLayerDatasetSourceUnavailableError",
    "OpenLayerDatasetSourcePayloadError",
    "OpenLayerDatasetSourceResult",
    "OpenLayerDatasetSourceService",
    "DatasetSourceService",
    "DatasetSourceResult",
]