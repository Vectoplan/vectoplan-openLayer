# services/openLayer/src/orchestrator/client.py
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import json
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
            "src.orchestrator.client konnte settings.py nicht importieren. "
            "Stelle sicher, dass Settings/get_settings verfügbar sind."
        ) from exc


# ---------------------------------------------------------------------------
# Modulweite Konstanten
# ---------------------------------------------------------------------------

_DEFAULT_REQUEST_TIMEOUT_SECONDS = 12
_DEFAULT_CACHE_TTL_SECONDS = 20
_DEFAULT_HEALTH_CACHE_TTL_SECONDS = 8
_DEFAULT_CATALOG_CACHE_TTL_SECONDS = 20
_DEFAULT_STYLE_CACHE_TTL_SECONDS = 25
_DEFAULT_WFS_FEATURE_LIMIT = 100

_ALLOWED_HTTP_SCHEMES = frozenset({"http", "https"})
_DEFAULT_JSON_ACCEPT = "application/json"
_DEFAULT_USER_AGENT = "openlayer-orchestrator-client/1.0"

_TRUE_VALUES = frozenset({"1", "true", "t", "yes", "y", "on", "ja"})
_FALSE_VALUES = frozenset({"0", "false", "f", "no", "n", "off", "nein"})


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


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return int(default)
        if isinstance(value, bool):
            return int(default)
        return int(str(value).strip())
    except Exception:
        return int(default)


def _safe_bool(value: Any, default: bool = False) -> bool:
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

    try:
        return bool(value)
    except Exception:
        return bool(default)


def _deepcopy_or_value(value: Any) -> Any:
    try:
        return deepcopy(value)
    except Exception:
        return value


def _safe_json_loads(text: str) -> Tuple[Any, Optional[str]]:
    try:
        return json.loads(text), None
    except Exception as exc:
        return None, f"{exc.__class__.__name__}: {exc}"


def _safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        try:
            return repr(value)
        except Exception:
            return "<unserializable>"


def _normalize_url(value: Optional[str]) -> Optional[str]:
    text_value = _safe_str(value)
    if text_value is None:
        return None

    try:
        normalized = text_value.rstrip("/")
        return normalized if normalized else None
    except Exception:
        return text_value


def _join_url(base_url: str, relative_path: str) -> str:
    normalized_base = _normalize_url(base_url)
    if not normalized_base:
        raise OrchestratorConfigurationError("Die Orchestrator-Basis-URL ist leer oder ungültig.")

    normalized_path = _safe_str(relative_path, "") or ""
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"

    while "//" in normalized_path:
        normalized_path = normalized_path.replace("//", "/")

    return f"{normalized_base}{normalized_path}"


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
            return result
    except Exception:
        pass

    return result


