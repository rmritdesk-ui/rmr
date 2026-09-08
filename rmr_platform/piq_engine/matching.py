"""Pure Google-only qualification policy. Numeric policy is versioned, not AI.

Weights: geography 20 (inferred 6), industry 25 (related 15), contacts
15 (one 8), operational listing 10 + meaningful rating/reviews 10,
observed keywords 5 each (first four). No normalization of unused weights.
Unsupported employee/revenue requirements never change fit points or rejection.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata
from typing import Any

from .contracts import NormalizedCandidate, PiqProviderError
from .profile import _terms

SCORING_VERSION = "piq-match-v1"
GENERIC_CATEGORIES = {"establishment", "point of interest", "business", "company"}
CATEGORY_ALIASES = {"realtor": "real estate agency", "real estate agent": "real estate agency"}
# Only explicitly disjoint known families justify hard category rejection.
CATEGORY_FAMILIES = {
    "finance": {"finance", "bank", "mortgage broker", "loan agency", "financial advisor"},
    "food": {"restaurant", "cafe", "bakery", "bar", "meal takeaway"},
    "health": {"doctor", "dentist", "hospital", "dental clinic", "physiotherapist"},
    "property": {"real estate agency", "real estate consultant"},
    "automotive": {"car dealer", "car repair", "car rental"},
}
_STATES = (
    "AL:Alabama|AK:Alaska|AZ:Arizona|AR:Arkansas|CA:California|CO:Colorado|CT:Connecticut|"
    "DE:Delaware|FL:Florida|GA:Georgia|HI:Hawaii|ID:Idaho|IL:Illinois|IN:Indiana|IA:Iowa|"
    "KS:Kansas|KY:Kentucky|LA:Louisiana|ME:Maine|MD:Maryland|MA:Massachusetts|MI:Michigan|"
    "MN:Minnesota|MS:Mississippi|MO:Missouri|MT:Montana|NE:Nebraska|NV:Nevada|NH:New Hampshire|"
    "NJ:New Jersey|NM:New Mexico|NY:New York|NC:North Carolina|ND:North Dakota|OH:Ohio|"
    "OK:Oklahoma|OR:Oregon|PA:Pennsylvania|RI:Rhode Island|SC:South Carolina|SD:South Dakota|"
    "TN:Tennessee|TX:Texas|UT:Utah|VT:Vermont|VA:Virginia|WA:Washington|WV:West Virginia|"
    "WI:Wisconsin|WY:Wyoming|DC:District of Columbia"
)


def text(value: Any) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", str(value or "")).casefold().replace("_", " ")).split())


def category(value: str) -> str:
    words = text(value).split()
    words = [word[:-3] + "y" if word.endswith("ies") else
             word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word
             for word in words]
    normalized = " ".join(words)
    return CATEGORY_ALIASES.get(normalized, normalized)


REGION_ALIASES = {text(code): text(name) for code, name in (item.split(":") for item in _STATES.split("|"))}
REGION_ALIASES.update({"us": "united states", "usa": "united states", "united states of america": "united states",
                       "uk": "united kingdom", "gb": "united kingdom"})
REGIONS = set(REGION_ALIASES.values()) | {"canada", "australia", "pakistan", "india"}


def region(value: str | None) -> str:
    normalized = text(re.sub(r"\b\d[\d -]*$", "", value or ""))
    return REGION_ALIASES.get(normalized, normalized)


def location_state(requested: str, candidate: NormalizedCandidate) -> str:
    parts = [region(part) for part in requested.split(",") if region(part)]
    structured = {region(value) for value in (candidate.city, candidate.state, candidate.country) if value}
    address = {region(part) for part in (candidate.formatted_address or "").split(",") if region(part)}
    # Structured components outrank conflicting formatted text.
    observed = structured if candidate.city and candidate.state else structured | address
    if parts and all(part in observed for part in parts):
        return "confirmed"
    # A matching city with a conflicting explicit region is NOT a fit. Only
    # comparable structured geography proves mismatch; unfamiliar regions stay open.
    if parts:
        requested_regions = [part for part in parts if part in REGIONS]
        observed_regions = {region(value) for value in (candidate.state, candidate.country) if value}
        for part in requested_regions:
            comparable = region(candidate.country) if part in {"united states", "united kingdom", "canada", "australia", "pakistan", "india"} else region(candidate.state)
            if comparable and part not in observed_regions:
                return "contradicted"
        if len(parts) >= 2 and candidate.city and requested_regions and region(candidate.city) != parts[0] and parts[0] not in REGIONS:
            return "contradicted"
    return "unresolved"


@dataclass(frozen=True)
class CriterionResult:
    criterion: str
    requested: Any
    observed: Any
    state: str
    score_effect: int
    reason: str
    evidence_refs: tuple[str, ...] = ()
    assessable: bool = True
    profile_criterion: bool = True


@dataclass(frozen=True)
class MatchResult:
    scoring_version: str
    qualified: bool
    base_match_score: int
    confidence_score: int
    evidence_completeness_pct: int
    criteria: tuple[CriterionResult, ...]
    score_breakdown: dict[str, Any]
    explanation: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def match_candidate(snapshot: dict[str, Any], candidate: NormalizedCandidate) -> MatchResult:
    industries = _terms(snapshot.get("industries"), limit=25)
    locations = _terms(snapshot.get("locations"), limit=25)
    if not snapshot.get("active") or not industries or not locations:
        raise PiqProviderError("invalid_profile", "Active industry/location profile required for matching.", retryable=False)
    if candidate.external_provider != "google_places":
        raise PiqProviderError("invalid_provider", "Matching requires Google Places evidence.", retryable=False)
    criteria: list[CriterionResult] = []
    rejection: list[str] = []

    def add(key, requested, observed, state, points, reason, *, assessable=True, profile=True):
        refs = (key,) if state != "unresolved" and observed not in (None, [], {}, "") else ()
        criteria.append(CriterionResult(key, requested, observed, state, points, reason, refs, assessable, profile))

    categories = sorted({category(value) for value in candidate.categories} - GENERIC_CATEGORIES - {""})
    targets = {category(value) for value in industries}
    families = lambda values: {key for key, members in CATEGORY_FAMILIES.items() if members.intersection(values)}
    if targets.intersection(categories):
        industry_state, points = "confirmed", 25
    elif families(targets).intersection(families(categories)) or any(set(a.split()) & set(b.split()) for a in targets for b in categories):
        industry_state, points = "inferred", 15
    elif categories and all(any(value in members for members in CATEGORY_FAMILIES.values()) for value in targets) and families(categories) and not families(targets).intersection(families(categories)):
        industry_state, points = "contradicted", 0
        rejection.append("Source categories clearly conflict with the required industry.")
    else:
        industry_state, points = "unresolved", 0
    add("industry", industries, list(candidate.categories), industry_state, points,
        f"Industry {industry_state} from provider categories only; query terms are not category evidence.")

    geo_states = [location_state(value, candidate) for value in locations]
    geo_observed = {"address": candidate.formatted_address, "city": candidate.city, "state": candidate.state, "country": candidate.country}
    query = candidate.source_metadata.get("discovery_query", {})
    if "confirmed" in geo_states:
        geo_state, points = "confirmed", 20
    elif all(state == "contradicted" for state in geo_states):
        geo_state, points = "contradicted", 0
        rejection.append("Observed geography conflicts with every requested location.")
    elif not any(geo_observed.values()) and isinstance(query, dict) and query.get("location") in locations:
        geo_state, points = "inferred", 6
        geo_observed = {"search_area": query["location"], "query": query.get("text", "")[:400]}
    else:
        geo_state, points = "unresolved", 0
    add("geography", locations, geo_observed, geo_state, points,
        "Search-area inference only; no observed location." if geo_state == "inferred" else f"Geography {geo_state} using observed address/components, not search intent.")

    for index, exclusion in enumerate(_terms(snapshot.get("exclusions"), limit=25)):
        label = exclusion.split(":", 1)[-1].strip()
        prefix = text(exclusion.split(":", 1)[0]) if ":" in exclusion else ""
        if prefix not in {"", "category", "industry", "location", "geography"}:
            label = exclusion  # Unknown prose prefixes are not exclusion syntax.
        category_hit = prefix not in {"location", "geography"} and category(label) in categories
        geo_hit = prefix not in {"category", "industry"} and location_state(label, candidate) == "confirmed"
        hit = category_hit or geo_hit
        reason = f"Confirmed exclusion: {exclusion}." if hit else "Exclusion not proven by Google fields; absence is not confirmation of compliance."
        if hit:
            rejection.append(reason)
        add(f"exclusion:{index}", exclusion, list(candidate.categories) if category_hit else geo_observed if geo_hit else None,
            "contradicted" if hit else "unresolved", 0, reason)

    contacts = {key: value for key, value in {"phone": candidate.phone, "website": candidate.website}.items() if value}
    add("contactability", "observed phone/website", contacts or None, "confirmed" if contacts else "unresolved",
        15 if len(contacts) == 2 else 8 if contacts else 0,
        "Only returned phone/website counts; reachability and ownership are not verified.", profile=False)
    closed = candidate.business_status in {"CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY", "INACTIVE"}
    active = candidate.business_status == "OPERATIONAL"
    reviews = candidate.review_count is not None and candidate.review_count > 0 and candidate.rating is not None and 1 <= candidate.rating <= 5
    if closed:
        rejection.append("Google explicitly reports the business closed/inactive.")
    add("source_quality", "operational listing; rating/reviews optional", {"business_status": candidate.business_status, "rating": candidate.rating, "review_count": candidate.review_count},
        "contradicted" if closed else "confirmed" if active else "unresolved", (10 + (10 if reviews else 0)) if active else 0,
        "Listing metadata is single-source public evidence, not independent corroboration or buying intent.", profile=False)

    source_fields = [text(candidate.company_name), *(text(value) for value in candidate.categories)]
    for index, keyword in enumerate(_terms(snapshot.get("keywords"), limit=25)):
        hit = bool(text(keyword)) and any(f" {text(keyword)} " in f" {value} " for value in source_fields)
        add(f"keyword:{index}", keyword, {"name": candidate.company_name, "categories": list(candidate.categories)} if hit else None,
            "confirmed" if hit else "unresolved", 5 if hit and index < 4 else 0,
            "Keyword observed in provider name/categories." if hit else "Keyword not observed; search-query use is not evidence and absence is not rejection.")
    if snapshot.get("employee_min") or snapshot.get("employee_max"):
        add("employees", {"min": snapshot.get("employee_min"), "max": snapshot.get("employee_max")}, None, "unresolved", 0,
            "Google Places does not supply verified employee counts.", assessable=False)
    if snapshot.get("revenue_min_cents"):
        add("revenue", snapshot["revenue_min_cents"], None, "unresolved", 0,
            "Google Places does not supply verified company revenue.", assessable=False)

    raw_score = sum(item.score_effect for item in criteria)
    guards: list[dict[str, Any]] = []
    def cap(value, reason, refs):
        guards.append({"cap": value, "reason": reason, "criterion_refs": refs})
    if geo_state != "confirmed":
        cap(55, "Observed geography is not confirmed.", ["geography"])
    if industry_state == "unresolved":
        cap(40, "Industry evidence is unresolved.", ["industry"])
    elif industry_state == "inferred":
        cap(65, "Related category does not prove exact industry fit.", ["industry"])
    if not active:
        cap(65, "Operational business status is not confirmed.", ["source_quality"])
    if not contacts:
        cap(60, "No observed contact method.", ["contactability"])
    if rejection:
        cap(0, "Source-backed hard rejection.", [item.criterion for item in criteria if item.state == "contradicted"])
    final_score = max(0, min([100, raw_score] + [item["cap"] for item in guards]))
    assessable = [item for item in criteria if item.assessable]
    strength = {"confirmed": 1.0, "contradicted": 1.0, "inferred": 0.35, "unresolved": 0.0}
    confidence = round(90 * sum(strength[item.state] for item in assessable) / len(assessable))
    # One source never means 100% confidence; unsupported requested criteria are
    # disclosed without swamping the denominator, and cap confidence at 80.
    if any(not item.assessable for item in criteria):
        confidence = min(confidence, 80)
    profile_criteria = [item for item in assessable if item.profile_criterion]
    completeness = round(100 * sum(1 if item.state in {"confirmed", "contradicted"} else 0.5 if item.state == "inferred" else 0 for item in profile_criteria) / len(profile_criteria))
    explanation = " ".join(rejection) if rejection else "Eligible discovery candidate; unresolved requirements remain unverified. Not a fully qualified sales lead."
    return MatchResult(SCORING_VERSION, not rejection, final_score, confidence, completeness, tuple(criteria), {
        "components": {item.criterion: item.score_effect for item in criteria},
        "raw_score": raw_score, "guardrails": guards, "guardrail_adjustment": final_score - raw_score,
        "final_score": final_score, "confidence_policy": "single_source_90; confirmed/contradicted=1,inferred=.35,unresolved=0; unsupported_cap=80",
        "completeness_policy": "assessable_profile_only; confirmed/contradicted=1,inferred=.5,unresolved=0; unsupported_excluded",
        "assessable_profile_count": len(profile_criteria), "unsupported_criteria": [item.criterion for item in criteria if not item.assessable],
    }, explanation)
