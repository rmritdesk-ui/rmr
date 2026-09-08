#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

RELEASE = "5.1.0-commercial-cb1-r1"
EXPECTED_ARTIFACT = "RMR-Software-v5.1-Commercial-Candidate-Correction-Build-1-Revision-1-Product-Owner-Test.zip"
EXPECTED_PARENT_CB1_SHA256 = "33a93d7ac3af3aec1b1ca106355d47143512645b854c41c1851fe8680d36d0ad"
EXPECTED_CANDIDATE_SHA256 = "506042dff3170c2c2275fd76255f1730992728f5521b5f3d20e6c34e0db7a533"
EXPECTED_FROZEN_DB_SHA256 = "a014ab80ab9762d76398fc9e61619cb0ce6760e51e1107bbec6f404e0b239664"


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class Gate:
    gate_id: str
    title: str
    passed: bool
    checks: list[Check]


class GateFailure(Exception):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def read_json(path: Path) -> dict:
    return json.loads(read_text(path))


def evaluate(name: str, predicate: Callable[[], bool], detail: str) -> Check:
    try:
        passed = bool(predicate())
        return Check(name=name, passed=passed, detail=detail if passed else f"FAILED: {detail}")
    except Exception as exc:  # objective gate output should record, not hide, errors
        return Check(name=name, passed=False, detail=f"ERROR: {detail}: {exc}")


def require_file(root: Path, rel: str) -> Path:
    path = root / rel
    if not path.is_file():
        raise GateFailure(f"missing required file: {rel}")
    return path


def gate_r1_01(root: Path) -> Gate:
    base = root / "evidence/cb1-r1/control-reproduction"
    stderr = read_text(require_file(root, "evidence/cb1-r1/control-reproduction/unchanged-cb1-migrate.stderr.txt"))
    stdout = read_text(require_file(root, "evidence/cb1-r1/control-reproduction/unchanged-cb1-migrate.stdout.txt"))
    exit_code = read_text(require_file(root, "evidence/cb1-r1/control-reproduction/unchanged-cb1-migrate.exit-code.txt")).strip()
    snapshot = read_json(require_file(root, "evidence/cb1-r1/control-reproduction/predecessor-snapshot.json"))
    comparison = read_text(require_file(root, "evidence/cb1-r1/control-reproduction/hash-comparison.txt"))
    checks = [
        evaluate("unchanged CB1 migration exits 1", lambda: exit_code == "1", f"recorded exit code={exit_code}"),
        evaluate(
            "exact future-import SyntaxError preserved",
            lambda: "SyntaxError: from __future__ imports must occur at the beginning of the file" in stderr,
            "stderr contains the exact interpreter error",
        ),
        evaluate("failure occurred before migration stdout", lambda: stdout.strip() == "", "stdout is empty"),
        evaluate(
            "controlled CAF predecessor present",
            lambda: snapshot.get("tenant", {}).get("name") == "Cactus Air Filters, LLC"
            and snapshot.get("tenant", {}).get("id") == "caf-controlled-predecessor-tenant",
            "snapshot identifies the fixed CAF predecessor fixture",
        ),
        evaluate("failed command did not change database files", lambda: "files_equal=true" in comparison, "database/WAL/SHM hashes are equal"),
        evaluate("root-cause patch evidence present", lambda: (base / "minimum-db-correction.patch").is_file(), "minimum-db-correction.patch exists"),
    ]
    return Gate("R1-01", "Controlled failure reproduction", all(c.passed for c in checks), checks)


