#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MANIFEST_NAME = "PACKAGE-MANIFEST.json"
RELEASE = "5.4.1.2-interaction-regression-correction-po1"
ARTIFACT = "RMR Global v5.4.1.2 Interaction Regression Correction Windows/Docker Product Owner Candidate - Packaging Correction C"
SELF_REFERENTIAL_EVIDENCE = {
    "qa/V5412-CLEAN-EXTRACTION-RESULTS.json",
    "qa/V5412-PACKAGE-INTEGRITY.json",
    "qa/V5412-FINAL-VALIDATION-SUMMARY.json",
    "qa/V5412C-CLEAN-EXTRACTION-RESULTS.json",
    "qa/V5412C-PACKAGE-INTEGRITY.json",
    "qa/V5412C-FINAL-VALIDATION-SUMMARY.json",
}
EXCLUDED_PARTS = {
    "__pycache__", ".git", ".pytest_cache", ".mypy_cache",
    "product-owner-data", "product-owner-data-archive",
    "product-owner-data-v54", "product-owner-data-v54-archive",
    "product-owner-data-v541", "product-owner-data-v541-archive",
    "product-owner-data-v5411", "product-owner-data-v5411-archive",
    "product-owner-data-v5412", "product-owner-data-v5412-archive",
    "v531-final-logs",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
RUNTIME_FILES = {
    ".env", ".env.product-owner", ".env.product-owner-v54",
    ".env.product-owner-v541", ".env.product-owner-v5411",
    ".env.product-owner-v5412", "rmr_platform.db",
    "rmr_platform.db-shm", "rmr_platform.db-wal",
}


def include(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if rel.name == MANIFEST_NAME or rel.as_posix() in SELF_REFERENTIAL_EVIDENCE:
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


def inventory(root: Path) -> list[dict[str, object]]:
    files = []
    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix().lower()):
        if include(path, root):
            files.append({
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": digest(path),
                "mode": oct(path.stat().st_mode & 0o777),
            })
    return files


def create(root: Path) -> int:
    files = inventory(root)
    payload = {
        "product": "RMR Global",
        "release": RELEASE,
        "artifact": ARTIFACT,
        "source_baseline": {
            "release": "5.4.1.2-interaction-regression-correction-po1",
            "artifact": "RMR-Global-v5.4.1.2B-PO-Packaging-Correction.zip",
            "zip_sha256": "1b4ced87fc65ca68d1157fa5cab44eab2d5384387d89fde55bfd7edc0acfdebc"
        },
        "hash_algorithm": "SHA-256",
        "self_referential_evidence_excluded": sorted(SELF_REFERENTIAL_EVIDENCE),
        "file_count": len(files),
        "files": files,
    }
    (root / MANIFEST_NAME).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "created", "file_count": len(files), "manifest": MANIFEST_NAME}, indent=2))
    return 0


def verify(root: Path) -> int:
    path = root / MANIFEST_NAME
    if not path.exists():
        raise SystemExit(f"Manifest not found: {path}")
    expected = json.loads(path.read_text(encoding="utf-8"))
    current = {item["path"]: item for item in inventory(root)}
    declared = {item["path"]: item for item in expected.get("files", [])}
    missing = sorted(set(declared) - set(current))
    unexpected = sorted(set(current) - set(declared))
    mismatches = []
    for name in sorted(set(current) & set(declared)):
        actual = current[name]
        wanted = declared[name]
        for field in ("size", "sha256"):
            if actual[field] != wanted[field]:
                mismatches.append({"path": name, "field": field, "expected": wanted[field], "actual": actual[field]})
    result = {
        "status": "passed" if not missing and not unexpected and not mismatches else "failed",
        "release": expected.get("release"),
        "declared_files": len(declared),
        "current_files": len(current),
        "missing": missing,
        "unexpected": unexpected,
        "mismatches": mismatches,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "verify"])
    parser.add_argument("root", nargs="?", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    return create(root) if args.action == "create" else verify(root)


if __name__ == "__main__":
    raise SystemExit(main())
