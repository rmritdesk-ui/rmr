from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RELEASE = "5.4.1-four-workspace-themes-po1"
MIGRATION = "005.006.100-four-workspace-themes"
BASELINE_MIGRATION = "005.006.000-tenant-themes"


def run(root: Path, args: list[str], data_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(root),
        "RMR_DATA_DIR": str(data_dir),
        "RMR_ENVIRONMENT": "pilot",
        "RMR_INSTALL_PROFILE": "demo",
        "RMR_ALLOW_DEMO_CREDENTIALS": "true",
        "RMR_AUTO_MIGRATE": "true",
        "RMR_AUTO_SEED": "false",
        "RMR_SECRET_KEY": "upgrade-preservation-test-secret",
        "RMR_CREDENTIAL_ENCRYPTION_KEY": "upgrade-preservation-test-key",
        "RMR_INTEGRATION_ENCRYPTION_KEY": "upgrade-preservation-test-key",
    })
    return subprocess.run(
        ["python3", *args], cwd=root, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def snapshot(db_path: Path) -> dict[str, Any]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    data: dict[str, Any] = {"tables": tables, "schemas": {}, "rows": {}, "counts": {}}
    for table in tables:
        columns = [r[1] for r in con.execute(f"PRAGMA table_info({quote(table)})")]
        data["schemas"][table] = columns
        rows = [dict(r) for r in con.execute(f"SELECT * FROM {quote(table)} ORDER BY rowid")]
        data["rows"][table] = rows
        data["counts"][table] = len(rows)
    con.close()
    return data


def add(checks: list[dict[str, Any]], name: str, passed: bool, detail: Any) -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-root", required=True)
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    baseline = Path(args.baseline_root).resolve()
    candidate = Path(args.candidate_root).resolve()
    work = Path(args.work_dir).resolve()
    output = Path(args.output).resolve()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    data_dir = work / "data"
    data_dir.mkdir()
    checks: list[dict[str, Any]] = []

    baseline_run = run(baseline, ["-m", "rmr_platform.cli", "seed"], data_dir)
    add(checks, "Exact v5.4.0 baseline can create its complete demo/reference database", baseline_run.returncode == 0, {"exit_code": baseline_run.returncode, "stdout": baseline_run.stdout[-1000:], "stderr": baseline_run.stderr[-1000:]})
    db_path = data_dir / "rmr_platform.db"
    add(checks, "Baseline database file was created", db_path.is_file(), str(db_path))
    before = snapshot(db_path) if db_path.is_file() else {"tables": [], "schemas": {}, "rows": {}, "counts": {}}
    before_migrations = [r.get("version") for r in before.get("rows", {}).get("schema_migrations", [])]
    add(checks, "Baseline migration history ends at v5.4.0 tenant themes", bool(before_migrations and before_migrations[-1] == BASELINE_MIGRATION), before_migrations)
    before_tenants = {r.get("slug"): r.get("id") for r in before.get("rows", {}).get("tenants", [])}
    add(checks, "Baseline contains Kerry and CAF", {"kerry-real-estate", "cactus-air-filters"}.issubset(before_tenants), before_tenants)
    before_users = {r.get("email"): r.get("id") for r in before.get("rows", {}).get("users", [])}

    candidate_run = run(candidate, ["-m", "rmr_platform.cli", "migrate"], data_dir)
    add(checks, "v5.4.1 additive migration completes against the v5.4.0 database", candidate_run.returncode == 0, {"exit_code": candidate_run.returncode, "stdout": candidate_run.stdout[-1500:], "stderr": candidate_run.stderr[-1500:]})
    after = snapshot(db_path) if db_path.is_file() else {"tables": [], "schemas": {}, "rows": {}, "counts": {}}
    after_migrations = [r.get("version") for r in after.get("rows", {}).get("schema_migrations", [])]
    add(checks, "Migration history appends only the v5.4.1 four-theme migration", after_migrations == before_migrations + [MIGRATION], {"before": before_migrations, "after": after_migrations})
    add(checks, "No existing database table is removed or replaced", set(after["tables"]) == set(before["tables"]), {"before": before["tables"], "after": after["tables"]})

    schema_changes = {t: {"before": before["schemas"][t], "after": after["schemas"][t]} for t in before["tables"] if before["schemas"][t] != after["schemas"][t]}
    add(checks, "Only tenant_themes schema changes", set(schema_changes) == {"tenant_themes"}, schema_changes)
    expected_columns = before["schemas"].get("tenant_themes", []) + ["workspace_style"]
    add(checks, "tenant_themes receives exactly one additive workspace_style column", after["schemas"].get("tenant_themes") == expected_columns, after["schemas"].get("tenant_themes"))

    count_changes = {t: {"before": before["counts"][t], "after": after["counts"][t]} for t in before["tables"] if before["counts"][t] != after["counts"][t]}
    add(checks, "Business-record counts remain unchanged", set(count_changes).issubset({"schema_migrations"}) and count_changes.get("schema_migrations", {}).get("after") == count_changes.get("schema_migrations", {}).get("before", -1) + 1, count_changes)

    exact_rows_ok = True
    exact_row_differences: list[str] = []
    for table in before["tables"]:
        if table in {"schema_migrations", "tenant_themes"}:
            continue
        if before["rows"][table] != after["rows"][table]:
            exact_rows_ok = False
            exact_row_differences.append(table)
    add(checks, "Every pre-existing business row outside tenant_themes is byte-for-byte unchanged", exact_rows_ok, exact_row_differences)

    before_theme_columns = before["schemas"].get("tenant_themes", [])
    normalized_after_themes = [{key: row.get(key) for key in before_theme_columns} for row in after["rows"].get("tenant_themes", [])]
    add(checks, "All existing tenant branding values are preserved exactly", normalized_after_themes == before["rows"].get("tenant_themes", []), {"before": before["rows"].get("tenant_themes", []), "after_common": normalized_after_themes})
    add(checks, "Existing v5.4.0 tenant themes receive safe Classic Blue preset default", all(row.get("workspace_style") == "classic-blue" for row in after["rows"].get("tenant_themes", [])), [row.get("workspace_style") for row in after["rows"].get("tenant_themes", [])])

    after_tenants = {r.get("slug"): r.get("id") for r in after["rows"].get("tenants", [])}
    after_users = {r.get("email"): r.get("id") for r in after["rows"].get("users", [])}
    add(checks, "Tenant IDs remain stable through upgrade", after_tenants == before_tenants, {"before": before_tenants, "after": after_tenants})
    add(checks, "User IDs remain stable through upgrade", after_users == before_users, {"before_count": len(before_users), "after_count": len(after_users)})

    status = "passed" if all(c["passed"] for c in checks) else "failed"
    result = {
        "status": status,
        "release": RELEASE,
        "source_baseline": "5.4.0-tenant-themes-po1",
        "source_sha256": "a814b8fd36a1e7fad09963f3186075b8596975141508ef350436384494ee0300",
        "migration": MIGRATION,
        "passed": sum(c["passed"] for c in checks),
        "failed": sum(not c["passed"] for c in checks),
        "checks": checks,
        "database_sha256_after": hashlib.sha256(db_path.read_bytes()).hexdigest() if db_path.is_file() else "",
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "passed", "failed", "migration")}, indent=2))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