def gate_r1_02(root: Path) -> Gate:
    db_path = require_file(root, "rmr_platform/db.py")
    db_text = read_text(db_path)
    integrity = read_json(require_file(root, "evidence/cb1-r1/source-integrity.json"))
    integration = read_json(require_file(root, "evidence/cb1-r1/post-migration-integration/comparison.json"))
    main_text = read_text(require_file(root, "rmr_platform/main.py"))
    checks = [
        evaluate("db.py starts with mandatory future import", lambda: db_text.startswith("from __future__ import annotations\n"), "future import is first"),
        evaluate("unused leading import removed", lambda: not db_text.startswith("import os\n"), "no ordinary import precedes future import"),
        evaluate("db.py matches frozen predecessor hash", lambda: sha256(db_path) == EXPECTED_FROZEN_DB_SHA256, f"sha256={sha256(db_path)}"),
        evaluate(
            "source-integrity comparison confirms exact predecessor match",
            lambda: integrity.get("final_db_matches_frozen_candidate") is True,
            "source-integrity.json final_db_matches_frozen_candidate=true",
        ),
        evaluate(
            "separate router typo was reproduced after db-only correction",
            lambda: integration.get("db_only_exit_code") == 1
            and "name 'get_current_user' is not defined" in integration.get("db_only_stderr", ""),
            "db-only correction exposes the undefined CB1 dependency name",
        ),
        evaluate(
            "router wiring correction is one existing dependency identifier",
            lambda: "_build_cb1_router(current_user)" in main_text and "_build_cb1_router(get_current_user)" not in main_text,
            "approved CB1 router uses already imported current_user",
        ),
        evaluate("final application imports after minimal corrections", lambda: integration.get("final_r1_exit_code") == 0, "recorded final import exit code=0"),
    ]
    return Gate("R1-02", "Proven minimum correction", all(c.passed for c in checks), checks)


def gate_r1_03(root: Path) -> Gate:
    base = root / "evidence/cb1-r1/corrected-migration"
    cli_ec = read_text(require_file(root, "evidence/cb1-r1/corrected-migration/cli-migrate.exit-code.txt")).strip()
    cb1_ec = read_text(require_file(root, "evidence/cb1-r1/corrected-migration/cb1-migration.exit-code.txt")).strip()
    cb1_stdout = read_text(require_file(root, "evidence/cb1-r1/corrected-migration/cb1-migration.stdout.txt"))
    comparison = read_json(require_file(root, "evidence/cb1-r1/corrected-migration/data-preservation-comparison.json"))
    after = comparison.get("after", {})
    checks = [
        evaluate("base predecessor migration command passes", lambda: cli_ec == "0", f"exit code={cli_ec}"),
        evaluate("CB1 additive migration command passes", lambda: cb1_ec == "0", f"exit code={cb1_ec}"),
        evaluate(
            "governed CB1 migration marker returned",
            lambda: "005.002.000-commercial-correction-build-1" in cb1_stdout,
            "stdout contains the approved migration marker",
        ),
        evaluate("comparison status passed", lambda: comparison.get("status") == "passed", f"status={comparison.get('status')}"),
        evaluate("CB1 migration recorded", lambda: after.get("cb1_migration") == "005.002.000-commercial-correction-build-1", "post-migration marker matches"),
        evaluate("expected CB1 schema objects created", lambda: int(after.get("cb1_table_count", 0)) >= 22, f"CB1 table count={after.get('cb1_table_count')}"),
        evaluate("evidence set contains no database file", lambda: not any(p.name.startswith("rmr_platform.db") for p in base.iterdir()), "only sanitized evidence is packaged"),
    ]
    return Gate("R1-03", "Corrected additive migration", all(c.passed for c in checks), checks)


