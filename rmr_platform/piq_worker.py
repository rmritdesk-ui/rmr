from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
import threading
import uuid
from typing import Any, TypeVar

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .piq_engine.contracts import PiqProviderError
from .piq_engine.discovery import candidate_metadata, execute_google_discovery, persist_candidates
from .piq_engine.google_places import GooglePlacesAdapter
from .models import User, TenantService
from .permissions import CLIENT_OPERATION_WRITERS, is_global_admin
from .piq_models import PiqDiscoveryRun, PiqResearchRun
from .unified_models import ManagedTenantSession, PiqTargetProfile


logger = logging.getLogger(__name__)
LEASE_SECONDS = 300
_stop = threading.Event()
_thread: threading.Thread | None = None
_thread_lock = threading.Lock()
RunModel = TypeVar("RunModel", PiqDiscoveryRun, PiqResearchRun)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error_message(value: object) -> str:
    message = " ".join(str(value or "Worker error").split())[:500]
    lowered = message.lower()
    if "authorization:" in lowered or "bearer " in lowered or "api_key=" in lowered:
        return "Provider error details were redacted."
    return message


def get_discovery_run_for_tenant(db: Session, tenant_id: str, run_id: str) -> PiqDiscoveryRun | None:
    return db.scalar(select(PiqDiscoveryRun).where(
        PiqDiscoveryRun.id == run_id,
        PiqDiscoveryRun.tenant_id == tenant_id,
    ))


def get_research_run_for_tenant(db: Session, tenant_id: str, run_id: str) -> PiqResearchRun | None:
    return db.scalar(select(PiqResearchRun).where(
        PiqResearchRun.id == run_id,
        PiqResearchRun.tenant_id == tenant_id,
    ))


def managed_session_matches_tenant(db: Session, managed_session_id: str | None, tenant_id: str) -> bool:
    if not managed_session_id:
        return True
    return db.scalar(select(ManagedTenantSession.id).where(
        ManagedTenantSession.id == managed_session_id,
        ManagedTenantSession.tenant_id == tenant_id,
    )) is not None


