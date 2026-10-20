from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.inspection import inspect


def model_dict(obj: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    exclude = exclude or set()
    data: dict[str, Any] = {}
    for column in inspect(obj).mapper.column_attrs:
        key = column.key
        if key in exclude:
            continue
        value = getattr(obj, key)
        if isinstance(value, (datetime, date)):
            data[key] = value.isoformat()
        else:
            data[key] = value
    return data


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")[:120]


def dollars(cents: int | float) -> float:
    return round(float(cents) / 100, 2)


def allocation(revenue_cents: int, direct_cost_cents: int, split_basis: str,
               rmr_share_pct: float, step2_share_pct: float) -> tuple[int, int, int]:
    distributable = max(revenue_cents - direct_cost_cents, 0) if split_basis == "net" else max(revenue_cents, 0)
    rmr = round(distributable * rmr_share_pct / 100)
    step2 = round(distributable * step2_share_pct / 100)
    return distributable, rmr, step2


def normalize_datetime_utc(value: datetime | None) -> datetime | None:
    """Treat naive persisted/API datetimes as UTC and normalize aware values to UTC."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def datetime_iso_utc(value: datetime | None) -> str | None:
    normalized = normalize_datetime_utc(value)
    return normalized.isoformat() if normalized else None
