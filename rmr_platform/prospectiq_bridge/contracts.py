"""v1 wire contracts, NOT FastAPI routes. Unknown fields fail closed."""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text120 = Annotated[str, StringConstraints(min_length=1, max_length=120)]
Opaque = Annotated[str, StringConstraints(min_length=32, max_length=512)]
Pkce = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$")]
Verifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._~-]{43,128}$")]
WebUrl = Annotated[str, StringConstraints(pattern=r"^https?://[^\s/]+(?:/[^\s]*)?$", max_length=2000)]
Positive = Annotated[int, Field(strict=True, ge=1)]
Score = Annotated[int, Field(strict=True, ge=0, le=100)]
Capability = Literal["prospects.read", "profiles.manage_own", "profiles.manage_workspace",
                     "discovery.run", "research.run", "crm.transfer"]
Destination = Literal["prospects", "target_profiles"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Versioned(Contract):
    version: Literal["1"] = "1"


class LaunchRequest(Versioned):
    mapping_id: UUID
    destination: Destination


class LaunchResponse(Versioned):
    transaction_id: UUID
    expires_at: Positive  # UTC Unix seconds


class AuthorizeRequest(Versioned):
    transaction_id: UUID
    callback_id: Text120  # server-registered callback, never a supplied URL
    state: Opaque
    nonce: Opaque
    code_challenge: Pkce
    code_challenge_method: Literal["S256"]


class AuthorizeResponse(Versioned):
    code: Opaque  # transient wire field ONLY; persistence is SHA-256 hash
    state: Opaque


class ExchangeRequest(Versioned):
    integration_instance_id: Text120
    code: Opaque
    code_verifier: Verifier
    callback_id: Text120
    binding_reference: Text120


class ExchangeResponse(Versioned):
    assertion: Opaque
    expires_at: Positive


class GrantContext(Contract):
    grant_id: UUID
    rmr_user_id: UUID
    mapping_id: UUID
    mapping_version: Positive
    piq_client_id: UUID
    integration_instance_id: Text120
    capabilities: list[Capability] = Field(max_length=6)
    absolute_expires_at: Positive


class AssertionClaims(GrantContext):
    iss: Text120
    aud: Text120
    sub: UUID
    jti: UUID
    iat: Positive
    exp: Positive
    nonce: Opaque
    typ: Literal["rmr-piq-federation-v1"]


class GrantCheckRequest(Versioned):
    integration_instance_id: Text120
    grant_id: UUID
    mapping_version: Positive


class GrantCheckResponse(Versioned):
    active: bool = Field(strict=True)
    context: GrantContext | None = None
    reason: Literal["active", "expired", "revoked", "mapping_changed", "access_denied"]


class SessionResponse(Versioned):
    access_token: Opaque
    refresh_token: Opaque
    expires_at: Positive
    bridge_session_id: UUID
    context: GrantContext


class SessionRefreshRequest(Versioned):
    bridge_session_id: UUID
    refresh_token: Opaque


class Evidence(Contract):
    source_url: WebUrl
    claim: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    provider: Text120


class Prospect(Contract):
    company_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    contact_name: Annotated[str, StringConstraints(max_length=200)] | None = None
    email: Annotated[str, StringConstraints(max_length=255)] | None = None
    phone: Annotated[str, StringConstraints(max_length=100)] | None = None
    website: WebUrl | None = None
    address: Annotated[str, StringConstraints(max_length=1000)] | None = None
    piq_score: Score | None = None  # provenance; NOT an RMR qualification decision
    evidence: list[Evidence] = Field(max_length=100)


class CrmLeadRequest(Versioned):
    integration_instance_id: Text120
    mapping_id: UUID
    mapping_version: Positive
    piq_client_id: UUID
    prospect_public_id: UUID
    integration_event_id: UUID
    actor_grant_id: UUID
    prospect: Prospect
    # No tenant_id, actor_user_id, RMR score, destination URL, or overwrite switch.


class CrmLeadResponse(Versioned):
    receipt_id: UUID
    prospect_public_id: UUID
    status: Literal["created", "already_exists", "pending", "failed", "tombstoned"]
    rmr_lead_id: UUID | None = None
    crm_path: Annotated[str, StringConstraints(pattern=r"^/([A-Za-z0-9_-][A-Za-z0-9/_-]*)?$")] | None = None


class HandoffRequest(Versioned):
    prospect_public_id: UUID
    bridge_session_id: UUID  # client/mapping/grant derived server-side


class HandoffResponse(Versioned):
    handoff_id: UUID
    status: Literal["pending", "sending", "retry_wait", "succeeded", "failed"]
    rmr_lead_id: UUID | None = None


class HandoffLookupRequest(Contract):
    external_id: UUID  # path parameter: PIQ public prospect UUID, not an event ID


# Method, future path, request type, response type. Deliberately never registered.
ENDPOINTS = (
    ("POST", "/api/integrations/prospectiq/v1/launch", LaunchRequest, LaunchResponse),
    ("POST", "/api/integrations/prospectiq/v1/authorize", AuthorizeRequest, AuthorizeResponse),
    ("POST", "/api/integrations/prospectiq/v1/exchange", ExchangeRequest, ExchangeResponse),
    ("POST", "/api/integrations/prospectiq/v1/grants/check", GrantCheckRequest, GrantCheckResponse),
    ("POST", "/api/integrations/prospectiq/v1/crm/leads", CrmLeadRequest, CrmLeadResponse),
    ("GET", "/api/integrations/prospectiq/v1/crm/handoffs/{external_id}", HandoffLookupRequest, CrmLeadResponse),
    ("POST", "/api/integrations/rmr/v1/session/exchange", ExchangeRequest, SessionResponse),
    ("POST", "/api/integrations/rmr/v1/session/refresh", SessionRefreshRequest, SessionResponse),
    ("POST", "/api/integrations/rmr/v1/crm/handoffs", HandoffRequest, HandoffResponse),
)
