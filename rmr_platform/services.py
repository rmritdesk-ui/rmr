from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from .models import (
    Account,
    AuditEvent,
    EconomicTransaction,
    ForecastMonth,
    ForecastVersion,
    Lead,
    Notification,
    OnboardingProject,
    OnboardingStep,
    Opportunity,
    ServiceCatalog,
    SolutionInterest,
    SolutionRequest,
    Tenant,
    TenantService,
    TrainingProgress,
    TrainingResource,
    User,
)
from .utils import allocation


def audit(db: Session, actor: User | None, event_type: str, *, tenant_id: str | None = None,
          entity_type: str = "", entity_id: str = "", data: dict | None = None) -> None:
    db.add(AuditEvent(
        actor_user_id=actor.id if actor else None,
        tenant_id=tenant_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        event_data=data or {},
    ))


def recalculate_onboarding(db: Session, project: OnboardingProject) -> None:
    steps = list(db.scalars(select(OnboardingStep).where(OnboardingStep.project_id == project.id).order_by(OnboardingStep.stage_number)))
    completed = sum(1 for step in steps if step.status == "complete")
    total_steps = max(len(steps), 1)
    project.readiness_pct = (completed * 100 + total_steps // 2) // total_steps
    if completed == len(steps):
        project.status = "complete"
        project.current_stage = len(steps)
    else:
        project.status = "active"
        next_step = next((step for step in steps if step.status != "complete"), steps[-1])
        project.current_stage = next_step.stage_number
        if next_step.status == "not_started":
            next_step.status = "in_progress"


def activate_solution(db: Session, request: SolutionRequest, actor: User,
                      contract_price_cents: int | None = None, usage_price_cents: int | None = None) -> TenantService:
    catalog = db.scalar(select(ServiceCatalog).where(ServiceCatalog.code == request.service_code, ServiceCatalog.active.is_(True)))
    if not catalog:
        raise ValueError("Service catalog entry is missing")
    existing = db.scalar(select(TenantService).where(
        TenantService.tenant_id == request.tenant_id,
        TenantService.service_code == request.service_code,
    ))
    if existing:
        existing.status = "active"
        if contract_price_cents is not None:
            existing.contract_price_cents = contract_price_cents
        if usage_price_cents is not None:
            existing.usage_price_cents = usage_price_cents
        service = existing
    else:
        service = TenantService(
            tenant_id=request.tenant_id,
            service_code=request.service_code,
            contract_price_cents=contract_price_cents if contract_price_cents is not None else request.proposed_monthly_cents or catalog.standard_price_cents,
            usage_price_cents=usage_price_cents if usage_price_cents is not None else request.proposed_usage_cents,
            cadence=catalog.cadence,
            status="active",
            effective_date=date.today(),
            next_billing_date=date.today() + timedelta(days=30),
            source_request_id=request.id,
        )
        db.add(service)
    request.status = "Active"
    request.reviewed_by = actor.id
    request.reviewed_at = datetime.now(timezone.utc)

    # Synchronize required, role-appropriate training with the activated
    # solution. The Training Library remains governed by RMR; activation only
    # assigns already-published resources and never invents training content.
    keywords_by_service = {
        "platform_core": ("platform",),
        "crm": ("crm", "sales organization"),
        "forecasting": ("forecast",),
        "management_intelligence": ("management intelligence", "report"),
        "forecasting_management": ("forecast", "management intelligence", "report"),
        "managed_website": ("website",),
        "custom_website_connection": ("website",),
        "external_website_connection": ("website",),
        "monthly_seo": ("seo",),
        "piq_access": ("prospectiq", "piq"),
        "piq_enhancement": ("prospectiq", "piq"),
        "training": ("training", "adoption"),
        "campaigns": ("campaign", "content", "marketing"),
    }
    keywords = keywords_by_service.get(request.service_code, (catalog.category.lower(), catalog.name.lower()))
    resources = list(db.scalars(select(TrainingResource).where(
        TrainingResource.published.is_(True),
        TrainingResource.required.is_(True),
    )))
    users = list(db.scalars(select(User).where(User.tenant_id == request.tenant_id, User.active.is_(True))))
    for resource in resources:
        haystack = f"{resource.module} {resource.title}".lower()
        if not any(keyword.lower() in haystack for keyword in keywords):
            continue
        for tenant_user in users:
            if resource.roles_json and tenant_user.tenant_role not in resource.roles_json:
                continue
            existing_progress = db.scalar(select(TrainingProgress).where(
                TrainingProgress.tenant_id == request.tenant_id,
                TrainingProgress.user_id == tenant_user.id,
                TrainingProgress.resource_id == resource.id,
            ))
            if not existing_progress:
                db.add(TrainingProgress(
                    tenant_id=request.tenant_id,
                    user_id=tenant_user.id,
                    resource_id=resource.id,
                    status="not_started",
                    progress_pct=0,
                ))

    tenant = db.get(Tenant, request.tenant_id)
    db.add(Notification(
        recipient_scope=f"TENANT:{request.tenant_id}",
        tenant_id=request.tenant_id,
        notification_type="solution_activated",
        title=f"{catalog.name} is active",
        body="The solution is now available in your organization.",
        action_route="solutions",
        action_label="Open Solutions Center",
        entity_type="solution_request",
        entity_id=request.id,
    ))
    db.add(Notification(
        recipient_scope="GLOBAL_ADMIN",
        tenant_id=request.tenant_id,
        notification_type="solution_activation_follow_up",
        title=f"Service activated — {catalog.name}",
        body=(
            f"{tenant.name if tenant else 'Client'} now has {catalog.name}. "
            "Confirm provisioning, client access, and the first operational follow-up."
        ),
        action_route=f"client-360?tenant={request.tenant_id}",
        action_label="Open Client 360",
        entity_type="solution_request",
        entity_id=request.id,
    ))
    audit(db, actor, "solution.activated", tenant_id=request.tenant_id, entity_type="solution_request", entity_id=request.id,
          data={"service_code": request.service_code, "contract_price_cents": service.contract_price_cents})
    return service


def create_monthly_transaction(db: Session, tenant_id: str, service: TenantService, *, quantity: float = 1.0) -> EconomicTransaction:
    catalog = db.scalar(select(ServiceCatalog).where(ServiceCatalog.code == service.service_code))
    if not catalog:
        raise ValueError("Missing service catalog entry")
    unit_price = service.usage_price_cents if catalog.cadence == "usage" and service.usage_price_cents else service.contract_price_cents
    revenue = round(unit_price * quantity)
    direct_cost = round(catalog.direct_cost_cents * quantity)
    distributable, rmr_share, step2_share = allocation(revenue, direct_cost, catalog.split_basis, catalog.rmr_share_pct, catalog.step2_share_pct)
    period = date.today().strftime("%Y-%m")
    tx = EconomicTransaction(
        tenant_id=tenant_id,
        service_code=service.service_code,
        period=period,
        quantity=quantity,
        unit_price_cents=unit_price,
        revenue_cents=revenue,
        direct_cost_cents=direct_cost,
        split_basis=catalog.split_basis,
        rmr_share_pct=catalog.rmr_share_pct,
        step2_share_pct=catalog.step2_share_pct,
        rmr_share_cents=rmr_share,
        step2_share_cents=step2_share,
        invoice_reference=f"PILOT-{period}-{service.id[:8]}",
        trace_reference=f"TRACE-{service.id}-{datetime.now(timezone.utc).timestamp()}",
    )
    db.add(tx)
    return tx


def maybe_create_interest_notification(db: Session, tenant_id: str, service_code: str) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=14)
    count = db.scalar(select(func.count(SolutionInterest.id)).where(
        SolutionInterest.tenant_id == tenant_id,
        SolutionInterest.service_code == service_code,
        SolutionInterest.created_at >= since,
    )) or 0
    open_request = db.scalar(select(SolutionRequest).where(
        SolutionRequest.tenant_id == tenant_id,
        SolutionRequest.service_code == service_code,
        SolutionRequest.status.in_(["Requested", "Pending Activation", "Active"]),
    ))
    if count >= 3 and not open_request:
        already = db.scalar(select(Notification).where(
            Notification.tenant_id == tenant_id,
            Notification.notification_type == "expansion_interest",
            Notification.body.contains(service_code),
            Notification.created_at >= since,
        ))
        if not already:
            tenant = db.get(Tenant, tenant_id)
            catalog = db.scalar(select(ServiceCatalog).where(ServiceCatalog.code == service_code))
            db.add(Notification(
                recipient_scope="GLOBAL_ADMIN",
                tenant_id=tenant_id,
                notification_type="expansion_interest",
                title=f"Strong solution interest — {catalog.name if catalog else service_code}",
                body=f"{tenant.name if tenant else 'Client'} has explored {catalog.name if catalog else service_code} {count} times in the last 14 days.",
                action_route=f"client-360?tenant={tenant_id}",
                action_label="Open Client 360",
                entity_type="service_catalog",
                entity_id=service_code,
            ))


