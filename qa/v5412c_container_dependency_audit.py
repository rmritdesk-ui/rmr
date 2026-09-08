#!/usr/bin/env python3
"""Packaging-only audit for every file required by the v5.4.1.2C PO launcher chain."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

RELEASE = "5.4.1.2-interaction-regression-correction-po1"
REQUIRED = {
    "application_server": "rmr_platform/server.py",
    "functional_qc_module": "rmr_platform/product_owner_qc.py",
    "interaction_gate": "qa/v5412_interaction_regression_gate.py",
    "theme_preservation_gate": "qa/v5412_theme_preservation_gate.py",
    "container_dependency_audit": "qa/v5412c_container_dependency_audit.py",
    "unified_route_delegate": "public/ui.js",
    "unified_workspace_renderer": "public/pages/unified.js",
    "client_operational_renderer": "public/pages/client.js",
    "v53_preserved_routes": "public/pages/v53_client_experience.js",
    "theme_styles": "public/tenant-themes.css",
    "classic_blue_preview": "public/assets/workspace-themes/classic-blue.jpg",
    "metallic_silver_preview": "public/assets/workspace-themes/metallic-silver.jpg",
    "metallic_gold_preview": "public/assets/workspace-themes/metallic-gold.jpg",
    "champagne_gold_preview": "public/assets/workspace-themes/champagne-gold.jpg",
}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/app")
    parser.add_argument("--entrypoint", default="/usr/local/bin/rmr-entrypoint")
    parser.add_argument("--output")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    results: list[dict[str, Any]] = []
    for name, rel in REQUIRED.items():
        path = root / rel
        results.append({"name": name, "path": str(path), "exists": path.is_file()})
    entrypoint = Path(args.entrypoint)
    results.append({"name": "container_entrypoint", "path": str(entrypoint), "exists": entrypoint.is_file()})
    missing = [item for item in results if not item["exists"]]
    payload = {
        "release": RELEASE,
        "status": "passed" if not missing else "failed",
        "required_count": len(results),
        "passed": len(results) - len(missing),
        "failed": len(missing),
        "results": results,
        "missing": missing,
    }
    text = json.dumps(payload, indent=2)
    print(text)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    return 0 if not missing else 2

if __name__ == "__main__":
    raise SystemExit(main())