def gate_r1_04(root: Path) -> Gate:
    comparison = read_json(require_file(root, "evidence/cb1-r1/corrected-migration/data-preservation-comparison.json"))
    comps = comparison.get("comparisons", {})
    before = comparison.get("before", {})
    after = comparison.get("after", {})
    prices_before = {item["service_code"]: item["contract_price_cents"] for item in before.get("services", [])}
    prices_after = {item["service_code"]: item["contract_price_cents"] for item in after.get("services", [])}
    note_before = next((step.get("notes") for step in before.get("onboarding", {}).get("steps", []) if step.get("code") == "tenant_provisioning"), None)
    note_after = next((step.get("notes") for step in after.get("onboarding", {}).get("steps", []) if step.get("code") == "tenant_provisioning"), None)
    checks = [
        evaluate("CAF tenant exact", lambda: comps.get("tenant_exact") is True, "tenant_exact=true"),
        evaluate("CAF onboarding exact", lambda: comps.get("onboarding_exact") is True, "onboarding_exact=true"),
        evaluate("CAF services exact", lambda: comps.get("services_exact") is True, "services_exact=true"),
        evaluate("base migration state preserved", lambda: comps.get("base_migrations_preserved") is True, "base_migrations_preserved=true"),
        evaluate(
            "CAF prices preserved",
            lambda: prices_before == prices_after == {"crm": 15000, "managed_website": 12500, "platform_core": 2300},
            f"before={prices_before}, after={prices_after}",
        ),
        evaluate(
            "CAF onboarding note preserved",
            lambda: note_before == note_after and isinstance(note_before, str) and "preserve exactly" in note_before,
            f"before={note_before!r}, after={note_after!r}",
        ),
        evaluate(
            "CAF identity preserved",
            lambda: before.get("tenant", {}).get("name") == after.get("tenant", {}).get("name") == "Cactus Air Filters, LLC",
            "tenant name unchanged",
        ),
    ]
    return Gate("R1-04", "CAF data preservation", all(c.passed for c in checks), checks)


def gate_r1_05(root: Path) -> Gate:
    module = read_text(require_file(root, "scripts/RmrDeployment.psm1"))
    upgrade = read_text(require_file(root, "UPGRADE-FROM-V5.1-CANDIDATE.ps1"))
    function_match = re.search(r"function Invoke-RmrCapturedMigration \{(?P<body>.*?)\n\}", module, re.S)
    body = function_match.group("body") if function_match else ""
    diagnostic_pos = upgrade.find("Write-RmrDiagnostics -InstallPath $NewInstall -Reason \"Applying additive database migrations failed")
    cleanup_pos = upgrade.find("@('rm','-f',$migrationResult.ContainerName)", diagnostic_pos + 1 if diagnostic_pos >= 0 else 0)
    checks = [
        evaluate("captured migration function exists", lambda: bool(function_match), "Invoke-RmrCapturedMigration is defined"),
        evaluate("migration container is named and retained", lambda: "'compose','run','--name'" in body and "'--rm'" not in body, "compose run uses --name and not --rm"),
        evaluate("stdout and stderr are separate", lambda: "migration.stdout.txt" in body and "migration.stderr.txt" in body and "1> $stdoutPath 2> $stderrPath" in body, "separate files and redirection present"),
        evaluate(
            "safe container evidence is captured",
            lambda: all(token in body for token in ("container-state.json", "container-command.txt", "container-logs.txt", "container-ps.txt", "compose-ps.txt", "evidence-manifest.json")),
            "state, command, logs, ps, compose ps, and manifest are present",
        ),
        evaluate("manifest marks pre-cleanup capture", lambda: "captured_before_cleanup = $true" in body, "manifest field is true"),
        evaluate("main diagnostic accepts preserved evidence", lambda: "[string[]]$EvidencePaths" in module and "PRESERVED MIGRATION EVIDENCE CAPTURED BEFORE CLEANUP" in module, "evidence paths are embedded"),
        evaluate("diagnostic is written before cleanup on migration failure", lambda: diagnostic_pos >= 0 and cleanup_pos > diagnostic_pos, f"diagnostic index={diagnostic_pos}, cleanup index={cleanup_pos}"),
        evaluate("upgrade result records evidence paths", lambda: all(token in upgrade for token in ("migration_evidence_directory", "migration_stdout", "migration_stderr", "migration_container_evidence")), "LAST-UPGRADE-RESULT fields present"),
    ]
    return Gate("R1-05", "Pre-cleanup migration diagnostics", all(c.passed for c in checks), checks)


