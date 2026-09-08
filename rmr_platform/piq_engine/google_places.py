from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime, timezone
import logging
import math
import json
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .contracts import NormalizedCandidate, PiqProviderError, ProviderIssue, ProviderSearchResult


TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
DETAIL_FIELDS = (
    "place_id,name,formatted_address,address_components,formatted_phone_number,"
    "international_phone_number,website,type,rating,user_ratings_total,"
    "business_status,url,vicinity,geometry"
)
MAX_PAGES = 3
MAX_RAW_LIST_ITEMS = 20
MAX_RAW_TEXT = 1000
MAX_RESPONSE_BYTES = 1_000_000
_private_request = ContextVar("piq_google_private_request", default=False)


class _PrivateRequestFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Legacy Google uses query-string credentials. Suppress only this
        # request's HTTP wire logs, without disabling other RMR client logging.
        return not _private_request.get()


for _logger_name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2",
                     "httpcore.proxy", "httpcore.socks"):
    logging.getLogger(_logger_name).addFilter(_PrivateRequestFilter())


def _text(value: Any, *, limit: int = MAX_RAW_TEXT) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())[:limit]
    return cleaned or None


def safe_url(value: Any) -> str | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        # Preserve Google's numeric CID link, but discard credential-bearing
        # or otherwise unnecessary query parameters and fragments.
        query = urlencode([(key, val) for key, val in parse_qsl(parsed.query)
                           if key == "cid" and val.isascii() and val.isdigit() and len(val) <= 30])
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))[:1000]
    except ValueError:
        return None


