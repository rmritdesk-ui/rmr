from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Lead, Tenant, User, WebsitePage, WebsiteSection, WebsiteSite
from ..unified_models import WebsiteBlogPost, WebsiteResource, WebsiteTeamProfile
from ..permissions import require_client_website_write, require_tenant_access
from ..schemas import PublicLeadCreate, WebsitePageCreate, WebsitePageUpdate, WebsiteSectionCreate, WebsiteSectionUpdate, WebsiteUpdate
from ..security import current_user, require_request_origin
from ..services import audit
from ..utils import model_dict

router = APIRouter(tags=["website"])


@router.get("/api/tenants/{tenant_id}/website")
def get_website(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    site = db.scalar(select(WebsiteSite).where(WebsiteSite.tenant_id == tenant_id))
    if not site:
        raise HTTPException(status_code=404, detail="Website record not found")
    pages = list(db.scalars(select(WebsitePage).where(WebsitePage.site_id == site.id).order_by(WebsitePage.nav_order)))
    sections = list(db.scalars(select(WebsiteSection).where(
        WebsiteSection.page_id.in_([page.id for page in pages]) if pages else False
    ).order_by(WebsiteSection.page_id, WebsiteSection.position))) if pages else []
    return {
        "site": model_dict(site),
        "pages": [model_dict(page) for page in pages],
        "sections": [model_dict(section) for section in sections],
        "preview_url": f"/sites/{site.slug}?preview=1",
        "public_url": f"/sites/{site.slug}",
    }


@router.patch("/api/tenants/{tenant_id}/website")
def update_website(tenant_id: str, payload: WebsiteUpdate, request: Request,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_client_website_write(user, tenant_id)
    site = db.scalar(select(WebsiteSite).where(WebsiteSite.tenant_id == tenant_id))
    if not site:
        raise HTTPException(status_code=404, detail="Website record not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(site, field, value)
    audit(db, user, "website.settings.updated", tenant_id=tenant_id, entity_type="website_site", entity_id=site.id,
          data=payload.model_dump(exclude_none=True))
    db.commit()
    return {"site": model_dict(site)}


@router.post("/api/tenants/{tenant_id}/website/pages")
def create_page(tenant_id: str, payload: WebsitePageCreate, request: Request,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_client_website_write(user, tenant_id)
    site = db.scalar(select(WebsiteSite).where(WebsiteSite.tenant_id == tenant_id))
    if not site:
        raise HTTPException(status_code=404, detail="Website record not found")
    existing = db.scalar(select(WebsitePage).where(WebsitePage.site_id == site.id, WebsitePage.slug == payload.slug))
    if existing:
        raise HTTPException(status_code=409, detail="A page with this URL already exists")
    max_order = db.scalar(select(func.coalesce(func.max(WebsitePage.nav_order), 0)).where(WebsitePage.site_id == site.id)) or 0
    page = WebsitePage(site_id=site.id, nav_order=int(max_order) + 1, **payload.model_dump())
    db.add(page)
    db.flush()
    db.add(WebsiteSection(
        page_id=page.id,
        section_type="hero",
        position=1,
        settings_json={
            "eyebrow": page.title.upper(),
            "headline": page.title,
            "supporting_text": "Add the page message here.",
            "primary_button": "Contact Us",
            "layout": "centered",
            "background": "brand",
        },
    ))
    audit(db, user, "website.page.created", tenant_id=tenant_id, entity_type="website_page", entity_id=page.id,
          data={"slug": page.slug})
    db.commit()
    return {"page": model_dict(page)}


@router.patch("/api/website/pages/{page_id}")
def update_page(page_id: str, payload: WebsitePageUpdate, request: Request,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    page = db.get(WebsitePage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    site = db.get(WebsiteSite, page.site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Website record not found")
    require_client_website_write(user, site.tenant_id)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(page, field, value)
    audit(db, user, "website.page.updated", tenant_id=site.tenant_id, entity_type="website_page", entity_id=page.id,
          data=payload.model_dump(exclude_none=True))
    db.commit()
    return {"page": model_dict(page)}


@router.post("/api/tenants/{tenant_id}/website/sections")
def create_section(tenant_id: str, payload: WebsiteSectionCreate, request: Request,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_client_website_write(user, tenant_id)
    page = db.get(WebsitePage, payload.page_id)
    site = db.get(WebsiteSite, page.site_id) if page else None
    if not page or not site or site.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail="Invalid website page")
    section = WebsiteSection(
        page_id=payload.page_id,
        section_type=payload.section_type,
        position=payload.position,
        settings_json=payload.settings,
        visible=True,
    )
    db.add(section)
    db.flush()
    audit(db, user, "website.section.created", tenant_id=tenant_id, entity_type="website_section", entity_id=section.id,
          data={"section_type": section.section_type})
    db.commit()
    return {"section": model_dict(section)}


@router.patch("/api/website/sections/{section_id}")
def update_section(section_id: str, payload: WebsiteSectionUpdate, request: Request,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    section = db.get(WebsiteSection, section_id)
    page = db.get(WebsitePage, section.page_id) if section else None
    site = db.get(WebsiteSite, page.site_id) if page else None
    if not section or not page or not site:
        raise HTTPException(status_code=404, detail="Website section not found")
    require_client_website_write(user, site.tenant_id)
    if payload.position is not None:
        section.position = payload.position
    if payload.visible is not None:
        section.visible = payload.visible
    if payload.settings is not None:
        section.settings_json = payload.settings
    audit(db, user, "website.section.updated", tenant_id=site.tenant_id, entity_type="website_section", entity_id=section.id,
          data=payload.model_dump(exclude_none=True))
    db.commit()
    return {"section": model_dict(section)}


@router.get("/sites/{site_slug}", response_class=HTMLResponse)
def public_site(site_slug: str, request: Request, page: str = "home", preview: int = 0, db: Session = Depends(get_db)):
    site = db.scalar(select(WebsiteSite).where(WebsiteSite.slug == site_slug))
    if not site:
        raise HTTPException(status_code=404, detail="Website not found")
    if site.mode in {"external", "custom"} and site.external_url and not preview:
        return RedirectResponse(site.external_url, status_code=302)
    page_row = db.scalar(select(WebsitePage).where(WebsitePage.site_id == site.id, WebsitePage.slug == page))
    if not page_row:
        page_row = db.scalar(select(WebsitePage).where(WebsitePage.site_id == site.id).order_by(WebsitePage.nav_order))
    if not page_row:
        raise HTTPException(status_code=404, detail="Website page not found")
    pages = list(db.scalars(select(WebsitePage).where(
        WebsitePage.site_id == site.id,
        WebsitePage.status == "published" if not preview else WebsitePage.status.in_(["published", "draft"]),
    ).order_by(WebsitePage.nav_order)))
    sections = list(db.scalars(select(WebsiteSection).where(
        WebsiteSection.page_id == page_row.id,
        WebsiteSection.visible.is_(True),
    ).order_by(WebsiteSection.position)))
    from ..templating import templates
    return templates.TemplateResponse(
        request=request,
        name="public_site.html",
        context={
            "site": site,
            "page": page_row,
            "pages": pages,
            "sections": sections,
            "posts": list(db.scalars(select(WebsiteBlogPost).where(
                WebsiteBlogPost.tenant_id == site.tenant_id,
                WebsiteBlogPost.status == "published",
            ).order_by(WebsiteBlogPost.published_at.desc(), WebsiteBlogPost.created_at.desc()).limit(12))),
            "resources": list(db.scalars(select(WebsiteResource).where(
                WebsiteResource.tenant_id == site.tenant_id,
                WebsiteResource.status == "published",
            ).order_by(WebsiteResource.created_at.desc()).limit(12))),
            "team_profiles": list(db.scalars(select(WebsiteTeamProfile).where(
                WebsiteTeamProfile.tenant_id == site.tenant_id,
                WebsiteTeamProfile.visible.is_(True),
            ).order_by(WebsiteTeamProfile.display_order, WebsiteTeamProfile.full_name))),
            "preview": bool(preview),
        },
    )


@router.post("/api/public/sites/{site_slug}/leads")
def public_site_lead(site_slug: str, payload: PublicLeadCreate, request: Request, db: Session = Depends(get_db)):
    require_request_origin(request)
    site = db.scalar(select(WebsiteSite).where(WebsiteSite.slug == site_slug))
    if not site:
        raise HTTPException(status_code=404, detail="Website not found")
    lead = Lead(
        tenant_id=site.tenant_id,
        company_name=payload.company,
        contact_name=payload.name,
        email=payload.email,
        phone=payload.phone,
        source="Website",
        status="New",
        notes=payload.message,
    )
    db.add(lead)
    db.flush()
    audit(db, None, "website.lead.created", tenant_id=site.tenant_id, entity_type="lead", entity_id=lead.id,
          data={"site_slug": site_slug})
    db.commit()
    return {"ok": True, "lead_id": lead.id}
