"""Tenant authorization, immutable estimates and lease-fenced research persistence."""
from datetime import datetime, timedelta, timezone
import secrets

from fastapi import HTTPException
from sqlalchemy import select, update

from ..models import PiqOpportunity, TenantService, User
from ..permissions import is_global_admin, require_tenant_access
from ..piq_models import PiqProfileMatch, PiqResearchRun
from ..unified_models import ManagedTenantSession, PiqEvidence, PiqTargetProfile
from .profile import snapshot_target_profile
from .research import configuration, digest, fail, request_body, safe_url, score_delta, ResponsesResearchAdapter, researchable, MAX_TASKS, REJECTION_CODES
from .contracts import PiqProviderError


def now():
    return datetime.now(timezone.utc)


def access(db, user, opportunity_id, *, spend=False, managed_id=None):
    row = db.get(PiqOpportunity, opportunity_id)
    if not row or (not is_global_admin(user) and user.tenant_id != row.tenant_id):
        raise HTTPException(404, "ProspectIQ record not found")
    require_tenant_access(user, row.tenant_id)
    if not user.active or not db.scalar(select(TenantService.id).where(
            TenantService.tenant_id == row.tenant_id, TenantService.service_code == "piq_access",
            TenantService.status == "active")):
        raise HTTPException(403, "ProspectIQ access required")
    if spend:
        if is_global_admin(user):
            session_id = managed_id or getattr(user, "_managed_session_id", None)
            valid = db.scalar(select(ManagedTenantSession.id).where(
                ManagedTenantSession.id == session_id, ManagedTenantSession.tenant_id == row.tenant_id,
                ManagedTenantSession.admin_user_id == user.id, ManagedTenantSession.status == "active",
                ManagedTenantSession.access_type == "managed_write", ManagedTenantSession.expires_at > now()))
            if not valid:
                raise HTTPException(403, "An active tenant-bound managed_write session is required")
        elif user.tenant_role != "CLIENT_ADMIN" or user.tenant_id != row.tenant_id:
            raise HTTPException(403, "Only CLIENT_ADMIN can confirm live research")
    return row


def snapshot_for(db, row):
    match = db.scalar(select(PiqProfileMatch).where(
        PiqProfileMatch.tenant_id == row.tenant_id, PiqProfileMatch.opportunity_id == row.id
    ).order_by(PiqProfileMatch.created_at.desc(), PiqProfileMatch.id).limit(1))
    profile = db.get(PiqTargetProfile, match.target_profile_id) if match else None
    if (not match or not profile or profile.tenant_id != row.tenant_id or not profile.active
            or not (match.criteria_result_json or {}).get("qualified") or row.base_match_score is None
            or row.provider != "google_places" or row.moved_to_crm):
        raise HTTPException(409, "A qualified, unmoved live prospect with an active Target Profile is required")
    if not safe_url(row.website) or not row.location:
        raise HTTPException(409, "A known public HTTPS business website and location are required")
    tasks = []
    for c in (match.criteria_result_json or {}).get("criteria", []):
        if researchable(c.get("criterion")) and c.get("state") in ("unknown", "unresolved", "inferred", "contradicted", "uncertain"):
            tasks.append({k: c.get(k) for k in ("criterion", "state", "requested", "reason")})
        if len(tasks) == MAX_TASKS:
            break
    if not tasks:
        raise HTTPException(409, "No researchable criteria")
    google = list(db.scalars(select(PiqEvidence).where(PiqEvidence.opportunity_id == row.id,
                       PiqEvidence.tenant_id == row.tenant_id, PiqEvidence.provider == "google_places")
                       .order_by(PiqEvidence.id).limit(12)))
    return {"target": {"id": row.id, "company_name": row.company_name, "website": row.website,
                       "location": row.location}, "profile": snapshot_target_profile(profile),
            "match_id": match.id, "base_match_score": row.base_match_score, "tasks": tasks,
            "discovery_evidence": [{"fact": e.fact[:500], "criterion": e.profile_criterion,
                                    "state": e.evidence_state} for e in google]}


