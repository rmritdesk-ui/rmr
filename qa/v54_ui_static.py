#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; checks=[]
def text(p): return (ROOT/p).read_text(encoding="utf-8", errors="replace")
def check(name,ok,detail=""): checks.append({"name":name,"passed":bool(ok),"detail":detail}); print(f"[{'PASS' if ok else 'FAIL'}] {name}")
manager=text("public/pages/theme_manager.js"); theme=text("public/tenant-theme.js"); css=text("public/tenant-themes.css"); index=text("public/index.html"); app=text("public/app.js"); ui=text("public/ui.js")
check("Theme module is linked", "tenant-themes.css" in index and "tenant-theme.js" in app)
check("Preview contains branded navigation and actions", all(x in manager for x in ("Dashboard","CRM","Reporting","Primary action","Secondary action")))
check("Preview identifies selected tenant", "data.tenant_name" in manager and "Tenant Branding" in manager)
check("Logo uploader is bounded", 'accept="image/png,image/jpeg,image/webp"' in manager and "max 2 MB" in manager)
check("Approved fonts are server supplied", "allowed_fonts" in manager and "font_family" in manager)
check("Three controlled colors are editable", all(x in manager for x in ("primary_color","secondary_color","accent_color")))
check("Save, logo removal, and reset are wired", all(x in manager for x in ("Save & Apply","remove-theme-logo","reset-tenant-theme")))
check("Default theme fallback exists", "DEFAULTS" in theme and "RMR Global" in theme)
check("Theme is suppressed in global portfolio context", "!isGlobalAdmin() || state.adminClientWorkspace" in theme)
check("Tenant brand logo is protected API content", "/api/tenants/" in theme and "/theme/logo" in manager)
check("Theme CSS is confined behind tenant-theme-active", css.count(".tenant-theme-active") >= 10)
check("Status/error semantics are not broadly recolored", ".danger" in css and ":not(.danger)" in css)
check("Sidebar preserves RMR platform attribution", "Powered by RMR Global" in theme)
check("No iframe, custom CSS, or script injection UI exists", all(x not in manager.lower() for x in ("<iframe", "css_text", "javascript", "custom code")))
check("Theme rendering escapes user-controlled values", "esc(" in manager and "esc(" in theme)
check("Theme refresh occurs at login, tenant switch, and workspace entry", app.count("await loadTenantTheme()") >= 4, app.count("await loadTenantTheme()"))
check("Responsive theme UI is included", "@media(max-width:760px)" in css)
status="passed" if all(r["passed"] for r in checks) else "failed"; result={"status":status,"release":"5.4.0-tenant-themes-po1","passed":sum(r["passed"] for r in checks),"failed":sum(not r["passed"] for r in checks),"checks":checks}
(ROOT/"qa/V54-UI-STATIC-RESULTS.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
print(json.dumps({k:result[k] for k in ("status","passed","failed")},indent=2)); raise SystemExit(0 if status=="passed" else 1)
