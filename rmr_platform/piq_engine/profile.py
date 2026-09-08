from __future__ import annotations

from typing import Any

from .contracts import DiscoveryPlan, DiscoveryQuery, PiqProviderError


MAX_KEYWORDS_PER_QUERY = 2
MAX_TERM_LENGTH = 80


def _terms(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        term = " ".join(str(item or "").split())[:MAX_TERM_LENGTH]
        key = term.casefold()
        if not term or key in seen:
            continue
        seen.add(key)
        result.append(term)
        if len(result) >= limit:
            break
    return result


def snapshot_target_profile(profile: Any) -> dict[str, Any]:
    return {
        "id": str(profile.id),
        "name": str(profile.name or ""),
        "industries": list(profile.industries_json or []),
        "locations": list(profile.locations_json or []),
        "employee_min": int(profile.employee_min or 0),
        "employee_max": int(profile.employee_max or 0),
        "revenue_min_cents": int(profile.revenue_min_cents or 0),
        "keywords": list(profile.keywords_json or []),
        "exclusions": list(profile.exclusions_json or []),
        "active": bool(profile.active),
    }


def plan_profile_queries(profile_snapshot: dict[str, Any], *, max_queries: int) -> DiscoveryPlan:
    if not bool(profile_snapshot.get("active")):
        raise PiqProviderError("invalid_profile", "An active Target Profile is required for live discovery.", retryable=False)

    cap = max(1, min(int(max_queries), 25))
    industries = _terms(profile_snapshot.get("industries"), limit=cap)
    locations = _terms(profile_snapshot.get("locations"), limit=cap)
    keywords = _terms(profile_snapshot.get("keywords"), limit=MAX_KEYWORDS_PER_QUERY)
    exclusions = _terms(profile_snapshot.get("exclusions"), limit=25)
    if not industries or not locations:
        raise PiqProviderError(
            "invalid_profile",
            "Live discovery requires at least one industry and one location.",
            retryable=False,
        )

    refinement = f" {' '.join(keywords)}" if keywords else ""
    queries: list[DiscoveryQuery] = []
    for industry in industries:
        for location in locations:
            queries.append(DiscoveryQuery(
                text=f"{industry}{refinement} in {location}",
                industry=industry,
                location=location,
                keywords=tuple(keywords),
            ))
            if len(queries) >= cap:
                return DiscoveryPlan(queries=tuple(queries), exclusions=tuple(exclusions))
    return DiscoveryPlan(queries=tuple(queries), exclusions=tuple(exclusions))
