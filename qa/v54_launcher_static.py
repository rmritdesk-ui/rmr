#!/usr/bin/env python3
from __future__ import annotations
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "5.4.0-tenant-themes-po1"
checks=[]

def text(p): return (ROOT/p).read_text(encoding="utf-8", errors="replace")
def check(name, ok, detail=""):
    checks.append({"name":name,"passed":bool(ok),"detail":detail}); print(f"[{'PASS' if ok else 'FAIL'}] {name}")

ps=text("START-PRODUCT-OWNER-TEST.ps1"); bat=text("START-PRODUCT-OWNER-TEST.bat")
compose=text("docker-compose.product-owner.yml"); stop=text("STOP-PRODUCT-OWNER-TEST.ps1")
reset=text("RESET-PRODUCT-OWNER-DEMO.ps1"); diag=text("COLLECT-PRODUCT-OWNER-DIAGNOSTICS.ps1")
readme=text("README-FIRST.txt")
check("Launcher targets exact v5.4 release", f'$Release = "{RELEASE}"' in ps)
check("Launcher uses isolated v5.4 Docker project", '$Project = "rmr-global-v540-product-owner"' in ps)
check("Launcher uses isolated port 8085", "$Port = 8085" in ps and "8085:8000" not in compose and "RMR_PUBLIC_PORT:-8085" in compose)
check("Launcher uses isolated configuration", '.env.product-owner-v54' in ps and '.env.product-owner-v54' in compose)
check("Compose service env file matches launcher", "- .env.product-owner-v54" in compose)
check("Launcher uses isolated persistent data", 'product-owner-data-v54' in ps and './product-owner-data-v54:/data' in compose)
check("Launcher verifies package manifest", "Verify-Manifest" in ps and "PACKAGE-MANIFEST.json" in ps)
check("Launcher verifies sealed v5.3.1 identity", "V531-PRODUCTION-BASELINE-SEAL.json" in ps and "d188a52eab6494cb61bcecd828616d4bc17a1fa30cd5ddd2ff54e28555b5f1bf" in ps)
check("Launcher verifies Docker engine and Compose", 'Invoke-Docker @("version")' in ps and 'Invoke-Docker @("compose","version")' in ps)
check("Launcher protects port collision", "Test-Port $Port" in ps and "already in use" in ps)
check("Launcher builds isolated app", 'ComposeArgs @("up","-d","--build")' in ps)
check("Launcher verifies exact migration", "005.006.000-tenant-themes" in ps)
check("Launcher runs functional tenant-theme QC", "rmr_platform.product_owner_qc" in ps and "tenant-theme isolation QC" in ps)
check("Launcher restarts and verifies persistence", 'ComposeArgs @("restart","app")' in ps and "--verify-persistence" in ps)
check("Launcher collects failure diagnostics", "Collect-Failure" in ps and "COLLECT-PRODUCT-OWNER-DIAGNOSTICS.ps1" in ps)
check("Launcher opens Product Owner URL", 'Start-Process "http://localhost:$Port"' in ps)
check("Stop targets only isolated v5.4 project", "rmr-global-v540-product-owner" in stop and ".env.product-owner-v54" in stop)
check("Reset targets only isolated v5.4 data", "rmr-global-v540-product-owner" in reset and "product-owner-data-v54" in reset)
check("Diagnostics target only isolated v5.4 environment", all(x in diag for x in ("rmr-global-v540-product-owner", ".env.product-owner-v54", "product-owner-data-v54", "8085")))
check("BAT wrapper invokes the PowerShell launcher", "START-PRODUCT-OWNER-TEST.ps1" in bat and "ExecutionPolicy Bypass" in bat)
check("README gives short Windows extraction path", "C:\\RMR540" in readme and "START-PRODUCT-OWNER-TEST.bat" in readme)
check("No placeholder markers remain", not re.search(r"(?i)\bTODO\b|PLACEHOLDER|NOT IMPLEMENTED", ps+compose+diag+readme))
check("PowerShell launcher delimiters are balanced", ps.count("{")==ps.count("}") and ps.count("(")==ps.count(")"), {"braces":ps.count("{")-ps.count("}"),"parens":ps.count("(")-ps.count(")")})
status="passed" if all(r["passed"] for r in checks) else "failed"
result={"status":status,"release":RELEASE,"passed":sum(r["passed"] for r in checks),"failed":sum(not r["passed"] for r in checks),"checks":checks}
(ROOT/"qa/V54-LAUNCHER-STATIC-RESULTS.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
print(json.dumps({k:result[k] for k in ("status","passed","failed")},indent=2)); raise SystemExit(0 if status=="passed" else 1)
