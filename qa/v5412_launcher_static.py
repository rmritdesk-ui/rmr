#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "5.4.1.2-interaction-regression-correction-po1"
checks = []

def check(name, ok, evidence=None):
    checks.append({"name": name, "passed": bool(ok), "evidence": evidence})

start = (ROOT / "START-PRODUCT-OWNER-TEST.ps1").read_text(encoding="utf-8", errors="replace")
compose = (ROOT / "docker-compose.product-owner.yml").read_text(encoding="utf-8", errors="replace")
readme = (ROOT / "README-FIRST.txt").read_text(encoding="utf-8", errors="replace")

check("Release identity in launcher", f'$Release = "{RELEASE}"' in start)
check("Isolated project", 'rmr-global-v5412-product-owner' in start)
check("Isolated port", '$Port = 8088' in start and '8088:8000' not in compose)
check("Isolated env file", '.env.product-owner-v5412' in start and '.env.product-owner-v5412' in compose)
check("Isolated data directory", 'product-owner-data-v5412' in start and 'product-owner-data-v5412:/data' in compose)
check("Package manifest verification", 'Verify-Manifest' in start)
check("Exact release health verification", '$health.version -eq $Release' in start)
check("Current migration verification", '005.006.100-four-workspace-themes' in start)
check("Functional QC execution", 'rmr_platform.product_owner_qc' in start)
check("Interaction regression gate execution", 'v5412_interaction_regression_gate.py' in start)
check("Four-theme preservation gate execution", 'v5412_theme_preservation_gate.py' in start)
check("Controlled restart", '@("restart","app")' in start)
check("Persistence verification", '--verify-persistence' in start)
check("Manual first test covers tiles", 'Your growth tools tile' in readme and 'Forecasting fully loads' in readme)

failed = [x for x in checks if not x['passed']]
payload = {"release": RELEASE, "status": "passed" if not failed else "failed", "passed": len(checks)-len(failed), "failed": len(failed), "results": checks}
out = ROOT / "qa/V5412-LAUNCHER-STATIC-RESULTS.json"
out.write_text(json.dumps(payload, indent=2)+"\n", encoding="utf-8")
print(json.dumps(payload, indent=2))
raise SystemExit(1 if failed else 0)
