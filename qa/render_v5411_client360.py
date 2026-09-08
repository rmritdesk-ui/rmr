#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageStat, ImageDraw

from rmr_platform.tenant_themes import WORKSPACE_STYLES, WORKSPACE_STYLE_KEYS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa" / "v5411-rendered-client360"
OUT.mkdir(parents=True, exist_ok=True)

BASE_CSS = "\n".join(
    (ROOT / path).read_text(encoding="utf-8", errors="replace")
    for path in [
        "public/styles.css",
        "public/client-admin-correction.css",
        "public/cumulative-product-repair.css",
        "public/v53-experience.css",
        "public/tenant-themes.css",
    ]
)


def css_vars(tokens: dict[str, str], defaults: dict[str, str]) -> str:
    mapping = {
        "--tenant-primary": defaults["primary_color"],
        "--tenant-secondary": defaults["secondary_color"],
        "--tenant-accent": defaults["accent_color"],
        "--tenant-on-primary": "#FFFFFF",
        "--tenant-on-secondary": "#111827",
        "--tenant-on-accent": "#FFFFFF",
        "--tenant-primary-text": defaults["primary_color"],
        "--tenant-accent-text": defaults["accent_color"],
        "--tenant-font-family": "system-ui,Segoe UI,sans-serif",
        "--workspace-nav": tokens["nav_background"],
        "--workspace-nav-end": tokens["nav_background_end"],
        "--workspace-nav-text": tokens["nav_text"],
        "--workspace-nav-muted": tokens["nav_muted"],
        "--workspace-nav-active": tokens["nav_active"],
        "--workspace-nav-active-text": tokens["nav_active_text"],
        "--workspace-canvas": tokens["canvas"],
        "--workspace-surface": tokens["surface"],
        "--workspace-surface-alt": tokens["surface_alt"],
        "--workspace-line": tokens["line"],
        "--workspace-topbar": tokens["topbar"],
        "--workspace-hero-start": tokens["hero_start"],
        "--workspace-hero-end": tokens["hero_end"],
        "--workspace-hero-text": tokens["hero_text"],
        "--workspace-metallic": tokens["metallic"],
        "--workspace-action": tokens["action"],
        "--workspace-action-text": tokens["action_text"],
        "--workspace-display-accent": tokens["display_accent"],
        "--workspace-chart": tokens["chart"],
        "--workspace-shadow": tokens["shadow"],
        "--workspace-pattern-a": tokens["pattern_a"],
        "--workspace-pattern-b": tokens["pattern_b"],
    }
    return ";".join(f"{key}:{value}" for key, value in mapping.items())


