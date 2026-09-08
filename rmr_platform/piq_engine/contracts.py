from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class PiqProviderError(RuntimeError):
    """Safe provider failure suitable for durable run state."""

    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code[:80]
        self.public_message = message[:500]
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class DiscoveryQuery:
    text: str
    industry: str
    location: str
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveryPlan:
    queries: tuple[DiscoveryQuery, ...]
    exclusions: tuple[str, ...] = ()
    ignored_provider_filters: tuple[str, ...] = (
        "employee_min",
        "employee_max",
        "revenue_min_cents",
    )


@dataclass(frozen=True, slots=True)
class NormalizedCandidate:
    external_provider: str
    external_id: str
    company_name: str
    formatted_address: str | None
    city: str | None
    state: str | None
    country: str | None
    latitude: float | None
    longitude: float | None
    categories: tuple[str, ...]
    business_status: str | None
    phone: str | None
    website: str | None
    rating: float | None
    review_count: int | None
    source_url: str | None
    source_metadata: dict[str, Any]
    raw_metadata: dict[str, Any]
    retrieved_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderIssue:
    code: str
    message: str
    retryable: bool
    operation: str


@dataclass(slots=True)
class ProviderSearchResult:
    candidates: list[NormalizedCandidate] = field(default_factory=list)
    issues: list[ProviderIssue] = field(default_factory=list)
    page_count: int = 0
    details_request_count: int = 0


@dataclass(slots=True)
class DiscoveryExecutionResult:
    plan: DiscoveryPlan
    candidates: list[NormalizedCandidate]
    status: str
    diagnostics: dict[str, Any]
