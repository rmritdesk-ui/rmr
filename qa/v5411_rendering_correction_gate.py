#!/usr/bin/env python3
from pathlib import Path
from PIL import Image
import hashlib, json

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "5.4.1.1-four-workspace-themes-rendering-correction-po1"
BASELINE_SHA = "bf519df3b2e67001ac69f8e81011bfcab23d6c113b87fcc0af08161a252a7a32"
STYLE_KEYS = ("classic-blue", "metallic-silver", "metallic-gold", "champagne-gold")
checks=[]

def text(path): return (ROOT/path).read_text(encoding="utf-8", errors="replace")
def check(name, ok, detail=""):
    checks.append({"name":name,"passed":bool(ok),"detail":detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))

app=text("public/app.js"); theme=text("public/tenant-theme.js"); css=text("public/tenant-themes.css"); router=text("rmr_platform/tenant_themes.py")
check("Exact corrected release identity is active", RELEASE in text("rmr_platform/__init__.py") and RELEASE in router)
check("Exact v5.4.1 source baseline is declared", BASELINE_SHA in text("V5411-PRODUCT-OWNER-SCOPE-LOCK.md"))
check("Tenant-scoped Client 360 activates theme for global administrator", "ADMIN_TENANT_THEME_ROUTES = new Set(['client-360'])" in theme and "inTenantScopedAdminView" in theme)
check("Route changes reapply selected tenant theme", "routeTenantChanged" in app and "applyTenantTheme();" in app and "await loadTenantTheme()" in app)
check("All four preview URLs use mounted static path", all(f'/static/assets/workspace-themes/{key}.jpg' in router for key in STYLE_KEYS))
asset_hashes=[]
for key in STYLE_KEYS:
    path=ROOT/f"public/assets/workspace-themes/{key}.jpg"
    ok=path.is_file()
    size=None
    if ok:
        with Image.open(path) as img: size=img.size
        asset_hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    check(f"{key} preview is individual 640x360 image", ok and size==(640,360), str(size))
check("All four preview assets are byte-distinct", len(set(asset_hashes))==4, asset_hashes)
for key in STYLE_KEYS:
    check(f"{key} has dedicated Client 360 canvas treatment", f".workspace-style-{key}.tenant-theme-active .main-area" in css)
check("Shared Client 360 cards and actions are theme-driven", all(x in css for x in (".tenant-theme-active .action-card", ".tenant-theme-active .list-item", ".tenant-theme-active .kpi", ".tenant-theme-active .hero-card")))
check("Metallic Gold has material gold canvas and red actions", "#D3A83C" in css and "#D51C29" in css)
check("Metallic Silver has material silver surfaces", "#E1E5EA" in css and "#DDE2E8" in css)
check("Champagne Gold remains reduced and restrained", "#F2E6CE" in css and "#FBF7EF" in css)
check("No database migration was added", 'MIGRATION_VERSION = "005.006.100-four-workspace-themes"' in text("rmr_platform/migrations.py"))
check("Public website remains outside authenticated theme system", "tenant-themes.css" not in text("templates/public_site.html"))
status="passed" if all(c["passed"] for c in checks) else "failed"
result={"status":status,"release":RELEASE,"source_baseline_sha256":BASELINE_SHA,"passed":sum(c["passed"] for c in checks),"failed":sum(not c["passed"] for c in checks),"checks":checks}
(ROOT/"qa/V5411-RENDERING-CORRECTION-GATE.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps({k:result[k] for k in ("status","passed","failed")},indent=2))
raise SystemExit(0 if status=="passed" else 1)
