#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

BASELINE_SHA256 = "2c528badcf90c1683d68f45a59d5d5004cc82cf3ed1d8d4bd1c4fb901b6fc22f"
OLD_RELEASE = "5.1.0-commercial-cb1-r2"
NEW_RELEASE = "5.3.1-final-production-corrections-po1"
NEW_MIGRATION = "005.005.000-cumulative-product-repair"

TABLES = [
    "tenants", "users", "service_catalog", "tenant_services", "economic_transactions",
    "onboarding_projects", "onboarding_steps", "accounts", "contacts", "leads",
    "opportunities", "activities", "forecast_versions", "forecast_months",
    "training_resources", "training_progress", "website_sites", "website_pages",
    "website_sections", "campaigns", "piq_opportunities", "audit_events",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)


def db_snapshot(path: Path) -> dict[str, object]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    result: dict[str, object] = {"tables": {}, "tenants": [], "caf": {}, "kerry": {}, "migrations": []}
    try:
        names = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
        for table in TABLES:
            if table in names:
                result["tables"][table] = connection.execute(f"select count(*) from {table}").fetchone()[0]  # type: ignore[index]
        result["tenants"] = [dict(row) for row in connection.execute(
            "select id,name,slug,industry,status,website_mode,website_url,adoption_score,training_completion_pct,health_status,renewal_risk from tenants order by slug"
        )]
        for key, slug in (("caf", "cactus-air-filters"), ("kerry", "kerry-real-estate")):
            tenant = connection.execute("select * from tenants where slug=?", (slug,)).fetchone()
            if not tenant:
                continue
            tenant_id = tenant["id"]
            tenant_data: dict[str, object] = {"tenant": dict(tenant)}
            tenant_data["services"] = [dict(row) for row in connection.execute(
                "select * from tenant_services where tenant_id=? order by service_code", (tenant_id,)
            )]
            project = connection.execute("select * from onboarding_projects where tenant_id=?", (tenant_id,)).fetchone()
            tenant_data["onboarding_project"] = dict(project) if project else {}
            tenant_data["onboarding"] = [dict(row) for row in connection.execute(
                "select * from onboarding_steps where project_id=? order by stage_number", (project["id"],)
            )] if project else []
            tenant_data["crm_counts"] = {
                table: connection.execute(f"select count(*) from {table} where tenant_id=?", (tenant_id,)).fetchone()[0]
                for table in ("accounts", "contacts", "leads", "opportunities", "activities") if table in names
            }
            result[key] = tenant_data
        result["migrations"] = [row[0] for row in connection.execute("select version from schema_migrations order by applied_at")]
    finally:
        connection.close()
    return result


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-zip", default="/mnt/data/RMR-Software-v5.1-Commercial-Candidate-Correction-Build-1-Revision-2-Product-Owner-Test.zip")
    parser.add_argument("--candidate-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", default=str(Path(__file__).resolve().with_name("V531-UPGRADE-PRESERVATION-RESULTS.json")))
    args = parser.parse_args()

    baseline_zip = Path(args.baseline_zip).resolve()
    candidate_root = Path(args.candidate_root).resolve()
    output = Path(args.output).resolve()
    checks: list[dict[str, object]] = []

    def check(name: str, ok: bool, detail: object = "") -> None:
        checks.append({"name": name, "passed": bool(ok), "detail": detail})

    check("Frozen CB1-R2 artifact exists", baseline_zip.is_file(), str(baseline_zip))
    actual_hash = sha256(baseline_zip) if baseline_zip.is_file() else ""
    check("Frozen CB1-R2 SHA-256 matches accepted baseline", actual_hash == BASELINE_SHA256, actual_hash)

    with tempfile.TemporaryDirectory(prefix="rmr-v531-upgrade-") as temp_value:
        temp = Path(temp_value)
        extract_dir = temp / "baseline"
        baseline_data = temp / "baseline-data"
        upgrade_data = temp / "upgrade-data"
        extract_dir.mkdir()
        baseline_data.mkdir()
        upgrade_data.mkdir()
        with ZipFile(baseline_zip) as archive:
            archive.extractall(extract_dir)
        candidates = [p for p in extract_dir.iterdir() if p.is_dir()]
        baseline_root = candidates[0] if len(candidates) == 1 else extract_dir

        base_env = os.environ.copy()
        base_env.update({
            "PYTHONPATH": str(baseline_root), "RMR_DATA_DIR": str(baseline_data),
            "RMR_ENVIRONMENT": "pilot", "RMR_AUTO_MIGRATE": "true", "RMR_AUTO_SEED": "false",
            "RMR_ALLOW_DEMO_CREDENTIALS": "true", "RMR_SECRET_KEY": "upgrade-preservation-baseline-secret",
            "RMR_APP_VERSION": OLD_RELEASE,
        })
        baseline_run = run([sys.executable, "-m", "rmr_platform.cli", "reset-demo"], baseline_root, base_env)
        check("Frozen CB1-R2 controlled predecessor database created", baseline_run.returncode == 0, {"stdout": baseline_run.stdout[-1000:], "stderr": baseline_run.stderr[-1000:]})
        baseline_db = baseline_data / "rmr_platform.db"
        check("Controlled predecessor database exists", baseline_db.is_file() and baseline_db.stat().st_size > 0, baseline_db.stat().st_size if baseline_db.exists() else 0)
        before = db_snapshot(baseline_db)
        check("Controlled predecessor includes Kerry tenant", bool(before.get("kerry")), before.get("kerry", {}))
        check("Controlled predecessor includes customer portfolio", int(before.get("tables", {}).get("tenants", 0)) >= 1, before.get("tables", {}))

        # Copy only the coherent SQLite database after closing the baseline process.
        shutil.copy2(baseline_db, upgrade_data / "rmr_platform.db")
        candidate_env = os.environ.copy()
        candidate_env.update({
            "PYTHONPATH": str(candidate_root), "RMR_DATA_DIR": str(upgrade_data),
            "RMR_ENVIRONMENT": "pilot", "RMR_AUTO_MIGRATE": "true", "RMR_AUTO_SEED": "false",
            "RMR_ALLOW_DEMO_CREDENTIALS": "true", "RMR_SECRET_KEY": "upgrade-preservation-candidate-secret",
            "RMR_APP_VERSION": NEW_RELEASE,
        })
        migration_run = run([sys.executable, "-m", "rmr_platform.cli", "migrate"], candidate_root, candidate_env)
        check("v5.3.1 cumulative additive migration command succeeds", migration_run.returncode == 0, {"stdout": migration_run.stdout[-2000:], "stderr": migration_run.stderr[-2000:]})
        upgraded_db = upgrade_data / "rmr_platform.db"
        after = db_snapshot(upgraded_db)

        check("All predecessor table row counts preserved", before.get("tables") == after.get("tables"), {"before": before.get("tables"), "after": after.get("tables")})
        check("All predecessor tenant records preserved byte-for-byte at field level", canonical(before.get("tenants")) == canonical(after.get("tenants")), {"before_count": len(before.get("tenants", [])), "after_count": len(after.get("tenants", []))})
        check("CAF tenant/services/onboarding/CRM evidence preserved", canonical(before.get("caf")) == canonical(after.get("caf")), {"before": before.get("caf"), "after": after.get("caf")})
        check("Kerry tenant/services/onboarding/CRM evidence preserved", canonical(before.get("kerry")) == canonical(after.get("kerry")), {"before": before.get("kerry"), "after": after.get("kerry")})
        before_migrations = list(before.get("migrations", []))
        after_migrations = list(after.get("migrations", []))
        check("All prior migration records preserved", all(item in after_migrations for item in before_migrations), {"before": before_migrations, "after": after_migrations})
        check("Required cumulative additive migration remains current", after_migrations and after_migrations[-1] == NEW_MIGRATION, after_migrations)
        new_tables = set()
        con = sqlite3.connect(upgraded_db)
        try:
            new_tables = {row[0] for row in con.execute("select name from sqlite_master where type='table'")}
        finally:
            con.close()
        expected_new = {
            "website_media", "website_blog_posts", "website_resources", "website_team_profiles",
            "appointment_requests", "seo_work_items", "piq_target_profiles", "piq_evidence",
            "piq_import_batches", "managed_tenant_sessions",
            "v521_client_training_resources", "v521_client_training_assignments", "v521_forecast_import_batches",
            "v521_campaign_export_packages", "v521_social_generation_metadata", "v521_solution_request_preferences",
            "v521_email_connection_events",
            "v522_client_service_commercial_terms", "v522_commercial_term_history",
            "v522_message_delivery_context", "v522_social_content_revisions",
        }
        check("All cumulative additive product tables remain present", expected_new.issubset(new_tables), sorted(expected_new - new_tables))

    result = {
        "status": "passed" if all(row["passed"] for row in checks) else "failed",
        "release": NEW_RELEASE,
        "baseline_release": OLD_RELEASE,
        "baseline_sha256": actual_hash,
        "checks": checks,
        "passed": sum(1 for row in checks if row["passed"]),
        "failed": sum(1 for row in checks if not row["passed"]),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "passed": result["passed"], "failed": result["failed"], "output": str(output)}, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