def research_summary(run):
    """Read-only projection: old receipts remain readable without rewriting historical runs."""
    receipt = (run.diagnostics_json or {}).get("receipt") or {}
    detail = receipt.get("diagnostics") or {}
    def count(value):
        # Malformed over-limit arrays still need honest diagnostic counts. Raw responses
        # are already size bounded; this is a display bound, not an acceptance limit.
        return max(0, min(524288, value)) if type(value) is int else 0
    def reasons(value):
        return {k: count(v) for k, v in (value or {}).items() if k in REJECTION_CODES and count(v)}
    accepted = count(len(receipt.get("claims") or []))
    rejected = count(receipt.get("rejected"))
    returned = count(detail.get("returned", accepted + rejected)) if receipt else None
    tasks = []
    for task in detail.get("tasks", [])[:MAX_TASKS]:
        if not researchable(task.get("criterion")):
            continue
        tasks.append({"criterion": task["criterion"],
                      "provider_outcome": task.get("provider_outcome") if task.get("provider_outcome") in ("found", "not_found", "malformed") else "malformed",
                      "searched": task.get("searched") if type(task.get("searched")) is bool else None,
                      **{k: count(task.get(k)) for k in ("returned", "entering_validation", "accepted", "rejected")},
                      "reasons": reasons(task.get("reasons"))})
    outcome = ("failed" if run.status == "failed" else "accepted" if accepted else
               "findings_rejected" if returned else "no_findings" if returned == 0 else "unknown")
    return {"outcome": outcome, "returned": returned, "accepted": accepted, "rejected": rejected,
            "entering_validation": count(detail.get("entering_validation")) if detail else None,
            "tasks_planned": len((run.input_snapshot_json or {}).get("snapshot", {}).get("tasks", [])),
            "tasks_researched": sum(t["searched"] is True for t in tasks) if detail.get("contract") == "task_results_v1" else None,
            "tasks_found": sum(t["provider_outcome"] == "found" for t in tasks) if detail else None,
            "tasks_not_found": sum(t["provider_outcome"] == "not_found" for t in tasks) if detail else None,
            "tasks": tasks, "reasons": reasons(detail.get("reasons"))}


def safe_run(run):
    status = run.status
    if status == "awaiting_confirmation" and run.confirmation_expires_at.replace(tzinfo=timezone.utc) <= now():
        status = "expired"
    usage = run.usage_json or {}
    return {"run_id": run.id, "opportunity_id": run.opportunity_id, "status": status,
            "provider": run.provider, "provider_mode": "live", "model": run.model,
            "estimated_cost_microusd": run.estimated_cost_microusd,
            "maximum_cost_microusd": run.maximum_cost_microusd,
            "actual_cost_microusd": run.actual_cost_microusd,
            "cost_accounting_complete": usage.get("complete", False),
            "reserved_exposure_microusd": usage.get("exposure_microusd", 0),
            "adaptive_score_delta": run.adaptive_score_delta,
            "task_count": len((run.input_snapshot_json or {}).get("snapshot", {}).get("tasks", [])),
            "expires_at": run.confirmation_expires_at.isoformat() if run.confirmation_expires_at else None,
            "error_code": run.error_code, "summary": research_summary(run)}


def estimate(db, user, opportunity_id, cfg):
    row = access(db, user, opportunity_id)
    if not getattr(cfg, "piq_live_research_enabled", False):
        return {"provider_mode": "demonstration"}
    config = configuration(cfg)
    snapshot = snapshot_for(db, row)
    request_body(snapshot, config["model"])
    token = secrets.token_urlsafe(32)
    run = PiqResearchRun(tenant_id=row.tenant_id, opportunity_id=row.id, requested_by=user.id,
        provider="openai", model=config["model"], status="awaiting_confirmation",
        idempotency_key="estimate:" + secrets.token_hex(24),
        estimated_cost_microusd=config["estimated_cost_microusd"], maximum_cost_microusd=config["maximum_cost_microusd"],
        confirmation_token_hash=digest(token), confirmation_expires_at=now()+timedelta(minutes=10),
        input_snapshot_json={"snapshot": snapshot, "config": config})
    db.add(run); db.commit(); db.refresh(run)
    try:
        access(db, user, opportunity_id, spend=True)
        can_confirm = True
    except HTTPException:
        can_confirm = False
    return {**safe_run(run), "confirmation_token": token, "can_confirm": can_confirm}


