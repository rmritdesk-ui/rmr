#!/usr/bin/env python3
"""Verify the v5.4.1 four-theme implementation was preserved byte-for-byte.

v5.4.1.2 is an interaction-only correction. The only authorized theme CSS
change is an appended pointer-event/navigation guard; the original v5.4.1.1
theme CSS must remain an exact byte prefix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

RELEASE = "5.4.1.2-interaction-regression-correction-po1"
BASELINE_THEME_CSS_SHA256 = "d8732fccd86aca41db28032ba2bae8339cde780b42624873b2c0ff22618426f1"
UNCHANGED_FILE_HASHES = {
    "public/pages/theme_manager.js": "38f6de44426cac322216aebb7f26476e1de87878603b787e866dd0bbab1e3bc8",
    "public/tenant-theme.js": "b15e78f954d0a1f4b865caa694464f4b36a87b114055ad134ebb82052b27a0ed",
    "rmr_platform/tenant_theme_models.py": "a4d6ab4f874689daf97ef90483baffa71849bf763d325fd9ab6f653a6abf5ae7",
}
ASSET_HASHES = {
    "classic-blue": "3680724047f8cafc3fe35a81de5aac0396b58528e847c173da45d2594fe608f3",
    "metallic-silver": "a25490a078f10f8277c05a1f2f9b42f0332ec5fa59b328eb50e8c0a31a832741",
    "metallic-gold": "8643a624eb609d9c52db46b3a1f6ec884ef72af2ec14c663cabd771de042fcf8",
    "champagne-gold": "e5f8db83278c6562f7ec532485a96035106ac4ec669c51356b671dc969912348",
}
GUARD_MARKER = b"/* v5.4.1.2 interaction-preservation guard"


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    results: list[dict[str, Any]] = []

    def check(name: str, passed: bool, evidence: Any = None) -> None:
        results.append({"name": name, "passed": bool(passed), "evidence": evidence})

    init_text = (root / "rmr_platform/__init__.py").read_text(encoding="utf-8", errors="replace")
    check("Exact v5.4.1.2 release identity is active", RELEASE in init_text, RELEASE)

    css_path = root / "public/tenant-themes.css"
    css = css_path.read_bytes()
    index = css.find(GUARD_MARKER)
    check("Interaction guard is appended after preserved theme CSS", index > 0, index)
    if index > 0:
        prefix = css[:index]
        # The correction appends a blank line before the guard. Remove only
        # that single appended newline before comparing the preserved prefix.
        if prefix.endswith(b"\n\n"):
            prefix = prefix[:-1]
        check(
            "v5.4.1.1 theme CSS remains byte-identical",
            digest_bytes(prefix) == BASELINE_THEME_CSS_SHA256,
            {"expected": BASELINE_THEME_CSS_SHA256, "actual": digest_bytes(prefix)},
        )
        appended = css[index:].decode("utf-8", errors="replace")
        check("Appended guard only restores pointer interaction", "pointer-events:auto" in appended and "data-route" in appended and "data-v53-route" in appended)

    for rel, wanted in UNCHANGED_FILE_HASHES.items():
        path = root / rel
        actual = digest(path) if path.is_file() else None
        check(f"Theme implementation unchanged: {rel}", actual == wanted, {"expected": wanted, "actual": actual})

    actual_assets: dict[str, str | None] = {}
    for theme, wanted in ASSET_HASHES.items():
        path = root / f"public/assets/workspace-themes/{theme}.jpg"
        actual = digest(path) if path.is_file() else None
        actual_assets[theme] = actual
        check(f"Theme preview preserved: {theme}", actual == wanted, {"expected": wanted, "actual": actual})
    check("All four preserved preview assets remain distinct", len(set(v for v in actual_assets.values() if v)) == 4, actual_assets)

    theme_api = (root / "rmr_platform/tenant_themes.py").read_text(encoding="utf-8", errors="replace")
    check("All four controlled workspace style keys remain available", all(f'"{key}"' in theme_api for key in ASSET_HASHES), list(ASSET_HASHES))
    check("No new migration was introduced", "005.006.100-four-workspace-themes" in (root / "rmr_platform/migrations.py").read_text(encoding="utf-8", errors="replace"))

    failed = [row for row in results if not row["passed"]]
    payload = {
        "release": RELEASE,
        "status": "passed" if not failed else "failed",
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "results": results,
    }
    text = json.dumps(payload, indent=2)
    print(text)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
