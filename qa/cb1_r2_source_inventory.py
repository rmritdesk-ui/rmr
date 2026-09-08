#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha(path)
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-root", required=True)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    parent = Path(args.parent_root).resolve()
    root = Path(args.root).resolve()
    before = files(parent)
    after = files(root)
    common = set(before) & set(after)
    changed = sorted(name for name in common if before[name] != after[name])
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))

    application_roots = ("rmr_platform/", "public/", "templates/", "static/")
    identity_only_app = {
        "rmr_platform/__init__.py",
        "rmr_platform/cb1_router.py",
        "rmr_platform/commercial/__init__.py",
        "rmr_platform/commercial/router.py",
        "public/cb1_enhancements.js",
        "templates/cb1_commercial.html",
    }
    unexpected_app = [
        name for name in changed
        if name.startswith(application_roots) and name not in identity_only_app
    ] + [name for name in added if name.startswith(application_roots)] + [name for name in removed if name.startswith(application_roots)]

    expected_removed = {"CB1-R1-READ-ME-FIRST.txt", "CB1-R1-SCOPE-LOCK.txt"}
    unexpected_removed = [name for name in removed if name not in expected_removed]
    functional_source_changes = [name for name in changed if name == "scripts/RmrDeployment.psm1"]
    unexpected_functional = [
        name for name in changed
        if name.startswith(("scripts/", "rmr_platform/", "public/", "templates/", "static/"))
        and name not in identity_only_app
        and name != "scripts/RmrDeployment.psm1"
    ]
    scope_ok = not unexpected_app and not unexpected_removed and not unexpected_functional and functional_source_changes == ["scripts/RmrDeployment.psm1"]

    result = {
        "release": "5.3.1-final-production-corrections-po1",
        "parent_release": "5.1.0-commercial-cb1-r1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "parent_artifact_sha256": "458f53319c20f5bf494b806b22ea9a61c16a8776c1764db9771a477286000878",
        "summary": {"changed": len(changed), "added": len(added), "removed": len(removed)},
        "functional_source_changes": functional_source_changes,
        "application_release_identity_only": sorted(identity_only_app & set(changed)),
        "changed_files": changed,
        "added_files": added,
        "removed_files": removed,
        "unexpected_changed_application_files": sorted(set(unexpected_app)),
        "unexpected_functional_source_changes": sorted(set(unexpected_functional)),
        "unexpected_removed_files": unexpected_removed,
        "scope_inventory_status": "passed" if scope_ok else "failed",
        "scope_statement": "CB1-R2 contains one deployment-wrapper functional correction; all application differences are release-identity labels only.",
    }
    output = Path(args.output).resolve() if args.output else root / "evidence/cb1-r2/source-change-inventory.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("scope_inventory_status", "summary", "functional_source_changes", "unexpected_changed_application_files", "unexpected_functional_source_changes", "unexpected_removed_files")}, indent=2))
    return 0 if scope_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
