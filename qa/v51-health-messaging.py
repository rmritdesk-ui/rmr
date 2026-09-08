#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

work = tempfile.TemporaryDirectory(prefix="rmr-v51-health-")
os.environ["RMR_DATA_DIR"] = work.name
os.environ["DATABASE_URL"] = f"sqlite:///{Path(work.name) / 'health.db'}"
os.environ["RMR_SECRET_KEY"] = "v51-health-secret-" + "x" * 64
os.environ["RMR_SETUP_TOKEN"] = "v51-health-token"
os.environ["RMR_AUTO_SEED"] = "false"
os.environ["RMR_INSTALL_PROFILE"] = "empty"

from rmr_platform.db import SessionLocal  # noqa: E402
from rmr_platform.migrations import migrate  # noqa: E402
from rmr_platform.routes.system import health  # noqa: E402

REPORT = Path(__file__).resolve().parent / "V51RC3-HEALTH-MESSAGING-RESULTS.json"
checks: list[dict[str, object]] = []


def record(name: str, ok: bool, detail: object = "") -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    if not ok:
        raise AssertionError(f"{name}: {detail}")


def main() -> int:
    migrate()
    with SessionLocal() as db:
        normal = health(db)
        record("healthy business headline is plain language", normal["business_status"]["headline"] == "Core platform services are operating normally.", normal["business_status"])
        record("healthy status includes impact and action", bool(normal["business_status"]["impact"]) and bool(normal["business_status"]["action"]), normal["business_status"])
        with patch("rmr_platform.routes.system.os.access", return_value=False):
            degraded = health(db)
        record("degraded status is reported", degraded["status"] == "degraded", degraded)
        record("degraded headline is plain language", degraded["business_status"]["headline"] == "One or more core services need attention.", degraded["business_status"])
        record("degraded status explains business impact", "may be unavailable" in degraded["business_status"]["impact"], degraded["business_status"])
        record("degraded status recommends action", "contact platform support" in degraded["business_status"]["action"].lower(), degraded["business_status"])
    result = {"status":"passed","release":"5.3.1-final-production-corrections-po1","passed":sum(1 for item in checks if item["ok"]),"failed":sum(1 for item in checks if not item["ok"]),"checks":checks}
    REPORT.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({k:result[k] for k in ["status","passed","failed"]},indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        work.cleanup()
