from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    CostAllocationRule,
    CostCategory,
    CostEntry,
    EconomicTransaction,
    ServiceCatalog,
    Tenant,
    TenantService,
    User,
)
from ..permissions import is_global_admin, require_global_admin, require_tenant_access
from ..schemas import CostAllocationRuleCreate, CostEntryCreate, TenantServiceCreate, TenantServiceUpdate
from ..security import current_user, require_request_origin
from ..services import audit, create_monthly_transaction
from ..utils import model_dict

router = APIRouter(prefix="/api", tags=["services"])


def _active_rule(db: Session, category_code: str, on_date: date | None = None) -> CostAllocationRule | None:
    on_date = on_date or date.today()
    return db.scalar(
        select(CostAllocationRule)
        .where(
            CostAllocationRule.category_code == category_code,
            CostAllocationRule.active.is_(True),
            CostAllocationRule.effective_date <= on_date,
            or_(CostAllocationRule.end_date.is_(None), CostAllocationRule.end_date >= on_date),
        )
        .order_by(CostAllocationRule.effective_date.desc())
    )


def _allocated_costs(db: Session, period: str) -> dict[str, object]:
    entries = list(
        db.scalars(
            select(CostEntry).where(CostEntry.period == period).order_by(CostEntry.created_at.desc())
        )
    )
    categories = {row.code: row for row in db.scalars(select(CostCategory))}
    tenant_ids = list(db.scalars(select(Tenant.id).where(Tenant.status.in_(["live", "private", "onboarding"]))))
    transaction_revenue = dict(
        db.execute(
            select(EconomicTransaction.tenant_id, func.sum(EconomicTransaction.revenue_cents))
            .where(EconomicTransaction.period == period)
            .group_by(EconomicTransaction.tenant_id)
        ).all()
    )
    total_revenue = sum(int(value or 0) for value in transaction_revenue.values())

    allocations: list[dict[str, object]] = []
    unallocated_cents = 0
    additional_direct_cents = 0
    allocated_shared_cents = 0
    by_tenant: defaultdict[str, int] = defaultdict(int)

    for entry in entries:
        category = categories.get(entry.category_code)
        rule = _active_rule(db, entry.category_code)
        basis = entry.allocation_basis or (rule.allocation_basis if rule else "pending_policy")
        settlement = entry.partner_settlement_treatment or (
            rule.partner_settlement_treatment if rule else "pending_policy"
        )
        allocation_rows: list[dict[str, object]] = []

        if entry.tenant_id:
            by_tenant[entry.tenant_id] += entry.amount_cents
            additional_direct_cents += entry.amount_cents
            allocation_rows.append({"tenant_id": entry.tenant_id, "amount_cents": entry.amount_cents})
        elif entry.allocation_scope == "portfolio" and basis == "equal_client" and tenant_ids:
            base, remainder = divmod(entry.amount_cents, len(tenant_ids))
            for index, tenant_id in enumerate(tenant_ids):
                amount = base + (1 if index < remainder else 0)
                by_tenant[tenant_id] += amount
                allocated_shared_cents += amount
                allocation_rows.append({"tenant_id": tenant_id, "amount_cents": amount})
        elif entry.allocation_scope == "portfolio" and basis == "revenue_share" and total_revenue > 0:
            revenue_tenant_ids = [tenant_id for tenant_id in tenant_ids if int(transaction_revenue.get(tenant_id, 0) or 0) > 0]
            if revenue_tenant_ids:
                remaining = entry.amount_cents
                for index, tenant_id in enumerate(revenue_tenant_ids):
                    if index == len(revenue_tenant_ids) - 1:
                        amount = remaining
                    else:
                        amount = round(entry.amount_cents * int(transaction_revenue.get(tenant_id, 0) or 0) / total_revenue)
                        remaining -= amount
                    by_tenant[tenant_id] += amount
                    allocated_shared_cents += amount
                    allocation_rows.append({"tenant_id": tenant_id, "amount_cents": amount})
            else:
                unallocated_cents += entry.amount_cents
        else:
            unallocated_cents += entry.amount_cents

        allocations.append(
            {
                "entry": model_dict(entry),
                "category": model_dict(category) if category else None,
                "effective_rule": model_dict(rule) if rule else None,
                "allocation_basis_used": basis,
                "partner_settlement_treatment": settlement,
                "allocations": allocation_rows,
                "policy_pending": not allocation_rows,
            }
        )

    return {
        "entries": allocations,
        "additional_direct_cents": additional_direct_cents,
        "allocated_shared_cents": allocated_shared_cents,
        "unallocated_policy_pending_cents": unallocated_cents,
        "by_tenant": dict(by_tenant),
    }


