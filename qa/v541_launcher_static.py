#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "5.4.1-four-workspace-themes-po1"
MIGRATION = "005.006.100-four-workspace-themes"
checks: list[dict[str, object]] = []


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def check(name: str, ok: bool, detail: object = "") -> None:
    checks.append({"name": name, "passed": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))


ps = text("START-PRODUCT-OWNER-TEST.ps1")
bat = text("START-PRODUCT-OWNER-TEST.bat")
compose = text("docker-compose.product-owner.yml")
stop = text("STOP-PRODUCT-OWNER-TEST.ps1")
reset = text("RESET-PRODUCT-OWNER-DEMO.ps1")
diag = text("COLLECT-PRODUCT-OWNER-DIAGNOSTICS.ps1")
readme = text("README-FIRST.txt")

check("Launcher targets exact v5.4.1 release", f'$Release = "{RELEASE}"' in ps)
check("Launcher uses isolated v5.4.1 Docker project", '$Project = "rmr-global-v541-product-owner"' in ps)
check("Launcher uses new isolated port 8086", "$Port = 8086" in ps and "RMR_PUBLIC_PORT:-8086" in compose)
check("Launcher uses isolated v5.4.1 configuration", ".env.product-owner-v541" in ps and "- .env.product-owner-v541" in compose)
check("Launcher uses isolated v5.4.1 persistent data", "product-owner-data-v541" in ps and "./product-owner-data-v541:/data" in compose)
check("Reset archive path is correctly isolated", "product-owner-data-v541-archive" in reset and "product-owner-data-v5411" not in reset)
check("Launcher verifies package manifest before build", "Verify-Manifest" in ps and "PACKAGE-MANIFEST.json" in ps)
check("Launcher verifies frozen v5.3.1 seal", "V531-PRODUCTION-BASELINE-SEAL.json" in ps and "d188a52eab6494cb61bcecd828616d4bc17a1fa30cd5ddd2ff54e28555b5f1bf" in ps)
check("Launcher verifies Docker engine and Compose", 'Invoke-Docker @("version")' in ps and 'Invoke-Docker @("compose","version")' in ps)
check("Launcher safely creates first-run environment before cleanup", ps.find("Created protected local Product Owner configuration") < ps.find('ComposeArgs @("down","--remove-orphans")'))
check("Launcher protects port collision", "Test-Port $Port" in ps and "already in use" in ps)
check("Launcher builds only the isolated app", 'ComposeArgs @("up","-d","--build")' in ps)
check("Launcher verifies exact release and migration", RELEASE in ps and MIGRATION in ps)
check("Launcher runs comprehensive Product Owner QC", "rmr_platform.product_owner_qc" in ps and "PRODUCT-OWNER-QC-LATEST.json" in ps)
check("Launcher restarts the app and verifies persistence", 'ComposeArgs @("restart","app")' in ps and "--verify-persistence" in ps)
check("Launcher captures diagnostics on failure", "Collect-Failure" in ps and "COLLECT-PRODUCT-OWNER-DIAGNOSTICS.ps1" in ps)
check("Launcher opens the Product Owner URL", 'Start-Process "http://localhost:$Port"' in ps)
check("Stop targets only isolated v5.4.1 project", all(token in stop for token in ("rmr-global-v541-product-owner", ".env.product-owner-v541")))
check("Reset targets only isolated v5.4.1 project/data", all(token in reset for token in ("rmr-global-v541-product-owner", "product-owner-data-v541")))
check("Diagnostics target only isolated v5.4.1 environment", all(token in diag for token in ("rmr-global-v541-product-owner", ".env.product-owner-v541", "product-owner-data-v541", "8086")))
check("BAT wrapper invokes the PowerShell launcher", "START-PRODUCT-OWNER-TEST.ps1" in bat and "ExecutionPolicy Bypass" in bat)
check("README gives short Windows extraction path", "C:\\RMR541" in readme and "START-PRODUCT-OWNER-TEST.bat" in readme)
check("Compose healthcheck verifies exact release", RELEASE in compose and "/api/health" in compose)
check("No placeholder markers remain", not re.search(r"(?i)\bTODO\b|PLACEHOLDER|NOT IMPLEMENTED", ps + compose + diag + readme))
check("PowerShell launcher delimiters are balanced", ps.count("{") == ps.count("}") and ps.count("(") == ps.count(")"), {"braces": ps.count("{") - ps.count("}"), "parens": ps.count("(") - ps.count(")")})

status = "passed" if all(row["passed"] for row in checks) else "failed"
result = {
    "status": status,
    "release": RELEASE,
    "migration": MIGRATION,
    "docker_project": "rmr-global-v541-product-owner",
    "port": 8086,
    "passed": sum(1 for row in checks if row["passed"]),
    "failed": sum(1 for row in checks if not row["passed"]),
    "checks": checks,
}
(ROOT / "qa/V541-LAUNCHER-STATIC-RESULTS.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: result[k] for k in ("status", "passed", "failed")}, indent=2))
raise SystemExit(0 if status == "passed" else 1)
