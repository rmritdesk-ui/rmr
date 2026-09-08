#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "5.4.1-four-workspace-themes-po1"
STYLE_KEYS = ("classic-blue", "metallic-silver", "metallic-gold", "champagne-gold")
checks: list[dict[str, object]] = []


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def check(name: str, ok: bool, detail: object = "") -> None:
    checks.append({"name": name, "passed": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))


manager = text("public/pages/theme_manager.js")
theme = text("public/tenant-theme.js")
css = text("public/tenant-themes.css")
index = text("public/index.html")
app = text("public/app.js")
router = text("rmr_platform/tenant_themes.py")
assets: dict[str, dict[str, object]] = {}
for key in STYLE_KEYS:
    path = ROOT / f"public/assets/workspace-themes/{key}.jpg"
    assets[key] = {
        "exists": path.is_file(),
        "size": path.stat().st_size if path.is_file() else 0,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing",
    }

style_order = re.search(r"const STYLE_ORDER = \[(.*?)\];", manager)
order_text = style_order.group(1) if style_order else ""
check("Theme module is linked into the authenticated application", "tenant-themes.css" in index and "tenant-theme.js" in app)
check("Choose Workspace Style is visibly labeled", "Choose Workspace Style" in manager)
check("Exactly four controlled style keys appear in selector order", all(order_text.find(key) >= 0 for key in STYLE_KEYS) and order_text.count("'") == 8, order_text)
check("Four visual preview cards are rendered from server style data", "workspace-style-grid" in manager and "workspace-style-card" in manager and "preview_url" in manager)
check("Preview cards expose radio-selection semantics", 'type="radio" name="workspace_style"' in manager)
check("Selected card receives a visible selected state", "style.value===selected?'selected':''" in manager and "workspace-style-check" in manager and ".workspace-style-card.selected" in css)
check("Each frozen preview asset exists and is nontrivial", all(item["exists"] and item["size"] > 50000 for item in assets.values()), assets)
check("All four preview images are byte-distinct", len({item["sha256"] for item in assets.values()}) == 4, assets)
check("Each style has a dedicated authenticated-workspace class", all(f"workspace-style-{key}" in css and f"workspace-style-{key}" in theme for key in STYLE_KEYS))
check("Workspace style is applied to body state", "body.dataset.workspaceStyle" in theme and "body.classList.add(`workspace-style-${theme.workspace_style" in theme)
check("Style tokens apply across navigation, canvas, surfaces, actions, and charts", all(token in theme for token in ("--workspace-nav", "--workspace-canvas", "--workspace-surface", "--workspace-action", "--workspace-chart")))
check("The four style token definitions are structurally distinct", len({hashlib.sha256(json.dumps(re.findall(rf'\"{key}\": \{{(.*?)\n    \}},', router, re.S), sort_keys=True).encode()).hexdigest() for key in STYLE_KEYS}) == 4)
check("Classic Blue has its own workspace canvas treatment", ".workspace-style-classic-blue.tenant-theme-active" in css)
check("Metallic Silver has silver surface treatment", ".workspace-style-metallic-silver.tenant-theme-active .card" in css)
check("Metallic Gold has gold surfaces and red action treatment", ".workspace-style-metallic-gold.tenant-theme-active .card" in css and "#C71420" in css)
check("Champagne Gold has restrained ivory/champagne treatment", ".workspace-style-champagne-gold.tenant-theme-active .card" in css and "#F1E1BF" in css)
check("Selecting a card updates the active preset and preview", "card.addEventListener('click'" in manager and "form.workspace_style.value=style.value" in manager and "form.enabled.checked=true;sync()" in manager)
check("Save & Apply persists workspace_style", "Save & Apply" in manager and "workspace_style:form.workspace_style.value" in manager)
check("Existing tenant brand name control remains", 'name="brand_name"' in manager)
check("Existing approved typography control remains", 'name="font_family"' in manager and "allowed_fonts" in manager)
check("Existing three color controls remain", all(f'name="{name}"' in manager for name in ("primary_color", "secondary_color", "accent_color")))
check("Existing logo upload/remove controls remain", 'name="logo"' in manager and "remove-theme-logo" in manager and "image/png,image/jpeg,image/webp" in manager)
check("Reset to RMR Default remains", "Reset to RMR Default" in manager and "reset-tenant-theme" in manager)
check("RMR Global attribution remains visible", "Powered by RMR Global" in theme and "Powered by RMR Global" in manager)
check("Theme management escapes user-controlled values", "esc(" in manager and "esc(" in theme)
check("No iframe or custom-code injection UI exists", all(token not in manager.lower() for token in ("<iframe", "custom css", "custom javascript", "script injection")))
check("Four-card selector is responsive", "@media(max-width:1080px)" in css and "@media(max-width:760px)" in css and ".workspace-style-grid" in css)
check("Danger/error semantics remain separately styled", ":not(.danger)" in css and ".danger" in css)
check("Public website template does not load authenticated theme CSS", "tenant-themes.css" not in text("templates/public_site.html"))

status = "passed" if all(row["passed"] for row in checks) else "failed"
result = {
    "status": status,
    "release": RELEASE,
    "style_order": list(STYLE_KEYS),
    "preview_assets": assets,
    "passed": sum(1 for row in checks if row["passed"]),
    "failed": sum(1 for row in checks if not row["passed"]),
    "checks": checks,
}
(ROOT / "qa/V541-UI-STATIC-RESULTS.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: result[k] for k in ("status", "passed", "failed")}, indent=2))
raise SystemExit(0 if status == "passed" else 1)