def _claim_next(
    db: Session,
    model: type[RunModel],
    *,
    worker_id: str,
    now: datetime,
    tenant_id: str | None = None,
) -> RunModel | None:
    due = and_(
        model.status.in_(("queued", "retry_wait")),
        model.attempt_count < settings.piq_job_max_attempts,
        or_(model.next_attempt_at.is_(None), model.next_attempt_at <= now),
        or_(model.lease_expires_at.is_(None), model.lease_expires_at <= now),
    )
    query = select(model.id).where(due)
    if tenant_id is not None:
        query = query.where(model.tenant_id == tenant_id)
    candidate_id = db.scalar(query.order_by(model.created_at, model.id).limit(1))
    if not candidate_id:
        return None

    claimed = db.execute(
        update(model)
        .where(model.id == candidate_id, due)
        .values(
            status="running",
            attempt_count=model.attempt_count + 1,
            lease_owner=worker_id,
            lease_expires_at=now + timedelta(seconds=max(LEASE_SECONDS,
                getattr(settings, "piq_research_timeout_seconds", 120) + 90 if model is PiqResearchRun
                else getattr(settings, "piq_discovery_timeout_seconds", 30) + 30)),
            started_at=func.coalesce(model.started_at, now),
            updated_at=now,
            error_code=None,
            error_message=None,
        )
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        db.rollback()
        return None
    db.commit()
    return db.get(model, candidate_id, populate_existing=True)


def claim_next_discovery_run(
    db: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    tenant_id: str | None = None,
) -> PiqDiscoveryRun | None:
    return _claim_next(db, PiqDiscoveryRun, worker_id=worker_id, now=now or utcnow(), tenant_id=tenant_id)


def claim_next_research_run(
    db: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    tenant_id: str | None = None,
) -> PiqResearchRun | None:
    return _claim_next(db, PiqResearchRun, worker_id=worker_id, now=now or utcnow(), tenant_id=tenant_id)


def _recover_expired_for_model(db: Session, model: type[RunModel], *, now: datetime) -> int:
    rows = list(db.scalars(select(model).where(
        model.status == "running",
        model.lease_expires_at.is_not(None),
        model.lease_expires_at <= now,
    )))
    for run in rows:
        exhausted = run.attempt_count >= settings.piq_job_max_attempts
        db.execute(update(model).where(
            model.id == run.id, model.status == "running",
            model.lease_expires_at <= now,
            model.attempt_count == run.attempt_count,
        ).values(
            lease_owner=None, lease_expires_at=None, error_code="lease_expired",
            error_message="The prior worker lease expired before the run completed.",
            updated_at=now, status="failed" if exhausted else "retry_wait",
            completed_at=now if exhausted else None,
            next_attempt_at=None if exhausted else now,
        ).execution_options(synchronize_session="fetch"))
    db.commit()
    return len(rows)


def recover_expired_leases(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    current = now or utcnow()
    return {
        "discovery": _recover_expired_for_model(db, PiqDiscoveryRun, now=current),
        "research": _recover_expired_for_model(db, PiqResearchRun, now=current),
    }


def mark_run_failure(
    db: Session,
    run: PiqDiscoveryRun | PiqResearchRun,
    *,
    error_code: str,
    error_message: object,
    retryable: bool,
    now: datetime | None = None,
) -> None:
    current = now or utcnow()
    run.error_code = str(error_code or "worker_error")[:80]
    run.error_message = _safe_error_message(error_message)
    run.lease_owner = None
    run.lease_expires_at = None
    run.updated_at = current
    if retryable and run.attempt_count < settings.piq_job_max_attempts:
        delay_seconds = min(300, 5 * (2 ** max(0, run.attempt_count - 1)))
        run.status = "retry_wait"
        run.next_attempt_at = current + timedelta(seconds=delay_seconds)
        run.completed_at = None
    else:
        run.status = "failed"
        run.next_attempt_at = None
        run.completed_at = current
    db.commit()


def _fail_unimplemented_research(run_id: str, tenant_id: str, worker_id: str) -> None:
    with SessionLocal() as db:
        run = get_research_run_for_tenant(db, tenant_id, run_id)
        if not run or run.status != "running" or run.lease_owner != worker_id:
            return
        mark_run_failure(
            db,
            run,
            error_code="provider_not_implemented",
            error_message="Live PIQ provider execution is not implemented in Phase 0.",
            retryable=False,
        )


def _adapter() -> GooglePlacesAdapter:
    return GooglePlacesAdapter(
        api_key=settings.google_places_api_key,
        timeout_seconds=settings.piq_discovery_timeout_seconds,
    )


def _owned_discovery(db: Session, run_id: str, tenant_id: str, worker_id: str, attempt: int) -> PiqDiscoveryRun | None:
    now = utcnow()
    # A conditional write fences completion against expiry, cancellation and
    # recovery/reclaim, including a reclaim by the same worker identity.
    owned = db.execute(update(PiqDiscoveryRun).where(
        PiqDiscoveryRun.id == run_id, PiqDiscoveryRun.tenant_id == tenant_id,
        PiqDiscoveryRun.status == "running", PiqDiscoveryRun.lease_owner == worker_id,
        PiqDiscoveryRun.lease_expires_at > now, PiqDiscoveryRun.attempt_count == attempt,
    ).values(updated_at=now).execution_options(synchronize_session=False))
    return db.get(PiqDiscoveryRun, run_id, populate_existing=True) if owned.rowcount == 1 else None


def _validate_run_owner(db: Session, run: PiqDiscoveryRun) -> None:
    profile = db.scalar(select(PiqTargetProfile).where(
        PiqTargetProfile.id == run.target_profile_id, PiqTargetProfile.tenant_id == run.tenant_id,
    ))
    user = db.get(User, run.requested_by) if run.requested_by else None
    entitlement = db.scalar(select(TenantService.id).where(
        TenantService.tenant_id == run.tenant_id, TenantService.service_code == "piq_access",
        TenantService.status == "active",
    ))
    if not profile or not user or not user.active or not entitlement:
        raise PiqProviderError("run_access_denied", "Discovery ownership or access is no longer valid.", retryable=False)
    if is_global_admin(user):
        valid = db.scalar(select(ManagedTenantSession.id).where(
            ManagedTenantSession.id == run.managed_session_id,
            ManagedTenantSession.tenant_id == run.tenant_id,
            ManagedTenantSession.admin_user_id == user.id,
            ManagedTenantSession.status == "active",
            ManagedTenantSession.access_type == "managed_write",
            ManagedTenantSession.expires_at > utcnow(),
        ))
        if not valid:
            raise PiqProviderError("managed_session_invalid", "An active tenant-bound managed write session is required.", retryable=False)
    elif user.tenant_id != run.tenant_id or user.tenant_role not in CLIENT_OPERATION_WRITERS or run.managed_session_id:
        raise PiqProviderError("run_access_denied", "Discovery requester is not authorized for this tenant.", retryable=False)


def process_discovery_run(
    run_id: str,
    tenant_id: str,
    worker_id: str,
    *,
    adapter_factory: Any = None,
) -> None:
    with SessionLocal() as db:
        run = get_discovery_run_for_tenant(db, tenant_id, run_id)
        if not run or run.status != "running" or run.lease_owner != worker_id:
            return
        attempt = run.attempt_count
        run = _owned_discovery(db, run_id, tenant_id, worker_id, attempt)
        if run is None:
            return
        if not settings.piq_live_discovery_enabled:
            mark_run_failure(
                db,
                run,
                error_code="live_discovery_disabled",
                error_message="Live PIQ discovery is disabled.",
                retryable=False,
            )
            return
        if settings.piq_discovery_provider != "google_places" or run.provider != "google_places":
            mark_run_failure(
                db,
                run,
                error_code="invalid_configuration",
                error_message="The configured PIQ discovery provider is not supported.",
                retryable=False,
            )
            return
        if not managed_session_matches_tenant(db, run.managed_session_id, run.tenant_id):
            mark_run_failure(
                db,
                run,
                error_code="managed_session_tenant_mismatch",
                error_message="The managed session is not valid for this tenant.",
                retryable=False,
            )
            return
        profile_snapshot = dict(run.profile_snapshot_json or {})
        requested_count = run.requested_count
        if not 1 <= requested_count <= min(50, settings.piq_max_results_per_run):
            mark_run_failure(db, run, error_code="invalid_configuration",
                             error_message="Requested count exceeds current discovery limits.", retryable=False)
            return
        candidate_budget = min(100, requested_count * 2,
                               getattr(settings, "piq_max_candidates_per_run", requested_count))
        try:
            _validate_run_owner(db, run)
        except PiqProviderError as exc:
            mark_run_failure(db, run, error_code=exc.code, error_message=exc.public_message, retryable=False)
            return
        db.commit()

    try:
        result = execute_google_discovery(
            profile_snapshot,
            adapter=(adapter_factory or _adapter)(),
            max_queries=settings.piq_max_queries_per_run,
            max_results=candidate_budget,
        )
    except PiqProviderError as exc:
        with SessionLocal() as db:
            run = _owned_discovery(db, run_id, tenant_id, worker_id, attempt)
            if run:
                mark_run_failure(
                    db,
                    run,
                    error_code=exc.code,
                    error_message=exc.public_message,
                    retryable=exc.retryable,
                )
        return
    except Exception:
        with SessionLocal() as db:
            run = _owned_discovery(db, run_id, tenant_id, worker_id, attempt)
            if run:
                mark_run_failure(
                    db,
                    run,
                    error_code="worker_error",
                    error_message="The PIQ discovery worker encountered an unexpected error.",
                    retryable=False,
                )
        return

    try:
        with SessionLocal() as db:
            run = _owned_discovery(db, run_id, tenant_id, worker_id, attempt)
            if not run:
                return
            _validate_run_owner(db, run)
            result.diagnostics["candidate_budget"] = candidate_budget
            created_count, duplicate_count = persist_candidates(db, run, result)
            completed_at = utcnow()
            run.result_count = created_count
            run.status = result.status
            run.diagnostics_json = {
                **result.diagnostics,
                "created_count": created_count,
                "duplicate_count": duplicate_count,
                "candidates": [candidate_metadata(item) for item in result.candidates[:requested_count]],
            }
            issues = result.diagnostics.get("issues", [])
            run.error_code = issues[0]["code"] if issues else None
            run.error_message = issues[0]["message"] if issues else None
            run.next_attempt_at = None
            run.lease_owner = None
            run.lease_expires_at = None
            run.completed_at = completed_at
            run.updated_at = completed_at
            db.commit()
    except Exception:
        # The failed session rolls back all candidate inserts before recording a
        # safe terminal error. Never log SQL parameters or provider payloads.
        with SessionLocal() as db:
            run = _owned_discovery(db, run_id, tenant_id, worker_id, attempt)
            if run:
                mark_run_failure(db, run, error_code="persistence_failed",
                                 error_message="Discovery candidates could not be saved.", retryable=False)


def tick(*, worker_id: str | None = None) -> dict[str, Any]:
    identity = worker_id or f"piq-worker-{os.getpid()}-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        recovered = recover_expired_leases(db)

    claimed: list[tuple[str, str, str]] = []
    if settings.piq_live_discovery_enabled:
        with SessionLocal() as db:
            discovery = claim_next_discovery_run(db, worker_id=identity)
            if discovery:
                claimed.append(("discovery", discovery.id, discovery.tenant_id))
    with SessionLocal() as db:
        research = claim_next_research_run(db, worker_id=identity)
        if research:
            claimed.append(("research", research.id, research.tenant_id))

    for run_type, run_id, tenant_id in claimed:
        if run_type == "discovery":
            process_discovery_run(run_id, tenant_id, identity)
        else:
            from .piq_engine.research_service import process_research_run
            process_research_run(run_id, tenant_id, identity)
    return {"recovered": recovered, "claimed": len(claimed)}


def _loop() -> None:
    while not _stop.is_set():
        try:
            tick()
        except Exception:
            logger.error("PIQ worker tick failed; any expired lease will be recovered on a later tick")
        _stop.wait(settings.piq_worker_poll_seconds)


def start() -> bool:
    global _thread
    if not settings.piq_worker_enabled:
        return False
    with _thread_lock:
        if _thread and _thread.is_alive():
            return False
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="rmr-piq-worker", daemon=True)
        _thread.start()
        return True


def stop(timeout: float = 10.0) -> None:
    global _thread
    _stop.set()
    with _thread_lock:
        thread = _thread
    if thread and thread.is_alive():
        thread.join(timeout=max(0.0, timeout))
    with _thread_lock:
        if _thread is thread and (not thread or not thread.is_alive()):
            _thread = None


def is_running() -> bool:
    return bool(_thread and _thread.is_alive())
