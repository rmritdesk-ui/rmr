from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, ForecastMonth, ForecastVersion, User
from ..permissions import is_global_admin, require_client_operational_write, require_tenant_access
from ..schemas import ForecastMonthUpdate, ForecastVersionCreate
from ..security import current_user, require_request_origin
from ..services import audit
from ..utils import model_dict

router = APIRouter(prefix="/api", tags=["forecast"])


def _require_forecast_account_scope(user: User, account: Account | None) -> None:
    if not account:
        return
    if user.tenant_role == "SALES_REP" and account.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="This account is not assigned to you")
    if user.tenant_role == "SALES_MANAGER" and account.team_name != user.team_name:
        raise HTTPException(status_code=403, detail="This account is outside your team")


@router.get("/tenants/{tenant_id}/forecast")
def get_forecast(tenant_id: str, fiscal_year: int | None = None,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    year = fiscal_year or date.today().year
    version = db.scalar(select(ForecastVersion).where(
        ForecastVersion.tenant_id == tenant_id,
        ForecastVersion.fiscal_year == year,
        ForecastVersion.is_active.is_(True),
    ).order_by(ForecastVersion.created_at.desc()))
    if not version:
        return {"version": None, "accounts": [], "months": [], "read_only": is_global_admin(user)}
    account_query = select(Account).where(Account.tenant_id == tenant_id)
    if user.tenant_role == "SALES_REP":
        account_query = account_query.where(Account.owner_user_id == user.id)
    elif user.tenant_role == "SALES_MANAGER":
        account_query = account_query.where(Account.team_name == user.team_name)
    accounts = list(db.scalars(account_query.order_by(Account.name)))
    account_ids = [account.id for account in accounts]
    months = list(db.scalars(select(ForecastMonth).where(
        ForecastMonth.version_id == version.id,
        ForecastMonth.account_id.in_(account_ids) if account_ids else False,
    ).order_by(ForecastMonth.account_id, ForecastMonth.month))) if account_ids else []
    return {
        "version": model_dict(version),
        "accounts": [model_dict(account) for account in accounts],
        "months": [model_dict(month) for month in months],
        "read_only": is_global_admin(user),
    }


@router.post("/tenants/{tenant_id}/forecast/versions")
def create_forecast_version(tenant_id: str, payload: ForecastVersionCreate, request: Request,
                            user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_client_operational_write(user, tenant_id)
    prior = db.scalar(select(ForecastVersion).where(
        ForecastVersion.tenant_id == tenant_id,
        ForecastVersion.fiscal_year == payload.fiscal_year,
        ForecastVersion.is_active.is_(True),
    ))
    if prior:
        prior.is_active = False
    version = ForecastVersion(
        tenant_id=tenant_id,
        fiscal_year=payload.fiscal_year,
        name=payload.name,
        status="draft",
        annual_goal_cents=payload.annual_goal_cents,
        is_active=True,
        created_by=user.id,
    )
    db.add(version)
    db.flush()
    accounts = list(db.scalars(select(Account).where(Account.tenant_id == tenant_id)))
    for account in accounts:
        for month in range(1, 13):
            prior_row = None
            if prior:
                prior_row = db.scalar(select(ForecastMonth).where(
                    ForecastMonth.version_id == prior.id,
                    ForecastMonth.account_id == account.id,
                    ForecastMonth.month == month,
                ))
            prior_actual = prior_row.actual_cents if prior_row else 0
            db.add(ForecastMonth(
                version_id=version.id,
                account_id=account.id,
                month=month,
                prior_actual_cents=prior_actual,
                forecast_cents=prior_actual,
                actual_cents=0,
                growth_pct=0,
            ))
    audit(db, user, "forecast.version.created", tenant_id=tenant_id, entity_type="forecast_version", entity_id=version.id,
          data={"fiscal_year": payload.fiscal_year, "name": payload.name})
    db.commit()
    return {"version": model_dict(version)}


@router.patch("/forecast/months/{month_id}")
def update_forecast_month(month_id: str, payload: ForecastMonthUpdate, request: Request,
                          user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    month = db.get(ForecastMonth, month_id)
    if not month:
        raise HTTPException(status_code=404, detail="Forecast month not found")
    version = db.get(ForecastVersion, month.version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Forecast version not found")
    require_client_operational_write(user, version.tenant_id)
    account = db.get(Account, month.account_id)
    _require_forecast_account_scope(user, account)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(month, field, value)
    if payload.growth_pct is not None and payload.forecast_cents is None:
        month.forecast_cents = max(0, round(month.prior_actual_cents * (1 + payload.growth_pct / 100)))
    audit(db, user, "forecast.month.updated", tenant_id=version.tenant_id, entity_type="forecast_month", entity_id=month.id,
          data=payload.model_dump(exclude_none=True))
    db.commit()
    return {"month": model_dict(month)}


@router.post("/tenants/{tenant_id}/sales-import")
def import_sales(tenant_id: str, request: Request, payload: dict[str, Any],
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_client_operational_write(user, tenant_id)
    version_id = str(payload.get("version_id", ""))
    version = db.get(ForecastVersion, version_id)
    if not version or version.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail="Invalid forecast version")
    rows = payload.get("rows", [])
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=400, detail="No import rows supplied")
    matched = 0
    exceptions: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        try:
            account_name = str(row.get("account", "")).strip()
            month_number = int(row.get("month"))
            amount_cents = int(round(float(row.get("amount", 0)) * 100))
            account = db.scalar(select(Account).where(
                Account.tenant_id == tenant_id,
                func.lower(Account.name) == account_name.lower(),
            ))
            if not account:
                exceptions.append({"row": index, "account": account_name, "reason": "Account not matched"})
                continue
            try:
                _require_forecast_account_scope(user, account)
            except HTTPException:
                exceptions.append({"row": index, "account": account_name, "reason": "Account outside permitted scope"})
                continue
            forecast_month = db.scalar(select(ForecastMonth).where(
                ForecastMonth.version_id == version.id,
                ForecastMonth.account_id == account.id,
                ForecastMonth.month == month_number,
            ))
            if not forecast_month:
                forecast_month = ForecastMonth(
                    version_id=version.id,
                    account_id=account.id,
                    month=month_number,
                )
                db.add(forecast_month)
            target = str(row.get("target", "prior_actual"))
            if target == "actual":
                forecast_month.actual_cents = amount_cents
            elif target == "forecast":
                forecast_month.forecast_cents = amount_cents
            else:
                forecast_month.prior_actual_cents = amount_cents
            matched += 1
        except (ValueError, TypeError) as exc:
            exceptions.append({"row": index, "reason": f"Invalid row: {exc}"})
    audit(db, user, "sales_data.imported", tenant_id=tenant_id, entity_type="forecast_version", entity_id=version.id,
          data={"matched": matched, "exceptions": len(exceptions)})
    db.commit()
    return {"matched": matched, "exceptions": exceptions}


@router.get("/tenants/{tenant_id}/reports/ttm")
def ttm_report(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    version = db.scalar(select(ForecastVersion).where(
        ForecastVersion.tenant_id == tenant_id,
        ForecastVersion.is_active.is_(True),
    ).order_by(ForecastVersion.created_at.desc()))
    if not version:
        return {"summary": {}, "accounts": []}
    query = select(Account, ForecastMonth).join(ForecastMonth, ForecastMonth.account_id == Account.id).where(
        Account.tenant_id == tenant_id,
        ForecastMonth.version_id == version.id,
    )
    if user.tenant_role == "SALES_REP":
        query = query.where(Account.owner_user_id == user.id)
    elif user.tenant_role == "SALES_MANAGER":
        query = query.where(Account.team_name == user.team_name)
    rows = list(db.execute(query))
    by_account: dict[str, dict[str, Any]] = {}
    for account, month in rows:
        entry = by_account.setdefault(account.id, {
            "account_id": account.id,
            "account_name": account.name,
            "team_name": account.team_name,
            "prior_ttm_cents": 0,
            "current_ttm_cents": 0,
            "forecast_cents": 0,
        })
        entry["prior_ttm_cents"] += month.prior_actual_cents
        entry["current_ttm_cents"] += month.actual_cents or month.forecast_cents
        entry["forecast_cents"] += month.forecast_cents
    accounts = list(by_account.values())
    for entry in accounts:
        prior = entry["prior_ttm_cents"]
        current = entry["current_ttm_cents"]
        entry["change_cents"] = current - prior
        entry["change_pct"] = round((current - prior) / prior * 100, 1) if prior else 0
    accounts.sort(key=lambda row: row["current_ttm_cents"], reverse=True)
    return {
        "summary": {
            "prior_ttm_cents": sum(row["prior_ttm_cents"] for row in accounts),
            "current_ttm_cents": sum(row["current_ttm_cents"] for row in accounts),
            "forecast_cents": sum(row["forecast_cents"] for row in accounts),
            "account_count": len(accounts),
        },
        "accounts": accounts,
    }