def _number(value: Any, kind: type[float] | type[int]) -> float | int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = kind(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_raw(data: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key in (
        "place_id",
        "name",
        "formatted_address",
        "vicinity",
        "formatted_phone_number",
        "international_phone_number",
        "website",
        "business_status",
        "rating",
        "user_ratings_total",
        "url",
    ):
        value = data.get(key)
        if key in {"website", "url"}:
            value = safe_url(value)
        elif isinstance(value, str):
            value = _text(value)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            if isinstance(value, (int, float)) and not math.isfinite(value):
                continue
            safe[key] = value
    types = data.get("types")
    if isinstance(types, list):
        safe["types"] = [item[:80] for item in types[:MAX_RAW_LIST_ITEMS] if isinstance(item, str)]
    geometry = data.get("geometry")
    if isinstance(geometry, dict) and isinstance(geometry.get("location"), dict):
        location = geometry["location"]
        safe["geometry"] = {"location": {"lat": _number(location.get("lat"), float), "lng": _number(location.get("lng"), float)}}
    return safe


def _address_parts(data: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    city = state = country = None
    components = data.get("address_components")
    if not isinstance(components, list):
        return city, state, country
    for component in components[:30]:
        if not isinstance(component, dict):
            continue
        types = component.get("types") if isinstance(component.get("types"), list) else []
        value = _text(component.get("long_name"), limit=160)
        if "locality" in types or (not city and "postal_town" in types):
            city = value
        elif "administrative_area_level_1" in types:
            state = value
        elif "country" in types:
            country = value
    return city, state, country


def normalize_place(details: dict[str, Any], fallback: dict[str, Any]) -> NormalizedCandidate | None:
    merged = {**fallback, **{key: value for key, value in details.items() if value is not None}}
    if details.get("place_id") and fallback.get("place_id") and details["place_id"] != fallback["place_id"]:
        raise PiqProviderError("malformed_response", "Google Places returned mismatched place details.", retryable=False)
    place_id = _text(merged.get("place_id"), limit=255)
    name = _text(merged.get("name"), limit=200)
    if not place_id or not name:
        return None
    formatted_address = _text(merged.get("formatted_address") or merged.get("vicinity"), limit=300)
    phone = _text(
        merged.get("formatted_phone_number") or merged.get("international_phone_number"),
        limit=80,
    )
    website = safe_url(merged.get("website"))
    source_url = safe_url(merged.get("url"))
    categories = tuple(
        str(item)[:80]
        for item in (merged.get("types") if isinstance(merged.get("types"), list) else [])[:MAX_RAW_LIST_ITEMS]
        if isinstance(item, str) and item.strip()
    )
    geometry = merged.get("geometry") if isinstance(merged.get("geometry"), dict) else {}
    coordinates = geometry.get("location") if isinstance(geometry.get("location"), dict) else {}
    city, state, country = _address_parts(merged)
    return NormalizedCandidate(
        external_provider="google_places",
        external_id=place_id,
        company_name=name,
        formatted_address=formatted_address,
        city=city,
        state=state,
        country=country,
        latitude=_number(coordinates.get("lat"), float),
        longitude=_number(coordinates.get("lng"), float),
        categories=categories,
        business_status=_text(merged.get("business_status"), limit=60),
        phone=phone,
        website=website,
        rating=_number(merged.get("rating"), float),
        review_count=_number(merged.get("user_ratings_total"), int),
        source_url=source_url,
        source_metadata={"api": "places_web_service_legacy", "details_enriched": bool(details)},
        raw_metadata=_safe_raw(merged),
        retrieved_at=datetime.now(timezone.utc),
    )


class GooglePlacesAdapter:
    provider = "google_places"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: int,
        client: httpx.Client | None = None,
        page_delay_seconds: float = 2.2,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key.strip()
        self._timeout_seconds = max(1, min(int(timeout_seconds), 300))
        self._provided_client = client
        self._owned_client: httpx.Client | None = None
        self._page_delay_seconds = max(0.0, min(page_delay_seconds, 5.0))
        self._sleep = sleep
        self._clock = clock
        self._deadline: float | None = None

    def close(self) -> None:
        if self._owned_client is not None:
            self._owned_client.close()
            self._owned_client = None

    def _client(self) -> httpx.Client:
        if self._provided_client is not None:
            return self._provided_client
        if self._owned_client is None:
            self._owned_client = httpx.Client(
                timeout=self._timeout_seconds,
                headers={"User-Agent": "RMR-Global-ProspectIQ/1.0"},
            )
        return self._owned_client

    def _remaining_timeout(self) -> float:
        if self._deadline is None:
            self._deadline = self._clock() + self._timeout_seconds
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise PiqProviderError("provider_timeout", "Google Places discovery timed out.", retryable=True)
        return max(0.1, min(float(self._timeout_seconds), remaining))

    def _request_json(self, url: str, params: dict[str, str], *, operation: str) -> dict[str, Any]:
        if not self._api_key:
            raise PiqProviderError(
                "invalid_configuration",
                "Google Places is not configured for live discovery.",
                retryable=False,
            )
        token = _private_request.set(True)
        try:
            with self._client().stream("GET", url, params=params, timeout=self._remaining_timeout(), follow_redirects=False) as response:
                chunks = bytearray()
                for chunk in response.iter_bytes():
                    self._remaining_timeout()
                    chunks.extend(chunk)
                    if len(chunks) > MAX_RESPONSE_BYTES:
                        raise PiqProviderError("malformed_response", "Google Places response exceeded the size limit.", retryable=False)
                content = bytes(chunks)
        except httpx.TimeoutException:
            raise PiqProviderError("provider_timeout", "Google Places discovery timed out.", retryable=True) from None
        except httpx.RequestError:
            raise PiqProviderError(
                "provider_unavailable",
                "Google Places could not be reached.",
                retryable=False,
            ) from None
        finally:
            _private_request.reset(token)
        if response.status_code in {401, 403}:
            raise PiqProviderError("provider_auth", "Google Places rejected the configured credentials.", retryable=False)
        if response.status_code == 429:
            raise PiqProviderError("provider_rate_limit", "Google Places rate limit reached.", retryable=True)
        if response.status_code >= 500:
            raise PiqProviderError("provider_5xx", "Google Places is temporarily unavailable.", retryable=True)
        if response.status_code != 200:
            raise PiqProviderError("provider_request", f"Google Places rejected the {operation} request.", retryable=False)
        try:
            payload = json.loads(content)
        except ValueError:
            raise PiqProviderError("malformed_response", "Google Places returned malformed data.", retryable=False) from None
        if not isinstance(payload, dict):
            raise PiqProviderError("malformed_response", "Google Places returned malformed data.", retryable=False)
        return payload

    @staticmethod
    def _validate_status(payload: dict[str, Any], *, operation: str, zero_allowed: bool = False) -> str:
        status = str(payload.get("status") or "")
        if status == "OK" or (zero_allowed and status == "ZERO_RESULTS"):
            return status
        if status == "REQUEST_DENIED":
            raise PiqProviderError("provider_auth", "Google Places rejected the configured credentials.", retryable=False)
        if status in {"OVER_QUERY_LIMIT", "RESOURCE_EXHAUSTED"}:
            raise PiqProviderError("provider_rate_limit", "Google Places rate limit reached.", retryable=True)
        if status == "UNKNOWN_ERROR":
            raise PiqProviderError("provider_5xx", "Google Places is temporarily unavailable.", retryable=True)
        if status == "INVALID_REQUEST":
            raise PiqProviderError("invalid_configuration", "Google Places rejected the request parameters.", retryable=False)
        raise PiqProviderError("malformed_response", f"Google Places returned an invalid {operation} response.", retryable=False)

    def _details(self, place_id: str) -> dict[str, Any]:
        payload = self._request_json(
            PLACE_DETAILS_URL,
            {"place_id": place_id, "fields": DETAIL_FIELDS, "key": self._api_key},
            operation="details",
        )
        self._validate_status(payload, operation="details")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise PiqProviderError("malformed_response", "Google Places returned malformed details.", retryable=False)
        return result

    def search(self, query: str, *, max_results: int) -> ProviderSearchResult:
        cap = max(1, min(int(max_results), 100))
        result = ProviderSearchResult()
        params = {"query": " ".join(query.split())[:400], "key": self._api_key}
        raw_places: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for page_number in range(1, MAX_PAGES + 1):
            payload = self._request_json(TEXT_SEARCH_URL, params, operation="text search")
            status = self._validate_status(payload, operation="text search", zero_allowed=True)
            result.page_count += 1
            if status == "ZERO_RESULTS":
                break
            rows = payload.get("results")
            if not isinstance(rows, list):
                raise PiqProviderError("malformed_response", "Google Places returned malformed results.", retryable=False)
            if any(not isinstance(row, dict) or not _text(row.get("place_id")) or not _text(row.get("name")) for row in rows):
                raise PiqProviderError("malformed_response", "Google Places returned a malformed candidate.", retryable=False)
            for row in rows:
                if row["place_id"] not in seen_ids:
                    seen_ids.add(row["place_id"])
                    raw_places.append(row)
                    if len(raw_places) >= cap:
                        break
            if len(raw_places) >= cap:
                break
            next_token = _text(payload.get("next_page_token"), limit=500)
            if not next_token or page_number >= MAX_PAGES:
                break
            if self._page_delay_seconds:
                if self._clock() + self._page_delay_seconds >= (self._deadline or float("inf")):
                    raise PiqProviderError("provider_timeout", "Google Places discovery timed out.", retryable=True)
                self._sleep(self._page_delay_seconds)
            params = {"pagetoken": next_token, "key": self._api_key}

        for raw in raw_places[:cap]:
            place_id = _text(raw.get("place_id"), limit=255)
            if not place_id:
                result.issues.append(ProviderIssue(
                    code="missing_place_id",
                    message="Google Places omitted a candidate identifier.",
                    retryable=False,
                    operation="normalization",
                ))
                continue
            details: dict[str, Any] = {}
            try:
                result.details_request_count += 1
                details = self._details(place_id)
            except PiqProviderError as exc:
                if exc.retryable or exc.code in {"provider_auth", "invalid_configuration"}:
                    raise
                result.issues.append(ProviderIssue(
                    code=exc.code,
                    message=exc.public_message,
                    retryable=exc.retryable,
                    operation="details",
                ))
            candidate = normalize_place(details, raw)
            if candidate is not None:
                result.candidates.append(candidate)
            else:
                raise PiqProviderError("malformed_response", "Google Places returned a malformed candidate.", retryable=False)
        return result
