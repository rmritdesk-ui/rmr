#!/usr/bin/env python3
"""Evidence utility for the sealed v5.3.1 -> v5.4 additive upgrade.

This utility deliberately does not spawn application initializers. Run the
sealed baseline initialization and the v5.4 migration as separate processes,
then use this file to snapshot and compare the same SQLite database. Keeping
processes separate avoids module/configuration leakage between source trees.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RELEASE = "5.4.0-tenant-themes-po1"
BASELINE_RELEASE = "5.3.1-final-production-corrections-po1"
BASELINE_SHA256 = "d188a52eab6494cb61bcecd828616d4bc17a1fa30cd5ddd2ff54e28555b5f1bf"
NEW_MIGRATION = "005.006.000-tenant-themes"
PRIOR_MIGRATION = "005.005.000-cumulative-product-repair"
EXCLUDED_FROM_ROW_EQUALITY = {"schema_migrations", "tenant_themes"}


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _canonical_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    return value


def snapshot_database(db_path: Path) -> dict[str, Any]:
    if not db_path.is_file():
        raise FileNotFoundError(f"Database does not exist: {db_path}")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        table_results: dict[str, Any] = {}
        for table in tables:
            quoted = _quoted(table)
            columns = [
                {
                    "name": str(row[1]),
                    "type": str(row[2]),
                    "not_null": bool(row[3]),
                    "default": row[4],
                    "primary_key_order": int(row[5]),
                }
                for row in connection.execute(f"PRAGMA table_info({quoted})")
            ]
            canonical_rows: list[str] = []
            for row in connection.execute(f"SELECT * FROM {quoted}"):
                item = {
                    key: _canonical_value(value)
                    for key, value in dict(row).items()
                }
                canonical_rows.append(
                    json.dumps(item, sort_keys=True, default=str, separators=(",", ":"))
                )
            digest = hashlib.sha256()
            for encoded in sorted(canonical_rows):
                digest.update(encoded.encode("utf-8"))
                digest.update(b"\n")
            table_results[table] = {
                "columns": columns,
                "row_count": len(canonical_rows),
                "row_sha256": digest.hexdigest(),
            }

        tenant_ids: dict[str, str] = {}
        user_ids: dict[str, str] = {}
        if "tenants" in tables:
            tenant_ids = {
                str(row["slug"]): str(row["id"])
                for row in connection.execute("SELECT id, slug FROM tenants ORDER BY slug")
            }
        if "users" in tables:
            user_ids = {
                str(row["email"]): str(row["id"])
                for row in connection.execute("SELECT id, email FROM users ORDER BY email")
            }
        migrations: list[str] = []
        if "schema_migrations" in tables:
            migrations = [
                str(row[0])
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY applied_at, version"
                )
            ]
        themes: dict[str, dict[str, Any]] = {}
        if "tenant_themes" in tables and "tenants" in tables:
            themes = {
                str(row["slug"]): {
                    "primary_color": row["primary_color"],
                    "secondary_color": row["secondary_color"],
                    "accent_color": row["accent_color"],
                    "font_family": row["font_family"],
                    "enabled": bool(row["enabled"]),
                }
                for row in connection.execute(
                    "SELECT t.slug, th.primary_color, th.secondary_color, "
                    "th.accent_color, th.font_family, th.enabled "
                    "FROM tenant_themes th JOIN tenants t ON t.id=th.tenant_id "
                    "ORDER BY t.slug"
                )
            }
        return {
            "database": str(db_path.resolve()),
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "tables": table_results,
            "tenant_ids": tenant_ids,
            "user_ids": user_ids,
            "migrations": migrations,
            "themes": themes,
        }
    finally:
        connection.close()


def compare_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: Any = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    before_tables = before.get("tables", {})
    after_tables = after.get("tables", {})
    removed = sorted(set(before_tables) - set(after_tables))
    introduced = sorted(set(after_tables) - set(before_tables))
    common_business = sorted(
        (set(before_tables) & set(after_tables)) - EXCLUDED_FROM_ROW_EQUALITY
    )
    changed = {
        table: {"before": before_tables[table], "after": after_tables[table]}
        for table in common_business
        if before_tables[table] != after_tables[table]
    }

    check("No v5.3.1 database table was removed", not removed, removed)
    check(
        "All pre-existing business table definitions and rows were preserved",
        not changed,
        changed,
    )
    check(
        "Tenant identities were preserved",
        before.get("tenant_ids") == after.get("tenant_ids"),
        {"before": before.get("tenant_ids"), "after": after.get("tenant_ids")},
    )
    check(
        "User identities were preserved",
        before.get("user_ids") == after.get("user_ids"),
        {
            "before_count": len(before.get("user_ids", {})),
            "after_count": len(after.get("user_ids", {})),
        },
    )
    check(
        "Kerry and CAF remain present after upgrade",
        {"kerry-real-estate", "cactus-air-filters"}.issubset(
            set(after.get("tenant_ids", {}))
        ),
        sorted(after.get("tenant_ids", {})),
    )
    check(
        "Only the authorized tenant_themes table was introduced",
        introduced == ["tenant_themes"],
        introduced,
    )
    migrations = list(after.get("migrations", []))
    check(
        "All prior migration history was retained",
        set(before.get("migrations", [])).issubset(set(migrations)),
        {"before": before.get("migrations", []), "after": migrations},
    )
    check(
        "The additive tenant-theme migration is current",
        bool(migrations)
        and migrations[-1] == NEW_MIGRATION
        and PRIOR_MIGRATION in migrations,
        migrations,
    )
    theme_table = after_tables.get("tenant_themes", {})
    check(
        "The tenant-theme table contains only the two isolated PO demo themes",
        theme_table.get("row_count") == 2,
        theme_table,
    )
    themes = after.get("themes", {})
    check(
        "Kerry and CAF received distinct tenant-scoped demo themes",
        themes.get("kerry-real-estate", {}).get("primary_color") == "#173F73"
        and themes.get("cactus-air-filters", {}).get("primary_color") == "#146B52"
        and themes.get("kerry-real-estate") != themes.get("cactus-air-filters"),
        themes,
    )

    passed = sum(1 for row in checks if row["passed"])
    failed = len(checks) - passed
    return {
        "status": "passed" if failed == 0 else "failed",
        "release": RELEASE,
        "baseline_release": BASELINE_RELEASE,
        "baseline_artifact_sha256": BASELINE_SHA256,
        "migration": NEW_MIGRATION,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "failed": failed,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--database", type=Path, required=True)
    snapshot_parser.add_argument("--output", type=Path, required=True)

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--before", type=Path, required=True)
    compare_parser.add_argument("--after", type=Path, required=True)
    compare_parser.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "snapshot":
        payload = snapshot_database(args.database.resolve())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        print(json.dumps({"status": "passed", "tables": len(payload["tables"]), "output": str(args.output)}, indent=2))
        return 0

    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    result = compare_snapshots(before, after)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    for row in result["checks"]:
        print(f"[{'PASS' if row['passed'] else 'FAIL'}] {row['name']}")
    print(json.dumps({"status": result["status"], "passed": result["passed"], "failed": result["failed"], "output": str(args.output)}, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