def markup(style_key: str) -> str:
    style = WORKSPACE_STYLES[style_key]
    tokens = style["tokens"]
    defaults = style["defaults"]
    return f"""<!doctype html><html><head><meta charset='utf-8'><style>
@page {{ size: 1600px 950px; margin: 0; }}
html,body{{margin:0;width:1600px;height:950px;overflow:hidden}}
{BASE_CSS}
</style></head><body class='tenant-theme-active workspace-style-{style_key}' style='{css_vars(tokens, defaults)}'>
<div class='app-shell'>
<aside class='sidebar'><div class='sidebar-brand'><div class='brand-mark'>R</div><div><strong>RMR Global</strong><span>{style['label']} · Powered by RMR Global</span></div></div><div class='nav-label'>KERRY LAUGHLIN REAL ESTATE</div>
<button class='nav-link active'><span class='nav-icon'>⌂</span><span>Dashboard</span></button><button class='nav-link'><span class='nav-icon'>▤</span><span>CRM</span></button><button class='nav-link'><span class='nav-icon'>✉</span><span>Email & Activities</span></button><button class='nav-link'><span class='nav-icon'>↗</span><span>Forecasting</span></button><button class='nav-link'><span class='nav-icon'>▥</span><span>Reporting</span></button><button class='nav-link'><span class='nav-icon'>▶</span><span>Training</span></button><div class='sidebar-footer'>v5.4.1.1<br>Theme Rendering Correction</div></aside>
<main class='main-area'><header class='topbar'><div class='grow'><strong>Kerry Laughlin Real Estate</strong></div><button class='button secondary small'>Notifications</button><div class='avatar'>DL</div><div class='identity-copy'><strong>Dave Laughlin</strong><small>RMR OWNER</small></div></header>
<div class='main-content'><nav class='breadcrumbs'><span>Portfolio</span><span>›</span><strong>Kerry Laughlin Real Estate</strong></nav><div class='page-head'><div><h1>Kerry Laughlin Real Estate — Client 360</h1><p>RMR and Step2 relationship, adoption, services, access, and authorized support view.</p></div><div class='page-actions'><button class='button secondary'>Return to Portfolio</button><button class='button secondary'>Manage Branding</button><button class='button'>Open Client Workspace</button></div></div>
<section class='hero-card'><div><div class='eyebrow'>CLIENT RELATIONSHIP</div><h2>Kerry Laughlin Real Estate</h2><p>Real Estate · United States · RMR Managed</p></div><div class='hero-stat'><span>Client status</span><strong>live</strong><small>Strong</small></div></section>
<div class='kpi-grid'><div class='kpi'><span>MRR</span><strong>$0</strong><small>Contracted monthly services</small></div><div class='kpi'><span>Usage revenue</span><strong>$0</strong><small>Current period</small></div><div class='kpi'><span>Adoption</span><strong>96%</strong><small>Platform activity</small></div><div class='kpi'><span>Training</span><strong>88%</strong><small>Assigned learning</small></div><div class='kpi'><span>Client access</span><strong>Active</strong><small>1 active administrator</small></div><div class='kpi'><span>Onboarding</span><strong>100%</strong><small>8 of 8 stages</small></div></div>
<div class='grid two'><section class='card'><h2>RMR relationship actions</h2><div class='action-grid'><button class='action-card'><strong>Client Pricing</strong><span>Services, rates, and billing schedule</span></button><button class='action-card'><strong>Client Onboarding</strong><span>Setup stages and client access</span></button><button class='action-card'><strong>Client Operations — Read Only</strong><span>Review CRM and activity for support</span></button><button class='action-card'><strong>Website Management</strong><span>Configuration and content</span></button></div></section><section class='card'><h2>Website & platform</h2><div class='list-item'><span class='grow'><strong>RMR Managed</strong><small>Website is configured</small></span><button class='button secondary small'>View website</button></div><div class='list-item'><span class='grow'><strong>{style['label']}</strong><small>Workspace style active</small></span><button class='button secondary small'>Manage Branding</button></div></section></div>
<div class='grid two'><section class='card'><h2>Active services</h2><div class='list-item'><span class='grow'><strong>RMR Platform Core</strong><small>$0 monthly</small></span><span class='badge green'>Active</span></div></section><section class='card'><h2>Client value evidence</h2><div class='grid two'><div class='kpi'><span>CRM accounts</span><strong>10</strong><small>Client-owned records</small></div><div class='kpi'><span>Open opportunities</span><strong>4</strong><small>Client pipeline</small></div></div></section></div>
</div></main></div></body></html>"""


results = []
images = []
for key in WORKSPACE_STYLE_KEYS:
    html = OUT / f"{key}.html"
    pdf = OUT / f"{key}.pdf"
    png_prefix = OUT / key
    png = OUT / f"{key}.png"
    html.write_text(markup(key), encoding="utf-8")
    subprocess.run(["weasyprint", str(html), str(pdf)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pdftoppm", "-png", "-singlefile", "-r", "96", str(pdf), str(png_prefix)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with Image.open(png) as img:
        rgb = img.convert("RGB")
        digest = hashlib.sha256(png.read_bytes()).hexdigest()
        mean = tuple(round(x, 2) for x in ImageStat.Stat(rgb).mean)
        images.append((key, rgb.copy()))
        results.append({"style": key, "sha256": digest, "mean_rgb": mean, "size": rgb.size})

# Pairwise image differences prove the rendered workspace changes materially.
pairwise = []
for i, (a_key, a_img) in enumerate(images):
    for b_key, b_img in images[i + 1:]:
        diff = ImageChops.difference(a_img, b_img)
        stat = ImageStat.Stat(diff)
        mean_delta = round(sum(stat.mean) / 3, 3)
        pairwise.append({"first": a_key, "second": b_key, "mean_pixel_delta": mean_delta, "materially_distinct": mean_delta >= 5.0})

# Contact sheet for review.
thumb_w, thumb_h = 760, 451
sheet = Image.new("RGB", (thumb_w * 2, (thumb_h + 52) * 2), "white")
draw = ImageDraw.Draw(sheet)
for index, (key, img) in enumerate(images):
    thumb = img.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
    x = (index % 2) * thumb_w
    y = (index // 2) * (thumb_h + 52)
    sheet.paste(thumb, (x, y + 36))
    draw.text((x + 16, y + 10), WORKSPACE_STYLES[key]["label"], fill="black")
contact = OUT / "V5411-FOUR-THEME-CLIENT360-CONTACT-SHEET.png"
sheet.save(contact, optimize=True)

status = "passed" if len({r["sha256"] for r in results}) == 4 and all(p["materially_distinct"] for p in pairwise) else "failed"
report = {
    "status": status,
    "release": "5.4.1.1-four-workspace-themes-rendering-correction-po1",
    "rendered_styles": results,
    "pairwise_differences": pairwise,
    "contact_sheet": str(contact.relative_to(ROOT)),
}
(ROOT / "qa/V5411-FOUR-THEME-VISUAL-RENDERING.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
raise SystemExit(0 if status == "passed" else 1)
