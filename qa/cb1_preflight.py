from __future__ import annotations

import ast
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "qa" / "cb1_preflight_result.json"
checks: list[dict] = []


def check(identifier: str, condition: bool, detail: str = "") -> None:
    checks.append({"id": identifier, "pass": bool(condition), "detail": detail})
    if not condition:
        raise AssertionError(f"{identifier}: {detail}")


def find_app_module() -> str:
    candidates = []
    for path in (ROOT / "rmr_platform").rglob("*.py"):
        text = path.read_text(errors="replace")
        if re.search(r"\bapp\s*=\s*FastAPI\s*\(", text):
            rel = path.relative_to(ROOT).with_suffix("")
            candidates.append(".".join(rel.parts))
    if not candidates:
        raise AssertionError("No FastAPI app module found")
    # Prefer conventional entrypoints.
    candidates.sort(key=lambda x: (0 if x.endswith((".main", ".app")) else 1, len(x)))
    return candidates[0]


def main() -> int:
    try:
        # Syntax/AST validation for every Python file.
        for path in ROOT.rglob("*.py"):
            ast.parse(path.read_text(errors="replace"), filename=str(path))
        check("CB1-PRE-001", True, "All Python files parse")

        # Frozen-baseline and approved-scope traceability.
        control = ROOT / "control"
        check("CB1-PRE-002", (control / "BUILD-PROVENANCE.json").exists(), "Build provenance present")
        provenance = json.loads((control / "BUILD-PROVENANCE.json").read_text())
        check("CB1-PRE-003", provenance.get("version") == "5.3.1-final-production-corrections-po1", json.dumps(provenance, sort_keys=True))

        # No malformed literal double-brace route parameters remain.
        bad = []
        for path in ROOT.rglob("*.py"):
            text = path.read_text(errors="replace")
            if re.search(r"@[A-Za-z0-9_\.]+\.(?:get|post|put|patch|delete)\([^\n]*\{\{", text):
                bad.append(str(path.relative_to(ROOT)))
        check("CB1-PRE-004", not bad, "Malformed route files: " + ", ".join(bad))

        # Required generated correction modules/assets.
        required = [
            "rmr_platform/cb1_models.py",
            "rmr_platform/cb1_services.py",
            "rmr_platform/cb1_router.py",
            "rmr_platform/cb1_worker.py",
            "rmr_platform/cb1_migration.py",
            "templates/cb1_commercial.html",
            "templates/cb1_activate.html",
            "public/cb1.css",
            "public/cb1_enhancements.js",
            "docker-compose.postgres.yml",
        ]
        missing = [x for x in required if not (ROOT / x).exists()]
        check("CB1-PRE-005", not missing, "Missing: " + ", ".join(missing))

        # Static contract checks.
        all_text = "\n".join(p.read_text(errors="replace") for p in ROOT.rglob("*.py"))
        all_ui = "\n".join(p.read_text(errors="replace") for p in [ROOT / "public/cb1_enhancements.js", ROOT / "templates/cb1_commercial.html", ROOT / "public/cb1.css"] if p.exists())
        terms = {
            "CB1-PRE-006": "Client Administrator",
            "CB1-PRE-007": "Data Custody",
            "CB1-PRE-008": "Microsoft",
            "CB1-PRE-009": "Gmail",
            "CB1-PRE-010": "SMTP",
            "CB1-PRE-011": "Copy Post",
            "CB1-PRE-012": "Commercial Readiness",
            "CB1-PRE-013": "show password",
        }
        corpus = all_text + all_ui
        for cid, term in terms.items():
            check(cid, term.lower() in corpus.lower(), f"Required term/control: {term}")

        with tempfile.TemporaryDirectory(prefix="rmr-cb1-") as td:
            db_path = Path(td) / "cb1.sqlite3"
            os.environ["RMR_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
            os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
            os.environ["RMR_DATA_DIR"] = td
            os.environ["RMR_APP_VERSION"] = "5.3.1-final-production-corrections-po1"
            os.environ["RMR_AUTO_MIGRATE"] = "true"
            os.environ["RMR_AUTO_SEED"] = "false"
            os.environ["RMR_PAYMENT_PROVIDER"] = "mock"
            os.environ.setdefault("RMR_SECRET_KEY", "cb1-preflight-only-not-production")
            os.environ.setdefault("RMR_ENCRYPTION_KEY", "cb1-preflight-encryption-key")
            sys.path.insert(0, str(ROOT))
            module_name = find_app_module()
            module = importlib.import_module(module_name)
            app = getattr(module, "app")
            check("CB1-PRE-014", app is not None, module_name)

            routes = []
            for route in getattr(app, "routes", []):
                routes.append({"path": getattr(route, "path", ""), "methods": sorted(getattr(route, "methods", []) or [])})
            route_paths = [x["path"] for x in routes]
            check("CB1-PRE-015", "/commercial" in route_paths, json.dumps(route_paths))
            check("CB1-PRE-016", not any("{{" in x or "}}" in x for x in route_paths), json.dumps(route_paths))
            required_route_fragments = [
                "/api/cb1/client-admin",
                "/api/cb1/custody",
                "/api/cb1/exports",
                "/api/cb1/provider-connections",
                "/api/cb1/campaigns",
                "/api/cb1/social",
                "/api/cb1/commercial-readiness",
            ]
            for i, fragment in enumerate(required_route_fragments, start=17):
                check(f"CB1-PRE-{i:03d}", any(p.startswith(fragment) for p in route_paths), fragment)

            # Route precedence: /commercial must occur before any catch-all route.
            commercial_idx = route_paths.index("/commercial")
            catch_idxs = [i for i,p in enumerate(route_paths) if "{path:path}" in p or p in ("/{path}", "/{full_path:path}")]
            check("CB1-PRE-024", not catch_idxs or commercial_idx < min(catch_idxs), f"commercial={commercial_idx}, catch={catch_idxs}")

            # Exercise public health and commercial pages through ASGI TestClient.
            from fastapi.testclient import TestClient
            with TestClient(app) as client:
                health = client.get("/api/health")
                check("CB1-PRE-025", health.status_code == 200, health.text[:1000])
                version = health.json().get("version", "")
                check("CB1-PRE-026", "5.3.1-final-production-corrections-po1" in version, version)
                commercial = client.get("/commercial")
                check("CB1-PRE-027", commercial.status_code == 401, commercial.text[:500])
                commercial_template = (ROOT / "templates" / "cb1_commercial.html").read_text(errors="replace")
                check("CB1-PRE-028", "Commercial Readiness" in commercial_template, commercial_template[:500])
                activate = client.get("/activate-client-admin?token=cb1-invalid-token")
                check("CB1-PRE-029", activate.status_code == 200, f"status={activate.status_code}")

        payload = {
            "status": "passed",
            "release": "5.3.1-final-production-corrections-po1",
            "passed": sum(1 for c in checks if c["pass"]),
            "failed": 0,
            "checks": checks,
        }
        RESULT.write_text(json.dumps(payload, indent=2))
        print(json.dumps(payload, indent=2))
        return 0
    except Exception as exc:
        payload = {
            "status": "failed",
            "release": "5.3.1-final-production-corrections-po1",
            "passed": sum(1 for c in checks if c["pass"]),
            "failed": 1,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "checks": checks,
        }
        RESULT.write_text(json.dumps(payload, indent=2))
        print(json.dumps(payload, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
