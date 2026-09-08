"""Persist piq-match-v1 facts using Phase 0 tables; never synthesize contacts."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import PiqOpportunity
from ..piq_models import PiqDiscoveryRun, PiqProfileMatch
from ..unified_models import PiqEvidence
from .contracts import NormalizedCandidate
from .google_places import safe_url
from .matching import MatchResult


def evidence_hash(tenant_id: str, run_id: str, opportunity_id: str, version: str, criterion: dict) -> str:
    """Retry-stable identity; retrieval/insert time deliberately excluded."""
    payload = [tenant_id, run_id, opportunity_id, version, criterion]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def persist_match(db: Session, run: PiqDiscoveryRun, opportunity: PiqOpportunity,
                  candidate: NormalizedCandidate, match: MatchResult) -> None:
    if not match.qualified or opportunity.tenant_id != run.tenant_id or opportunity.provider != "google_places":
        raise ValueError("Only qualified, same-tenant Google candidates can be persisted")
    existing_match = db.scalar(select(PiqProfileMatch).where(
        PiqProfileMatch.tenant_id == run.tenant_id,
        PiqProfileMatch.discovery_run_id == run.id,
        PiqProfileMatch.opportunity_id == opportunity.id,
    ))
    if existing_match:
        return
    rows = []
    source_url = safe_url(candidate.source_url) or ""
    for criterion in match.criteria:
        data = asdict(criterion)
        if not criterion.evidence_refs:
            rows.append(data)
            continue
        digest = evidence_hash(run.tenant_id, run.id, opportunity.id, match.scoring_version, data)
        if not db.scalar(select(PiqEvidence.id).where(PiqEvidence.tenant_id == run.tenant_id, PiqEvidence.evidence_hash == digest)):
            db.add(PiqEvidence(
                tenant_id=run.tenant_id, opportunity_id=opportunity.id,
                provider="google_places", evidence_type="profile_criterion",
                source_name="Google Places", source_url=source_url,
                source_title=candidate.company_name[:500], source_domain=urlsplit(source_url).hostname or None,
                fact=f"{criterion.reason} Observed: {json.dumps(criterion.observed, ensure_ascii=True, sort_keys=True)}",
                confidence_pct=35 if criterion.state == "inferred" else 90,
                evidence_state=criterion.state, verified=criterion.state in {"confirmed", "contradicted"},
                is_synthesized=False, profile_criterion=criterion.criterion,
                discovery_run_id=run.id, observed_at=candidate.retrieved_at, evidence_hash=digest,
                # Phase 0 has no dedicated score_effect column. Preserve it in
                # structured raw_json and the match breakdown, without migration.
                raw_json={"scoring_version": match.scoring_version, "external_id": candidate.external_id,
                          "source_fields": criterion.observed, "requested": criterion.requested,
                          "score_effect": criterion.score_effect, "reason": criterion.reason},
            ))
        data["evidence_refs"] = [digest]
        rows.append(data)
    db.flush()
    db.add(PiqProfileMatch(
        tenant_id=run.tenant_id, discovery_run_id=run.id, opportunity_id=opportunity.id,
        target_profile_id=run.target_profile_id, scoring_version=match.scoring_version,
        base_match_score=match.base_match_score, confidence_score=match.confidence_score,
        evidence_completeness_pct=match.evidence_completeness_pct,
        score_breakdown_json=match.score_breakdown,
        criteria_result_json={"qualified": True, "criteria": rows, "explanation": match.explanation},
        explanation=match.explanation,
    ))
    opportunity.base_match_score = opportunity.score = match.base_match_score
    opportunity.confidence_score = match.confidence_score
    opportunity.evidence_completeness_pct = match.evidence_completeness_pct
    opportunity.signal = "Google candidate qualified for discovery; unresolved criteria remain unverified."
    opportunity.evidence_count = db.scalar(select(func.count()).select_from(PiqEvidence).where(
        PiqEvidence.tenant_id == run.tenant_id, PiqEvidence.opportunity_id == opportunity.id,
    )) or 0