def gate_r1_06(root: Path) -> Gate:
    upgrade = read_text(require_file(root, "UPGRADE-FROM-V5.1-CANDIDATE.ps1"))
    rollback = read_text(require_file(root, "ROLLBACK-TO-V5.1-CANDIDATE.ps1"))
    model = read_json(require_file(root, "evidence/cb1-r1/rollback/rollback-data-comparison.json"))
    status_ec = read_text(require_file(root, "evidence/cb1-r1/rollback/candidate-status.exit-code.txt")).strip()
    source_hash = read_text(require_file(root, "evidence/cb1-r1/rollback/source-hash-comparison.txt"))
    preflight_pos = upgrade.find("Wait-RmrPlatformReady -InstallPath $ExistingInstall")
    backup_pos = upgrade.find("Creating a v5.1 Commercial Candidate safety backup")
    stop_pos = upgrade.find("Stopping the v5.1 Commercial Candidate application cleanly")
    failure_diag_pos = upgrade.find("Write-RmrDiagnostics -InstallPath $NewInstall -Reason $failureMessage")
    new_down_pos = upgrade.find("Removing the unsuccessful Correction Build 1 Revision 1 container", failure_diag_pos + 1 if failure_diag_pos >= 0 else 0)
    predecessor_up_pos = upgrade.find("Starting the previous v5.1 Commercial Candidate installation", new_down_pos + 1 if new_down_pos >= 0 else 0)
    rollback_health_pos = upgrade.find("Wait-RmrPlatformReady -InstallPath $ExistingInstall", predecessor_up_pos + 1 if predecessor_up_pos >= 0 else 0)
    checks = [
        evaluate("predecessor preflight precedes backup and stop", lambda: 0 <= preflight_pos < backup_pos < stop_pos, f"positions={preflight_pos},{backup_pos},{stop_pos}"),
        evaluate("automatic rollback remains in upgrade catch", lambda: "$oldStopped" in upgrade and "rollbackStatus" in upgrade and "v5.1 Commercial Candidate-restored-and-healthy" in upgrade, "failure branch and verified status present"),
        evaluate("diagnostics precede failed-stack cleanup", lambda: failure_diag_pos >= 0 and new_down_pos > failure_diag_pos, f"positions={failure_diag_pos},{new_down_pos}"),
        evaluate("predecessor restart precedes health gate", lambda: new_down_pos >= 0 and predecessor_up_pos > new_down_pos and rollback_health_pos > predecessor_up_pos, f"positions={new_down_pos},{predecessor_up_pos},{rollback_health_pos}"),
        evaluate("manual rollback script verifies predecessor version", lambda: "docker compose up -d" in rollback and "5\\.1\\.0-commercial-rc1" in rollback and "ROLLBACK COMPLETED SUCCESSFULLY" in rollback, "manual health/version loop present"),
        evaluate("controlled predecessor candidate status passes", lambda: status_ec == "0", f"candidate status exit code={status_ec}"),
        evaluate("rollback model preserves CAF exactly", lambda: model.get("status") == "passed" and all(model.get("comparisons", {}).values()), f"comparisons={model.get('comparisons')}"),
        evaluate("controlled predecessor source stayed unchanged", lambda: "PASS:" in source_hash and "byte-for-byte unchanged" in source_hash, "before/after source hashes match"),
    ]
    return Gate("R1-06", "Rollback preservation and evidence", all(c.passed for c in checks), checks)


def artifact_boundary_checks(artifact: Path) -> tuple[list[Check], str]:
    artifact_sha = sha256(artifact)
    checks = [
        evaluate("artifact has exact separate name", lambda: artifact.name == EXPECTED_ARTIFACT, f"artifact={artifact.name}"),
        evaluate("artifact is non-empty", lambda: artifact.stat().st_size > 1_000_000, f"size={artifact.stat().st_size}"),
    ]
    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
        lowered = [name.lower() for name in names]
        forbidden = [
            name for name in names
            if Path(name).name in {".env", "rmr_platform.db", "rmr_platform.db-shm", "rmr_platform.db-wal"}
            or "__pycache__" in name
            or name.endswith((".pyc", ".pyo"))
        ]
        checks.extend([
            evaluate("artifact has one R1 root folder", lambda: bool(names) and all(name.startswith("RMR-Software-v5.1-Commercial-Candidate-Correction-Build-1-Revision-1/") for name in names), "all ZIP entries are under the R1 folder"),
            evaluate("artifact excludes runtime and cache files", lambda: forbidden == [], f"forbidden entries={forbidden[:10]}"),
            evaluate("artifact excludes Hasan handoff", lambda: not any("hasan-handoff" in name or "hasan_handoff" in name for name in lowered), "no handoff document in ZIP"),
            evaluate("artifact contains R1 evidence and instructions", lambda: any(name.endswith("docs/CB1-R1-ROOT-CAUSE-REPORT.md") for name in names) and any(name.endswith("docs/CB1-R1-EXACT-LOCAL-UPGRADE-INSTRUCTIONS.md") for name in names), "required documents are packaged"),
        ])
    return checks, artifact_sha


