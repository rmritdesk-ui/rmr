from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import asdict, replace
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import PiqOpportunity, Tenant
from ..piq_models import PiqDiscoveryRun
from ..unified_models import PiqTargetProfile
from .contracts import DiscoveryExecutionResult, NormalizedCandidate, PiqProviderError
from .google_places import GooglePlacesAdapter
from .profile import plan_profile_queries
from .matching import match_candidate, SCORING_VERSION
from .evidence import persist_match


def normalized_domain(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
        hostname = (parsed.hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""
    return hostname[4:] if hostname.startswith("www.") else hostname


def _identity_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join("".join(char if char.isalnum() else " " for char in normalized).split())


def candidate_fingerprint(candidate: NormalizedCandidate) -> str:
    if candidate.external_id:
        identity = f"{candidate.external_provider}:place:{candidate.external_id}"
    elif normalized_domain(candidate.website):
        identity = f"{candidate.external_provider}:domain:{normalized_domain(candidate.website)}"
    else:
        identity = (
            f"{candidate.external_provider}:name-location:"
            f"{_identity_text(candidate.company_name)}:{_identity_text(candidate.formatted_address)}"
        )
    if len(identity) <= 255:
        return identity
    return f"{candidate.external_provider}:sha256:{hashlib.sha256(identity.encode()).hexdigest()}"


def _same_candidate(left: NormalizedCandidate, right: NormalizedCandidate) -> bool:
    if left.external_id and right.external_id and left.external_id == right.external_id:
        return True
    left_domain = normalized_domain(left.website)
    right_domain = normalized_domain(right.website)
    if left_domain and right_domain and left_domain == right_domain:
        return True
    return bool(
        _identity_text(left.company_name)
        and _identity_text(left.company_name) == _identity_text(right.company_name)
        and _identity_text(left.formatted_address)
        and _identity_text(left.formatted_address) == _identity_text(right.formatted_address)
    )


def execute_google_discovery(
    profile_snapshot: dict[str, Any],
    *,
    adapter: GooglePlacesAdapter,
    max_queries: int,
    max_results: int,
) -> DiscoveryExecutionResult:
    cap = max(1, min(int(max_results), 100))
    candidates: list[NormalizedCandidate] = []
    issues: list[dict[str, Any]] = []
    pages = details_requests = queries_executed = 0
    fetched_count = 0
    try:
        plan = plan_profile_queries(profile_snapshot, max_queries=max_queries)
        for query in plan.queries:
            remaining = cap - fetched_count
            if remaining <= 0:
                break
            try:
                provider_result = adapter.search(query.text, max_results=remaining)
            except PiqProviderError as exc:
                # Transient failures retry the bounded run; persistence has not
                # begun. Authentication/configuration failures always fail.
                if exc.retryable or exc.code in {"provider_auth", "invalid_configuration"}:
                    raise
                if not candidates:
                    raise
                issues.append({
                    "code": exc.code,
                    "message": exc.public_message,
                    "retryable": exc.retryable,
                    "operation": "text_search",
                })
                break
            queries_executed += 1
            pages += provider_result.page_count
            details_requests += provider_result.details_request_count
            fetched_count += len(provider_result.candidates)
            issues.extend({
                "code": issue.code,
                "message": issue.message,
                "retryable": issue.retryable,
                "operation": issue.operation,
            } for issue in provider_result.issues[:25])
            for candidate in provider_result.candidates:
                candidate = replace(candidate, source_metadata={
                    **candidate.source_metadata,
                    "discovery_query": {"text": query.text, "industry": query.industry, "location": query.location},
                })
                if any(_same_candidate(candidate, prior) for prior in candidates):
                    continue
                candidates.append(candidate)
                if len(candidates) >= cap:
                    break
    finally:
        adapter.close()

    status = "partial" if issues and candidates else "completed"
    return DiscoveryExecutionResult(
        plan=plan,
        candidates=candidates,
        status=status,
        diagnostics={
            "provider": "google_places",
            "api_mode": "places_web_service_legacy",
            "planned_query_count": len(plan.queries),
            "executed_query_count": queries_executed,
            "page_count": pages,
            "details_request_count": details_requests,
            "provider_candidate_count": fetched_count,
            "unique_candidate_count": len(candidates),
            "issues": issues[:25],
            "employee_revenue_filters_applied": False,
        },
    )


def candidate_metadata(candidate: NormalizedCandidate) -> dict[str, Any]:
    """Bounded normalized observations; criterion evidence is persisted separately."""
    data = asdict(candidate)
    data["retrieved_at"] = candidate.retrieved_at.isoformat()
    return data


def _matches_existing(candidate: NormalizedCandidate, existing: PiqOpportunity) -> bool:
    if candidate.external_id and existing.source_external_id == candidate.external_id:
        return True
    candidate_domain = normalized_domain(candidate.website)
    existing_domain = normalized_domain(existing.website)
    if candidate_domain and existing_domain and candidate_domain == existing_domain:
        return True
    return bool(
        _identity_text(candidate.company_name) == _identity_text(existing.company_name)
        and _identity_text(candidate.formatted_address)
        and _identity_text(candidate.formatted_address) == _identity_text(existing.location)
    )


def persist_candidates(
    db: Session,
    run: PiqDiscoveryRun,
    result: DiscoveryExecutionResult,
) -> tuple[int, int]:
    # Serialize same-tenant persistence across distinct runs, including domain
    # dedupe. No provider I/O occurs within this short write transaction.
    from sqlalchemy import update
    if run.provider != "google_places" or not db.scalar(select(PiqTargetProfile.id).where(
        PiqTargetProfile.id == run.target_profile_id, PiqTargetProfile.tenant_id == run.tenant_id,
    )) or run.profile_snapshot_json.get("id") != run.target_profile_id:
        raise PiqProviderError("invalid_profile", "Discovery profile does not belong to this tenant/run.", retryable=False)
    locked = db.execute(update(Tenant).where(Tenant.id == run.tenant_id).values(
        id=Tenant.id, updated_at=Tenant.updated_at,
    ))
    if locked.rowcount != 1:
        raise PiqProviderError("invalid_tenant", "Discovery tenant no longer exists.", retryable=False)
    existing = list(db.scalars(select(PiqOpportunity).where(
        PiqOpportunity.tenant_id == run.tenant_id,
        PiqOpportunity.provider == "google_places",
    )))
    created_count = duplicate_count = 0
    rejected: list[dict[str, Any]] = []
    evaluated_count = 0
    for candidate in result.candidates[:100]:
        if created_count >= run.requested_count:
            break
        if candidate.external_provider != "google_places":
            raise PiqProviderError("invalid_provider", "Unexpected discovery provider identity.", retryable=False)
        if any(_matches_existing(candidate, row) for row in existing):
            duplicate_count += 1
            continue
        evaluated_count += 1
        match = match_candidate(run.profile_snapshot_json, candidate)
        if not match.qualified:
            rejected.append({"external_id": candidate.external_id, "company_name": candidate.company_name,
                             "source_url": candidate.source_url, "match": match.as_dict()})
            continue
        business_status = candidate.business_status or "UNKNOWN"
        row = PiqOpportunity(
            tenant_id=run.tenant_id,
            target_profile_id=run.target_profile_id,
            provider="google_places",
            source_external_id=candidate.external_id,
            source_url=candidate.source_url,
            fingerprint=candidate_fingerprint(candidate),
            company_name=candidate.company_name,
            website=candidate.website,
            location=candidate.formatted_address,
            industry=", ".join(candidate.categories[:5])[:180] or None,
            phone=candidate.phone,
            score=0,
            signal=f"Google Places business status: {business_status}",
            evidence_count=0,
            estimated_value_cents=0,
            status="Discovered",
            enhanced=False,
            enhancement_price_cents=0,
            moved_to_crm=False,
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            duplicate = db.scalar(select(PiqOpportunity.id).where(
                PiqOpportunity.tenant_id == run.tenant_id,
                PiqOpportunity.provider == "google_places",
                PiqOpportunity.fingerprint == candidate_fingerprint(candidate),
            ))
            if not duplicate:
                raise
            duplicate_count += 1
            continue
        existing.append(row)
        persist_match(db, run, row, candidate, match)
        created_count += 1
    received = result.diagnostics.get("provider_candidate_count", len(result.candidates))
    upstream_duplicates = max(0, received - len(result.candidates))
    result.diagnostics.update({
        "scoring_version": SCORING_VERSION,
        "candidates_received": received,
        "duplicates_skipped": duplicate_count + upstream_duplicates,
        "rejected": len(rejected), "qualified": created_count, "persisted": created_count,
        "evaluated_count": evaluated_count,
        "retained_limit": run.requested_count,
        "provider_errors": len(result.diagnostics.get("issues", [])),
        "rejected_candidates": rejected,
        "rejection_summary": [{"external_id": item["external_id"], "company_name": item["company_name"],
                               "reason": item["match"]["explanation"], "source_url": item["source_url"]} for item in rejected],
    })
    run.diagnostics_json = {**(run.diagnostics_json or {}), **result.diagnostics}
    return created_count, duplicate_count
