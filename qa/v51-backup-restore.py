#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPORT = Path(os.getenv("RMR_BACKUP_REPORT", ROOT / "qa/V51RC3-BACKUP-RESTORE-RESULTS.json"))
checks: list[dict[str, object]] = []


def record(name: str, ok: bool, detail: object = "") -> None:
    checks.append({"name": name, "ok": ok, "detail": detail})
    if not ok:
        raise AssertionError(f"{name}: {detail}")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_health(base: str, process: subprocess.Popen[str], timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server exited early with code {process.returncode}")
        try:
            data = httpx.get(base + "/api/health", timeout=2).json()
            if data.get("status") == "healthy":
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("Server did not become healthy")


def start_server(env: dict[str, str], port: int) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [sys.executable, "-m", "rmr_platform.server"],
        cwd=ROOT,
        env={**env, "RMR_PORT": str(port), "RMR_HOST": "127.0.0.1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        text=True,
    )
    wait_health(f"http://127.0.0.1:{port}", process)
    return process


def stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def api(client: httpx.Client, method: str, path: str, body=None, expected: int = 200):
    headers = {"X-RMR-Request": "1"} if method != "GET" else {}
    response = client.request(method, path, json=body, headers=headers)
    record(f"{method} {path}", response.status_code == expected, {"status": response.status_code, "body": response.text[:300]})
    return response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text


def main() -> int:
    started = time.time()
    process: subprocess.Popen[str] | None = None
    with tempfile.TemporaryDirectory(prefix="rmr-v51-backup-") as temp_text:
        data_dir = Path(temp_text) / "data"
        data_dir.mkdir()
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(ROOT),
            "RMR_DATA_DIR": str(data_dir),
            "RMR_ENVIRONMENT": "test",
            "RMR_SECRET_KEY": "backup-restore-smoke-secret-with-sufficient-length",
            "RMR_SETUP_TOKEN": "backup-restore-smoke-token",
            "RMR_INSTALL_PROFILE": "demo",
            "RMR_AUTO_MIGRATE": "true",
            "RMR_AUTO_SEED": "true",
            "RMR_ALLOW_DEMO_CREDENTIALS": "true",
            "RMR_PAYMENT_PROVIDER": "mock",
        })
        try:
            process = start_server(env, port)
            with httpx.Client(base_url=base, timeout=20) as client:
                api(client, "POST", "/api/auth/login", {"email": "dave@rmr.local", "password": "RMR-Owner-2026!"})
                suffix = uuid.uuid4().hex[:6]
                before_name = f"Backup Before {suffix}"
                after_name = f"Backup After {suffix}"
                create_payload = {
                    "name": before_name,
                    "slug": f"backup-before-{suffix}",
                    "industry": "Business Consulting",
                    "country": "United States",
                    "timezone": "America/Phoenix",
                    "seller_org": "RMR",
                    "seller_name": "Backup Smoke",
                    "website_mode": "managed",
                    "website_url": "",
                    "primary_contact_name": "Backup Test",
                    "primary_contact_email": f"before-{suffix}@example.com",
                    "services": [{"service_code": "platform_core", "contract_price_cents": 29500}],
                }
                api(client, "POST", "/api/tenants", create_payload)

                backup_path = data_dir / "backups" / "certification-backup.tar.gz"
                result = subprocess.run(
                    [sys.executable, "-m", "rmr_platform.cli", "backup", "--output", str(backup_path)],
                    cwd=ROOT, env=env, capture_output=True, text=True,
                )
                record("backup CLI exits successfully", result.returncode == 0, result.stdout + result.stderr)
                record("backup archive exists", backup_path.exists() and backup_path.stat().st_size > 0, str(backup_path))

                after_payload = {**create_payload, "name": after_name, "slug": f"backup-after-{suffix}", "primary_contact_email": f"after-{suffix}@example.com"}
                api(client, "POST", "/api/tenants", after_payload)
                tenants = api(client, "GET", "/api/tenants")["tenants"]
                record("post-backup tenant exists before restore", any(t["name"] == after_name for t in tenants), len(tenants))

            stop_server(process)
            process = None
            restore = subprocess.run(
                [sys.executable, "-m", "rmr_platform.cli", "restore", str(backup_path)],
                cwd=ROOT, env=env, capture_output=True, text=True,
            )
            record("restore CLI exits successfully", restore.returncode == 0, restore.stdout + restore.stderr)
            record("pre-restore safety backup created", any((data_dir / "backups").glob("pre-restore-*.tar.gz")), list((data_dir / "backups").glob("*.tar.gz")))

            port = free_port()
            base = f"http://127.0.0.1:{port}"
            process = start_server(env, port)
            with httpx.Client(base_url=base, timeout=20) as client:
                api(client, "POST", "/api/auth/login", {"email": "dave@rmr.local", "password": "RMR-Owner-2026!"})
                tenants = api(client, "GET", "/api/tenants")["tenants"]
                record("pre-backup tenant survives restore", any(t["name"] == before_name for t in tenants), len(tenants))
                record("post-backup tenant removed by restore", not any(t["name"] == after_name for t in tenants), len(tenants))
        finally:
            if process is not None:
                stop_server(process)

    result = {
        "status": "passed",
        "passed": sum(1 for c in checks if c["ok"]),
        "failed": sum(1 for c in checks if not c["ok"]),
        "duration_seconds": round(time.time() - started, 2),
        "checks": checks,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ["status", "passed", "failed", "duration_seconds"]}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps({"status": "failed", "error": str(exc), "checks": checks}, indent=2, default=str), encoding="utf-8")
        raise
