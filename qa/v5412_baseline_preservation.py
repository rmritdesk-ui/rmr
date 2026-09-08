#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

RELEASE = "5.4.1.2-interaction-regression-correction-po1"
BASELINE_RELEASE = "5.4.1.1-four-workspace-themes-rendering-correction-po1"
BASELINE_ZIP_SHA256 = "1aa552533e5471ac70ffc2d82ab88551b748a7934e1e3ddbb89aa6405a9efed9"

AUTHORIZED_CHANGED = {
    ".env.example",
    "BUILD-IDENTITY.txt",
    "CHANGE-IMPACT.json",
    "COLLECT-PRODUCT-OWNER-DIAGNOSTICS.ps1",
    "INSTALL.ps1",
    "PACKAGE-MANIFEST.json",
    "PRE-BUILD-IMPACT.json",
    "PRODUCT-OWNER-DEMO-CREDENTIALS.txt",
    "README-FIRST.txt",
    "README.md",
    "README.txt",
    "RESET-PRODUCT-OWNER-DEMO.ps1",
    "RUN-CB1-AUTOMATED-QC.ps1",
    "START-PRODUCT-OWNER-TEST.bat",
    "START-PRODUCT-OWNER-TEST.ps1",
    "STOP-PRODUCT-OWNER-TEST.ps1",
    "UPGRADE-FROM-V5.0.ps1",
    "UPGRADE-FROM-V5.1-CANDIDATE.ps1",
    "docker-compose.postgres.yml",
    "docker-compose.product-owner.yml",
    "docker-compose.yml",
    "public/cb1_enhancements.js",
    "public/index.html",
    "public/pages/unified.js",
    "public/tenant-themes.css",
    "public/ui.js",
    "qa/package-manifest.py",
    "pyproject.toml",
    "rmr_platform/__init__.py",
    "rmr_platform/cb1_router.py",
    "rmr_platform/client_admin_corrections.py",
    "rmr_platform/commercial/__init__.py",
    "rmr_platform/commercial/router.py",
    "rmr_platform/product_owner_qc.py",
    "rmr_platform/tenant_themes.py",
    "rmr_platform/unified_services.py",
    "static/unified-workspace.js",
    "templates/cb1_commercial.html",
}

PRESERVED_THEME_FILES = [
    "public/tenant-theme.js",
    "public/pages/theme_manager.js",
    "public/assets/workspace-themes/classic-blue.jpg",
    "public/assets/workspace-themes/metallic-silver.jpg",
    "public/assets/workspace-themes/metallic-gold.jpg",
    "public/assets/workspace-themes/champagne-gold.jpg",
    "evidence/v541-visual-source/RMR-Global-v541-four-workspace-themes-source.png",
    "evidence/v5411-visual-source/RMR-Global-v5411-four-workspace-themes-source.png",
    "rmr_platform/tenant_theme_models.py",
    "rmr_platform/migrations.py",
]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inventory(root: Path) -> dict[str, str]:
    result = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if "__pycache__" in path.parts or ".pytest_cache" in path.parts or rel.endswith(".pyc"):
            continue
        result[rel] = digest(path)
    return result


def added_is_authorized(path: str) -> bool:
    return (
        path == "V5412-PRODUCT-OWNER-SCOPE-LOCK.md"
        or path == "control/V5412-AUTHORIZED-CHANGESET.json"
        or path == "docs/V5.4.1.2-INTERACTION-REGRESSION-CORRECTION.md"
        or path == "tests/test_interaction_regression.py"
        or path.startswith("qa/V5412-")
        or path.startswith("qa/v5412_")
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-root", required=True)
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--baseline-zip")
    parser.add_argument("--output", required=True)
    parser.add_argument("--changeset", required=True)
    args = parser.parse_args()

    baseline = Path(args.baseline_root).resolve()
    candidate = Path(args.candidate_root).resolve()
    base_inv = inventory(baseline)
    cand_inv = inventory(candidate)

    changed = sorted(k for k in base_inv.keys() & cand_inv.keys() if base_inv[k] != cand_inv[k])
    added = sorted(cand_inv.keys() - base_inv.keys())
    removed = sorted(base_inv.keys() - cand_inv.keys())
    unauthorized_changed = sorted(set(changed) - AUTHORIZED_CHANGED)
    unauthorized_added = sorted(path for path in added if not added_is_authorized(path))

    checks = []
    def check(name, passed, evidence=None):
        checks.append({"name": name, "passed": bool(passed), "evidence": evidence})

    check("No v5.4.1.1 baseline file was removed", not removed, removed)
    check("Every changed baseline file is authorized", not unauthorized_changed, unauthorized_changed)
    check("Every added file is authorized", not unauthorized_added, unauthorized_added)

    if args.baseline_zip:
        zip_hash = digest(Path(args.baseline_zip))
        check("Exact v5.4.1.1 source artifact was used", zip_hash == BASELINE_ZIP_SHA256, zip_hash)

    theme_hashes = {}
    for rel in PRESERVED_THEME_FILES:
        base_hash = base_inv.get(rel)
        cand_hash = cand_inv.get(rel)
        theme_hashes[rel] = {"baseline": base_hash, "candidate": cand_hash}
        check(f"Preserved theme component unchanged: {rel}", bool(base_hash and cand_hash and base_hash == cand_hash), theme_hashes[rel])

    base_css = (baseline / "public/tenant-themes.css").read_text(encoding="utf-8", errors="replace")
    cand_css = (candidate / "public/tenant-themes.css").read_text(encoding="utf-8", errors="replace")
    check("Theme rendering CSS remains byte-for-byte prefix preserved", cand_css.startswith(base_css), {"baseline_bytes": len(base_css), "candidate_bytes": len(cand_css)})
    suffix = cand_css[len(base_css):]
    check("Only interaction pointer-event guard was appended to theme CSS", "v5.4.1.2 interaction-preservation guard" in suffix and "pointer-events:auto" in suffix, suffix.strip())

    failed = [row for row in checks if not row["passed"]]
    payload = {
        "release": RELEASE,
        "source_release": BASELINE_RELEASE,
        "source_zip_sha256": BASELINE_ZIP_SHA256,
        "status": "passed" if not failed else "failed",
        "passed": len(checks) - len(failed),
        "failed": len(failed),
        "changed_count": len(changed),
        "added_count": len(added),
        "removed_count": len(removed),
        "changed": changed,
        "added": added,
        "removed": removed,
        "unauthorized_changed": unauthorized_changed,
        "unauthorized_added": unauthorized_added,
        "preserved_theme_hashes": theme_hashes,
        "checks": checks,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    changeset = {
        "release": RELEASE,
        "source_release": BASELINE_RELEASE,
        "source_zip_sha256": BASELINE_ZIP_SHA256,
        "authorized_changed_files": changed,
        "authorized_added_files": added,
        "removed_files": removed,
        "theme_rendering_changed": False,
        "database_migration_added": False,
        "interaction_code_changes": [
            "public/ui.js",
    "qa/package-manifest.py",
            "public/pages/unified.js",
            "public/tenant-themes.css",
            "rmr_platform/product_owner_qc.py",
        ],
    }
    changeset_path = Path(args.changeset)
    changeset_path.parent.mkdir(parents=True, exist_ok=True)
    changeset_path.write_text(json.dumps(changeset, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({k: payload[k] for k in ("status","passed","failed","changed_count","added_count","removed_count")}, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
