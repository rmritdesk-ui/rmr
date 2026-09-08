from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, select

from . import __version__
from . import cb1_models
from .config import settings
from .db import db_session
from .models import (Activity, Campaign, ForecastMonth, Lead, Notification, Opportunity, PasswordResetToken, PiqOpportunity, SolutionRequest, Tenant, TenantService, User, WebsiteSite)
from .unified_models import AppointmentRequest, ManagedTenantSession, PiqEvidence, PiqImportBatch, SeoWorkItem, WebsiteBlogPost, WebsiteMedia, WebsiteResource, WebsiteTeamProfile
from .client_admin_models import (CampaignExportPackage, ClientTrainingAssignment, ClientTrainingResource, EmailConnectionEvent, ForecastImportBatch, SocialGenerationMetadata, SolutionRequestPreference)
from .cumulative_product_models import ClientServiceCommercialTerm, CommercialTermHistory, MessageDeliveryContext, SocialContentRevision
from .tenant_theme_models import TenantTheme

EXPECTED_RELEASE = "5.4.1.2-interaction-regression-correction-po1"
REQUEST_HEADERS = {"X-RMR-Request": "1"}


class QCFailure(RuntimeError):
    pass


class ProductOwnerQC:
    def __init__(self, base_url: str, output: Path):
        self.base_url = base_url.rstrip("/")
        self.output = output
        self.run_id = f"PO-QC-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
        self.started_at = datetime.now(timezone.utc)
        self.checks: list[dict[str, Any]] = []
        self.cleanup: dict[str, list[str]] = {
            "activities": [], "campaigns": [], "leads": [], "opportunities": [],
            "piq": [], "piq_batches": [], "blog_posts": [], "website_media": [],
            "website_resources": [], "website_team": [], "seo_items": [], "social": [],
            "messages": [], "appointments": [], "managed_sessions": [],
            "campaign_exports": [], "forecast_batches": [], "client_training": [],
            "solution_requests": [], "email_connection_events": [], "password_reset_users": [],
        }
        self.persistence_marker_id: str | None = None
        self.kerry_id = ""
        self.caf_id = ""
        self.theme_test_id = ""
        self.theme_state_path = self.output.parent / "TENANT-THEME-PERSISTENCE-STATE.json"

    def record(self, name: str, passed: bool, detail: Any = "") -> None:
        item = {"name": name, "passed": bool(passed), "detail": detail}
        self.checks.append(item)
        printable = str(detail)
        if len(printable) > 1200:
            printable = printable[:1200] + "... [detail truncated in console; full evidence retained in JSON]"
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" | {printable}" if detail else ""), flush=True)
        if not passed:
            raise QCFailure(f"{name}: {detail}")

    def response(self, name: str, response: httpx.Response, expected: int | tuple[int, ...] = 200) -> Any:
        wanted = (expected,) if isinstance(expected, int) else expected
        detail = f"HTTP {response.status_code}"
        if response.status_code not in wanted:
            try:
                detail += f" | {response.json()}"
            except Exception:
                detail += f" | {response.text[:500]}"
            self.record(name, False, detail)
        self.record(name, True, detail)
        if not response.content:
            return None
        try:
            return response.json()
        except Exception:
            return response.text

    def login(self, email: str, password: str) -> tuple[httpx.Client, dict[str, Any]]:
        client = httpx.Client(base_url=self.base_url, timeout=25, follow_redirects=True)
        data = self.response(
            f"Login works for {email}",
            client.post("/api/auth/login", json={"email": email, "password": password}, headers=REQUEST_HEADERS),
        )
        return client, data["user"]

    def run(self) -> dict[str, Any]:
        try:
            self._foundation()
            self._rmr_owner_path()
            self._tenant_theme_path()
            self._kerry_client_path()
            self._client_admin_correction_path()
            self._cumulative_product_repair_path()
            self._kerry_marketing_path()
            self._caf_path()
            self._public_website_path()
            self._create_persistence_marker()
            status = "passed"
            error = ""
        except Exception as exc:
            status = "failed"
            error = str(exc)
            print(traceback.format_exc(), file=sys.stderr)
        finally:
            self._cleanup(keep_persistence_marker=(status == "passed"))

        result = {
            "status": status,
            "release": EXPECTED_RELEASE,
            "runtime_release": __version__,
            "run_id": self.run_id,
            "started_utc": self.started_at.isoformat(),
            "completed_utc": datetime.now(timezone.utc).isoformat(),
            "passed": sum(1 for check in self.checks if check["passed"]),
            "failed": sum(1 for check in self.checks if not check["passed"]) + (1 if status == "failed" and all(c["passed"] for c in self.checks) else 0),
            "checks": self.checks,
            "persistence_marker_id": self.persistence_marker_id,
            "error": error,
        }
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": status, "passed": result["passed"], "failed": result["failed"], "persistence_marker_id": self.persistence_marker_id}, indent=2))
        return result

    def _foundation(self) -> None:
        with httpx.Client(base_url=self.base_url, timeout=20) as client:
            health = self.response("Health endpoint responds", client.get("/api/health"))
            self.record("Exact packaged release is running", health.get("version") == EXPECTED_RELEASE, health.get("version"))
            self.record("Database health passes", bool(health.get("checks", {}).get("database", {}).get("ok")), health.get("checks", {}).get("database"))
            self.record("Persistent storage health passes", bool(health.get("checks", {}).get("storage", {}).get("ok")), health.get("checks", {}).get("storage"))
            migrations = health.get("checks", {}).get("migrations", {})
            self.record("Tenant Themes additive migration is current", migrations.get("current") == "005.006.100-four-workspace-themes", migrations)
            users = self.response("Product Owner demo credentials are available", client.get("/api/auth/demo-users"))["users"]
            emails = {row["email"] for row in users}
            required = {"dave@rmr.local", "admin@kerry-real-estate.demo", "marketing@kerry-real-estate.demo", "admin@cactus-air-filters.demo"}
            self.record("RMR, Kerry, and CAF demo roles are provisioned", required.issubset(emails), sorted(emails))
            public = client.get("/sites/kerry-real-estate")
            self.record("Kerry is embedded as a managed RMR Global website tenant", public.status_code == 200 and "Kerry Laughlin Real Estate" in public.text and "Request an appointment" in public.text, f"HTTP {public.status_code}")

            source_root = Path(__file__).resolve().parent.parent
            ui_source = (source_root / "public" / "ui.js").read_text(encoding="utf-8", errors="replace")
            unified_source = (source_root / "public" / "pages" / "unified.js").read_text(encoding="utf-8", errors="replace")
            self.record(
                "Actionable dashboard and module tiles retain delegated click-through navigation",
                "[data-route],[data-v53-route]" in ui_source
                and "stopImmediatePropagation" in ui_source
                and "addEventListener('click', routeDelegate, true)" in ui_source,
                "capture-phase delegated route controls",
            )
            self.record(
                "Forecasting and preserved operational modules cannot remain on the Loading state",
                "['forecast','training','organization','solutions'].includes(route)" in unified_source
                and "ctx.renderClientOperational(route, readOnly)" in unified_source,
                "unified workspace operational fallback",
            )

    def _rmr_owner_path(self) -> None:
        client, user = self.login("dave@rmr.local", "RMR-Owner-2026!")
        try:
            self.record("RMR Owner role is correct", user.get("global_role") == "RMR_OWNER", user.get("global_role"))
            tenants = self.response("RMR portfolio tenant list loads", client.get("/api/tenants"))["tenants"]
            by_slug = {row["slug"]: row for row in tenants}
            self.record("Kerry and CAF are real tenants in one application", {"kerry-real-estate", "cactus-air-filters"}.issubset(by_slug), sorted(by_slug))
            self.kerry_id = by_slug["kerry-real-estate"]["id"]
            self.caf_id = by_slug["cactus-air-filters"]["id"]
            theme_test = next((row for slug, row in by_slug.items() if slug not in {"kerry-real-estate", "cactus-air-filters"}), None)
            self.record("A separate tenant is available for non-destructive theme persistence testing", bool(theme_test), sorted(by_slug))
            self.theme_test_id = theme_test["id"]
            self.response("Portfolio Command Center data loads", client.get("/api/portfolio/summary"))
            self.response("Kerry Client 360 loads", client.get(f"/api/tenants/{self.kerry_id}/client360"))
            self.response("Client pricing and active services load", client.get(f"/api/tenants/{self.kerry_id}/services"))
            self.response("Partner economics and revenue-share controls load", client.get("/api/partner-economics"))
            commercial_status = self.response("Preserved commercial operations API remains executable", client.get("/api/commercial/status"))
            self.record("Commercial operations API reports the exact cumulative release", commercial_status.get("version") == EXPECTED_RELEASE, commercial_status)
            legacy_console = client.get("/commercial-legacy")
            self.record("Preserved commercial operations console remains reachable", legacy_console.status_code == 200 and "RMR GLOBAL v5.2" in legacy_console.text, f"HTTP {legacy_console.status_code}")
            access = self.response("Client access management loads", client.get(f"/api/tenants/{self.kerry_id}/access"))
            self.record("Kerry has active client users", len(access.get("users", [])) >= 1, {"users": len(access.get("users", []))})
            readiness = self.response("Kerry commercial readiness evidence loads", client.get(f"/api/cb1/tenants/{self.kerry_id}/readiness"))
            self.record("Kerry Product Owner tenant is fully demo-ready", bool(readiness.get("go_live_complete")) and readiness.get("readiness_pct") == 100, readiness)
            denied = client.post(
                f"/api/tenants/{self.kerry_id}/opportunities",
                json={"account_id": None, "name": f"[{self.run_id}] denied", "stage": "Prospecting", "value_cents": 10000, "probability_pct": 10, "expected_close_date": None, "source": "QC", "next_action": ""},
                headers=REQUEST_HEADERS,
            )
            self.response("RMR cannot silently change client CRM outside a managed session", denied, 403)
            denied_website = client.post(
                f"/api/tenants/{self.kerry_id}/blog-posts",
                json={"title": f"[{self.run_id}] denied website change", "slug": f"{self.run_id.lower()}-denied", "summary": "", "body": "", "status": "draft", "seo_title": "", "seo_description": "", "featured_image_url": ""},
                headers=REQUEST_HEADERS,
            )
            self.response("RMR cannot silently change client website content outside a managed session", denied_website, 403)
            denied_campaign = client.post(
                f"/api/tenants/{self.kerry_id}/campaigns",
                json={"title": f"[{self.run_id}] denied campaign", "channel": "Social", "status": "Draft", "content": "Denied outside managed session"},
                headers=REQUEST_HEADERS,
            )
            self.response("RMR cannot silently change client campaigns outside a managed session", denied_campaign, 403)
            session = self.response(
                "RMR can start an authorized audited client workspace session",
                client.post(f"/api/tenants/{self.kerry_id}/managed-session", json={"reason": f"{self.run_id} automated managed services validation", "minutes": 15}, headers=REQUEST_HEADERS),
            )["session"]
            self.cleanup["managed_sessions"].append(session["id"])
            managed_headers = {**REQUEST_HEADERS, "X-RMR-Managed-Session": session["id"]}
            created = self.response(
                "RMR managed session can perform authorized client CRM work",
                client.post(
                    f"/api/tenants/{self.kerry_id}/opportunities",
                    json={"account_id": None, "name": f"[{self.run_id}] managed opportunity", "stage": "Qualified", "value_cents": 150000, "probability_pct": 50, "expected_close_date": None, "source": "Managed Services QC", "next_action": "Confirm audited attribution"},
                    headers=managed_headers,
                ),
            )["opportunity"]
            self.cleanup["opportunities"].append(created["id"])
            managed_blog = self.response(
                "RMR managed session can perform authorized client website work",
                client.post(
                    f"/api/tenants/{self.kerry_id}/blog-posts",
                    json={"title": f"[{self.run_id}] managed website content", "slug": f"{self.run_id.lower()}-managed", "summary": "Managed services QC", "body": "Audited RMR website work.", "status": "draft", "seo_title": "", "seo_description": "", "featured_image_url": ""},
                    headers=managed_headers,
                ),
            )["post"]
            self.cleanup["blog_posts"].append(managed_blog["id"])
            managed_campaign = self.response(
                "RMR managed session can perform authorized client campaign work",
                client.post(
                    f"/api/tenants/{self.kerry_id}/campaigns",
                    json={"title": f"[{self.run_id}] managed campaign", "channel": "Social", "status": "Draft", "content": "Audited RMR campaign work."},
                    headers=managed_headers,
                ),
            )["campaign"]
            self.cleanup["campaigns"].append(managed_campaign["id"])
            events = self.response("RMR audit history loads", client.get("/api/audit"))["events"]
            self.record("Managed client action is attributed in the audit trail", any(row.get("entity_id") == created["id"] and row.get("event_type") == "crm.opportunity.created" for row in events), created["id"])
            self.response("RMR managed session ends explicitly", client.post(f"/api/managed-session/{session['id']}/end", headers=managed_headers))
        finally:
            client.close()

    def _tenant_theme_path(self) -> None:
        """Exercise v5.4.1 four-preset workspace styles plus all preserved v5.4 branding boundaries.

        One reversible marker is left in a non-Kerry/non-CAF tenant for restart proof.
        """
        style_keys = ["classic-blue", "metallic-silver", "metallic-gold", "champagne-gold"]
        rmr, _ = self.login("dave@rmr.local", "RMR-Owner-2026!")
        try:
            kerry = self.response("RMR Owner can load Kerry workspace style and branding", rmr.get(f"/api/tenants/{self.kerry_id}/theme"))
            caf = self.response("RMR Owner can load CAF workspace style and branding", rmr.get(f"/api/tenants/{self.caf_id}/theme"))
            test_theme = self.response("RMR Owner can load a separate tenant's default workspace style", rmr.get(f"/api/tenants/{self.theme_test_id}/theme"))
            self.record("Tenant theme API reports the exact v5.4.1 release", kerry.get("release") == EXPECTED_RELEASE, kerry.get("release"))
            exposed = [row.get("value") for row in kerry.get("workspace_styles", [])]
            self.record("Exactly four approved workspace styles are exposed in the frozen order", exposed == style_keys, exposed)
            style_rows = {row.get("value"): row for row in kerry.get("workspace_styles", [])}
            self.record("Each workspace style exposes a visual preview and controlled design tokens", all(style_rows.get(key, {}).get("preview_url") and style_rows.get(key, {}).get("tokens") for key in style_keys), style_rows)
            self.record("Kerry begins in RMR Classic Blue for direct Product Owner comparison", bool(kerry["theme"].get("enabled")) and kerry["theme"].get("workspace_style") == "classic-blue", kerry["theme"])
            self.record("CAF begins in Metallic Silver for tenant-isolation comparison", bool(caf["theme"].get("enabled")) and caf["theme"].get("workspace_style") == "metallic-silver", caf["theme"])
            self.record("RMR Owner is authorized to manage workspace styles", bool(kerry.get("can_manage") and caf.get("can_manage") and test_theme.get("can_manage")), {"kerry": kerry.get("can_manage"), "caf": caf.get("can_manage"), "test": test_theme.get("can_manage")})

            snapshot: dict[str, Any] = {"tenant_id": self.theme_test_id, "row": None, "logo_b64": ""}
            with db_session() as db:
                row = db.get(TenantTheme, self.theme_test_id)
                if row:
                    snapshot["row"] = {
                        "enabled": row.enabled,
                        "workspace_style": row.workspace_style,
                        "brand_name": row.brand_name,
                        "primary_color": row.primary_color,
                        "secondary_color": row.secondary_color,
                        "accent_color": row.accent_color,
                        "font_family": row.font_family,
                        "logo_filename": row.logo_filename,
                        "logo_content_type": row.logo_content_type,
                        "logo_original_name": row.logo_original_name,
                        "revision": row.revision,
                        "updated_by_user_id": row.updated_by_user_id,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    }
                    if row.logo_filename:
                        logo_path = settings.data_dir / "tenant-themes" / self.theme_test_id / row.logo_filename
                        if logo_path.is_file():
                            snapshot["logo_b64"] = base64.b64encode(logo_path.read_bytes()).decode("ascii")
            self.theme_state_path.parent.mkdir(parents=True, exist_ok=True)
            self.theme_state_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")

            marker_brand = f"Tenant Theme Restart Marker {self.run_id[-8:]}"
            marker_payload = {
                "enabled": True,
                "workspace_style": "champagne-gold",
                "brand_name": marker_brand,
                "primary_color": "#204D74",
                "secondary_color": "#EFF5FA",
                "accent_color": "#C47A33",
                "font_family": "verdana",
            }
            updated = self.response(
                "RMR Owner can save an isolated tenant workspace style",
                rmr.patch(f"/api/tenants/{self.theme_test_id}/theme", json=marker_payload, headers=REQUEST_HEADERS),
            )
            self.record("Saved workspace style and branding values are returned exactly", all(updated["theme"].get(k) == v for k, v in marker_payload.items()), updated["theme"])

            rendered_signatures = set()
            for style_key in style_keys:
                style = style_rows[style_key]
                defaults = style.get("defaults", {})
                payload = {
                    "enabled": True,
                    "workspace_style": style_key,
                    "brand_name": marker_brand,
                    "primary_color": defaults.get("primary_color", marker_payload["primary_color"]),
                    "secondary_color": defaults.get("secondary_color", marker_payload["secondary_color"]),
                    "accent_color": defaults.get("accent_color", marker_payload["accent_color"]),
                    "font_family": defaults.get("font_family", "system"),
                }
                saved = self.response(
                    f"RMR Owner can select and save {style.get('label', style_key)}",
                    rmr.patch(f"/api/tenants/{self.theme_test_id}/theme", json=payload, headers=REQUEST_HEADERS),
                )
                theme = saved["theme"]
                self.record(f"{style.get('label', style_key)} returns its selected preset", theme.get("workspace_style") == style_key and bool(theme.get("workspace_tokens")), theme)
                rendered_signatures.add(json.dumps(theme.get("workspace_tokens", {}), sort_keys=True))
            self.record("All four workspace styles provide visibly distinct controlled token sets", len(rendered_signatures) == 4, len(rendered_signatures))

            # Restore the Champagne Gold marker so restart validation proves selection persistence.
            persisted = self.response(
                "A reversible Champagne Gold marker is saved for restart validation",
                rmr.patch(f"/api/tenants/{self.theme_test_id}/theme", json=marker_payload, headers=REQUEST_HEADERS),
            )
            unaffected = self.response("Kerry workspace still loads after another tenant is changed", rmr.get(f"/api/tenants/{self.kerry_id}/theme"))
            self.record("Changing another tenant does not alter Kerry's selected style", unaffected["theme"].get("workspace_style") == kerry["theme"].get("workspace_style"), unaffected["theme"])

            png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
            logo = self.response(
                "RMR Owner can upload a tenant-scoped PNG logo",
                rmr.post(f"/api/tenants/{self.theme_test_id}/theme/logo", files={"file": ("tenant-theme-qc.png", png, "image/png")}, headers=REQUEST_HEADERS),
            )
            self.record("Uploaded logo is attached only to the selected tenant", bool(logo["theme"].get("has_logo")), logo["theme"])
            logo_response = rmr.get(f"/api/tenants/{self.theme_test_id}/theme/logo")
            self.record("Authorized logo retrieval is inline and byte-accurate", logo_response.status_code == 200 and logo_response.content == png and logo_response.headers.get("content-type", "").startswith("image/png") and "inline" in logo_response.headers.get("content-disposition", "").lower(), {"status": logo_response.status_code, "type": logo_response.headers.get("content-type"), "disposition": logo_response.headers.get("content-disposition")})
            removed = self.response("RMR Owner can remove the tenant logo", rmr.delete(f"/api/tenants/{self.theme_test_id}/theme/logo", headers=REQUEST_HEADERS))
            self.record("Logo removal preserves the selected workspace style", not removed["theme"].get("has_logo") and removed["theme"].get("workspace_style") == marker_payload["workspace_style"], removed["theme"])
            reset = self.response("RMR Owner can reset one tenant to the RMR Global default", rmr.post(f"/api/tenants/{self.theme_test_id}/theme/reset", headers=REQUEST_HEADERS))
            self.record("Reset disables only the selected tenant and returns Classic Blue defaults", reset["theme"].get("enabled") is False and reset["theme"].get("workspace_style") == "classic-blue" and reset["theme"].get("primary_color") == "#315EFB", reset["theme"])
            caf_after_reset = self.response("CAF theme still loads after another tenant is reset", rmr.get(f"/api/tenants/{self.caf_id}/theme"))
            self.record("Resetting one tenant does not affect CAF Metallic Silver", caf_after_reset["theme"].get("workspace_style") == "metallic-silver", caf_after_reset["theme"])

            persisted = self.response(
                "The restart marker is restored after reset testing",
                rmr.patch(f"/api/tenants/{self.theme_test_id}/theme", json=marker_payload, headers=REQUEST_HEADERS),
            )
            snapshot["marker"] = marker_payload
            snapshot["marker_revision"] = persisted["theme"].get("revision")
            self.theme_state_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        finally:
            rmr.close()

        kerry_admin, _ = self.login("admin@kerry-real-estate.demo", "Client-Admin-2026!")
        try:
            own = self.response("Kerry Client Administrator can load own workspace style", kerry_admin.get(f"/api/tenants/{self.kerry_id}/theme"))
            self.record("Kerry Client Administrator can manage only own tenant workspace style", own.get("can_manage") is True, own.get("can_manage"))
            own_payload = {key: own["theme"][key] for key in ("enabled", "workspace_style", "brand_name", "primary_color", "secondary_color", "accent_color", "font_family")}
            self.response("Kerry Client Administrator can save own workspace style", kerry_admin.patch(f"/api/tenants/{self.kerry_id}/theme", json=own_payload, headers=REQUEST_HEADERS))
            self.response("Kerry Client Administrator cannot view CAF workspace style", kerry_admin.get(f"/api/tenants/{self.caf_id}/theme"), 403)
            self.response("Kerry Client Administrator cannot modify CAF workspace style", kerry_admin.patch(f"/api/tenants/{self.caf_id}/theme", json=own_payload, headers=REQUEST_HEADERS), 403)
        finally:
            kerry_admin.close()

        marketing, _ = self.login("marketing@kerry-real-estate.demo", "Marketing-2026!")
        try:
            visible = self.response("Kerry Marketing User can view own tenant presentation", marketing.get(f"/api/tenants/{self.kerry_id}/theme"))
            self.record("Marketing User is not granted workspace-style administration", visible.get("can_manage") is False, visible.get("can_manage"))
            denied_payload = {key: visible["theme"][key] for key in ("enabled", "workspace_style", "brand_name", "primary_color", "secondary_color", "accent_color", "font_family")}
            self.response("Marketing User cannot change tenant workspace style", marketing.patch(f"/api/tenants/{self.kerry_id}/theme", json=denied_payload, headers=REQUEST_HEADERS), 403)
        finally:
            marketing.close()

    def _kerry_client_path(self) -> None:
        client, user = self.login("admin@kerry-real-estate.demo", "Client-Admin-2026!")
        try:
            self.record("Kerry Client Administrator is tenant-scoped", user.get("tenant_id") == self.kerry_id and user.get("tenant_role") == "CLIENT_ADMIN", user)
            modules = self.response("Kerry module entitlement service loads", client.get(f"/api/tenants/{self.kerry_id}/modules"))
            enabled = {row["key"] for row in modules["modules"] if row.get("enabled")}
            expected = {"home", "website", "crm", "piq", "campaigns", "email", "forecast", "reports", "training", "organization"}
            self.record("All cumulative Kerry customer modules are enabled", expected.issubset(enabled), sorted(enabled))
            self.response("Unified customer dashboard loads", client.get(f"/api/tenants/{self.kerry_id}/workspace"))
            site = self.response("Website Studio loads", client.get(f"/api/tenants/{self.kerry_id}/website"))
            self.record("Kerry uses the embedded managed website mode", site["site"]["mode"] == "managed", site["site"])
            self.response("Website CMS, media, blog, resources, team, SEO and appointments load", client.get(f"/api/tenants/{self.kerry_id}/website-content"))

            media = self.response(
                "Website media library creates a tenant-owned asset",
                client.post(
                    f"/api/tenants/{self.kerry_id}/website-media",
                    json={"title": f"[{self.run_id}] Listing Image", "media_type": "image", "url": "https://example.com/listing.jpg", "alt_text": "Temporary Product Owner QC listing image", "tags": ["listing", "qc"]},
                    headers=REQUEST_HEADERS,
                ),
            )["media"]
            self.cleanup["website_media"].append(media["id"])
            resource = self.response(
                "Website resource library creates a downloadable guide",
                client.post(
                    f"/api/tenants/{self.kerry_id}/website-resources",
                    json={"title": f"[{self.run_id}] Seller Guide", "description": "Temporary Product Owner QC resource.", "resource_type": "guide", "url": "https://example.com/seller-guide.pdf", "lead_capture_required": True, "status": "published"},
                    headers=REQUEST_HEADERS,
                ),
            )["resource"]
            self.cleanup["website_resources"].append(resource["id"])
            team = self.response(
                "Website team profiles create a published tenant profile",
                client.post(
                    f"/api/tenants/{self.kerry_id}/website-team",
                    json={"full_name": f"{self.run_id} Team Member", "title": "Real Estate Advisor", "bio": "Temporary Product Owner QC profile.", "email": "team@example.com", "phone": "602-555-0100", "photo_url": "", "display_order": 99, "visible": True},
                    headers=REQUEST_HEADERS,
                ),
            )["profile"]
            self.cleanup["website_team"].append(team["id"])
            seo = self.response(
                "SEO workspace creates and tracks an optimization item",
                client.post(
                    f"/api/tenants/{self.kerry_id}/seo-items",
                    json={"page_id": None, "item_type": "content", "title": f"[{self.run_id}] Improve seller page", "status": "open", "priority": "high", "recommendation": "Add a clear local-market seller call to action.", "evidence": {"source": "Product Owner QC"}},
                    headers=REQUEST_HEADERS,
                ),
            )["item"]
            self.cleanup["seo_items"].append(seo["id"])

            blog = self.response(
                "Kerry Client Administrator can publish website content",
                client.post(
                    f"/api/tenants/{self.kerry_id}/blog-posts",
                    json={"title": f"[{self.run_id}] Website QC", "slug": self.run_id.lower(), "summary": "Temporary packaged functional QC content.", "body": "This record proves Website Studio publishing works.", "status": "published", "seo_title": "Packaged Website QC", "seo_description": "Temporary functional QC content", "featured_image_url": ""},
                    headers=REQUEST_HEADERS,
                ),
            )["post"]
            self.cleanup["blog_posts"].append(blog["id"])

            opportunity = self.response(
                "Kerry can create a CRM opportunity",
                client.post(
                    f"/api/tenants/{self.kerry_id}/opportunities",
                    json={"account_id": None, "name": f"[{self.run_id}] Client opportunity", "stage": "Qualified", "value_cents": 2500000, "probability_pct": 60, "expected_close_date": None, "source": "Product Owner QC", "next_action": "Demonstrate the all-inclusive product"},
                    headers=REQUEST_HEADERS,
                ),
            )["opportunity"]
            self.cleanup["opportunities"].append(opportunity["id"])

            won_candidate = self.response(
                "Kerry can create an opportunity for the Mark Won shortcut",
                client.post(
                    f"/api/tenants/{self.kerry_id}/opportunities",
                    json={"account_id": None, "name": f"[{self.run_id}] Quick Close Won", "stage": "Proposal", "value_cents": 325000, "probability_pct": 75, "expected_close_date": None, "source": "Product Owner QC", "next_action": "Confirm final win"},
                    headers=REQUEST_HEADERS,
                ),
            )["opportunity"]
            self.cleanup["opportunities"].append(won_candidate["id"])
            won_result = self.response(
                "Mark Won uses the existing opportunity and updates persisted revenue",
                client.post(
                    f"/api/v531/opportunities/{won_candidate['id']}/quick-close",
                    json={"stage": "Closed Won", "close_date": datetime.now(timezone.utc).date().isoformat(), "final_value_cents": 350000, "note": "v5.3.1 Product Owner quick-close validation", "loss_reason": ""},
                    headers=REQUEST_HEADERS,
                ),
            )
            self.cleanup["activities"].append(won_result["activity"]["id"])
            self.record("Mark Won preserves the Opportunity record and recalculates win metrics", won_result["opportunity"]["id"] == won_candidate["id"] and won_result["opportunity"]["stage"] == "Closed Won" and won_result["opportunity"]["probability_pct"] == 100 and won_result["summary"]["won_revenue_cents"] >= 350000, won_result)

            lost_candidate = self.response(
                "Kerry can create an opportunity for the Mark Lost shortcut",
                client.post(
                    f"/api/tenants/{self.kerry_id}/opportunities",
                    json={"account_id": None, "name": f"[{self.run_id}] Quick Close Lost", "stage": "Qualified", "value_cents": 175000, "probability_pct": 45, "expected_close_date": None, "source": "Product Owner QC", "next_action": "Confirm loss reason"},
                    headers=REQUEST_HEADERS,
                ),
            )["opportunity"]
            self.cleanup["opportunities"].append(lost_candidate["id"])
            lost_result = self.response(
                "Mark Lost requires and records a loss reason without increasing won revenue",
                client.post(
                    f"/api/v531/opportunities/{lost_candidate['id']}/quick-close",
                    json={"stage": "Closed Lost", "close_date": datetime.now(timezone.utc).date().isoformat(), "final_value_cents": 175000, "note": "v5.3.1 Product Owner quick-close validation", "loss_reason": "Timing"},
                    headers=REQUEST_HEADERS,
                ),
            )
            self.cleanup["activities"].append(lost_result["activity"]["id"])
            self.record("Mark Lost preserves the Opportunity record and records the outcome", lost_result["opportunity"]["id"] == lost_candidate["id"] and lost_result["opportunity"]["stage"] == "Closed Lost" and lost_result["opportunity"]["probability_pct"] == 0 and lost_result["opportunity"]["loss_reason"] == "Timing", lost_result)

            self.response("CRM pipeline and records reload", client.get(f"/api/tenants/{self.kerry_id}/opportunities"))
            self.response("CRM search works across records", client.get(f"/api/tenants/{self.kerry_id}/crm/search", params={"q": self.run_id}))
            self.response("CRM duplicate analysis loads", client.get(f"/api/tenants/{self.kerry_id}/crm/duplicates"))

            self.response("ProspectIQ target profile loads", client.get(f"/api/tenants/{self.kerry_id}/piq/target-profile"))
            preview = self.response(
                "ProspectIQ list import preview validates client rows",
                client.post(
                    f"/api/tenants/{self.kerry_id}/piq/import-preview",
                    json={"filename": f"{self.run_id}.csv", "rows": [{"company_name": f"{self.run_id} Prospect", "signal": "Relocation partnership expansion", "score": 88, "estimated_value_cents": 7500000}]},
                    headers=REQUEST_HEADERS,
                ),
            )
            self.cleanup["piq_batches"].append(preview["batch"]["id"])
            imported = self.response(
                "ProspectIQ imports an approved prospect list",
                client.post(f"/api/tenants/{self.kerry_id}/piq/import", json={"filename": f"{self.run_id}.csv", "rows": [], "batch_id": preview["batch"]["id"]}, headers=REQUEST_HEADERS),
            )
            self.record("ProspectIQ import created exactly one record", imported.get("count") == 1, imported)
            piq_id = imported["created"][0]["id"]
            self.cleanup["piq"].append(piq_id)
            profile = self.response("ProspectIQ evidence profile loads", client.get(f"/api/piq/{piq_id}/profile"))
            self.record("ProspectIQ profile includes source evidence", len(profile.get("evidence", [])) >= 1, len(profile.get("evidence", [])))
            researched = self.response("ProspectIQ Adaptive Research executes", client.post(f"/api/piq/{piq_id}/adaptive-research", json={}, headers=REQUEST_HEADERS))
            self.record("Adaptive Research adds evidence and recalculates score", len(researched.get("facts", [])) >= 2 and researched["opportunity"].get("evidence_count", 0) >= 4 and researched["opportunity"]["score"] >= 88, researched["opportunity"])
            moved = self.response("Qualified ProspectIQ record moves into CRM", client.post(f"/api/piq/{piq_id}/move-to-crm", json={}, headers=REQUEST_HEADERS))
            if moved.get("lead"):
                self.cleanup["leads"].append(moved["lead"]["id"])

            campaign = self.response(
                "Kerry can create a campaign",
                client.post(f"/api/tenants/{self.kerry_id}/campaigns", json={"title": f"[{self.run_id}] Campaign", "channel": "Multi-channel", "status": "Approved", "content": "Product Owner campaign validation"}, headers=REQUEST_HEADERS),
            )["campaign"]
            self.cleanup["campaigns"].append(campaign["id"])
            social = self.response(
                "Campaigns & Social generates Facebook, Instagram, LinkedIn and X drafts",
                client.post(f"/api/tenants/{self.kerry_id}/marketing/generate-social", json={"title": f"[{self.run_id}] Social", "message": "Clear real estate guidance starts with the client goal.", "call_to_action": "Talk with Kerry", "hashtags": ["RealEstate", "Arizona"]}, headers=REQUEST_HEADERS),
            )["items"]
            self.cleanup["social"].extend(row["id"] for row in social)
            self.record("Four platform-specific social drafts were created", {row["platform"] for row in social} == {"FACEBOOK", "INSTAGRAM", "LINKEDIN", "X"}, [row["platform"] for row in social])
            self.response("Manual social publication can be recorded", client.post(f"/api/social-content/{social[0]['id']}/published", json={"published_url": "https://example.com/product-owner-qc"}, headers=REQUEST_HEADERS))

            draft = self.response(
                "Supported-fact outreach draft generation works",
                client.post(f"/api/tenants/{self.kerry_id}/marketing/generate-email", json={"recipient_name": "Jordan Partner", "recipient_email": "jordan@example.com", "facts": ["Kerry serves Arizona", "Kerry serves Colorado"], "call_to_action": "Would a brief conversation be worthwhile?"}, headers=REQUEST_HEADERS),
            )["draft"]
            self.record("Generated outreach contains a subject and body", bool(draft.get("subject") and draft.get("body")), draft)
            email = self.response(
                "CRM email sends in safe demo mode and records an activity",
                client.post(f"/api/tenants/{self.kerry_id}/crm/email", json={"recipient_email": "jordan@example.com", "recipient_name": "Jordan Partner", "subject": f"[{self.run_id}] Follow-up", "body": "This is an isolated Product Owner functional QC message.", "opportunity_id": opportunity["id"], "supported_facts": ["Kerry serves Arizona"], "send_now": True}, headers=REQUEST_HEADERS),
            )
            self.cleanup["messages"].append(email["message"]["id"])
            self.cleanup["activities"].append(email["activity"]["id"])
            self.response("Email & Activities unified timeline loads", client.get(f"/api/tenants/{self.kerry_id}/timeline"))
            report = self.response("Cross-channel growth and management reporting loads", client.get(f"/api/tenants/{self.kerry_id}/growth-report"))
            self.record("Reporting includes website, PIQ, CRM, social and email funnel measures", all(key in report.get("funnel", {}) for key in ("website_leads", "piq_records", "piq_to_crm", "open_opportunities", "social_drafts", "emails")), report.get("funnel"))
            self.response("Forecasting loads", client.get(f"/api/tenants/{self.kerry_id}/forecast"))
            self.response("Trailing-twelve-month reporting loads", client.get(f"/api/tenants/{self.kerry_id}/reports/ttm"))
            training = self.response("Role-based training library loads", client.get("/api/training"))
            self.record("Training library includes resources", len(training.get("resources", [])) >= 1, len(training.get("resources", [])))
            organization = self.response("Client team and role management loads", client.get(f"/api/tenants/{self.kerry_id}/sales-organization"))
            self.record("Kerry team includes active users", len(organization.get("people", [])) >= 2, len(organization.get("people", [])))
            self.response("Solutions and module expansion center loads", client.get(f"/api/tenants/{self.kerry_id}/solutions"))
            denied = client.get(f"/api/tenants/{self.caf_id}/workspace")
            self.response("Kerry cannot access CAF tenant data", denied, 403)
        finally:
            client.close()

    def _client_admin_correction_path(self) -> None:
        """Exercise business outcomes added by the frozen Client Administrator correction scope."""
        client, user = self.login("admin@kerry-real-estate.demo", "Client-Admin-2026!")
        original_site: dict[str, Any] | None = None
        try:
            environment = self.response(
                "Client Administrator correction environment reports the cumulative release",
                client.get(f"/api/v521/tenants/{self.kerry_id}/environment"),
            )
            self.record(
                "Bulk email delivery is deliberately excluded while campaign exports are supported",
                environment.get("bulk_email_delivery") is False and "mailchimp" in environment.get("campaign_export_formats", []),
                environment,
            )

            original_site = self.response(
                "External/custom website strategy loads",
                client.get(f"/api/v521/tenants/{self.kerry_id}/website-connection"),
            )
            changed_site = self.response(
                "Client Administrator can configure an external/custom website",
                client.patch(
                    f"/api/v521/tenants/{self.kerry_id}/website-connection",
                    json={"mode": "external", "external_url": "https://example.com/kerry-product-owner-qc"},
                    headers=REQUEST_HEADERS,
                ),
            )
            self.record("External website link is stored as a complete HTTPS URL", changed_site.get("mode") == "external" and changed_site.get("external_url", "").startswith("https://"), changed_site)
            website_test = self.response(
                "External website connection can be validated without replacing the managed-site capability",
                client.post(
                    f"/api/v521/tenants/{self.kerry_id}/website-connection/test",
                    json={"mode": "external", "external_url": "https://example.com/kerry-product-owner-qc"},
                    headers=REQUEST_HEADERS,
                ),
            )
            self.record("External website validation reports a usable URL", bool(website_test.get("ok") and website_test.get("url")), website_test)

            social_result = self.response(
                "AI-assisted social generation creates finished platform-specific content from user intent",
                client.post(
                    f"/api/v521/tenants/{self.kerry_id}/social/generate",
                    json={
                        "objective": f"{self.run_id} help Arizona homeowners plan a move to Northern Colorado",
                        "audience": "homeowners considering an Arizona-to-Colorado relocation",
                        "tone": "friendly, knowledgeable, and concise",
                        "call_to_action": "Schedule a relocation planning conversation",
                        "keywords": ["Arizona real estate", "Northern Colorado", "relocation"],
                        "suggested_visual": "A welcoming relocation image connecting Arizona and Colorado",
                    },
                    headers=REQUEST_HEADERS,
                ),
            )
            social_items = social_result.get("items", [])
            self.cleanup["social"].extend(row["id"] for row in social_items)
            self.record("AI social generation returns Facebook, Instagram, LinkedIn and X posts", {row.get("platform") for row in social_items} == {"FACEBOOK", "INSTAGRAM", "LINKEDIN", "X"}, [row.get("platform") for row in social_items])
            self.record("Generated social posts contain finished copy, hashtags, CTA and creative metadata", all(row.get("post_text") and row.get("hashtags") and row.get("generation", {}).get("cta") and row.get("generation", {}).get("suggested_visual") for row in social_items), social_items)
            self.record("Platform-specific posts are not four identical copies", len({row.get("post_text") for row in social_items}) >= 3, [row.get("post_text") for row in social_items])

            export_result = self.response(
                "Client Administrator can create a provider-ready segmented campaign export",
                client.post(
                    f"/api/v521/tenants/{self.kerry_id}/campaign-exports",
                    json={
                        "name": f"{self.run_id} Mailchimp Audience",
                        "provider_format": "mailchimp",
                        "include_leads": True,
                        "include_contacts": True,
                        "include_piq": False,
                        "lead_statuses": [],
                        "sources": [],
                        "subject": "Your relocation planning guide",
                        "preview_text": "Helpful next steps for an Arizona-to-Colorado move",
                        "email_body": "Campaign content prepared by RMR Global for delivery through the client's chosen email platform.",
                        "call_to_action": "Schedule a conversation",
                    },
                    headers=REQUEST_HEADERS,
                ),
            )
            export_package = export_result["package"]
            self.cleanup["campaign_exports"].append(export_package["id"])
            self.record("Campaign export contains recipients and does not send bulk email", export_package.get("record_count", 0) >= 1 and environment.get("bulk_email_delivery") is False, export_package)
            export_download = client.get(export_result["download_url"])
            self.record("Email-platform-ready CSV download works", export_download.status_code == 200 and b"Email Address" in export_download.content, f"HTTP {export_download.status_code}; bytes={len(export_download.content)}")

            email_workspace = self.response(
                "Email Connections, Messages and Activities are actionable data sources",
                client.get(f"/api/v521/tenants/{self.kerry_id}/email-workspace"),
            )
            self.record("Email workspace declares client-owned one-to-one sending and no bulk delivery", email_workspace.get("policy", {}).get("one_to_one_only") is True and email_workspace.get("policy", {}).get("client_owned_sender") is True and email_workspace.get("policy", {}).get("bulk_delivery") is False, email_workspace.get("policy"))
            connections = email_workspace.get("connections", [])
            self.record("Client Administrator has an actionable connected mailbox", bool(connections), connections)
            connection = next((row for row in connections if str(row.get("provider", "")).upper() == "MOCK"), connections[0])
            connection_test = self.response(
                "Connected mailbox Test action executes",
                client.post(
                    f"/api/v521/tenants/{self.kerry_id}/email-connections/{connection['id']}/action",
                    json={"action": "test"},
                    headers=REQUEST_HEADERS,
                ),
            )
            self.record("Connected mailbox action returns operational detail", bool(connection_test.get("detail")), connection_test)
            sent = self.response(
                "One-to-one email sends through the client's configured mailbox and records CRM activity",
                client.post(
                    f"/api/v521/tenants/{self.kerry_id}/one-to-one-email",
                    json={
                        "connection_id": connection["id"],
                        "recipient_email": f"{self.run_id.lower()}@example.com",
                        "recipient_name": "Product Owner Test Prospect",
                        "subject": f"[{self.run_id}] Individual follow-up",
                        "body": "This one-to-one message is tied to the CRM opportunity and sent through the client's configured mailbox.",
                        "opportunity_id": self.cleanup["opportunities"][0] if self.cleanup["opportunities"] else None,
                    },
                    headers=REQUEST_HEADERS,
                ),
            )
            self.cleanup["messages"].append(sent["message"]["id"])
            self.cleanup["activities"].append(sent["activity"]["id"])
            self.record("One-to-one communication is linked to a CRM activity record", sent.get("activity", {}).get("activity_type") == "Email" and bool(sent.get("message", {}).get("provider_message_id")), sent)

            forecast = self.response("Corrected forecasting data loads", client.get(f"/api/tenants/{self.kerry_id}/forecast"))
            self.record("Forecasting has an active version and account rows", bool(forecast.get("version") and forecast.get("accounts") and forecast.get("months")), {"version": forecast.get("version"), "accounts": len(forecast.get("accounts", [])), "months": len(forecast.get("months", []))})
            first_account = forecast["accounts"][0]
            first_month = next(row for row in forecast["months"] if row["account_id"] == first_account["id"])
            amount = f"{int(first_month.get('prior_actual_cents') or 0) / 100:.2f}"
            csv_payload = f"Account,Month,Amount,Target\n{first_account['name']},January,{amount},prior_actual\n".encode("utf-8")
            preview = self.response(
                "CSV forecast upload parses, normalizes, validates and previews rows",
                client.post(
                    f"/api/v521/tenants/{self.kerry_id}/forecast-import/preview",
                    data={"version_id": forecast["version"]["id"]},
                    files={"file": (f"{self.run_id}.csv", csv_payload, "text/csv")},
                    headers=REQUEST_HEADERS,
                ),
            )
            self.cleanup["forecast_batches"].append(preview["batch"]["id"])
            self.record("Forecast preview identifies a valid import row with no exceptions", preview.get("ready_to_import") is True and len(preview.get("rows", [])) == 1 and not preview.get("exceptions"), preview)
            committed = self.response(
                "Validated forecast import commits and reports the changed row",
                client.post(
                    f"/api/v521/tenants/{self.kerry_id}/forecast-import/commit",
                    json={"batch_id": preview["batch"]["id"]},
                    headers=REQUEST_HEADERS,
                ),
            )
            self.record("Forecast import confirmation identifies before and after currency values", len(committed.get("changed_rows", [])) == 1 and "before_cents" in committed["changed_rows"][0] and "after_cents" in committed["changed_rows"][0], committed)
            provenance = self.response("Forecast actuals, won revenue, forecast and goal provenance is explicit", client.get(f"/api/v521/tenants/{self.kerry_id}/forecast-provenance"))
            self.record("Forecast provenance names the source of every major number", all(provenance.get(key) for key in ("actual_source", "closed_won_source", "forecast_source", "annual_goal_source")), provenance)

            action_report = self.response("Growth Reporting returns actionable KPIs and management attention items", client.get(f"/api/v521/tenants/{self.kerry_id}/action-report"))
            self.record("Every Reporting KPI includes an underlying drill-down route", bool(action_report.get("kpis")) and all(row.get("route") for row in action_report.get("kpis", [])), action_report.get("kpis"))
            self.record("Reporting includes What Needs My Attention actions", bool(action_report.get("attention")) and all(row.get("route") and row.get("label") for row in action_report.get("attention", [])), action_report.get("attention"))

            organization = self.response("Client team members load for training assignment and password reset", client.get(f"/api/tenants/{self.kerry_id}/sales-organization"))
            team_people = organization.get("people", [])
            target_user = next((row for row in team_people if row.get("id") != user.get("id")), team_people[0])
            training = self.response(
                "Client Administrator can add company-specific workflow training",
                client.post(
                    f"/api/v521/tenants/{self.kerry_id}/client-training",
                    data={
                        "title": f"{self.run_id} Sales Workflow",
                        "description": "How this company expects its sales team to use RMR Global.",
                        "category": "Sales Workflow",
                        "media_url": "https://example.com/client-training-video",
                        "required": "true",
                        "roles_json": "[]",
                        "user_ids_json": json.dumps([target_user["id"]]),
                        "due_date": (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat(),
                    },
                    headers=REQUEST_HEADERS,
                ),
            )
            training_id = training["resource"]["id"]
            self.cleanup["client_training"].append(training_id)
            library = self.response("Client-managed Training Library reloads", client.get(f"/api/v521/tenants/{self.kerry_id}/client-training"))
            resource = next(row for row in library.get("resources", []) if row.get("id") == training_id)
            self.record("Client training is assigned to the selected employee and tracks completion", len(resource.get("assignments", [])) == 1, resource)
            assignment_id = resource["assignments"][0]["id"]
            completed = self.response(
                "Client training completion can be recorded",
                client.patch(
                    f"/api/v521/client-training/assignments/{assignment_id}",
                    json={"status": "complete", "progress_pct": 100},
                    headers=REQUEST_HEADERS,
                ),
            )
            self.record("Training completion records status, progress and completion time", completed.get("assignment", {}).get("status") == "complete" and completed.get("assignment", {}).get("progress_pct") == 100 and bool(completed.get("assignment", {}).get("completed_at")), completed)

            self.cleanup["password_reset_users"].append(target_user["id"])
            reset = self.response(
                "Client Administrator can send a secure expiring single-use password reset",
                client.post(
                    f"/api/v521/tenants/{self.kerry_id}/users/send-password-reset",
                    json={"user_id": target_user["id"]},
                    headers=REQUEST_HEADERS,
                ),
            )
            self.record("Password reset is delivered through system email or an explicit non-production fallback", reset.get("delivery") in {"sent", "local_recovery"} and bool(reset.get("expires_at")), reset)

            solutions = self.response("Solutions Center loads active, available, and requested service states", client.get(f"/api/tenants/{self.kerry_id}/solutions"))
            available = next((row for row in solutions.get("solutions", []) if row.get("status") == "Available"), None)
            self.record("Solutions Center has an available service for a non-billing request workflow", available is not None, available)
            request_result = self.response(
                "Client can request a solution with explicit date, time and timezone without activation or billing",
                client.post(
                    f"/api/v521/tenants/{self.kerry_id}/solution-requests",
                    json={
                        "service_code": available["service"]["code"],
                        "note": f"{self.run_id} Product Owner contact request",
                        "preferred_contact_method": "Video Meeting",
                        "contact_date": (datetime.now(timezone.utc).date() + timedelta(days=3)).isoformat(),
                        "contact_time": "11:00",
                        "timezone": "America/Phoenix",
                    },
                    headers=REQUEST_HEADERS,
                ),
            )
            request_id = request_result["request"]["id"]
            self.cleanup["solution_requests"].append(request_id)
            self.record("Solution request is not automatically activated or billed and is clearly unconfirmed", request_result.get("request", {}).get("status") == "Requested" and request_result.get("preference", {}).get("confirmed") is False and "no service was activated" in request_result.get("confirmation", ""), request_result)
            duplicate = self.response(
                "Duplicate solution requests are prevented and return the existing request",
                client.post(
                    f"/api/v521/tenants/{self.kerry_id}/solution-requests",
                    json={
                        "service_code": available["service"]["code"],
                        "note": "duplicate attempt",
                        "preferred_contact_method": "Email",
                        "contact_date": (datetime.now(timezone.utc).date() + timedelta(days=4)).isoformat(),
                        "contact_time": "14:00",
                        "timezone": "America/Phoenix",
                    },
                    headers=REQUEST_HEADERS,
                ),
            )
            self.record("Solutions Center reports Request Submitted rather than creating a duplicate", duplicate.get("duplicate_prevented") is True and duplicate.get("request", {}).get("id") == request_id, duplicate)
        finally:
            if original_site:
                try:
                    client.patch(
                        f"/api/v521/tenants/{self.kerry_id}/website-connection",
                        json={"mode": original_site.get("mode", "managed"), "external_url": original_site.get("external_url") or "https://example.com"},
                        headers=REQUEST_HEADERS,
                    )
                except Exception as exc:
                    print(f"Website restoration warning: {exc}", file=sys.stderr)
            client.close()

    def _cumulative_product_repair_path(self) -> None:
        """Prove the v5.2.2 business corrections as real outcomes and restore test data."""
        admin, _ = self.login("dave@rmr.local", "RMR-Owner-2026!")
        original_item: dict[str, Any] | None = None
        tenant_service_id = ""
        try:
            schedule = self.response(
                "RMR Admin per-client, per-service commercial terms load",
                admin.get(f"/api/v522/admin/tenants/{self.kerry_id}/commercial-terms"),
            )
            items = schedule.get("items", [])
            self.record("Kerry has a service schedule that can be commercially managed", bool(items), schedule)
            original_item = next((row for row in items if row.get("tenant_service", {}).get("status") == "active"), items[0])
            subscription = original_item["tenant_service"]
            catalog = original_item["catalog"]
            tenant_service_id = subscription["id"]
            effective = subscription.get("effective_date") or datetime.now(timezone.utc).date().isoformat()
            test_price = max(int(subscription.get("contract_price_cents") or 0) + 12345, 25000)
            payload = {
                "contract_price_cents": test_price,
                "usage_price_cents": int(subscription.get("usage_price_cents") or 0),
                "cadence": subscription.get("cadence") or "monthly",
                "status": "active",
                "quantity": float(subscription.get("quantity") or 1.0),
                "effective_date": effective,
                "rmr_share_pct": 61.0,
                "step2_share_pct": 39.0,
                "split_basis": "gross",
                "direct_cost_cents": 1234,
                "seller_org": "RMR",
                "seller_name": "Product Owner QC",
                "notes": f"{self.run_id} reversible commercial-terms QC",
            }
            updated = self.response(
                "RMR Admin can set client-specific price and service-specific RMR/Step2 economics",
                admin.patch(
                    f"/api/v522/admin/tenants/{self.kerry_id}/commercial-terms/{tenant_service_id}",
                    json=payload,
                    headers=REQUEST_HEADERS,
                ),
            )
            calculation = updated.get("calculation", {})
            self.record(
                "Commercial terms calculate client MRR and reconcile the per-service split",
                calculation.get("monthly_revenue_cents") == test_price
                and calculation.get("rmr_share_pct") == 61.0
                and calculation.get("step2_share_pct") == 39.0
                and calculation.get("reconciles") is True,
                calculation,
            )
            reloaded = self.response(
                "Client-specific commercial terms persist after reload",
                admin.get(f"/api/v522/admin/tenants/{self.kerry_id}/commercial-terms"),
            )
            persisted = next(row for row in reloaded.get("items", []) if row.get("tenant_service", {}).get("id") == tenant_service_id)
            self.record(
                "Reloaded service retains negotiated price, seller, effective date, direct cost and split",
                persisted.get("tenant_service", {}).get("contract_price_cents") == test_price
                and persisted.get("commercial_term", {}).get("seller_name") == "Product Owner QC"
                and persisted.get("commercial_term", {}).get("direct_cost_cents") == 1234
                and persisted.get("commercial_term", {}).get("rmr_share_pct") == 61.0,
                persisted,
            )
            economics = self.response(
                "Partner Economics derives from actual client/service agreements",
                admin.get("/api/v522/admin/partner-economics"),
            )
            economics_item = next(row for row in economics.get("items", []) if row.get("tenant_service", {}).get("id") == tenant_service_id)
            summary = economics.get("summary", {})
            self.record(
                "Partner Economics exposes traceable source terms and mathematically reconciles",
                economics_item.get("terms_source") == "explicit_client_terms"
                and economics_item.get("calculation", {}).get("reconciles") is True
                and summary.get("split_reconciliation_difference_cents") == 0
                and bool(economics.get("data_provenance")),
                {"item": economics_item, "summary": summary},
            )
            trace = self.response(
                "Partner Economics drill-down exposes terms and change history",
                admin.get(f"/api/v522/admin/partner-economics/terms/{tenant_service_id}"),
            )
            self.record(
                "Partner Economics drill-down shows the configured client, service, formula and history",
                trace.get("item", {}).get("tenant", {}).get("id") == self.kerry_id
                and trace.get("item", {}).get("tenant_service", {}).get("id") == tenant_service_id
                and bool(trace.get("history")),
                trace,
            )
        finally:
            admin.close()
            if original_item and tenant_service_id:
                try:
                    with db_session() as db:
                        subscription = db.get(TenantService, tenant_service_id)
                        original_subscription = original_item.get("tenant_service", {})
                        if subscription:
                            for field in ("contract_price_cents", "usage_price_cents", "cadence", "status", "quantity", "effective_date", "notes"):
                                if field in original_subscription:
                                    value = original_subscription.get(field)
                                    if field == "effective_date" and isinstance(value, str) and value:
                                        value = datetime.fromisoformat(value).date()
                                    setattr(subscription, field, value)
                        term = db.scalar(select(ClientServiceCommercialTerm).where(ClientServiceCommercialTerm.tenant_service_id == tenant_service_id))
                        original_term = original_item.get("commercial_term")
                        if original_term is None:
                            if term:
                                db.execute(delete(CommercialTermHistory).where(CommercialTermHistory.commercial_term_id == term.id))
                                db.delete(term)
                        elif term:
                            for field in ("rmr_share_pct", "step2_share_pct", "split_basis", "direct_cost_cents", "seller_org", "seller_name", "notes", "source", "version_number", "updated_by", "created_at", "updated_at"):
                                if field in original_term:
                                    value = original_term.get(field)
                                    if field in {"created_at", "updated_at"} and isinstance(value, str) and value:
                                        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                                    setattr(term, field, value)
                            db.execute(delete(CommercialTermHistory).where(
                                CommercialTermHistory.commercial_term_id == term.id,
                                CommercialTermHistory.version_number > int(original_term.get("version_number") or 0),
                            ))
                except Exception as exc:
                    print(f"Commercial-term restoration warning: {exc}", file=sys.stderr)

        client, _ = self.login("admin@kerry-real-estate.demo", "Client-Admin-2026!")
        try:
            if self.cleanup["social"]:
                social_id = self.cleanup["social"][0]
                detail = self.response(
                    "Generated social content can be opened with its metadata and revision history",
                    client.get(f"/api/v522/tenants/{self.kerry_id}/social/{social_id}"),
                )
                original_text = detail.get("item", {}).get("post_text", "")
                edited = self.response(
                    "Client Administrator can edit and approve generated social content",
                    client.patch(
                        f"/api/v522/tenants/{self.kerry_id}/social/{social_id}",
                        json={
                            "title": f"{self.run_id} approved social",
                            "post_text": original_text + "\n\nProduct Owner approved edit.",
                            "hashtags": detail.get("item", {}).get("hashtags", ""),
                            "status": "APPROVED",
                        },
                        headers=REQUEST_HEADERS,
                    ),
                )
                self.record("Social edit persists an approved status", edited.get("item", {}).get("status") == "APPROVED", edited)
                regenerated = self.response(
                    "Client Administrator can regenerate platform-specific social content",
                    client.post(
                        f"/api/v522/tenants/{self.kerry_id}/social/{social_id}/regenerate",
                        json={"tone": "warm, direct, and locally knowledgeable"},
                        headers=REQUEST_HEADERS,
                    ),
                )
                after = self.response(
                    "Social content revision history is inspectable after edit and regenerate",
                    client.get(f"/api/v522/tenants/{self.kerry_id}/social/{social_id}"),
                )
                self.record(
                    "Social regeneration returns finished copy and preserves at least two prior revisions",
                    bool(regenerated.get("item", {}).get("post_text")) and len(after.get("revisions", [])) >= 2,
                    after,
                )
            if self.cleanup["messages"]:
                message_id = self.cleanup["messages"][-1]
                message = self.response(
                    "A SENT one-to-one email opens to the exact sent message and CRM context",
                    client.get(f"/api/v522/tenants/{self.kerry_id}/messages/{message_id}"),
                )
                self.record(
                    "Sent-message drill-down identifies sender, recipient, subject, body, mailbox, actor, status, time and CRM relationship",
                    bool(message.get("message", {}).get("subject"))
                    and bool(message.get("message", {}).get("body"))
                    and bool(message.get("delivery", {}).get("sender_email"))
                    and bool(message.get("message", {}).get("recipient_email"))
                    and bool(message.get("delivery", {}).get("provider"))
                    and bool(message.get("actor", {}).get("id"))
                    and bool(message.get("delivery", {}).get("delivery_status"))
                    and bool(message.get("message", {}).get("sent_at"))
                    and bool(message.get("relationship", {}).get("id")),
                    message,
                )
        finally:
            client.close()

    def _kerry_marketing_path(self) -> None:
        client, user = self.login("marketing@kerry-real-estate.demo", "Marketing-2026!")
        try:
            self.record("Kerry Marketing User role is correct", user.get("tenant_role") == "MARKETING_USER", user.get("tenant_role"))
            post = self.response(
                "Marketing User can manage website content",
                client.post(f"/api/tenants/{self.kerry_id}/blog-posts", json={"title": f"[{self.run_id}] Marketing content", "slug": f"{self.run_id.lower()}-marketing", "summary": "Marketing role QC", "body": "Marketing role website content", "status": "draft", "seo_title": "", "seo_description": "", "featured_image_url": ""}, headers=REQUEST_HEADERS),
            )["post"]
            self.cleanup["blog_posts"].append(post["id"])
            campaign = self.response(
                "Marketing User can create campaign content",
                client.post(f"/api/tenants/{self.kerry_id}/campaigns", json={"title": f"[{self.run_id}] Marketing campaign", "channel": "Social", "status": "Draft", "content": "Marketing role campaign"}, headers=REQUEST_HEADERS),
            )["campaign"]
            self.cleanup["campaigns"].append(campaign["id"])
            denied = client.post(f"/api/tenants/{self.kerry_id}/opportunities", json={"account_id": None, "name": f"[{self.run_id}] denied marketing CRM", "stage": "Prospecting", "value_cents": 100, "probability_pct": 10, "expected_close_date": None, "source": "QC", "next_action": ""}, headers=REQUEST_HEADERS)
            self.response("Marketing User cannot alter sales-owned CRM records", denied, 403)
            self.response("Marketing User remains isolated from CAF", client.get(f"/api/tenants/{self.caf_id}/modules"), 403)
        finally:
            client.close()

    def _caf_path(self) -> None:
        client, user = self.login("admin@cactus-air-filters.demo", "Client-Admin-2026!")
        try:
            self.record("CAF Client Administrator is tenant-scoped", user.get("tenant_id") == self.caf_id and user.get("tenant_role") == "CLIENT_ADMIN", user)
            modules = self.response("CAF cumulative client modules load", client.get(f"/api/tenants/{self.caf_id}/modules"))
            enabled = {row["key"] for row in modules["modules"] if row.get("enabled")}
            self.record("CAF CRM, PIQ, campaigns, email, reporting and training are enabled", {"crm", "piq", "campaigns", "email", "reports", "training"}.issubset(enabled), sorted(enabled))
            site = self.response("CAF website configuration loads", client.get(f"/api/tenants/{self.caf_id}/website"))
            self.record("External connected website remains a supported tenant mode", site["site"]["mode"] == "external", site["site"])
            opportunity = self.response(
                "CAF can operate its own CRM",
                client.post(f"/api/tenants/{self.caf_id}/opportunities", json={"account_id": None, "name": f"[{self.run_id}] CAF opportunity", "stage": "Prospecting", "value_cents": 50000, "probability_pct": 20, "expected_close_date": None, "source": "Product Owner QC", "next_action": "Confirm external-site tenant workflow"}, headers=REQUEST_HEADERS),
            )["opportunity"]
            self.cleanup["opportunities"].append(opportunity["id"])
            self.response("CAF growth dashboard loads", client.get(f"/api/tenants/{self.caf_id}/workspace"))
        finally:
            client.close()

    def _public_website_path(self) -> None:
        with httpx.Client(base_url=self.base_url, timeout=20) as client:
            lead = self.response(
                "Kerry public website captures a lead into CRM",
                client.post("/api/public/sites/kerry-real-estate/leads", json={"name": f"{self.run_id} Lead", "email": f"{self.run_id.lower()}@example.com", "phone": "602-555-0199", "company": "", "message": "Website lead functional QC"}, headers=REQUEST_HEADERS),
            )
            self.cleanup["leads"].append(lead["lead_id"])
            appointment = self.response(
                "Kerry public website captures an appointment request",
                client.post("/api/public/sites/kerry-real-estate/appointments", json={"name": f"{self.run_id} Visitor", "email": f"visitor-{self.run_id.lower()}@example.com", "phone": "602-555-0188", "preferred_time": "Friday morning", "message": "Appointment functional QC"}, headers=REQUEST_HEADERS),
            )
            self.cleanup["appointments"].append(appointment["request_id"])
            self.cleanup["leads"].append(appointment["lead_id"])

    def _create_persistence_marker(self) -> None:
        # This marker validates database persistence after a controlled container
        # restart. The Client Administrator create-opportunity workflow is already
        # exercised earlier in this same Golden Path; creating the marker directly
        # avoids rate-limit coupling between functional and persistence checks.
        with db_session() as db:
            marker = Opportunity(
                tenant_id=self.kerry_id,
                account_id=None,
                name=f"[{self.run_id}] RESTART PERSISTENCE MARKER",
                stage="Prospecting",
                value_cents=1,
                probability_pct=1,
                expected_close_date=None,
                source="Automated QC",
                next_action="Verify after container restart",
            )
            db.add(marker)
            db.flush()
            self.persistence_marker_id = marker.id
        self.record("Restart-persistence marker is created", bool(self.persistence_marker_id), self.persistence_marker_id)

    def _restore_theme_snapshot(self) -> None:
        if not self.theme_state_path.is_file():
            return
        state = json.loads(self.theme_state_path.read_text(encoding="utf-8"))
        tenant_id = state.get("tenant_id")
        if not tenant_id:
            return
        folder = settings.data_dir / "tenant-themes" / tenant_id
        with db_session() as db:
            row = db.get(TenantTheme, tenant_id)
            original = state.get("row")
            if original is None:
                if row:
                    db.delete(row)
            else:
                if not row:
                    row = TenantTheme(tenant_id=tenant_id)
                    db.add(row)
                for key in ("enabled", "workspace_style", "brand_name", "primary_color", "secondary_color", "accent_color", "font_family", "logo_filename", "logo_content_type", "logo_original_name", "revision", "updated_by_user_id"):
                    setattr(row, key, original.get(key))
                if original.get("created_at"):
                    row.created_at = datetime.fromisoformat(original["created_at"])
                if original.get("updated_at"):
                    row.updated_at = datetime.fromisoformat(original["updated_at"])
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        original = state.get("row") or {}
        logo_b64 = state.get("logo_b64") or ""
        if original.get("logo_filename") and logo_b64:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / original["logo_filename"]).write_bytes(base64.b64decode(logo_b64))
        self.theme_state_path.unlink(missing_ok=True)

    def _cleanup(self, keep_persistence_marker: bool) -> None:
        try:
            with db_session() as db:
                for row_id in self.cleanup["appointments"]:
                    row = db.get(AppointmentRequest, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["campaign_exports"]:
                    row = db.get(CampaignExportPackage, row_id)
                    if row:
                        if row.file_path:
                            try: Path(row.file_path).unlink(missing_ok=True)
                            except Exception: pass
                        db.delete(row)
                for row_id in self.cleanup["forecast_batches"]:
                    row = db.get(ForecastImportBatch, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["client_training"]:
                    db.execute(delete(ClientTrainingAssignment).where(ClientTrainingAssignment.resource_id == row_id))
                    row = db.get(ClientTrainingResource, row_id)
                    if row:
                        if row.file_path:
                            try: Path(row.file_path).unlink(missing_ok=True)
                            except Exception: pass
                        db.delete(row)
                for row_id in self.cleanup["solution_requests"]:
                    db.execute(delete(Notification).where(Notification.entity_type == "solution_request", Notification.entity_id == row_id))
                    preference = db.get(SolutionRequestPreference, row_id)
                    if preference: db.delete(preference)
                    row = db.get(SolutionRequest, row_id)
                    if row: db.delete(row)
                for user_id in self.cleanup["password_reset_users"]:
                    db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id, PasswordResetToken.created_at >= self.started_at))
                for row_id in self.cleanup["email_connection_events"]:
                    row = db.get(EmailConnectionEvent, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["activities"]:
                    row = db.get(Activity, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["messages"]:
                    db.execute(delete(MessageDeliveryContext).where(MessageDeliveryContext.message_id == row_id))
                    db.execute(delete(cb1_models.CB1MessageVersion).where(cb1_models.CB1MessageVersion.message_id == row_id))
                    row = db.get(cb1_models.CB1Message, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["social"]:
                    db.execute(delete(SocialContentRevision).where(SocialContentRevision.social_content_id == row_id))
                    metadata = db.get(SocialGenerationMetadata, row_id)
                    if metadata: db.delete(metadata)
                    row = db.get(cb1_models.CB1SocialContent, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["campaigns"]:
                    row = db.get(Campaign, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["website_media"]:
                    row = db.get(WebsiteMedia, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["website_resources"]:
                    row = db.get(WebsiteResource, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["website_team"]:
                    row = db.get(WebsiteTeamProfile, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["seo_items"]:
                    row = db.get(SeoWorkItem, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["blog_posts"]:
                    row = db.get(WebsiteBlogPost, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["leads"]:
                    row = db.get(Lead, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["piq"]:
                    db.execute(delete(PiqEvidence).where(PiqEvidence.opportunity_id == row_id))
                    row = db.get(PiqOpportunity, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["piq_batches"]:
                    row = db.get(PiqImportBatch, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["opportunities"]:
                    row = db.get(Opportunity, row_id)
                    if row: db.delete(row)
                for row_id in self.cleanup["managed_sessions"]:
                    row = db.get(ManagedTenantSession, row_id)
                    if row and row.status == "active":
                        row.status = "ended"
                        row.ended_at = datetime.now(timezone.utc)
                if not keep_persistence_marker and self.persistence_marker_id:
                    row = db.get(Opportunity, self.persistence_marker_id)
                    if row: db.delete(row)
            if not keep_persistence_marker:
                self._restore_theme_snapshot()
        except Exception as exc:
            print(f"Cleanup warning: {exc}", file=sys.stderr)


def _restore_theme_state_file(state_path: Path) -> None:
    if not state_path.is_file():
        return
    state = json.loads(state_path.read_text(encoding="utf-8"))
    tenant_id = state.get("tenant_id")
    if not tenant_id:
        return
    folder = settings.data_dir / "tenant-themes" / tenant_id
    with db_session() as db:
        row = db.get(TenantTheme, tenant_id)
        original = state.get("row")
        if original is None:
            if row:
                db.delete(row)
        else:
            if not row:
                row = TenantTheme(tenant_id=tenant_id)
                db.add(row)
            for key in ("enabled", "workspace_style", "brand_name", "primary_color", "secondary_color", "accent_color", "font_family", "logo_filename", "logo_content_type", "logo_original_name", "revision", "updated_by_user_id"):
                setattr(row, key, original.get(key))
            if original.get("created_at"):
                row.created_at = datetime.fromisoformat(original["created_at"])
            if original.get("updated_at"):
                row.updated_at = datetime.fromisoformat(original["updated_at"])
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    original = state.get("row") or {}
    logo_b64 = state.get("logo_b64") or ""
    if original.get("logo_filename") and logo_b64:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / original["logo_filename"]).write_bytes(base64.b64decode(logo_b64))
    state_path.unlink(missing_ok=True)


def verify_persistence(base_url: str, marker_id: str, output: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    theme_state_path = output.parent / "TENANT-THEME-PERSISTENCE-STATE.json"
    def record(name: str, passed: bool, detail: Any = "") -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})
        print(f"[{'PASS' if passed else 'FAIL'}] {name} | {detail}")
        if not passed: raise QCFailure(f"{name}: {detail}")
    status = "passed"; error = ""
    try:
        with httpx.Client(base_url=base_url.rstrip('/'), timeout=20) as client:
            health = client.get("/api/health")
            record("Application is healthy after restart", health.status_code == 200 and health.json().get("status") == "healthy", health.status_code)
            record("Exact release remains active after restart", health.json().get("version") == EXPECTED_RELEASE, health.json().get("version"))
            login = client.post("/api/auth/login", json={"email": "admin@kerry-real-estate.demo", "password": "Client-Admin-2026!"}, headers=REQUEST_HEADERS)
            record("Kerry can log in after restart", login.status_code == 200, login.status_code)
            tenant_id = login.json()["user"]["tenant_id"]
            rows = client.get(f"/api/tenants/{tenant_id}/opportunities")
            record("CRM loads after restart", rows.status_code == 200, rows.status_code)
            found = any(row.get("id") == marker_id for row in rows.json().get("opportunities", []))
            record("Database record persisted through container restart", found, marker_id)

        state = json.loads(theme_state_path.read_text(encoding="utf-8")) if theme_state_path.is_file() else {}
        theme_tenant_id = state.get("tenant_id")
        marker = state.get("marker") or {}
        record("Tenant-theme restart marker evidence is available", bool(theme_tenant_id and marker), theme_state_path.name)
        with httpx.Client(base_url=base_url.rstrip('/'), timeout=20) as rmr:
            login = rmr.post("/api/auth/login", json={"email": "dave@rmr.local", "password": "RMR-Owner-2026!"}, headers=REQUEST_HEADERS)
            record("RMR Owner can log in after restart", login.status_code == 200, login.status_code)
            theme_response = rmr.get(f"/api/tenants/{theme_tenant_id}/theme")
            theme = theme_response.json().get("theme", {}) if theme_response.status_code == 200 else {}
            record("Tenant theme loads after restart", theme_response.status_code == 200, theme_response.status_code)
            record("Tenant theme settings persisted through container restart", all(theme.get(key) == value for key, value in marker.items()), theme)
            caf_list = rmr.get("/api/tenants")
            caf_id = next((row["id"] for row in caf_list.json().get("tenants", []) if row.get("slug") == "cactus-air-filters"), "") if caf_list.status_code == 200 else ""
            caf_theme = rmr.get(f"/api/tenants/{caf_id}/theme") if caf_id else None
            record("CAF theme remains isolated after restart", bool(caf_theme and caf_theme.status_code == 200 and caf_theme.json().get("theme", {}).get("workspace_style") == "metallic-silver"), caf_theme.json().get("theme") if caf_theme and caf_theme.status_code == 200 else "missing")
        with db_session() as db:
            row = db.get(Opportunity, marker_id)
            if row: db.delete(row)
    except Exception as exc:
        status = "failed"; error = str(exc); print(traceback.format_exc(), file=sys.stderr)
    finally:
        try:
            _restore_theme_state_file(theme_state_path)
        except Exception as exc:
            status = "failed"
            error = f"{error}; theme restoration failed: {exc}" if error else f"Theme restoration failed: {exc}"
            print(traceback.format_exc(), file=sys.stderr)
    result = {"status": status, "release": EXPECTED_RELEASE, "marker_id": marker_id, "passed": sum(1 for c in checks if c["passed"]), "failed": sum(1 for c in checks if not c["passed"]) + (1 if status == "failed" and all(c["passed"] for c in checks) else 0), "checks": checks, "error": error, "completed_utc": datetime.now(timezone.utc).isoformat()}
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="RMR Global Product Owner functional QC")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default="/data/qc-results/PRODUCT-OWNER-QC-LATEST.json")
    parser.add_argument("--verify-persistence", default="")
    args = parser.parse_args()
    output = Path(args.output)
    if args.verify_persistence:
        result = verify_persistence(args.base_url, args.verify_persistence, output)
    else:
        result = ProductOwnerQC(args.base_url, output).run()
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
