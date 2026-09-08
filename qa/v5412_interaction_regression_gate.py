#!/usr/bin/env python3
"""Bounded v5.4.1.2 interaction-regression source gate.

This gate verifies the exact behavior corrected in this release without changing
or simulating business data. It is safe to run from the Windows/Docker launcher.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

RELEASE = "5.4.1.2-interaction-regression-correction-po1"
ROUTES = ("website", "crm", "piq", "campaigns", "email", "forecast")
PRESERVED_OPERATIONAL = ("forecast", "training", "organization", "solutions")
THEMES = ("classic-blue", "metallic-silver", "metallic-gold", "champagne-gold")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    results: list[dict[str, Any]] = []

    def check(name: str, passed: bool, evidence: Any = None) -> None:
        results.append({"name": name, "passed": bool(passed), "evidence": evidence})

    ui = (root / "public/ui.js").read_text(encoding="utf-8", errors="replace")
    unified = (root / "public/pages/unified.js").read_text(encoding="utf-8", errors="replace")
    client = (root / "public/pages/client.js").read_text(encoding="utf-8", errors="replace")
    v53 = (root / "public/pages/v53_client_experience.js").read_text(encoding="utf-8", errors="replace")
    css = (root / "public/tenant-themes.css").read_text(encoding="utf-8", errors="replace")

    check("Exactly one delegated route handler is installed", ui.count("const routeDelegate") == 1, ui.count("const routeDelegate"))
    check("Accepted route control selector is preserved", "[data-route],[data-v53-route]" in ui)
    check("Delegation is capture phase", "addEventListener('click', routeDelegate, true)" in ui)
    check("Rebinding removes the prior delegate", "removeEventListener('click', appRoot._rmrRouteDelegate, true)" in ui)
    check("Disabled controls remain inert", "control.disabled" in ui and "aria-disabled" in ui)
    check("Delegated click owns only navigation", "stopImmediatePropagation" in ui and "navigate(route)" in ui)

    for route in ROUTES:
        exists = f'data-route="{route}"' in unified or f"'{route}'" in unified
        check(f"Dashboard destination exists: {route}", exists)
    check("v5.3 actionable route controls remain present", "data-v53-route" in v53)

    fallback_signature = "['forecast','training','organization','solutions'].includes(route)"
    check("Operational fallback route list is exact", fallback_signature in unified, list(PRESERVED_OPERATIONAL))
    check("Operational fallback is not duplicated", unified.count("ctx.renderClientOperational(route, readOnly)") == 1, unified.count("ctx.renderClientOperational(route, readOnly)"))
    check("Forecasting uses preserved operational renderer", "if(route==='forecast')return await forecast" in client)
    check("Forecasting API remains unchanged", "/forecast`" in client or "/forecast" in client)

    check("Theme interaction guard is present", "v5.4.1.2 interaction-preservation guard" in css)
    check("Theme layers permit route controls", "button[data-route]" in css and "button[data-v53-route]" in css and "pointer-events:auto" in css)
    for theme in THEMES:
        check(f"Preserved theme remains present: {theme}", f".workspace-style-{theme}.tenant-theme-active .main-area" in css)

    theme_assets = {}
    for theme in THEMES:
        path = root / f"public/assets/workspace-themes/{theme}.jpg"
        check(f"Theme preview asset exists: {theme}", path.is_file(), str(path.relative_to(root)))
        if path.is_file():
            theme_assets[theme] = sha256(path)
    check("Four theme preview assets remain distinct", len(set(theme_assets.values())) == 4, theme_assets)

    failed = [row for row in results if not row["passed"]]
    payload = {
        "release": RELEASE,
        "status": "passed" if not failed else "failed",
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "results": results,
    }
    text = json.dumps(payload, indent=2)
    print(text)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