@router.get("/service-catalog")
def service_catalog(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = list(
        db.scalars(
            select(ServiceCatalog).where(ServiceCatalog.active.is_(True)).order_by(ServiceCatalog.sort_order)
        )
    )
    if is_global_admin(user):
        return {"services": [model_dict(row) for row in rows]}
    return {
        "services": [
            model_dict(row, exclude={"direct_cost_cents", "split_basis", "rmr_share_pct", "step2_share_pct"})
            for row in rows
        ]
    }


@router.get("/tenants/{tenant_id}/services")
def tenant_services(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    rows = list(
        db.execute(
            select(TenantService, ServiceCatalog)
            .join(ServiceCatalog, ServiceCatalog.code == TenantService.service_code)
            .where(TenantService.tenant_id == tenant_id)
            .order_by(ServiceCatalog.sort_order)
        )
    )
    result = []
    for tenant_service, catalog in rows:
        catalog_data = model_dict(catalog)
        if not is_global_admin(user):
            for key in ["direct_cost_cents", "split_basis", "rmr_share_pct", "step2_share_pct"]:
                catalog_data.pop(key, None)
        result.append({"tenant_service": model_dict(tenant_service), "catalog": catalog_data})
    return {"services": result}


@router.post("/tenants/{tenant_id}/services")
def add_tenant_service(
    tenant_id: str,
    payload: TenantServiceCreate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_global_admin(user)
    tenant = db.get(Tenant, tenant_id)
    catalog = db.scalar(
        select(ServiceCatalog).where(
            ServiceCatalog.code == payload.service_code, ServiceCatalog.active.is_(True)
        )
    )
    if not tenant or not catalog:
        raise HTTPException(status_code=404, detail="Client or service not found")
    existing = db.scalar(
        select(TenantService).where(
            TenantService.tenant_id == tenant_id, TenantService.service_code == payload.service_code
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="This service is already on the client schedule")
    service = TenantService(
        tenant_id=tenant_id,
        service_code=payload.service_code,
        contract_price_cents=payload.contract_price_cents,
        usage_price_cents=payload.usage_price_cents,
        cadence=payload.cadence or catalog.cadence,
        status="active",
        effective_date=payload.effective_date or date.today(),
        next_billing_date=date.today() + timedelta(days=30),
        notes=payload.notes,
    )
    db.add(service)
    db.flush()
    audit(
        db,
        user,
        "tenant_service.added",
        tenant_id=tenant_id,
        entity_type="tenant_service",
        entity_id=service.id,
        data={"service_code": service.service_code, "contract_price_cents": service.contract_price_cents},
    )
    db.commit()
    return {"service": model_dict(service)}


@router.patch("/tenant-services/{service_id}")
def update_tenant_service(
    service_id: str,
    payload: TenantServiceUpdate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_global_admin(user)
    service = db.get(TenantService, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Client service not found")
    for field in ["contract_price_cents", "usage_price_cents", "cadence", "status", "notes"]:
        value = getattr(payload, field)
        if value is not None:
            setattr(service, field, value)
    audit(
        db,
        user,
        "tenant_service.updated",
        tenant_id=service.tenant_id,
        entity_type="tenant_service",
        entity_id=service.id,
        data=payload.model_dump(exclude_none=True),
    )
    db.commit()
    return {"service": model_dict(service)}


@router.post("/tenant-services/{service_id}/generate-transaction")
def generate_transaction(
    service_id: str,
    request: Request,
    payload: dict,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_global_admin(user)
    service = db.get(TenantService, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Client service not found")
    quantity = float(payload.get("quantity", 1))
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")
    transaction = create_monthly_transaction(db, service.tenant_id, service, quantity=quantity)
    db.flush()
    audit(
        db,
        user,
        "economic_transaction.created",
        tenant_id=service.tenant_id,
        entity_type="economic_transaction",
        entity_id=transaction.id,
        data={"service_code": service.service_code, "quantity": quantity},
    )
    db.commit()
    return {"transaction": model_dict(transaction)}


@router.get("/cost-categories")
def cost_categories(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_global_admin(user)
    categories = list(db.scalars(select(CostCategory).where(CostCategory.active.is_(True)).order_by(CostCategory.sort_order)))
    return {
        "categories": [
            {
                **model_dict(category),
                "active_rule": model_dict(_active_rule(db, category.code)) if _active_rule(db, category.code) else None,
            }
            for category in categories
        ]
    }


@router.post("/partner-economics/costs")
def add_cost_entry(
    payload: CostEntryCreate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_global_admin(user)
    category = db.get(CostCategory, payload.category_code)
    if not category or not category.active:
        raise HTTPException(status_code=404, detail="Cost category not found")
    if payload.tenant_id and not db.get(Tenant, payload.tenant_id):
        raise HTTPException(status_code=404, detail="Client not found")
    entry = CostEntry(
        **payload.model_dump(),
        created_by_user_id=user.id,
        source="manual",
    )
    db.add(entry)
    db.flush()
    audit(
        db,
        user,
        "partner_economics.cost.created",
        tenant_id=entry.tenant_id,
        entity_type="cost_entry",
        entity_id=entry.id,
        data={
            "category_code": entry.category_code,
            "amount_cents": entry.amount_cents,
            "allocation_scope": entry.allocation_scope,
            "allocation_basis": entry.allocation_basis,
        },
    )
    db.commit()
    return {"cost": model_dict(entry)}


@router.post("/partner-economics/allocation-rules")
def add_allocation_rule(
    payload: CostAllocationRuleCreate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_global_admin(user)
    category = db.get(CostCategory, payload.category_code)
    if not category:
        raise HTTPException(status_code=404, detail="Cost category not found")
    rule = CostAllocationRule(
        category_code=payload.category_code,
        allocation_basis=payload.allocation_basis,
        partner_settlement_treatment=payload.partner_settlement_treatment,
        effective_date=payload.effective_date or date.today(),
        end_date=payload.end_date,
        notes=payload.notes,
        active=True,
    )
    db.add(rule)
    db.flush()
    audit(
        db,
        user,
        "partner_economics.allocation_rule.created",
        entity_type="cost_allocation_rule",
        entity_id=rule.id,
        data=payload.model_dump(mode="json"),
    )
    db.commit()
    return {"rule": model_dict(rule)}


@router.get("/partner-economics")
def partner_economics(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_global_admin(user)
    period = date.today().strftime("%Y-%m")
    totals = db.execute(
        select(
            func.coalesce(func.sum(EconomicTransaction.revenue_cents), 0),
            func.coalesce(func.sum(EconomicTransaction.direct_cost_cents), 0),
            func.coalesce(func.sum(EconomicTransaction.rmr_share_cents), 0),
            func.coalesce(func.sum(EconomicTransaction.step2_share_cents), 0),
            func.count(EconomicTransaction.id),
        ).where(EconomicTransaction.period == period)
    ).one()
    rows = list(
        db.execute(
            select(EconomicTransaction, Tenant, ServiceCatalog)
            .join(Tenant, Tenant.id == EconomicTransaction.tenant_id)
            .join(ServiceCatalog, ServiceCatalog.code == EconomicTransaction.service_code)
            .where(EconomicTransaction.period == period)
            .order_by(EconomicTransaction.created_at.desc())
        )
    )
    by_service = list(
        db.execute(
            select(
                EconomicTransaction.service_code,
                ServiceCatalog.name,
                func.sum(EconomicTransaction.revenue_cents),
                func.sum(EconomicTransaction.direct_cost_cents),
                func.sum(EconomicTransaction.rmr_share_cents),
                func.sum(EconomicTransaction.step2_share_cents),
            )
            .join(ServiceCatalog, ServiceCatalog.code == EconomicTransaction.service_code)
            .where(EconomicTransaction.period == period)
            .group_by(EconomicTransaction.service_code, ServiceCatalog.name)
            .order_by(func.sum(EconomicTransaction.revenue_cents).desc())
        )
    )
    cost_model = _allocated_costs(db, period)
    revenue = int(totals[0])
    transaction_direct = int(totals[1])
    additional_direct = int(cost_model["additional_direct_cents"])
    allocated_shared = int(cost_model["allocated_shared_cents"])
    known_costs = transaction_direct + additional_direct + allocated_shared
    return {
        "period": period,
        "summary": {
            "revenue_cents": revenue,
            "transaction_direct_costs_cents": transaction_direct,
            "additional_direct_costs_cents": additional_direct,
            "allocated_shared_operating_costs_cents": allocated_shared,
            "known_costs_cents": known_costs,
            "unallocated_policy_pending_cents": int(cost_model["unallocated_policy_pending_cents"]),
            "gross_profit_before_shared_costs_cents": revenue - transaction_direct - additional_direct,
            "contribution_after_allocated_costs_cents": revenue - known_costs,
            "rmr_share_cents": int(totals[2]),
            "step2_share_cents": int(totals[3]),
            "transaction_count": int(totals[4]),
        },
        "policy_status": {
            "partner_settlement": "Existing transaction-level split rules remain in effect.",
            "operating_cost_treatment": "Policy pending unless an effective allocation rule is configured.",
            "warning": "Unallocated costs are excluded from partner settlement calculations until RMR approves the accounting policy.",
        },
        "cost_model": cost_model,
        "by_service": [
            {
                "service_code": code,
                "service_name": name,
                "revenue_cents": int(service_revenue or 0),
                "direct_costs_cents": int(cost or 0),
                "rmr_share_cents": int(rmr or 0),
                "step2_share_cents": int(step2 or 0),
            }
            for code, name, service_revenue, cost, rmr, step2 in by_service
        ],
        "transactions": [
            {"transaction": model_dict(tx), "tenant": tenant.name, "service": catalog.name}
            for tx, tenant, catalog in rows
        ],
    }


@router.get("/partner-economics/scenarios")
def economics_scenarios(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_global_admin(user)
    tenants = list(db.scalars(select(Tenant).where(Tenant.status.in_(["live", "private"]))))
    active_count = max(len(tenants), 1)
    current = partner_economics(user=user, db=db)["summary"]
    scenarios = []
    for client_count in [active_count, 25, 50, 100, 250]:
        factor = client_count / active_count
        scenarios.append(
            {
                "clients": client_count,
                "revenue_cents": round(current["revenue_cents"] * factor),
                "known_costs_cents": round(current["known_costs_cents"] * factor),
                "unallocated_policy_pending_cents": round(
                    current["unallocated_policy_pending_cents"] * factor
                ),
                "rmr_share_cents": round(current["rmr_share_cents"] * factor),
                "step2_share_cents": round(current["step2_share_cents"] * factor),
                "method": "Current service mix, contract pricing, usage profile, and approved allocation rules",
            }
        )
    return {"scenarios": scenarios}