def confirm(db, user, opportunity_id, payload, cfg):
    row = access(db, user, opportunity_id, spend=True)
    config = configuration(cfg)
    # Serialize starts for this opportunity on both SQLite and PostgreSQL. This
    # same write precedes the active-run check, not just a SELECT FOR UPDATE.
    db.execute(update(PiqOpportunity).where(PiqOpportunity.id == row.id,
               PiqOpportunity.tenant_id == row.tenant_id).values(score=PiqOpportunity.score))
    db.refresh(row)
    run = db.scalar(select(PiqResearchRun).where(PiqResearchRun.id == payload.run_id,
        PiqResearchRun.tenant_id == row.tenant_id, PiqResearchRun.opportunity_id == row.id,
        PiqResearchRun.requested_by == user.id).execution_options(populate_existing=True))
    if not run or not secrets.compare_digest(run.confirmation_token_hash or "", digest(payload.confirmation_token)):
        raise HTTPException(409, "Invalid or already used research confirmation")
    if run.status != "awaiting_confirmation":
        raise HTTPException(409, "Research confirmation already used")
    if run.confirmation_expires_at.replace(tzinfo=timezone.utc) <= now():
        run.status = "expired"; run.confirmation_token_hash = None; db.commit()
        raise HTTPException(409, "Research confirmation expired")
    if config != run.input_snapshot_json["config"] or digest(snapshot_for(db, row)) != digest(run.input_snapshot_json["snapshot"]):
        raise HTTPException(409, "Research configuration or profile changed; request a new estimate")
    active = db.scalar(select(PiqResearchRun.id).where(PiqResearchRun.tenant_id == row.tenant_id,
        PiqResearchRun.opportunity_id == row.id, PiqResearchRun.status.in_(("queued", "running", "retry_wait"))))
    if active:
        raise HTTPException(409, "Adaptive Research is already active for this prospect")
    consumed = db.execute(update(PiqResearchRun).where(PiqResearchRun.id == run.id,
        PiqResearchRun.status == "awaiting_confirmation", PiqResearchRun.confirmation_token_hash == digest(payload.confirmation_token),
        PiqResearchRun.confirmation_expires_at > now()).values(
        status="queued", confirmation_token_hash=None, confirmed_at=now(), confirmed_by=user.id,
        managed_session_id=getattr(user, "_managed_session_id", None) if is_global_admin(user) else None,
        updated_at=now()).execution_options(synchronize_session=False))
    if consumed.rowcount != 1:
        raise HTTPException(409, "Research confirmation already used")
    db.commit(); db.refresh(run)
    return safe_run(run)


def owned(db, run_id, tenant_id, worker_id, attempt):
    result = db.execute(update(PiqResearchRun).where(PiqResearchRun.id == run_id,
        PiqResearchRun.tenant_id == tenant_id, PiqResearchRun.status == "running",
        PiqResearchRun.lease_owner == worker_id, PiqResearchRun.attempt_count == attempt,
        PiqResearchRun.lease_expires_at > now()).values(updated_at=now()).execution_options(synchronize_session=False))
    return db.get(PiqResearchRun, run_id, populate_existing=True) if result.rowcount == 1 else None


def validate_owner(db, run):
    user = db.get(User, run.requested_by) if run.requested_by else None
    if not user or run.confirmed_by != run.requested_by or not run.confirmed_at:
        raise fail("research_access_revoked")
    try:
        row = access(db, user, run.opportunity_id, spend=True, managed_id=run.managed_session_id)
        if row.tenant_id != run.tenant_id:
            raise fail("research_access_revoked")
        return row
    except HTTPException:
        raise fail("research_access_revoked") from None


def ledger(run, attempts):
    complete = all(a.get("usage", {}).get("complete", False) for a in attempts.values())
    known = sum(a.get("usage", {}).get("actual_cost_microusd") or 0 for a in attempts.values())
    exposure = sum(a.get("usage", {}).get("actual_cost_microusd") if a.get("usage", {}).get("complete")
                   else a["reserved_microusd"] for a in attempts.values())
    run.actual_cost_microusd = known if complete else None
    run.usage_json = {"provider": run.provider, "model": run.model, "pricing_version": run.input_snapshot_json["config"]["pricing_version"],
                      "attempts": attempts, "complete": complete, "known_cost_microusd": known,
                      "exposure_microusd": exposure}


