#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BASELINE_SHA256 = "aef36b9636fe20035b1276acb47d993785d06e002eab0c544a0df44429699653"
EXCLUDED_PARTS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", "product-owner-data", "product-owner-data-archive", "v531-final-logs"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
RUNTIME_FILES = {".env", ".env.product-owner", "rmr_platform.db", "rmr_platform.db-shm", "rmr_platform.db-wal"}


def include(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in rel.parts):
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    if rel.name in RUNTIME_FILES:
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


def inventory(root: Path) -> dict[str, dict[str, object]]:
    return {
        path.relative_to(root).as_posix(): {"size": path.stat().st_size, "sha256": digest(path)}
        for path in root.rglob("*")
        if include(path, root)
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "qa" / "V531-BASELINE-PRESERVATION-RESULTS.json")
    args = parser.parse_args()

    checks: list[dict[str, object]] = []
    def check(name: str, passed: bool, detail: object = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))

    baseline_hash = digest(args.baseline)
    check("Exact frozen v5.3 source artifact hash", baseline_hash == EXPECTED_BASELINE_SHA256, baseline_hash)

    control = json.loads((args.candidate / "control" / "V531-AUTHORIZED-CHANGESET.json").read_text(encoding="utf-8"))
    allowed_changed = set(control.get("allowed_changed_files", []))
    allowed_added = set(control.get("allowed_added_files", []))
    protected = set(control.get("protected_unchanged_files", []))

    with tempfile.TemporaryDirectory(prefix="rmr-v53-baseline-") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(args.baseline) as archive:
            bad = archive.testzip()
            check("Frozen v5.3 ZIP integrity", bad is None, bad or "CRC clean")
            archive.extractall(tmp_path)
        roots = [p for p in tmp_path.iterdir() if p.is_dir()]
        check("Frozen v5.3 ZIP has one application root", len(roots) == 1, [p.name for p in roots])
        if len(roots) != 1:
            raise SystemExit(1)
        base_root = roots[0]
        baseline = inventory(base_root)
        candidate = inventory(args.candidate)

    changed = sorted(name for name in baseline.keys() & candidate.keys() if baseline[name] != candidate[name])
    added = sorted(candidate.keys() - baseline.keys())
    removed = sorted(baseline.keys() - candidate.keys())
    unauthorized_changed = sorted(set(changed) - allowed_changed)
    unauthorized_added = sorted(set(added) - allowed_added)
    declared_but_unchanged = sorted(allowed_changed - set(changed))
    declared_added_missing = sorted(allowed_added - set(added))

    check("No baseline files were removed", not removed, removed)
    check("All changed baseline files are authorized", not unauthorized_changed, unauthorized_changed)
    check("All added files are authorized", not unauthorized_added, unauthorized_added)
    check("Authorized changed-file inventory is exact", not declared_but_unchanged, declared_but_unchanged)
    check("Authorized added-file inventory is exact", not declared_added_missing, declared_added_missing)

    protected_failures = []
    for name in sorted(protected):
        if name not in baseline or name not in candidate or baseline[name] != candidate[name]:
            protected_failures.append(name)
    check("Protected database, schema, permission and security files are byte-identical", not protected_failures, protected_failures)

    result = {
        "status": "passed" if all(row["passed"] for row in checks) else "failed",
        "release": "5.3.1-final-production-corrections-po1",
        "baseline_artifact": args.baseline.name,
        "baseline_sha256": baseline_hash,
        "baseline_file_count": len(baseline),
        "candidate_file_count": len(candidate),
        "unchanged_file_count": len(set(baseline) & set(candidate)) - len(changed),
        "authorized_changed_files": changed,
        "authorized_added_files": added,
        "removed_files": removed,
        "unauthorized_changed_files": unauthorized_changed,
        "unauthorized_added_files": unauthorized_added,
        "protected_files": sorted(protected),
        "checks": checks,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "passed": sum(1 for row in checks if row["passed"]), "failed": sum(1 for row in checks if not row["passed"]), "output": str(args.output)}, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
