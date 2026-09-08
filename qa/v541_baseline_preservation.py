#!/usr/bin/env python3
"""Exact source-preservation gate for RMR Global v5.4.0 -> v5.4.1."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_V54_ZIP_SHA256 = "a814b8fd36a1e7fad09963f3186075b8596975141508ef350436384494ee0300"
EXPECTED_V531_ZIP_SHA256 = "d188a52eab6494cb61bcecd828616d4bc17a1fa30cd5ddd2ff54e28555b5f1bf"
RELEASE = "5.4.1-four-workspace-themes-po1"
BASELINE_RELEASE = "5.4.0-tenant-themes-po1"
EXCLUDED_PARTS = {
    "__pycache__", ".git", ".pytest_cache", ".mypy_cache",
    "product-owner-data", "product-owner-data-archive",
    "product-owner-data-v54", "product-owner-data-v54-archive",
    "product-owner-data-v541", "product-owner-data-v541-archive",
    "v531-final-logs",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
RUNTIME_FILES = {
    ".env", ".env.product-owner", ".env.product-owner-v54", ".env.product-owner-v541",
    "rmr_platform.db", "rmr_platform.db-shm", "rmr_platform.db-wal",
}
PACKAGING_METADATA = {"PACKAGE-MANIFEST.json"}


def include(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if rel.as_posix() in PACKAGING_METADATA:
        return False
    if any(part in EXCLUDED_PARTS for part in rel.parts):
        return False
    if path.suffix in EXCLUDED_SUFFIXES or rel.name in RUNTIME_FILES:
        return False
    if rel.parts and rel.parts[0] == "data" and rel.name != ".gitkeep":
        return False
    return path.is_file()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inventory(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in root.rglob("*"):
        if include(path, root):
            result[path.relative_to(root).as_posix()] = {"size": path.stat().st_size, "sha256": digest(path)}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, default=ROOT)
    parser.add_argument("--baseline-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "qa/V541-BASELINE-PRESERVATION-RESULTS.json")
    args = parser.parse_args()

    baseline_root = args.baseline_root.resolve()
    candidate_root = args.candidate.resolve()
    baseline_zip = args.baseline_zip.resolve()
    output = args.output.resolve()
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: Any = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))

    actual_zip_hash = digest(baseline_zip) if baseline_zip.is_file() else "missing"
    check("Canonical v5.4.0 ZIP is present and byte-exact", actual_zip_hash == EXPECTED_V54_ZIP_SHA256, actual_zip_hash)
    bad_member = "not tested"
    if baseline_zip.is_file():
        with zipfile.ZipFile(baseline_zip) as archive:
            bad_member = archive.testzip()
    check("Canonical v5.4.0 ZIP has clean CRC integrity", bad_member is None, bad_member or "CRC clean")

    seal_path = candidate_root / "control/V531-PRODUCTION-BASELINE-SEAL.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8")) if seal_path.is_file() else {}
    check("Frozen v5.3.1 production seal remains canonical", seal.get("canonical_sha256") == EXPECTED_V531_ZIP_SHA256 and seal.get("status") == "sealed_unchanged", seal)

    control_path = candidate_root / "control/V541-AUTHORIZED-CHANGESET.json"
    control = json.loads(control_path.read_text(encoding="utf-8"))
    check("Authorized change set identifies exact v5.4.0 source", control.get("source_sha256") == EXPECTED_V54_ZIP_SHA256, control.get("source_sha256"))
    allowed_changed = set(control.get("allowed_changed_files", []))
    allowed_added = set(control.get("allowed_added_files", []))
    protected = set(control.get("protected_unchanged_files", []))

    baseline = inventory(baseline_root)
    candidate = inventory(candidate_root)
    changed = sorted(name for name in baseline.keys() & candidate.keys() if baseline[name] != candidate[name])
    added = sorted(candidate.keys() - baseline.keys())
    removed = sorted(baseline.keys() - candidate.keys())
    unauthorized_changed = sorted(set(changed) - allowed_changed)
    unauthorized_added = sorted(set(added) - allowed_added)
    declared_changed_missing = sorted(allowed_changed - set(changed))
    declared_added_missing = sorted(allowed_added - set(added))

    check("No v5.4.0 source file was removed", not removed, removed)
    check("Every changed v5.4.0 file is explicitly authorized", not unauthorized_changed, unauthorized_changed)
    check("Every added v5.4.1 file is explicitly authorized", not unauthorized_added, unauthorized_added)
    check("Authorized changed inventory exactly matches candidate", not declared_changed_missing, declared_changed_missing)
    check("Authorized added inventory exactly matches candidate", not declared_added_missing, declared_added_missing)

    protected_failures: list[str] = []
    for name in sorted(protected):
        if name not in baseline or name not in candidate or baseline[name] != candidate[name]:
            protected_failures.append(name)
    check("Protected business, security, CRM, website, role, and permission files remain byte-identical", not protected_failures, protected_failures)

    public_site = "templates/public_site.html"
    check("Kerry public website template remains byte-identical", baseline.get(public_site) == candidate.get(public_site), candidate.get(public_site))
    check("Only the additive v5.4.1 migration is introduced", "rmr_platform/migrations.py" in changed and not any(name.startswith("rmr_platform/models.py") for name in changed))

    passed = sum(1 for row in checks if row["passed"])
    failed = len(checks) - passed
    result = {
        "status": "passed" if failed == 0 else "failed",
        "release": RELEASE,
        "baseline_release": BASELINE_RELEASE,
        "baseline_artifact": baseline_zip.name,
        "baseline_sha256": actual_zip_hash,
        "frozen_v531_sha256": EXPECTED_V531_ZIP_SHA256,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_file_count": len(baseline),
        "candidate_file_count": len(candidate),
        "unchanged_baseline_file_count": len(set(baseline) & set(candidate)) - len(changed),
        "authorized_changed_files": changed,
        "authorized_added_files": added,
        "removed_files": removed,
        "unauthorized_changed_files": unauthorized_changed,
        "unauthorized_added_files": unauthorized_added,
        "protected_unchanged_files": sorted(protected),
        "passed": passed,
        "failed": failed,
        "checks": checks,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "passed": passed, "failed": failed, "output": str(output)}, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