def tenant_success_metrics(db: Session, tenant: Tenant) -> dict[str, object]:
    users = db.scalar(select(func.count(User.id)).where(User.tenant_id == tenant.id, User.active.is_(True))) or 0
    accounts = db.scalar(select(func.count(Account.id)).where(Account.tenant_id == tenant.id)) or 0
    opportunities = db.scalar(select(func.count(Opportunity.id)).where(Opportunity.tenant_id == tenant.id)) or 0
    leads = db.scalar(select(func.count(Lead.id)).where(Lead.tenant_id == tenant.id)) or 0
    training_total = db.scalar(select(func.count(TrainingProgress.id)).where(TrainingProgress.tenant_id == tenant.id)) or 0
    training_complete = db.scalar(select(func.count(TrainingProgress.id)).where(
        TrainingProgress.tenant_id == tenant.id, TrainingProgress.status == "complete"
    )) or 0
    forecast_version = db.scalar(select(ForecastVersion).where(ForecastVersion.tenant_id == tenant.id, ForecastVersion.is_active.is_(True)))
    forecast_used = bool(forecast_version)
    forecast_accuracy = 0
    if forecast_version:
        rows = list(db.scalars(select(ForecastMonth).where(ForecastMonth.version_id == forecast_version.id, ForecastMonth.actual_cents > 0)))
        forecast_total = sum(row.forecast_cents for row in rows)
        actual_total = sum(row.actual_cents for row in rows)
        if forecast_total:
            forecast_accuracy = max(0, round(100 - abs(actual_total - forecast_total) / forecast_total * 100))
    measured_activity = bool(accounts or opportunities or leads or training_total or forecast_used)
    return {
        "active_users": users,
        "accounts": accounts,
        "opportunities": opportunities,
        "leads": leads,
        "training_completion_pct": round(training_complete / training_total * 100) if training_total else tenant.training_completion_pct,
        "training_state": "measured" if training_total else "not_assigned",
        "forecast_used": forecast_used,
        "forecast_state": "active" if forecast_used else "not_started",
        "forecast_accuracy_pct": forecast_accuracy,
        "adoption_score": tenant.adoption_score,
        "adoption_state": "measured" if measured_activity else "not_measured",
        "operations_state": "active" if (accounts or opportunities or leads) else "no_records_yet",
        "health_status": tenant.health_status,
        "renewal_risk": tenant.renewal_risk,
    }