def _normalize_mapping(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    try:
        return {str(key): _deepcopy_or_value(item) for key, item in value.items()}
    except Exception:
        return {}


def _normalize_query_mapping(value: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    if not isinstance(value, Mapping):
        return normalized

    for key, item in value.items():
        normalized_key = _safe_str(key)
        if normalized_key is None:
            continue
        if item is None:
            continue
        normalized_value = _safe_str(item)
        if normalized_value is None:
            continue
        normalized[normalized_key] = normalized_value

    return normalized


def _build_url_with_query(base_url: str, query_params: Optional[Mapping[str, Any]]) -> str:
    normalized_params = _normalize_query_mapping(query_params)
    if not normalized_params:
        return base_url

    try:
        query_string = urlencode(normalized_params, doseq=True)
        split_result = urlsplit(base_url)

        existing_query_pairs = parse_qsl(split_result.query, keep_blank_values=True)
        merged_query_pairs: List[Tuple[str, str]] = []

        existing_keys = {str(key) for key, _value in existing_query_pairs}
        for key, value in existing_query_pairs:
            if key in normalized_params:
                continue
            merged_query_pairs.append((str(key), str(value)))

        for key, value in normalized_params.items():
            merged_query_pairs.append((key, value))

        final_query = urlencode(merged_query_pairs, doseq=True)
        return urlunsplit(
            (
                split_result.scheme,
                split_result.netloc,
                split_result.path,
                final_query,
                split_result.fragment,
            )
        )
    except Exception as exc:
        raise OrchestratorClientError(
            f"Query-Parameter konnten nicht aufgebaut werden: {exc}"
        ) from exc


def _truncate_text(value: Optional[str], max_length: int = 800) -> Optional[str]:
    text_value = _safe_str(value)
    if text_value is None:
        return None
    if len(text_value) <= max_length:
        return text_value
    return text_value[:max_length] + "...<truncated>"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class OrchestratorClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        status_code: Optional[int] = None,
        original_exception: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self.details = deepcopy(details) if isinstance(details, dict) else {}
        self.status_code = status_code
        self.original_exception = original_exception

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "message": str(self),
            "details": deepcopy(self.details),
            "status_code": self.status_code,
            "error_type": self.__class__.__name__,
        }
        if self.original_exception is not None:
            payload["original_exception_type"] = self.original_exception.__class__.__name__
            payload["original_exception_message"] = str(self.original_exception)
        return payload


class OrchestratorConfigurationError(OrchestratorClientError):
    pass


class OrchestratorHttpError(OrchestratorClientError):
    pass


class OrchestratorPayloadError(OrchestratorClientError):
    pass


class OrchestratorNotConfiguredError(OrchestratorConfigurationError):
    pass


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OrchestratorClientResponse:
    ok: bool
    method: str
    url: str
    path: str
    status_code: int
    payload: Any = None
    text: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    from_cache: bool = False
    stale_cache_used: bool = False
    cached_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    elapsed_ms: Optional[float] = None
    error: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def add_note(self, message: str) -> None:
        normalized = _safe_str(message)
        if normalized and normalized not in self.notes:
            self.notes.append(normalized)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "method": self.method,
            "url": self.url,
            "path": self.path,
            "status_code": self.status_code,
            "payload": _deepcopy_or_value(self.payload),
            "text": self.text,
            "headers": deepcopy(self.headers),
            "from_cache": self.from_cache,
            "stale_cache_used": self.stale_cache_used,
            "cached_at": _dt_to_iso(self.cached_at),
            "expires_at": _dt_to_iso(self.expires_at),
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
            "notes": list(self.notes),
        }

    def raise_for_status(self, message_prefix: Optional[str] = None) -> None:
        if self.ok:
            return

        prefix = _safe_str(message_prefix, "Orchestrator-Request fehlgeschlagen")
        raise OrchestratorHttpError(
            f"{prefix}: HTTP {self.status_code}",
            status_code=self.status_code,
            details={
                "url": self.url,
                "path": self.path,
                "payload": _deepcopy_or_value(self.payload),
                "text": _truncate_text(self.text),
                "headers": deepcopy(self.headers),
                "notes": list(self.notes),
                "error": self.error,
            },
        )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class GeoServerOrchestratorClient:
    """
    Robuster Low-Level-HTTP-Client für den GeoServer-Orchestrator.

    Ziele:
    - serverseitige Kommunikation OpenLayer -> GeoServer-Orchestrator kapseln
    - kleine TTL-Caches für wiederkehrende Read-Requests
    - stale-cache fallback bei temporären Fehlern
    - WFS-Links aus /catalog sicher auf ein Maximum von 100 Features begrenzen
    - keine Frontend-Kopplung an rohe Orchestrator-Endpunkte
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        base_url: Optional[str] = None,
        request_timeout_seconds: Optional[int] = None,
        cache_ttl_seconds: Optional[int] = None,
        health_cache_ttl_seconds: Optional[int] = None,
        catalog_cache_ttl_seconds: Optional[int] = None,
        style_cache_ttl_seconds: Optional[int] = None,
        wfs_feature_limit: Optional[int] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self.settings = settings or self._settings()
        self._cache_lock = RLock()
        self._response_cache: Dict[str, OrchestratorClientResponse] = {}
        self._summary_cache: Dict[str, Dict[str, Any]] = {}
        self._normalized_url_cache: Dict[str, Tuple[str, Dict[str, Any]]] = {}

        self.base_url = _normalize_url(base_url) or self._resolve_base_url(self.settings)
        self.request_timeout_seconds = self._resolve_request_timeout_seconds(
            request_timeout_seconds,
            self.settings,
        )
        self.cache_ttl_seconds = self._resolve_cache_ttl_seconds(
            cache_ttl_seconds,
            self.settings,
            fallback=_DEFAULT_CACHE_TTL_SECONDS,
        )
        self.health_cache_ttl_seconds = self._resolve_cache_ttl_seconds(
            health_cache_ttl_seconds,
            self.settings,
            fallback=_DEFAULT_HEALTH_CACHE_TTL_SECONDS,
            attr_candidates=(
                "geoserver_orchestrator_health_cache_ttl_seconds",
                "orchestrator_health_cache_ttl_seconds",
            ),
        )
        self.catalog_cache_ttl_seconds = self._resolve_cache_ttl_seconds(
            catalog_cache_ttl_seconds,
            self.settings,
            fallback=_DEFAULT_CATALOG_CACHE_TTL_SECONDS,
            attr_candidates=(
                "geoserver_orchestrator_catalog_cache_ttl_seconds",
                "orchestrator_catalog_cache_ttl_seconds",
            ),
        )
        self.style_cache_ttl_seconds = self._resolve_cache_ttl_seconds(
            style_cache_ttl_seconds,
            self.settings,
            fallback=_DEFAULT_STYLE_CACHE_TTL_SECONDS,
            attr_candidates=(
                "geoserver_orchestrator_style_cache_ttl_seconds",
                "orchestrator_style_cache_ttl_seconds",
            ),
        )
        self.wfs_feature_limit = self._resolve_wfs_feature_limit(
            wfs_feature_limit,
            self.settings,
        )
        self.user_agent = _safe_str(user_agent, None) or self._resolve_user_agent(self.settings)

    # ---------------------------------------------------------------------
    # Öffentliche Diagnose / Cache
    # ---------------------------------------------------------------------

    def clear_caches(self) -> None:
        with self._cache_lock:
            self._response_cache.clear()
            self._summary_cache.clear()
            self._normalized_url_cache.clear()

    def get_client_summary(self) -> Dict[str, Any]:
        cache_key = "client_summary"

        with self._cache_lock:
            cached = self._summary_cache.get(cache_key)
            if isinstance(cached, dict):
                return deepcopy(cached)

        summary = {
            "configured": self.is_configured(),
            "base_url": self.base_url,
            "request_timeout_seconds": self.request_timeout_seconds,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "health_cache_ttl_seconds": self.health_cache_ttl_seconds,
            "catalog_cache_ttl_seconds": self.catalog_cache_ttl_seconds,
            "style_cache_ttl_seconds": self.style_cache_ttl_seconds,
            "wfs_feature_limit": self.wfs_feature_limit,
            "user_agent": self.user_agent,
            "cache_size": self._get_cache_size(),
        }

        with self._cache_lock:
            self._summary_cache[cache_key] = deepcopy(summary)

        return summary

    def is_configured(self) -> bool:
        if not self.base_url:
            return False

        try:
            split_result = urlsplit(self.base_url)
            if _safe_str(split_result.scheme) not in _ALLOWED_HTTP_SCHEMES:
                return False
            if not _safe_str(split_result.netloc):
                return False
            return True
        except Exception:
            return False

    # ---------------------------------------------------------------------
    # Öffentliche Endpunkte
    # ---------------------------------------------------------------------

    def get_health_live(
        self,
        *,
        use_cache: bool = True,
        cache_ttl_seconds: Optional[int] = None,
        allow_stale_on_error: bool = True,
    ) -> OrchestratorClientResponse:
        return self._request_json(
            path="/health/live",
            use_cache=use_cache,
            cache_ttl_seconds=cache_ttl_seconds or self.health_cache_ttl_seconds,
            allow_stale_on_error=allow_stale_on_error,
            normalize_payload=False,
        )

    def get_health_ready(
        self,
        *,
        use_cache: bool = True,
        cache_ttl_seconds: Optional[int] = None,
        allow_stale_on_error: bool = True,
    ) -> OrchestratorClientResponse:
        return self._request_json(
            path="/health/ready",
            use_cache=use_cache,
            cache_ttl_seconds=cache_ttl_seconds or self.health_cache_ttl_seconds,
            allow_stale_on_error=allow_stale_on_error,
            normalize_payload=False,
        )

    def get_catalog_index(
        self,
        *,
        include_invalid: bool = True,
        include_source_files: bool = False,
        include_validation_reports: bool = False,
        include_state_payloads: bool = False,
        enrich_with_db: bool = False,
        dataset_ids: Optional[Sequence[str]] = None,
        use_cache: bool = True,
        cache_ttl_seconds: Optional[int] = None,
        allow_stale_on_error: bool = True,
    ) -> OrchestratorClientResponse:
        query_params: Dict[str, Any] = {
            "include_invalid": "true" if include_invalid else "false",
            "include_source_files": "true" if include_source_files else "false",
            "include_validation_reports": "true" if include_validation_reports else "false",
            "include_state_payloads": "true" if include_state_payloads else "false",
            "enrich_with_db": "true" if enrich_with_db else "false",
        }

        if dataset_ids:
            normalized_ids = [
                item_id
                for item_id in [self._safe_dataset_id(item) for item in dataset_ids]
                if item_id
            ]
            if normalized_ids:
                query_params["dataset_ids"] = ",".join(normalized_ids)

        return self._request_json(
            path="/catalog",
            query_params=query_params,
            use_cache=use_cache,
            cache_ttl_seconds=cache_ttl_seconds or self.catalog_cache_ttl_seconds,
            allow_stale_on_error=allow_stale_on_error,
            normalize_payload=True,
            payload_normalizer=self._normalize_catalog_payload,
        )

    def get_catalog_index_payload(self, **kwargs: Any) -> Dict[str, Any]:
        response = self.get_catalog_index(**kwargs)
        response.raise_for_status("Katalogliste konnte nicht geladen werden")
        return self._expect_mapping_payload(
            response.payload,
            context="catalog_index",
            response=response,
        )

    def get_catalog_entry(
        self,
        dataset_id: str,
        *,
        include_source_files: bool = True,
        include_validation_reports: bool = True,
        include_state_payloads: bool = True,
        enrich_with_db: bool = False,
        use_cache: bool = True,
        cache_ttl_seconds: Optional[int] = None,
        allow_stale_on_error: bool = True,
    ) -> OrchestratorClientResponse:
        normalized_dataset_id = self._safe_dataset_id(dataset_id)
        if not normalized_dataset_id:
            raise OrchestratorPayloadError(
                "dataset_id darf nicht leer sein.",
                details={"dataset_id": dataset_id},
            )

        query_params: Dict[str, Any] = {
            "include_source_files": "true" if include_source_files else "false",
            "include_validation_reports": "true" if include_validation_reports else "false",
            "include_state_payloads": "true" if include_state_payloads else "false",
            "enrich_with_db": "true" if enrich_with_db else "false",
        }

        return self._request_json(
            path=f"/catalog/{normalized_dataset_id}",
            query_params=query_params,
            use_cache=use_cache,
            cache_ttl_seconds=cache_ttl_seconds or self.catalog_cache_ttl_seconds,
            allow_stale_on_error=allow_stale_on_error,
            normalize_payload=True,
            payload_normalizer=self._normalize_catalog_entry_payload,
        )

    def get_catalog_entry_payload(self, dataset_id: str, **kwargs: Any) -> Dict[str, Any]:
        response = self.get_catalog_entry(dataset_id, **kwargs)
        response.raise_for_status("Katalogeintrag konnte nicht geladen werden")
        return self._expect_mapping_payload(
            response.payload,
            context="catalog_entry",
            response=response,
        )

    def get_style(
        self,
        dataset_id: str,
        *,
        view: str = "envelope",
        strict_validation: Optional[bool] = None,
        include_validation_report: Optional[bool] = None,
        include_catalog: bool = False,
        enrich_with_db: bool = False,
        include_issues: bool = True,
        include_rules: bool = True,
        include_raw_payload: bool = False,
        use_cache: bool = True,
        cache_ttl_seconds: Optional[int] = None,
        allow_stale_on_error: bool = True,
    ) -> OrchestratorClientResponse:
        normalized_dataset_id = self._safe_dataset_id(dataset_id)
        if not normalized_dataset_id:
            raise OrchestratorPayloadError(
                "dataset_id darf nicht leer sein.",
                details={"dataset_id": dataset_id},
            )

        normalized_view = _safe_str(view, "envelope") or "envelope"
        normalized_view = normalized_view.lower()
        if normalized_view not in {"payload", "envelope", "validation"}:
            raise OrchestratorPayloadError(
                f"Ungültiger Style-View '{view}'.",
                details={
                    "view": view,
                    "allowed_values": ["payload", "envelope", "validation"],
                },
            )

        query_params: Dict[str, Any] = {
            "view": normalized_view,
            "include_catalog": "true" if include_catalog else "false",
            "enrich_with_db": "true" if enrich_with_db else "false",
            "include_issues": "true" if include_issues else "false",
            "include_rules": "true" if include_rules else "false",
            "include_raw_payload": "true" if include_raw_payload else "false",
        }

        if strict_validation is not None:
            query_params["strict_validation"] = "true" if strict_validation else "false"

        if include_validation_report is not None:
            query_params["include_validation_report"] = "true" if include_validation_report else "false"

        return self._request_json(
            path=f"/styles/{normalized_dataset_id}",
            query_params=query_params,
            use_cache=use_cache,
            cache_ttl_seconds=cache_ttl_seconds or self.style_cache_ttl_seconds,
            allow_stale_on_error=allow_stale_on_error,
            normalize_payload=False,
        )

    def get_style_payload(
        self,
        dataset_id: str,
        *,
        strict_validation: bool = False,
        use_cache: bool = True,
        cache_ttl_seconds: Optional[int] = None,
        allow_stale_on_error: bool = True,
    ) -> Dict[str, Any]:
        response = self.get_style(
            dataset_id,
            view="payload",
            strict_validation=strict_validation,
            use_cache=use_cache,
            cache_ttl_seconds=cache_ttl_seconds,
            allow_stale_on_error=allow_stale_on_error,
        )
        response.raise_for_status("Style-Payload konnte nicht geladen werden")
        return self._expect_mapping_payload(
            response.payload,
            context="style_payload",
            response=response,
        )

    def get_style_envelope(
        self,
        dataset_id: str,
        *,
        strict_validation: bool = False,
        include_validation_report: bool = True,
        include_catalog: bool = False,
        enrich_with_db: bool = False,
        include_issues: bool = True,
        include_rules: bool = True,
        include_raw_payload: bool = False,
        use_cache: bool = True,
        cache_ttl_seconds: Optional[int] = None,
        allow_stale_on_error: bool = True,
    ) -> Dict[str, Any]:
        response = self.get_style(
            dataset_id,
            view="envelope",
            strict_validation=strict_validation,
            include_validation_report=include_validation_report,
            include_catalog=include_catalog,
            enrich_with_db=enrich_with_db,
            include_issues=include_issues,
            include_rules=include_rules,
            include_raw_payload=include_raw_payload,
            use_cache=use_cache,
            cache_ttl_seconds=cache_ttl_seconds,
            allow_stale_on_error=allow_stale_on_error,
        )
        response.raise_for_status("Style-Envelope konnte nicht geladen werden")
        return self._expect_mapping_payload(
            response.payload,
            context="style_envelope",
            response=response,
        )

    def get_style_validation(
        self,
        dataset_id: str,
        *,
        include_style: bool = True,
        include_normalized_payload: bool = True,
        include_rules: bool = True,
        include_issues: bool = True,
        use_cache: bool = True,
        cache_ttl_seconds: Optional[int] = None,
        allow_stale_on_error: bool = True,
    ) -> Dict[str, Any]:
        normalized_dataset_id = self._safe_dataset_id(dataset_id)
        if not normalized_dataset_id:
            raise OrchestratorPayloadError(
                "dataset_id darf nicht leer sein.",
                details={"dataset_id": dataset_id},
            )

        query_params = {
            "include_style": "true" if include_style else "false",
            "include_normalized_payload": "true" if include_normalized_payload else "false",
            "include_rules": "true" if include_rules else "false",
            "include_issues": "true" if include_issues else "false",
        }

        response = self._request_json(
            path=f"/styles/{normalized_dataset_id}/validation",
            query_params=query_params,
            use_cache=use_cache,
            cache_ttl_seconds=cache_ttl_seconds or self.style_cache_ttl_seconds,
            allow_stale_on_error=allow_stale_on_error,
            normalize_payload=False,
        )
        response.raise_for_status("Style-Validierung konnte nicht geladen werden")
        return self._expect_mapping_payload(
            response.payload,
            context="style_validation",
            response=response,
        )

    # ---------------------------------------------------------------------
    # Interner HTTP-Request
    # ---------------------------------------------------------------------

    def _request_json(
        self,
        *,
        path: str,
        query_params: Optional[Mapping[str, Any]] = None,
        method: str = "GET",
        use_cache: bool = True,
        cache_ttl_seconds: Optional[int] = None,
        allow_stale_on_error: bool = True,
        normalize_payload: bool = False,
        payload_normalizer: Optional[Any] = None,
    ) -> OrchestratorClientResponse:
        self._ensure_configured()

        normalized_method = (_safe_str(method, "GET") or "GET").upper()
        normalized_path = _safe_str(path, "") or ""
        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"

        absolute_url = _build_url_with_query(
            _join_url(self.base_url or "", normalized_path),
            query_params,
        )

        effective_cache_ttl_seconds = max(
            0,
            _safe_int(cache_ttl_seconds, self.cache_ttl_seconds),
        )
        cache_key = self._build_cache_key(normalized_method, absolute_url)

        if use_cache:
            cached = self._get_cached_response(
                cache_key,
                require_fresh=True,
            )
            if cached is not None:
                cached.from_cache = True
                cached.add_note("fresh_cache_hit")
                return cached

        request_headers = {
            "Accept": _DEFAULT_JSON_ACCEPT,
            "User-Agent": self.user_agent,
        }

        started_at = _utc_now()
        request_obj = Request(
            absolute_url,
            method=normalized_method,
            headers=request_headers,
        )

        stale_cached_response = None
        if use_cache and allow_stale_on_error:
            stale_cached_response = self._get_cached_response(
                cache_key,
                require_fresh=False,
            )

        try:
            self._log_info(
                "GeoServer-Orchestrator-Request %s %s",
                normalized_method,
                absolute_url,
            )

            with urlopen(request_obj, timeout=self.request_timeout_seconds) as raw_response:
                status_code = int(getattr(raw_response, "status", raw_response.getcode()))
                headers = _safe_headers_to_dict(getattr(raw_response, "headers", None))

                raw_bytes = raw_response.read()
                text = self._decode_response_bytes(raw_bytes, raw_response)
                payload, payload_error = _safe_json_loads(text) if text else (None, None)

                elapsed_ms = round((_utc_now() - started_at).total_seconds() * 1000.0, 3)

                if normalize_payload and callable(payload_normalizer):
                    try:
                        payload = payload_normalizer(payload)
                    except Exception as exc:
                        raise OrchestratorPayloadError(
                            f"Die Antwort von '{normalized_path}' konnte nicht normalisiert werden: {exc}",
                            details={
                                "path": normalized_path,
                                "url": absolute_url,
                                "status_code": status_code,
                                "text_excerpt": _truncate_text(text),
                            },
                            status_code=status_code,
                            original_exception=exc,
                        ) from exc

                response = OrchestratorClientResponse(
                    ok=200 <= status_code < 300,
                    method=normalized_method,
                    url=absolute_url,
                    path=normalized_path,
                    status_code=status_code,
                    payload=_deepcopy_or_value(payload),
                    text=text,
                    headers=headers,
                    from_cache=False,
                    stale_cache_used=False,
                    cached_at=_utc_now(),
                    expires_at=_utc_now() + timedelta(seconds=effective_cache_ttl_seconds),
                    elapsed_ms=elapsed_ms,
                    error=payload_error,
                    notes=[],
                )

                if payload_error:
                    response.add_note(f"json_decode_warning:{payload_error}")

                if use_cache and response.ok:
                    self._set_cached_response(cache_key, response)

                return response

        except HTTPError as exc:
            error_response = self._build_http_error_response(
                exc=exc,
                method=normalized_method,
                url=absolute_url,
                path=normalized_path,
                started_at=started_at,
            )

            if stale_cached_response is not None:
                stale_cached_response.stale_cache_used = True
                stale_cached_response.from_cache = True
                stale_cached_response.add_note(
                    f"stale_cache_used_after_http_error:{error_response.status_code}"
                )
                return stale_cached_response

            return error_response

        except URLError as exc:
            if stale_cached_response is not None:
                stale_cached_response.stale_cache_used = True
                stale_cached_response.from_cache = True
                stale_cached_response.add_note(
                    f"stale_cache_used_after_url_error:{exc.__class__.__name__}"
                )
                return stale_cached_response

            raise OrchestratorHttpError(
                f"Der GeoServer-Orchestrator ist nicht erreichbar: {exc}",
                details={
                    "url": absolute_url,
                    "path": normalized_path,
                    "method": normalized_method,
                },
                original_exception=exc,
            ) from exc

        except OrchestratorClientError:
            raise

        except Exception as exc:
            if stale_cached_response is not None:
                stale_cached_response.stale_cache_used = True
                stale_cached_response.from_cache = True
                stale_cached_response.add_note(
                    f"stale_cache_used_after_unexpected_error:{exc.__class__.__name__}"
                )
                return stale_cached_response

            raise OrchestratorClientError(
                f"Unerwarteter Fehler beim Request an den GeoServer-Orchestrator: {exc}",
                details={
                    "url": absolute_url,
                    "path": normalized_path,
                    "method": normalized_method,
                },
                original_exception=exc,
            ) from exc

    # ---------------------------------------------------------------------
    # Interne Payload-Normalisierung
    # ---------------------------------------------------------------------

    def _normalize_catalog_payload(self, payload: Any) -> Any:
        if not isinstance(payload, Mapping):
            return payload

        normalized = _deepcopy_or_value(payload)
        if not isinstance(normalized, dict):
            return payload

        entries = normalized.get("entries")
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, MutableMapping):
                    self._apply_wfs_limit_to_catalog_entry(entry)

        return normalized

    def _normalize_catalog_entry_payload(self, payload: Any) -> Any:
        if not isinstance(payload, Mapping):
            return payload

        normalized = _deepcopy_or_value(payload)
        if not isinstance(normalized, dict):
            return payload

        self._apply_wfs_limit_to_catalog_entry(normalized)
        return normalized

    def _apply_wfs_limit_to_catalog_entry(self, entry: MutableMapping[str, Any]) -> None:
        if not isinstance(entry, MutableMapping):
            return

        urls = entry.get("urls")
        if isinstance(urls, MutableMapping):
            self._apply_wfs_limit_to_mapping(urls, field_names=("wfs_url",))

        published_state_summary = entry.get("published_state_summary")
        if isinstance(published_state_summary, MutableMapping):
            self._apply_wfs_limit_to_mapping(published_state_summary, field_names=("wfs_url",))

        published_state = entry.get("published_state")
        if isinstance(published_state, MutableMapping):
            self._apply_wfs_limit_to_mapping(published_state, field_names=("wfs_url",))

        self._apply_wfs_limit_to_mapping(entry, field_names=("wfs_url",))

    def _apply_wfs_limit_to_mapping(
        self,
        mapping: MutableMapping[str, Any],
        *,
        field_names: Sequence[str],
    ) -> None:
        if not isinstance(mapping, MutableMapping):
            return

        for field_name in field_names:
            raw_url = _safe_str(mapping.get(field_name))
            if raw_url is None:
                continue

            limited_url, meta = self._get_limited_wfs_url(raw_url)
            if not limited_url:
                continue

            original_field_name = f"{field_name}_original"
            if limited_url != raw_url and original_field_name not in mapping:
                mapping[original_field_name] = raw_url

            mapping[field_name] = limited_url
            mapping["wfs_feature_limit"] = meta.get("effective_limit")
            mapping["wfs_feature_limit_applied"] = bool(meta.get("applied", False))
            mapping["wfs_feature_limit_request_type"] = meta.get("request")
            mapping["wfs_feature_limit_version"] = meta.get("version")

    def _get_limited_wfs_url(self, raw_url: str) -> Tuple[str, Dict[str, Any]]:
        cache_key = raw_url

        with self._cache_lock:
            cached = self._normalized_url_cache.get(cache_key)
            if isinstance(cached, tuple) and len(cached) == 2:
                return cached[0], deepcopy(cached[1])

        normalized_url, meta = self._apply_feature_limit_to_wfs_url(
            raw_url=raw_url,
            feature_limit=self.wfs_feature_limit,
        )

        with self._cache_lock:
            self._normalized_url_cache[cache_key] = (normalized_url, deepcopy(meta))

        return normalized_url, meta

    @staticmethod
    def _apply_feature_limit_to_wfs_url(
        *,
        raw_url: str,
        feature_limit: int,
    ) -> Tuple[str, Dict[str, Any]]:
        default_meta = {
            "applied": False,
            "effective_limit": feature_limit,
            "request": None,
            "version": None,
        }

        normalized_raw_url = _safe_str(raw_url)
        if normalized_raw_url is None:
            return raw_url, default_meta

        try:
            split_result = urlsplit(normalized_raw_url)
            query_pairs = parse_qsl(split_result.query, keep_blank_values=True)

            lowered_map: Dict[str, str] = {}
            for key, value in query_pairs:
                lowered_map[str(key).lower()] = str(value)

            request_value = _safe_str(lowered_map.get("request"))
            version_value = _safe_str(lowered_map.get("version"))
            has_typenames = "typenames" in lowered_map or "typename" in lowered_map
            has_output_format = "outputformat" in lowered_map

            is_get_feature_like = False
            if request_value is not None:
                is_get_feature_like = request_value.lower() == "getfeature"
            elif has_typenames or has_output_format:
                is_get_feature_like = True

            meta = {
                "applied": False,
                "effective_limit": feature_limit,
                "request": request_value,
                "version": version_value,
            }

            if not is_get_feature_like:
                return normalized_raw_url, meta

            existing_limit: Optional[int] = None
            for key_name in ("count", "maxfeatures"):
                raw_value = lowered_map.get(key_name)
                if raw_value is None:
                    continue
                try:
                    parsed_value = int(str(raw_value).strip())
                    if parsed_value > 0:
                        existing_limit = parsed_value
                        break
                except Exception:
                    continue

            effective_limit = feature_limit
            if existing_limit is not None and existing_limit > 0:
                effective_limit = min(existing_limit, feature_limit)

            filtered_pairs: List[Tuple[str, str]] = []
            for key, value in query_pairs:
                if str(key).lower() in {"count", "maxfeatures"}:
                    continue
                filtered_pairs.append((str(key), str(value)))

            filtered_pairs.append(("count", str(effective_limit)))
            filtered_pairs.append(("maxFeatures", str(effective_limit)))

            normalized_query = urlencode(filtered_pairs, doseq=True)
            normalized_url = urlunsplit(
                (
                    split_result.scheme,
                    split_result.netloc,
                    split_result.path,
                    normalized_query,
                    split_result.fragment,
                )
            )

            meta["applied"] = True
            meta["effective_limit"] = effective_limit
            return normalized_url, meta

        except Exception:
            return normalized_raw_url, default_meta

    # ---------------------------------------------------------------------
    # Interne Cache-Logik
    # ---------------------------------------------------------------------

    def _build_cache_key(self, method: str, url: str) -> str:
        return f"{method.upper()}::{url}"

    def _get_cache_size(self) -> int:
        with self._cache_lock:
            return len(self._response_cache)

    def _get_cached_response(
        self,
        cache_key: str,
        *,
        require_fresh: bool,
    ) -> Optional[OrchestratorClientResponse]:
        with self._cache_lock:
            cached = self._response_cache.get(cache_key)
            if not isinstance(cached, OrchestratorClientResponse):
                return None

            if require_fresh:
                if cached.expires_at is None:
                    return None
                if cached.expires_at < _utc_now():
                    return None

            return deepcopy(cached)

    def _set_cached_response(
        self,
        cache_key: str,
        response: OrchestratorClientResponse,
    ) -> None:
        with self._cache_lock:
            self._response_cache[cache_key] = deepcopy(response)

    # ---------------------------------------------------------------------
    # Interne Fehler-/Payload-Helfer
    # ---------------------------------------------------------------------

    def _build_http_error_response(
        self,
        *,
        exc: HTTPError,
        method: str,
        url: str,
        path: str,
        started_at: datetime,
    ) -> OrchestratorClientResponse:
        status_code = int(getattr(exc, "code", 500))
        headers = _safe_headers_to_dict(getattr(exc, "headers", None))

        text = None
        payload = None
        payload_error = None

        try:
            raw_bytes = exc.read()
            text = self._decode_response_bytes(raw_bytes, exc)
        except Exception:
            text = _safe_str(exc.reason)

        if text:
            payload, payload_error = _safe_json_loads(text)

        elapsed_ms = round((_utc_now() - started_at).total_seconds() * 1000.0, 3)

        response = OrchestratorClientResponse(
            ok=False,
            method=method,
            url=url,
            path=path,
            status_code=status_code,
            payload=_deepcopy_or_value(payload),
            text=text,
            headers=headers,
            from_cache=False,
            stale_cache_used=False,
            cached_at=None,
            expires_at=None,
            elapsed_ms=elapsed_ms,
            error=payload_error or _safe_str(exc.reason) or f"HTTP {status_code}",
            notes=[],
        )

        response.add_note("http_error_response")
        return response

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

    def _expect_mapping_payload(
        self,
        payload: Any,
        *,
        context: str,
        response: OrchestratorClientResponse,
    ) -> Dict[str, Any]:
        if isinstance(payload, Mapping):
            return {str(key): _deepcopy_or_value(value) for key, value in payload.items()}

        raise OrchestratorPayloadError(
            f"Der Orchestrator lieferte für '{context}' kein JSON-Objekt.",
            details={
                "context": context,
                "response": response.to_dict(),
                "actual_type": type(payload).__name__,
            },
            status_code=response.status_code,
        )

    def _ensure_configured(self) -> None:
        if not self.is_configured():
            raise OrchestratorNotConfiguredError(
                "Der GeoServer-Orchestrator ist nicht korrekt konfiguriert.",
                details={
                    "base_url": self.base_url,
                    "client_summary": self.get_client_summary(),
                },
            )

    def _safe_dataset_id(self, dataset_id: Any) -> Optional[str]:
        text_value = _safe_str(dataset_id)
        if text_value is None:
            return None

        settings = self.settings or self._settings()

        sanitizer = getattr(settings, "sanitize_dataset_id", None)
        if callable(sanitizer):
            try:
                return sanitizer(text_value)
            except Exception:
                return text_value

        return text_value

    # ---------------------------------------------------------------------
    # Settings / Defaults / Logging
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

    def _resolve_base_url(self, settings: Settings) -> Optional[str]:
        candidates = [
            getattr(settings, "geoserver_orchestrator_url", None),
            self._read_app_config_value("GEOSERVER_ORCHESTRATOR_URL"),
            self._read_app_config_value("ORCHESTRATOR_BASE_URL"),
        ]

        for candidate in candidates:
            normalized = _normalize_url(_safe_str(candidate))
            if normalized is not None:
                return normalized

        return None

    def _resolve_request_timeout_seconds(
        self,
        explicit_value: Optional[int],
        settings: Settings,
    ) -> int:
        if explicit_value is not None:
            return max(1, _safe_int(explicit_value, _DEFAULT_REQUEST_TIMEOUT_SECONDS))

        for attr_name in (
            "geoserver_orchestrator_timeout_seconds",
            "orchestrator_timeout_seconds",
            "http_request_timeout_seconds",
        ):
            try:
                value = getattr(settings, attr_name, None)
                if value is not None:
                    return max(1, _safe_int(value, _DEFAULT_REQUEST_TIMEOUT_SECONDS))
            except Exception:
                continue

        config_value = self._read_app_config_value("GEOSERVER_ORCHESTRATOR_TIMEOUT_SECONDS")
        if config_value is not None:
            return max(1, _safe_int(config_value, _DEFAULT_REQUEST_TIMEOUT_SECONDS))

        return _DEFAULT_REQUEST_TIMEOUT_SECONDS

    def _resolve_cache_ttl_seconds(
        self,
        explicit_value: Optional[int],
        settings: Settings,
        *,
        fallback: int,
        attr_candidates: Sequence[str] = (
            "geoserver_orchestrator_cache_ttl_seconds",
            "orchestrator_cache_ttl_seconds",
        ),
    ) -> int:
        if explicit_value is not None:
            return max(0, _safe_int(explicit_value, fallback))

        for attr_name in attr_candidates:
            try:
                value = getattr(settings, attr_name, None)
                if value is not None:
                    return max(0, _safe_int(value, fallback))
            except Exception:
                continue

        for attr_name in (
            "GEOSERVER_ORCHESTRATOR_CACHE_TTL_SECONDS",
            "ORCHESTRATOR_CACHE_TTL_SECONDS",
        ):
            config_value = self._read_app_config_value(attr_name)
            if config_value is not None:
                return max(0, _safe_int(config_value, fallback))

        return fallback

    def _resolve_wfs_feature_limit(
        self,
        explicit_value: Optional[int],
        settings: Settings,
    ) -> int:
        if explicit_value is not None:
            return max(1, _safe_int(explicit_value, _DEFAULT_WFS_FEATURE_LIMIT))

        for attr_name in (
            "geoserver_orchestrator_wfs_feature_limit",
            "orchestrator_wfs_feature_limit",
            "dataset_wfs_feature_limit",
        ):
            try:
                value = getattr(settings, attr_name, None)
                if value is not None:
                    return max(1, _safe_int(value, _DEFAULT_WFS_FEATURE_LIMIT))
            except Exception:
                continue

        for attr_name in (
            "GEOSERVER_ORCHESTRATOR_WFS_FEATURE_LIMIT",
            "ORCHESTRATOR_WFS_FEATURE_LIMIT",
        ):
            config_value = self._read_app_config_value(attr_name)
            if config_value is not None:
                return max(1, _safe_int(config_value, _DEFAULT_WFS_FEATURE_LIMIT))

        return _DEFAULT_WFS_FEATURE_LIMIT

    def _resolve_user_agent(self, settings: Settings) -> str:
        for candidate in (
            getattr(settings, "service_name", None),
            self._read_app_config_value("SERVICE_NAME"),
        ):
            normalized = _safe_str(candidate)
            if normalized:
                return f"{normalized}-orchestrator-client/1.0"
        return _DEFAULT_USER_AGENT

    def _read_app_config_value(self, key: str) -> Any:
        try:
            if has_app_context():
                app_config = getattr(current_app, "config", None)  # type: ignore[arg-type]
                if app_config is not None and key in app_config:
                    return app_config.get(key)
        except Exception:
            pass
        return None

    def _log_info(self, message: str, *args: Any) -> None:
        try:
            if has_app_context():
                current_app.logger.info(message, *args)  # type: ignore[arg-type]
                return
        except Exception:
            pass

    # kein harter Fallback-Logger nötig; der Client soll auch ohne Logging stabil laufen.

# Komfort-Alias
OrchestratorClient = GeoServerOrchestratorClient

__all__ = [
    "OrchestratorClientError",
    "OrchestratorConfigurationError",
    "OrchestratorHttpError",
    "OrchestratorPayloadError",
    "OrchestratorNotConfiguredError",
    "OrchestratorClientResponse",
    "GeoServerOrchestratorClient",
    "OrchestratorClient",
]