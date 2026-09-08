#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

V51_ROOT = Path(__file__).resolve().parents[1]
V50_ROOT = V51_ROOT.parent / "RMR-Platform-v5.0-Functional-Production-Pilot-Candidate"
REPORT = V51_ROOT / "qa" / "V51RC3-UPGRADE-PRESERVATION-RESULTS.json"
checks: list[dict[str, object]] = []


def record(name: str, ok: bool, detail: object = "") -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    if not ok:
        raise AssertionError(f"{name}: {detail}")


def port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def req(client: httpx.Client, base: str, method: str, path: str, body=None, expected=200):
    headers = {"X-RMR-Request": "1"} if method != "GET" else {}
    response = client.request(method, base + path, json=body, headers=headers)
    try:
        data = response.json()
    except Exception:
        data = response.text
    record(f"{method} {path}", response.status_code == expected, {"status": response.status_code, "body": data})
    return data


def start(root: Path, data_dir: Path, secret: str, setup_token: str, app_port: int, log_path: Path) -> tuple[subprocess.Popen, object, str]:
    base = f"http://127.0.0.1:{app_port}"
    env = os.environ.copy()
    env.update({
        "RMR_DATA_DIR": str(data_dir), "RMR_PORT": str(app_port), "RMR_BASE_URL": base,
        "RMR_SECRET_KEY": secret, "RMR_SETUP_TOKEN": setup_token, "RMR_AUTO_SEED": "false",
        "RMR_ALLOW_DEMO_CREDENTIALS": "false", "RMR_LOCAL_RECOVERY_MODE": "true",
        "RMR_INSTALL_PROFILE": "empty", "RMR_ENVIRONMENT": "pilot", "PYTHONUNBUFFERED": "1",
    })
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "-m", "rmr_platform.server"], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(120):
        try:
            if httpx.get(base + "/api/health", timeout=1).status_code == 200:
                return process, log, base
        except Exception:
            pass
        time.sleep(.2)
    process.terminate()
    raise RuntimeError(log_path.read_text(encoding="utf-8", errors="replace")[-6000:])


def stop(process: subprocess.Popen, log) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill(); process.wait(timeout=5)
    log.close()


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="rmr-v51-upgrade-"))
    data_dir = work / "data"; data_dir.mkdir()
    setup_token = "upgrade-token-" + uuid.uuid4().hex
    secret = "upgrade-secret-" + uuid.uuid4().hex + uuid.uuid4().hex
    owner_email = "upgrade-owner@rmr.test"
    owner_password = "Upgrade-Owner-Password-2026!"
    v50_log = work / "v50.log"
    v51_log = work / "v51.log"
    proc = None; log = None
    try:
        record("authoritative v5.0 baseline exists", V50_ROOT.exists(), str(V50_ROOT))
        proc, log, base50 = start(V50_ROOT, data_dir, secret, setup_token, port(), v50_log)
        client = httpx.Client(timeout=30)
        req(client, base50, "POST", "/api/setup/complete", {
            "setup_token": setup_token, "owner_name": "Upgrade Owner", "owner_email": owner_email,
            "owner_password": owner_password, "step2_name": "Step2 Upgrade", "step2_email": "step2-upgrade@rmr.test",
            "step2_password": "Step2-Upgrade-Password!",
        })
        # Login explicitly for portability across the v5.0 implementation.
        req(client, base50, "POST", "/api/auth/login", {"email": owner_email, "password": owner_password})
        slug = "preserve-" + uuid.uuid4().hex[:8]
        created = req(client, base50, "POST", "/api/tenants", {
            "name": "Preservation Client", "slug": slug, "industry": "Professional Services",
            "country": "United States", "timezone": "America/Phoenix", "seller_org": "RMR",
            "seller_name": "Upgrade Test", "website_mode": "managed", "website_url": "",
            "primary_contact_name": "Preserved Admin", "primary_contact_email": f"admin@{slug}.test",
            "services": [
                {"service_code": "platform_core", "contract_price_cents": 28700},
                {"service_code": "crm", "contract_price_cents": 16300},
            ],
        })
        tenant_id = created["tenant"]["id"]
        onboarding = req(client, base50, "GET", f"/api/tenants/{tenant_id}/onboarding")
        step = onboarding["steps"][0]
        qc_note = "PRODUCT OWNER QC NOTE — preserve this exact note through v5.1 migration."
        qc_data = {"business_context": "CAF-style product-owner annotation", "approved": False}
        req(client, base50, "PATCH", f"/api/onboarding/steps/{step['id']}", {
            "data": qc_data, "notes": qc_note, "status": "in_progress",
        })
        services = req(client, base50, "GET", f"/api/tenants/{tenant_id}/services")
        expected_prices = {row["tenant_service"]["service_code"]: row["tenant_service"]["contract_price_cents"] for row in services["services"]}
        stop(proc, log); proc = None; log = None

        proc, log, base51 = start(V51_ROOT, data_dir, secret, setup_token, port(), v51_log)
        owner = httpx.Client(timeout=30)
        req(owner, base51, "POST", "/api/auth/login", {"email": owner_email, "password": owner_password})
        migrated = req(owner, base51, "GET", f"/api/tenants/{tenant_id}/onboarding")
        migrated_step = next(row for row in migrated["steps"] if row["id"] == step["id"])
        record("v5.0 onboarding note preserved exactly", migrated_step["notes"] == qc_note, migrated_step)
        record("v5.0 onboarding structured data preserved exactly", migrated_step["data_json"] == qc_data, migrated_step)
        migrated_services = req(owner, base51, "GET", f"/api/tenants/{tenant_id}/services")
        actual_prices = {row["tenant_service"]["service_code"]: row["tenant_service"]["contract_price_cents"] for row in migrated_services["services"]}
        record("v5.0 service schedule and negotiated prices preserved", actual_prices == expected_prices, {"expected": expected_prices, "actual": actual_prices})
        tenants = req(owner, base51, "GET", "/api/tenants")
        record("v5.0 tenant survives additive migration", any(row["id"] == tenant_id and row["slug"] == slug for row in tenants["tenants"]), tenants)
        health = req(owner, base51, "GET", "/api/health")
        record("v5.1 migration preserved in cumulative release", "005.001.000-functional-client-experience" in health["checks"]["migrations"].get("applied", []), health["checks"]["migrations"])

        result = {"status": "passed", "passed": sum(1 for x in checks if x["ok"]), "failed": sum(1 for x in checks if not x["ok"]), "checks": checks}
        REPORT.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({k: result[k] for k in ["status", "passed", "failed"]}, indent=2))
        return 0
    except Exception as exc:
        result = {"status": "failed", "error": str(exc), "passed": sum(1 for x in checks if x["ok"]), "failed": sum(1 for x in checks if not x["ok"]), "checks": checks,
                  "v50_log": v50_log.read_text(encoding="utf-8", errors="replace")[-5000:] if v50_log.exists() else "",
                  "v51_log": v51_log.read_text(encoding="utf-8", errors="replace")[-5000:] if v51_log.exists() else ""}
        REPORT.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({k: result[k] for k in ["status", "error", "passed", "failed"]}, indent=2))
        raise
    finally:
        if proc is not None: stop(proc, log)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