def gate_r1_07(root: Path, artifact: Path | None) -> tuple[Gate, str | None]:
    identity = read_text(require_file(root, "BUILD-IDENTITY.txt"))
    provenance = read_json(require_file(root, "control/BUILD-PROVENANCE.json"))
    checks = [
        evaluate("separate release identity", lambda: RELEASE in identity and provenance.get("release") == RELEASE, f"release={provenance.get('release')}"),
        evaluate("candidate lineage hash preserved", lambda: provenance.get("candidate_sha256") == EXPECTED_CANDIDATE_SHA256, f"candidate_sha256={provenance.get('candidate_sha256')}"),
        evaluate("parent CB1 lineage hash preserved", lambda: provenance.get("parent_cb1_sha256") == EXPECTED_PARENT_CB1_SHA256, f"parent_cb1_sha256={provenance.get('parent_cb1_sha256')}"),
        evaluate("Product Owner-only boundary declared", lambda: "Product Owner" in provenance.get("hasan_handoff", "") and "NOT AUTHORIZED" in provenance.get("hasan_handoff", ""), provenance.get("hasan_handoff", "")),
        evaluate("no Hasan handoff document in tree", lambda: not (root / "docs/HASAN-HANDOFF.md").exists(), "docs/HASAN-HANDOFF.md absent"),
        evaluate("no runtime .env in tree", lambda: not (root / ".env").exists(), ".env absent"),
        evaluate("no packaged runtime database", lambda: not any(p.name in {"rmr_platform.db", "rmr_platform.db-shm", "rmr_platform.db-wal"} for p in root.rglob("*") if p.is_file()), "no runtime SQLite files"),
        evaluate("Windows/Docker gate is explicitly pending", lambda: "PENDING LOCAL EXECUTION" in identity, "not falsely marked passed"),
        evaluate("source-change scope inventory passed", lambda: read_json(require_file(root, "evidence/cb1-r1/source-change-inventory.json")).get("scope_inventory_status") == "passed", "no unexpected application or package changes"),
    ]
    artifact_sha = None
    if artifact is not None:
        extra, artifact_sha = artifact_boundary_checks(artifact)
        checks.extend(extra)
    return Gate("R1-07", "Separate candidate, boundaries, and regression integrity", all(c.passed for c in checks), checks), artifact_sha


def main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen CB1-R1 gates R1-01 through R1-07.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--artifact-zip", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    artifact = Path(args.artifact_zip).resolve() if args.artifact_zip else None
    if artifact is not None and not artifact.is_file():
        raise SystemExit(f"Artifact not found: {artifact}")

    gates = [
        gate_r1_01(root),
        gate_r1_02(root),
        gate_r1_03(root),
        gate_r1_04(root),
        gate_r1_05(root),
        gate_r1_06(root),
    ]
    r1_07, artifact_sha = gate_r1_07(root, artifact)
    gates.append(r1_07)
    passed = all(gate.passed for gate in gates)
    result = {
        "release": RELEASE,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if passed else "failed",
        "passed_gates": sum(1 for gate in gates if gate.passed),
        "failed_gates": sum(1 for gate in gates if not gate.passed),
        "artifact": str(artifact) if artifact else "not supplied",
        "artifact_sha256": artifact_sha,
        "environment_boundary": {
            "windows_docker_desktop_executed_here": False,
            "live_postgresql_executed_here": False,
            "required_local_gate": True,
        },
        "gates": [
            {
                **asdict(gate),
                "passed_checks": sum(1 for check in gate.checks if check.passed),
                "failed_checks": sum(1 for check in gate.checks if not check.passed),
            }
            for gate in gates
        ],
    }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