def process_research_run(run_id, tenant_id, worker_id, *, adapter_factory=None):
    from .. import piq_worker as worker
    attempt = None
    try:
        with worker.SessionLocal() as db:
            initial = db.get(PiqResearchRun, run_id)
            if not initial or initial.tenant_id != tenant_id or initial.status != "running" or initial.lease_owner != worker_id:
                return
            attempt = initial.attempt_count
            run = owned(db, run_id, tenant_id, worker_id, attempt)
            if not run:
                return
            validate_owner(db, run)
            current = configuration(worker.settings)
            config, snapshot = run.input_snapshot_json["config"], run.input_snapshot_json["snapshot"]
            if current != config or run.provider != "openai" or attempt > config["attempts"]:
                raise fail("research_configuration_changed")
            attempts = dict((run.usage_json or {}).get("attempts", {}))
            # A durable receipt permits completion after a crash without another call.
            receipt = (run.diagnostics_json or {}).get("receipt")
            if not receipt:
                if str(attempt) in attempts:
                    # Never repeat an invocation whose reservation already committed.
                    raise fail("research_attempt_already_reserved")
                exposure = (run.usage_json or {}).get("exposure_microusd", 0)
                if exposure + config["attempt_bound_microusd"] > min(config["maximum_cost_microusd"], current["maximum_cost_microusd"]):
                    raise fail("research_cost_cap")
                attempts[str(attempt)] = {"reserved_microusd": config["attempt_bound_microusd"]}
                ledger(run, attempts)
            db.commit()
        if not receipt:
            receipt = (adapter_factory or ResponsesResearchAdapter)(worker.settings).execute(snapshot, config)
            with worker.SessionLocal() as db:
                run = owned(db, run_id, tenant_id, worker_id, attempt)
                if not run:
                    return
                attempts = dict(run.usage_json["attempts"])
                attempts[str(attempt)] = {**attempts[str(attempt)], "usage": receipt["usage"]}
                ledger(run, attempts)
                run.diagnostics_json = {"receipt": receipt}
                db.commit()
        with worker.SessionLocal() as db:
            run = owned(db, run_id, tenant_id, worker_id, attempt)
            if not run:
                return
            row = validate_owner(db, run)
            if configuration(worker.settings) != config:
                raise fail("research_configuration_changed")
            # Lock the opportunity as well; evidence and score change atomically.
            db.execute(update(PiqOpportunity).where(PiqOpportunity.id == row.id).values(score=PiqOpportunity.score))
            db.refresh(row)
            if row.base_match_score != snapshot["base_match_score"]:
                raise fail("research_base_changed")
            if (run.usage_json or {}).get("exposure_microusd", 0) > config["maximum_cost_microusd"]:
                raise fail("research_cost_bound_exceeded")
            for c in receipt["claims"]:
                if db.scalar(select(PiqEvidence.id).where(PiqEvidence.tenant_id == tenant_id, PiqEvidence.evidence_hash == c["hash"])):
                    continue
                db.add(PiqEvidence(tenant_id=tenant_id, opportunity_id=row.id, provider="openai_research",
                    evidence_type="adaptive_research", source_name="First-party public website / OpenAI research",
                    source_url=c["source_url"], source_title=c["source_title"], source_domain=c["source_domain"],
                    fact=c["fact"], confidence_pct=c["confidence"], evidence_state=c["state"], verified=c["verified"],
                    is_synthesized=False, profile_criterion=c["criterion"], research_run_id=run.id,
                    observed_at=now(), evidence_hash=c["hash"], raw_json={"policy": c["policy"], "criterion": c["criterion"],
                        "effect": c["effect"], "contradiction": c["state"] == "contradicted", "literal_source_checked": True}))
            db.flush()
            if receipt["claims"]:
                evidence = list(db.scalars(select(PiqEvidence).where(PiqEvidence.opportunity_id == row.id,
                    PiqEvidence.tenant_id == tenant_id, PiqEvidence.provider == "openai_research")))
                delta = score_delta([e.raw_json for e in evidence])
                row.adaptive_score_delta = delta
                row.score = max(0, min(100, row.base_match_score + delta))
                row.enhanced = True
                row.evidence_count = len(list(db.scalars(select(PiqEvidence.id).where(PiqEvidence.opportunity_id == row.id))))
                run.adaptive_score_delta = delta
            else:
                run.adaptive_score_delta = 0
            run.status = receipt["status"]
            run.error_code = receipt.get("error_code")
            run.error_message = "Adaptive Research could not be completed safely." if run.error_code else None
            run.completed_at = now(); run.updated_at = now()
            run.lease_owner = None; run.lease_expires_at = None; run.next_attempt_at = None
            db.commit()
    except Exception as exc:
        if attempt is None:
            return
        with worker.SessionLocal() as db:
            run = owned(db, run_id, tenant_id, worker_id, attempt)
            if run:
                error = exc if isinstance(exc, PiqProviderError) else fail("research_worker_error")
                worker.mark_run_failure(db, run, error_code=error.code,
                    error_message=error.public_message, retryable=error.retryable)
