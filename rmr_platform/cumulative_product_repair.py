from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .cb1_models import CB1Message, CB1ProviderConnection, CB1SocialContent
from .client_admin_corrections import SocialGenerateIn, _real_social
from .client_admin_models import SocialGenerationMetadata
from .cumulative_product_models import (
    ClientServiceCommercialTerm,
    CommercialTermHistory,
    MessageDeliveryContext,
    SocialContentRevision,
)
from .db import get_db
from .models import (
    Account,
    Contact,
    Lead,
    Opportunity,
    ServiceCatalog,
    Tenant,
    TenantService,
    User,
)
from .permissions import is_global_admin, require_client_campaign_write, require_tenant_access
from .security import current_user, require_request_origin
from .services import audit
from .utils import model_dict

router = APIRouter(prefix="/api/v522", tags=["v5.2.2-cumulative-product-repair"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row(obj: Any, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    return model_dict(obj, exclude=set(exclude))


def _require_admin(user: User) -> None:
    if not is_global_admin(user):
        raise HTTPException(status_code=403, detail="RMR/Step2 administrator access required")


def _monthly_amount(cents: int, cadence: str, quantity: float) -> int:
    cadence = (cadence or "monthly").lower()
    value = int(round(int(cents or 0) * float(quantity or 1.0)))
    if cadence in {"annual", "annually", "yearly"}:
        return int(round(value / 12))
    if cadence in {"one_time", "one-time", "once", "project"}:
        return 0
    return value


def _term_snapshot(term: ClientServiceCommercialTerm) -> dict[str, Any]:
    return {
        "rmr_share_pct": term.rmr_share_pct,
        "step2_share_pct": term.step2_share_pct,
        "split_basis": term.split_basis,
        "direct_cost_cents": term.direct_cost_cents,
        "seller_org": term.seller_org,
        "seller_name": term.seller_name,
        "notes": term.notes,
        "source": term.source,
        "version_number": term.version_number,
        "updated_at": term.updated_at.isoformat() if term.updated_at else None,
    }


def _commercial_view(
    tenant: Tenant,
    subscription: TenantService,
    catalog: ServiceCatalog,
    term: ClientServiceCommercialTerm | None,
) -> dict[str, Any]:
    rmr_pct = float(term.rmr_share_pct if term else catalog.rmr_share_pct)
    step2_pct = float(term.step2_share_pct if term else catalog.step2_share_pct)
    direct_cost = int(term.direct_cost_cents if term else catalog.direct_cost_cents)
    raw_split_basis = str(term.split_basis if term else catalog.split_basis or "gross").lower()
    # v5.2.1 catalog data used ``net`` for a post-direct-cost split. The
    # cumulative model names the same business concept ``contribution``.
    # Normalize the legacy value so calculation, display, and edit forms do
    # not silently change a client agreement from net to gross.
    split_basis = "contribution" if raw_split_basis in {"net", "contribution"} else "gross"
    monthly_revenue = _monthly_amount(subscription.contract_price_cents, subscription.cadence, subscription.quantity)
    monthly_direct_cost = _monthly_amount(direct_cost, subscription.cadence, subscription.quantity)
    contribution = monthly_revenue - monthly_direct_cost
    # Revenue-share payouts never become negative merely because a zero-priced
    # service has a configured cost. Negative contribution remains visible, but
    # the split base floors at zero until there is distributable revenue.
    base = max(0, contribution) if split_basis == "contribution" else max(0, monthly_revenue)
    rmr_share = int(round(base * rmr_pct / 100))
    step2_share = int(round(base * step2_pct / 100))
    return {
        "tenant": {"id": tenant.id, "name": tenant.name, "seller_org": tenant.seller_org, "seller_name": tenant.seller_name},
        "catalog": _row(catalog),
        "tenant_service": _row(subscription),
        "commercial_term": _row(term) if term else None,
        "terms_source": "explicit_client_terms" if term else "catalog_default_requires_review",
        "calculation": {
            "monthly_revenue_cents": monthly_revenue,
            "monthly_direct_cost_cents": monthly_direct_cost,
            "monthly_contribution_cents": contribution,
            "split_basis": split_basis,
            "split_base_cents": base,
            "rmr_share_pct": rmr_pct,
            "step2_share_pct": step2_pct,
            "rmr_share_cents": rmr_share,
            "step2_share_cents": step2_share,
            "reconciles": abs((rmr_share + step2_share) - base) <= 1,
        },
    }


class CommercialTermUpdate(BaseModel):
    contract_price_cents: int = Field(ge=0)
    usage_price_cents: int = Field(default=0, ge=0)
    cadence: str = Field(default="monthly", max_length=30)
    status: str = Field(default="active", max_length=30)
    quantity: float = Field(default=1.0, gt=0)
    effective_date: date
    rmr_share_pct: float = Field(ge=0, le=100)
    step2_share_pct: float = Field(ge=0, le=100)
    split_basis: str = Field(default="gross", pattern="^(gross|contribution)$")
    direct_cost_cents: int = Field(default=0, ge=0)
    seller_org: str = Field(default="RMR", max_length=40)
    seller_name: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=5000)


class CommercialTermCreate(CommercialTermUpdate):
    service_code: str = Field(min_length=1, max_length=80)


class SocialContentUpdate(BaseModel):
    title: str = Field(default="", max_length=240)
    post_text: str = Field(min_length=1, max_length=10000)
    hashtags: str = Field(default="", max_length=2000)
    status: str = Field(default="DRAFT", pattern="^(DRAFT|APPROVED|PUBLISHED|ARCHIVED)$")


class SocialRegenerateIn(BaseModel):
    objective: str | None = Field(default=None, max_length=2000)
    audience: str | None = Field(default=None, max_length=1000)
    tone: str | None = Field(default=None, max_length=160)
    call_to_action: str | None = Field(default=None, max_length=300)
    keywords: list[str] | None = None
    suggested_visual: str | None = Field(default=None, max_length=1000)


@router.get("/admin/tenants/{tenant_id}/commercial-terms")
def list_commercial_terms(
    tenant_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    _require_admin(user)
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client not found")
    subscriptions = list(
        db.scalars(
            select(TenantService)
            .where(TenantService.tenant_id == tenant_id)
            .order_by(TenantService.created_at, TenantService.service_code)
        )
    )
    catalogs = {row.code: row for row in db.scalars(select(ServiceCatalog))}
    terms = {
        row.tenant_service_id: row
        for row in db.scalars(
            select(ClientServiceCommercialTerm).where(ClientServiceCommercialTerm.tenant_id == tenant_id)
        )
    }
    items = [
        _commercial_view(tenant, row, catalogs[row.service_code], terms.get(row.id))
        for row in subscriptions
        if row.service_code in catalogs
    ]
    total_mrr = sum(item["calculation"]["monthly_revenue_cents"] for item in items if item["tenant_service"]["status"] == "active")
    total_rmr = sum(item["calculation"]["rmr_share_cents"] for item in items if item["tenant_service"]["status"] == "active")
    total_step2 = sum(item["calculation"]["step2_share_cents"] for item in items if item["tenant_service"]["status"] == "active")
    return {
        "tenant": _row(tenant),
        "items": items,
        "totals": {"mrr_cents": total_mrr, "rmr_share_cents": total_rmr, "step2_share_cents": total_step2},
        "unreviewed_defaults": sum(1 for item in items if item["terms_source"] != "explicit_client_terms"),
    }


@router.post("/admin/tenants/{tenant_id}/commercial-terms")
def create_commercial_term(
    tenant_id: str,
    payload: CommercialTermCreate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    _require_admin(user)
    tenant = db.get(Tenant, tenant_id)
    catalog = db.scalar(select(ServiceCatalog).where(ServiceCatalog.code == payload.service_code, ServiceCatalog.active.is_(True)))
    if not tenant or not catalog:
        raise HTTPException(status_code=404, detail="Client or service not found")
    existing = db.scalar(select(TenantService).where(TenantService.tenant_id == tenant_id, TenantService.service_code == payload.service_code))
    if existing:
        raise HTTPException(status_code=409, detail="This service is already on the client schedule")
    if abs((payload.rmr_share_pct + payload.step2_share_pct) - 100.0) > 0.01:
        raise HTTPException(status_code=422, detail="RMR and Step2 shares must total 100%")
    subscription = TenantService(
        tenant_id=tenant_id,
        service_code=payload.service_code,
        contract_price_cents=payload.contract_price_cents,
        usage_price_cents=payload.usage_price_cents,
        cadence=payload.cadence,
        status=payload.status,
        effective_date=payload.effective_date,
        quantity=payload.quantity,
        notes=payload.notes,
    )
    db.add(subscription)
    db.flush()
    term = ClientServiceCommercialTerm(
        tenant_service_id=subscription.id,
        tenant_id=tenant_id,
        service_code=payload.service_code,
        rmr_share_pct=payload.rmr_share_pct,
        step2_share_pct=payload.step2_share_pct,
        split_basis=payload.split_basis,
        direct_cost_cents=payload.direct_cost_cents,
        seller_org=payload.seller_org,
        seller_name=payload.seller_name,
        notes=payload.notes,
        source="explicit_client_terms",
        version_number=1,
        updated_by=user.id,
    )
    db.add(term)
    db.flush()
    db.add(CommercialTermHistory(
        commercial_term_id=term.id,
        tenant_id=tenant_id,
        service_code=payload.service_code,
        version_number=1,
        snapshot_json={"tenant_service": _row(subscription), "commercial_term": _term_snapshot(term)},
        changed_by=user.id,
    ))
    audit(db, user, "commercial.terms.created", tenant_id=tenant_id, entity_type="tenant_service", entity_id=subscription.id, data={"service_code": payload.service_code})
    db.commit()
    return _commercial_view(tenant, subscription, catalog, term)


@router.patch("/admin/tenants/{tenant_id}/commercial-terms/{tenant_service_id}")
def update_commercial_term(
    tenant_id: str,
    tenant_service_id: str,
    payload: CommercialTermUpdate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    _require_admin(user)
    if abs((payload.rmr_share_pct + payload.step2_share_pct) - 100.0) > 0.01:
        raise HTTPException(status_code=422, detail="RMR and Step2 shares must total 100%")
    tenant = db.get(Tenant, tenant_id)
    subscription = db.get(TenantService, tenant_service_id)
    if not tenant or not subscription or subscription.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Client service not found")
    catalog = db.scalar(select(ServiceCatalog).where(ServiceCatalog.code == subscription.service_code))
    if not catalog:
        raise HTTPException(status_code=404, detail="Service catalog record not found")
    before_subscription = _row(subscription)
    subscription.contract_price_cents = payload.contract_price_cents
    subscription.usage_price_cents = payload.usage_price_cents
    subscription.cadence = payload.cadence
    subscription.status = payload.status
    subscription.quantity = payload.quantity
    subscription.effective_date = payload.effective_date
    subscription.notes = payload.notes
    term = db.scalar(select(ClientServiceCommercialTerm).where(ClientServiceCommercialTerm.tenant_service_id == tenant_service_id))
    if not term:
        term = ClientServiceCommercialTerm(
            tenant_service_id=tenant_service_id,
            tenant_id=tenant_id,
            service_code=subscription.service_code,
            updated_by=user.id,
        )
        db.add(term)
        db.flush()
    before_term = _term_snapshot(term)
    term.rmr_share_pct = payload.rmr_share_pct
    term.step2_share_pct = payload.step2_share_pct
    term.split_basis = payload.split_basis
    term.direct_cost_cents = payload.direct_cost_cents
    term.seller_org = payload.seller_org
    term.seller_name = payload.seller_name
    term.notes = payload.notes
    term.source = "explicit_client_terms"
    term.version_number = int(term.version_number or 0) + 1
    term.updated_by = user.id
    term.updated_at = _now()
    db.add(CommercialTermHistory(
        commercial_term_id=term.id,
        tenant_id=tenant_id,
        service_code=subscription.service_code,
        version_number=term.version_number,
        snapshot_json={"tenant_service": _row(subscription), "commercial_term": _term_snapshot(term)},
        changed_by=user.id,
    ))
    audit(
        db,
        user,
        "commercial.terms.updated",
        tenant_id=tenant_id,
        entity_type="tenant_service",
        entity_id=tenant_service_id,
        data={
            "before_subscription": before_subscription,
            "before_commercial_term": before_term,
            "after_subscription": _row(subscription),
            "after_commercial_term": _term_snapshot(term),
        },
    )
    db.commit()
    return _commercial_view(tenant, subscription, catalog, term)


@router.get("/admin/partner-economics")
def partner_economics(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    _require_admin(user)
    tenants = {row.id: row for row in db.scalars(select(Tenant))}
    catalogs = {row.code: row for row in db.scalars(select(ServiceCatalog))}
    subscriptions = list(db.scalars(select(TenantService).order_by(TenantService.tenant_id, TenantService.service_code)))
    terms = {row.tenant_service_id: row for row in db.scalars(select(ClientServiceCommercialTerm))}
    items = []
    for subscription in subscriptions:
        tenant = tenants.get(subscription.tenant_id)
        catalog = catalogs.get(subscription.service_code)
        if not tenant or not catalog:
            continue
        view = _commercial_view(tenant, subscription, catalog, terms.get(subscription.id))
        if subscription.status != "active":
            view["calculation"] = {**view["calculation"], "excluded_reason": "inactive subscription"}
        items.append(view)
    active_items = [x for x in items if x["tenant_service"]["status"] == "active"]
    totals = {
        "monthly_revenue_cents": sum(x["calculation"]["monthly_revenue_cents"] for x in active_items),
        "monthly_direct_cost_cents": sum(x["calculation"]["monthly_direct_cost_cents"] for x in active_items),
        "monthly_contribution_cents": sum(x["calculation"]["monthly_contribution_cents"] for x in active_items),
        "rmr_share_cents": sum(x["calculation"]["rmr_share_cents"] for x in active_items),
        "step2_share_cents": sum(x["calculation"]["step2_share_cents"] for x in active_items),
        "unreviewed_defaults": sum(1 for x in active_items if x["terms_source"] != "explicit_client_terms"),
    }
    totals["split_reconciliation_difference_cents"] = sum(
        (x["calculation"]["rmr_share_cents"] + x["calculation"]["step2_share_cents"] - x["calculation"]["split_base_cents"])
        for x in active_items
    )
    by_service: dict[str, dict[str, Any]] = {}
    for item in active_items:
        key = item["catalog"]["code"]
        bucket = by_service.setdefault(key, {
            "service_code": key,
            "service_name": item["catalog"]["name"],
            "client_count": 0,
            "monthly_revenue_cents": 0,
            "monthly_direct_cost_cents": 0,
            "monthly_contribution_cents": 0,
            "rmr_share_cents": 0,
            "step2_share_cents": 0,
        })
        bucket["client_count"] += 1
        for name in ("monthly_revenue_cents", "monthly_direct_cost_cents", "monthly_contribution_cents", "rmr_share_cents", "step2_share_cents"):
            bucket[name] += item["calculation"][name]
    return {
        "summary": totals,
        "items": items,
        "by_service": list(by_service.values()),
        "formula": {
            "gross": "RMR/Step2 split is calculated on monthly client revenue. Direct cost is shown separately in contribution.",
            "contribution": "RMR/Step2 split is calculated after the configured direct cost is deducted.",
            "monthlyization": "Annual subscriptions are divided by 12; one-time/project fees are excluded from MRR.",
        },
        "data_provenance": "Every amount is derived from the current client service schedule and its per-service commercial terms.",
    }


@router.get("/admin/partner-economics/terms/{tenant_service_id}")
def partner_economics_detail(
    tenant_service_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    _require_admin(user)
    subscription = db.get(TenantService, tenant_service_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Client service not found")
    tenant = db.get(Tenant, subscription.tenant_id)
    catalog = db.scalar(select(ServiceCatalog).where(ServiceCatalog.code == subscription.service_code))
    term = db.scalar(select(ClientServiceCommercialTerm).where(ClientServiceCommercialTerm.tenant_service_id == tenant_service_id))
    history = []
    if term:
        history = [
            _row(row)
            for row in db.scalars(
                select(CommercialTermHistory)
                .where(CommercialTermHistory.commercial_term_id == term.id)
                .order_by(CommercialTermHistory.version_number.desc())
            )
        ]
    return {"item": _commercial_view(tenant, subscription, catalog, term), "history": history}


def _message_relationships(db: Session, context: MessageDeliveryContext | None, message: CB1Message) -> dict[str, Any]:
    result: dict[str, Any] = {"type": None, "id": message.crm_record_id, "label": None}
    if context:
        candidates = [
            ("Opportunity", Opportunity, context.opportunity_id, "name"),
            ("Account", Account, context.account_id, "name"),
            ("Lead", Lead, context.lead_id, "company_name"),
            ("Contact", Contact, context.contact_id, None),
        ]
        for label, model, item_id, field in candidates:
            if not item_id:
                continue
            row = db.get(model, item_id)
            if not row:
                continue
            if field:
                value = getattr(row, field, "")
            else:
                value = f"{getattr(row, 'first_name', '')} {getattr(row, 'last_name', '')}".strip()
            return {"type": label, "id": item_id, "label": value or label}
    return result


@router.get("/tenants/{tenant_id}/messages/{message_id}")
def message_detail(
    tenant_id: str,
    message_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_tenant_access(user, tenant_id)
    message = db.get(CB1Message, message_id)
    if not message or message.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Message not found")
    context = db.get(MessageDeliveryContext, message_id)
    actor = db.get(User, message.created_by) if message.created_by else None
    connection = db.get(CB1ProviderConnection, context.connection_id) if context else None
    body = message.body_approved or message.body_draft
    return {
        "message": _row(message, ("supported_facts_json",)) | {"body": body},
        "delivery": _row(context) if context else {
            "sender_email": connection.sender_email if connection else "",
            "sender_name": connection.sender_name if connection else "",
            "provider": connection.provider if connection else "unknown",
            "delivery_status": message.status,
        },
        "actor": {"id": actor.id, "name": actor.full_name, "email": actor.email} if actor else None,
        "relationship": _message_relationships(db, context, message),
        "provenance": "Recorded one-to-one CRM communication" if message.campaign_id is None else "Campaign communication record",
    }


def _save_social_revision(db: Session, row: CB1SocialContent, user_id: str | None) -> None:
    revision = int(
        db.scalar(
            select(func.max(SocialContentRevision.revision_number)).where(
                SocialContentRevision.social_content_id == row.id
            )
        )
        or 0
    ) + 1
    db.add(SocialContentRevision(
        social_content_id=row.id,
        tenant_id=row.tenant_id,
        revision_number=revision,
        snapshot_json={
            "title": row.title,
            "post_text": row.post_text,
            "hashtags": row.hashtags,
            "status": row.status,
            "published_url": row.published_url,
        },
        created_by=user_id,
    ))


@router.get("/tenants/{tenant_id}/social/{social_id}")
def social_detail(
    tenant_id: str,
    social_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_tenant_access(user, tenant_id)
    row = db.get(CB1SocialContent, social_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Social content not found")
    meta = db.get(SocialGenerationMetadata, social_id)
    revisions = [
        _row(item)
        for item in db.scalars(
            select(SocialContentRevision)
            .where(SocialContentRevision.social_content_id == social_id)
            .order_by(SocialContentRevision.revision_number.desc())
        )
    ]
    return {"item": _row(row), "generation": _row(meta) if meta else None, "revisions": revisions}


@router.patch("/tenants/{tenant_id}/social/{social_id}")
def update_social_content(
    tenant_id: str,
    social_id: str,
    payload: SocialContentUpdate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_client_campaign_write(user, tenant_id)
    row = db.get(CB1SocialContent, social_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Social content not found")
    _save_social_revision(db, row, user.id)
    row.title = payload.title
    row.post_text = payload.post_text
    row.hashtags = payload.hashtags
    row.status = payload.status
    row.updated_at = _now()
    audit(db, user, "social.content.updated", tenant_id=tenant_id, entity_type="social_content", entity_id=row.id, data={"status": row.status})
    db.commit()
    return {"item": _row(row)}


@router.post("/tenants/{tenant_id}/social/{social_id}/regenerate")
def regenerate_social_content(
    tenant_id: str,
    social_id: str,
    payload: SocialRegenerateIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_client_campaign_write(user, tenant_id)
    row = db.get(CB1SocialContent, social_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Social content not found")
    meta = db.get(SocialGenerationMetadata, social_id)
    source = SocialGenerateIn(
        objective=payload.objective or (meta.objective if meta else row.title or row.post_text[:200]),
        audience=payload.audience or (meta.audience if meta else "the intended audience"),
        tone=payload.tone or (meta.tone if meta else "professional and approachable"),
        call_to_action=payload.call_to_action or (meta.call_to_action if meta else "Learn more"),
        keywords=payload.keywords if payload.keywords is not None else (meta.keywords_json if meta else []),
        suggested_visual=payload.suggested_visual or (meta.suggested_visual if meta else ""),
    )
    generated = _real_social(source)
    platform = row.platform.lower()
    if platform not in generated:
        raise HTTPException(status_code=502, detail=f"Generator did not return {row.platform} content")
    item = generated[platform]
    _save_social_revision(db, row, user.id)
    row.title = str(item.get("title") or item.get("hook") or source.objective)[:240]
    row.post_text = str(item.get("post") or "")
    row.hashtags = str(item.get("hashtags") or "")
    row.status = "DRAFT"
    row.updated_at = _now()
    if not meta:
        meta = SocialGenerationMetadata(social_content_id=row.id, tenant_id=tenant_id)
        db.add(meta)
    meta.provider = "regenerated"
    meta.objective = source.objective
    meta.audience = source.audience
    meta.tone = source.tone
    meta.hook = str(item.get("hook") or "")
    meta.call_to_action = str(item.get("cta") or source.call_to_action)
    meta.keywords_json = [str(x) for x in item.get("keywords", source.keywords)]
    meta.suggested_visual = str(item.get("suggested_visual") or source.suggested_visual)
    meta.metadata_json = {"platform": platform, "regenerated": True}
    audit(db, user, "social.content.regenerated", tenant_id=tenant_id, entity_type="social_content", entity_id=row.id, data={"platform": platform})
    db.commit()
    return {"item": _row(row), "generation": _row(meta)}
