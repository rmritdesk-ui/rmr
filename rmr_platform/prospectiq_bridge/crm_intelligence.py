"""Read-only customer projection of a tenant-bound CRM receipt; no name matching."""
from urllib.parse import urlsplit
from sqlalchemy import select
from .models import ProspectiqCrmReceipt


def lead_intelligence(db, tenant_id, lead_id):
    receipt = db.scalar(select(ProspectiqCrmReceipt).where(
        ProspectiqCrmReceipt.tenant_id == tenant_id,
        ProspectiqCrmReceipt.lead_id == lead_id,
        ProspectiqCrmReceipt.status == "accepted"))
    if not receipt:
        return None
    provenance = receipt.provenance_json or {}
    latest = provenance.get("latest_intelligence") or {}
    prospect = latest.get("prospect") or (provenance.get("import") or {}).get("prospect") or {}
    snapshot = prospect.get("intelligence_snapshot") or {}
    def text(value):
        return value[:2000] if isinstance(value, str) else ""
    def url(value):
        try:
            parsed = urlsplit(text(value))
            return text(value) if parsed.scheme in ("http", "https") and parsed.netloc and not parsed.username and not parsed.password else None
        except ValueError:
            return None
    def rows(value):
        return value[:24] if isinstance(value, list) else []
    def links(value):
        return [{"url": url(s.get("url")), "title": text(s.get("title"))}
                for s in rows(value)[:5] if isinstance(s, dict) and url(s.get("url"))]
    # Old receipts retain their immutable audit payload but never expose its raw
    # provider/debug branches through the CRM detail response.
    modern = snapshot.get("version") == 2
    return {
        "prospect_public_id": receipt.prospect_public_id,
        "transferred_at": latest.get("received_at") or receipt.created_at.isoformat(),
        "source": {key: prospect.get(key) for key in (
            "company_name", "contact_name", "email", "phone", "address", "industry", "piq_score")},
        "website": url(prospect.get("website")),
        "source_name": text(snapshot.get("source")),
        "source_url": url(snapshot.get("source_url")),
        "source_updated_at": text(snapshot.get("source_updated_at")),
        "status": text(snapshot.get("status")),
        "verified": [text(x) for x in rows(snapshot.get("verified"))] if modern else [],
        "needs_validation": [text(x) for x in rows(snapshot.get("needs_validation"))] if modern else [],
        "why_this_matched": [text(x) for x in rows(snapshot.get("why_this_matched"))] if modern else [],
        "recommended_next_step": text(snapshot.get("recommended_next_step")) if modern else "",
        "profile_matches": [{k: text(m.get(k)) for k in ("target_profile_id", "profile_name", "created_at")}
                            for m in rows(snapshot.get("profile_matches"))[:3] if isinstance(m, dict)],
        "research_results": [{**{k: text(r.get(k)) for k in ("label", "status", "explanation", "caveat")},
                              "sources": links(r.get("sources"))}
                             for r in rows(snapshot.get("research_results")) if isinstance(r, dict)] if modern else [],
        "research_evidence": [{**{k: text(r.get(k)) for k in ("claim", "explanation", "created_at")},
                               "sources": links(r.get("sources"))}
                              for r in rows(snapshot.get("research_evidence")) if isinstance(r, dict)] if modern else [],
        "research_runs": [{k: text(r.get(k)) for k in ("id", "status", "lead_status", "completed_at")}
                          for r in rows(snapshot.get("research_runs"))[:3] if isinstance(r, dict)] if modern else [],
        "note": text(snapshot.get("scope_note")) if modern else "Legacy transfer: refresh PIQ intelligence from ProspectIQ to include current research.",
        "verification": "Imported PIQ findings; not independently verified by RMR.",
    }
