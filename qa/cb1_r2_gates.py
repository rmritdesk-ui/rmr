#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

RELEASE = "5.3.1-final-production-corrections-po1"
EXPECTED_ARTIFACT = "RMR-Software-v5.1-Commercial-Candidate-Correction-Build-1-Revision-2-Product-Owner-Test.zip"
EXPECTED_PARENT_R1_SHA256 = "458f53319c20f5bf494b806b22ea9a61c16a8776c1764db9771a477286000878"
EXPECTED_PARENT_CB1_SHA256 = "33a93d7ac3af3aec1b1ca106355d47143512645b854c41c1851fe8680d36d0ad"
EXPECTED_CANDIDATE_SHA256 = "506042dff3170c2c2275fd76255f1730992728f5521b5f3d20e6c34e0db7a533"


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


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def data(path: Path) -> dict:
    return json.loads(text(path))


def evaluate(name: str, predicate: Callable[[], bool], detail: str) -> Check:
    try:
        ok = bool(predicate())
        return Check(name, ok, detail if ok else f"FAILED: {detail}")
    except Exception as exc:
        return Check(name, False, f"ERROR: {detail}: {exc}")


def required(root: Path, rel: str) -> Path:
    path = root / rel
    if not path.is_file():
        raise FileNotFoundError(rel)
    return path


def migration_function(module: str) -> str:
    start = module.index("function Invoke-RmrCapturedMigration")
    end = module.index("function Get-RmrContainerState", start)
    return module[start:end]


def gate_r2_01(root: Path) -> Gate:
    summary = text(required(root, "evidence/cb1-r2/windows-field-reproduction/CB1-R1-WINDOWS-MIGRATION-EVIDENCE-SUMMARY.txt"))
    observation = data(required(root, "evidence/cb1-r2/windows-field-reproduction/FIELD-OBSERVATION.json"))
    checks = [
        evaluate("field wrapper reported exit 1", lambda: "Exit code: 1" in summary and observation.get("wrapper_reported_exit_code") == 1, "wrapper false-failure evidence is present"),
        evaluate("Docker container actually exited 0", lambda: '"ExitCode":0' in summary and "Exited (0)" in summary and observation.get("docker_container_exit_code") == 0, "container state and listing show exit 0"),
        evaluate("migration command completed and returned status", lambda: '"current": "005.001.000-functional-client-experience"' in summary and '"required": "005.001.000-functional-client-experience"' in summary, "migration status output is present"),
        evaluate("only ordinary Compose stderr triggered wrapper", lambda: "Network rmr-software" in summary and "Creating" in summary and "RemoteException" in summary, "ordinary network progress was represented as a PowerShell error"),
        evaluate("evidence was captured before cleanup", lambda: "Captured before cleanup: true" in summary and observation.get("captured_before_cleanup") is True, "pre-cleanup evidence flag is true"),
        evaluate("field rollback restored predecessor", lambda: observation.get("predecessor_rollback_result") == "v5.1 Commercial Candidate restored and healthy", "predecessor restoration was recorded"),
    ]
    return Gate("R2-01", "Actual Windows field evidence reconciled", all(c.passed for c in checks), checks)


def gate_r2_02(root: Path) -> Gate:
    module = text(required(root, "scripts/RmrDeployment.psm1"))
    body = migration_function(module)
    inventory = data(required(root, "evidence/cb1-r2/source-change-inventory.json"))
    patch = text(required(root, "evidence/cb1-r2/correction/CB1-R2-DEPLOYMENT-WRAPPER-CORRECTION.patch"))
    checks = [
        evaluate("migration wrapper uses Start-Process", lambda: "Start-Process -FilePath 'docker'" in body, "native process is isolated from PowerShell error-stream promotion"),
        evaluate("stdout and stderr remain separate", lambda: "-RedirectStandardOutput $stdoutPath" in body and "-RedirectStandardError $stderrPath" in body, "separate evidence paths are preserved"),
        evaluate("Docker process ExitCode is authoritative", lambda: "$exitCode = [int]$process.ExitCode" in body and "$LASTEXITCODE" not in body, "Process.ExitCode is used and LASTEXITCODE is absent in the migration function"),
        evaluate("real launch exception remains failure", lambda: "catch" in body and "$exitCode = 1" in body, "catch path still records failure"),
        evaluate("minimum correction patch is preserved", lambda: "Start-Process" in patch and "$process.ExitCode" in patch and "Invoke-RmrCapturedMigration" in patch, "exact wrapper patch evidence exists"),
        evaluate("source inventory found no unexpected application changes", lambda: inventory.get("scope_inventory_status") == "passed" and inventory.get("unexpected_changed_application_files") == [], "scope inventory is clean"),
        evaluate("only deployment wrapper is a functional R2 source change", lambda: inventory.get("functional_source_changes") == ["scripts/RmrDeployment.psm1"], str(inventory.get("functional_source_changes"))),
    ]
    return Gate("R2-02", "Minimum deployment-wrapper correction", all(c.passed for c in checks), checks)


def gate_r2_03(root: Path) -> Gate:
    model = data(required(root, "evidence/cb1-r2/correction/wrapper-behavior-model.json"))
    scenarios = {item["name"]: item for item in model.get("scenarios", [])}
    success = scenarios.get("successful Docker migration with ordinary Compose stderr", {})
    checks = [
        evaluate("wrapper model passed", lambda: model.get("status") == "passed", "wrapper model reports passed"),
        evaluate("successful stderr scenario exists", lambda: bool(success), "success-with-stderr scenario is present"),
        evaluate("stderr does not override exit 0", lambda: success.get("native_exit") == 0 and bool(success.get("stderr")) and success.get("actual_wrapper_exit") == 0 and success.get("passed") is True, json.dumps(success, sort_keys=True)),
        evaluate("Windows field boundary is not falsely claimed", lambda: model.get("windows_powershell_5_1_executed_here") is False, "exact Windows retest remains pending"),
    ]
    return Gate("R2-03", "Success with nonfatal native stderr", all(c.passed for c in checks), checks)


def gate_r2_04(root: Path) -> Gate:
    model = data(required(root, "evidence/cb1-r2/correction/wrapper-behavior-model.json"))
    scenarios = {item["name"]: item for item in model.get("scenarios", [])}
    failure = scenarios.get("genuine Docker migration failure with stderr", {})
    launch = scenarios.get("Docker process launch exception", {})
    upgrade = text(required(root, "UPGRADE-FROM-V5.1-CANDIDATE.ps1"))
    diagnostic_pos = upgrade.find("Write-RmrDiagnostics -InstallPath $NewInstall -Reason \"Applying additive database migrations failed")
    cleanup_pos = upgrade.find("Invoke-RmrDocker -InstallPath $NewInstall -Arguments @('rm','-f',$migrationResult.ContainerName)", diagnostic_pos + 1)
    checks = [
        evaluate("genuine native exit 1 remains failure", lambda: failure.get("native_exit") == 1 and failure.get("actual_wrapper_exit") == 1 and failure.get("passed") is True, json.dumps(failure, sort_keys=True)),
        evaluate("process launch exception remains failure", lambda: launch.get("launched") is False and launch.get("actual_wrapper_exit") == 1 and launch.get("passed") is True, json.dumps(launch, sort_keys=True)),
        evaluate("upgrade still branches on nonzero migration exit", lambda: "if ($migrationResult.ExitCode -ne 0)" in upgrade, "nonzero gate is retained"),
        evaluate("failure diagnostic still precedes cleanup", lambda: diagnostic_pos >= 0 and cleanup_pos > diagnostic_pos, f"positions={diagnostic_pos},{cleanup_pos}"),
        evaluate("automatic rollback remains enabled", lambda: "$oldStopped" in upgrade and "v5.1 Commercial Candidate-restored-and-healthy" in upgrade, "rollback branch remains present"),
    ]
    return Gate("R2-04", "Genuine failure and rollback behavior preserved", all(c.passed for c in checks), checks)


def gate_r2_05(root: Path) -> Gate:
    module = text(required(root, "scripts/RmrDeployment.psm1"))
    body = migration_function(module)
    upgrade = text(required(root, "UPGRADE-FROM-V5.1-CANDIDATE.ps1"))
    diagnostic_pos = upgrade.find("Write-RmrDiagnostics -InstallPath $NewInstall -Reason \"Applying additive database migrations failed")
    cleanup_pos = upgrade.find("Invoke-RmrDocker -InstallPath $NewInstall -Arguments @('rm','-f',$migrationResult.ContainerName)", diagnostic_pos + 1)
    checks = [
        evaluate("migration container is named and retained", lambda: "'compose','run','--name'" in body and "'--rm'" not in body, "named container without --rm"),
        evaluate("separate stdout and stderr files remain", lambda: "migration.stdout.txt" in body and "migration.stderr.txt" in body, "separate evidence files exist"),
        evaluate("safe container evidence remains", lambda: all(token in body for token in ("container-state.json", "container-command.txt", "container-logs.txt", "container-ps.txt", "compose-ps.txt", "evidence-manifest.json")), "state, command, logs, ps, compose ps and manifest are retained"),
        evaluate("manifest marks capture before cleanup", lambda: "captured_before_cleanup = $true" in body, "pre-cleanup flag is retained"),
        evaluate("combined migration summary remains", lambda: "migration-evidence-summary.txt" in body and "MIGRATION STDOUT" in body and "MIGRATION STDERR" in body, "summary sections are retained"),
        evaluate("main diagnostics accept evidence paths", lambda: "[string[]]$EvidencePaths" in module and "PRESERVED MIGRATION EVIDENCE CAPTURED BEFORE CLEANUP" in module, "diagnostics embed preserved evidence"),
        evaluate("diagnostic precedes cleanup on failure", lambda: diagnostic_pos >= 0 and cleanup_pos > diagnostic_pos, f"positions={diagnostic_pos},{cleanup_pos}"),
        evaluate("upgrade result records evidence paths", lambda: all(token in upgrade for token in ("migration_evidence_directory", "migration_stdout", "migration_stderr", "migration_container_evidence")), "LAST-UPGRADE-RESULT fields remain"),
    ]
    return Gate("R2-05", "Pre-cleanup diagnostics preserved", all(c.passed for c in checks), checks)


def gate_r2_06(root: Path) -> Gate:
    provenance = data(required(root, "control/BUILD-PROVENANCE.json"))
    app = data(required(root, "evidence/cb1-r2/integrity/application-payload-integrity.json"))
    r1_gates = data(required(root, "qa/CB1-R1-GATE-RESULTS.json"))
    observation = data(required(root, "evidence/cb1-r2/windows-field-reproduction/FIELD-OBSERVATION.json"))
    rollback = text(required(root, "ROLLBACK-TO-V5.1-CANDIDATE.ps1"))
    upgrade = text(required(root, "UPGRADE-FROM-V5.1-CANDIDATE.ps1"))
    r1_all_pass = all(g.get("passed") is True for g in r1_gates.get("gates", [])) and len(r1_gates.get("gates", [])) == 7
    checks = [
        evaluate("sealed R1 parent hash is preserved", lambda: provenance.get("parent_cb1_r1_sha256") == EXPECTED_PARENT_R1_SHA256, str(provenance.get("parent_cb1_r1_sha256"))),
        evaluate("parent CB1 lineage is preserved", lambda: provenance.get("parent_cb1_sha256") == EXPECTED_PARENT_CB1_SHA256 and provenance.get("candidate_sha256") == EXPECTED_CANDIDATE_SHA256, "CB1 and candidate hashes match"),
        evaluate("all historical R1 gates remain passed", lambda: r1_all_pass, f"gate_count={len(r1_gates.get('gates', []))}"),
        evaluate("application payload integrity passed", lambda: app.get("status") == "passed" and app.get("unexpected_changed_application_files") == [], "application/schema/migration sources are preserved"),
        evaluate("critical database and migration files are byte-identical", lambda: all(item.get("equal") is True for item in app.get("critical_source_hashes", {}).values()), json.dumps(app.get("critical_source_hashes", {}), sort_keys=True)),
        evaluate("CAF preservation evidence remains inherited", lambda: (root / "evidence/cb1-r1/corrected-migration/data-preservation-comparison.json").is_file() and data(root / "evidence/cb1-r1/corrected-migration/data-preservation-comparison.json").get("status") == "passed", "R1 CAF comparison is present and passed"),
        evaluate("field rollback restored healthy predecessor", lambda: observation.get("predecessor_rollback_result") == "v5.1 Commercial Candidate restored and healthy", "field rollback result is preserved"),
        evaluate("manual rollback still verifies predecessor version", lambda: "5\\.1\\.0-commercial-rc1" in rollback and "ROLLBACK COMPLETED SUCCESSFULLY" in rollback, "manual rollback health/version gate remains"),
        evaluate("upgrade still backs up before stopping predecessor", lambda: upgrade.find("Creating a v5.1 Commercial Candidate safety backup") < upgrade.find("Stopping the v5.1 Commercial Candidate application cleanly"), "backup precedes stop"),
    ]
    return Gate("R2-06", "Application, CAF, lineage and rollback preservation", all(c.passed for c in checks), checks)


def artifact_checks(artifact: Path) -> tuple[list[Check], str]:
    artifact_sha = sha256(artifact)
    checks = [
        evaluate("artifact has exact R2 name", lambda: artifact.name == EXPECTED_ARTIFACT, artifact.name),
        evaluate("artifact is non-empty", lambda: artifact.stat().st_size > 1_000_000, f"size={artifact.stat().st_size}"),
    ]
    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
        lower = [n.lower() for n in names]
        root_prefix = "RMR-Software-v5.1-Commercial-Candidate-Correction-Build-1-Revision-2/"
        forbidden = [n for n in names if Path(n).name in {".env", "rmr_platform.db", "rmr_platform.db-shm", "rmr_platform.db-wal"} or "__pycache__" in n or n.endswith((".pyc", ".pyo"))]
        checks.extend([
            evaluate("all ZIP entries are under one R2 root", lambda: bool(names) and all(n.startswith(root_prefix) for n in names), root_prefix),
            evaluate("artifact excludes runtime/cache files", lambda: forbidden == [], f"forbidden={forbidden[:10]}"),
            evaluate("artifact excludes Hasan handoff", lambda: not any("hasan-handoff" in n or "hasan_handoff" in n for n in lower), "no handoff document"),
            evaluate("artifact contains R2 correction evidence", lambda: any(n.endswith("docs/CB1-R2-ROOT-CAUSE-REPORT.md") for n in names) and any(n.endswith("evidence/cb1-r2/correction/CB1-R2-DEPLOYMENT-WRAPPER-CORRECTION.patch") for n in names), "R2 root cause and patch are packaged"),
            evaluate("artifact contains exact local instructions", lambda: any(n.endswith("docs/CB1-R2-EXACT-LOCAL-UPGRADE-INSTRUCTIONS.md") for n in names), "R2 local instructions are packaged"),
            evaluate("artifact contains package manifest", lambda: any(n.endswith("PACKAGE-MANIFEST.json") for n in names), "manifest is packaged"),
        ])
    return checks, artifact_sha


def gate_r2_07(root: Path, artifact: Path | None) -> tuple[Gate, str | None]:
    identity = text(required(root, "BUILD-IDENTITY.txt"))
    provenance = data(required(root, "control/BUILD-PROVENANCE.json"))
    inventory = data(required(root, "evidence/cb1-r2/source-change-inventory.json"))
    checks = [
        evaluate("separate R2 release identity", lambda: RELEASE in identity and provenance.get("release") == RELEASE, RELEASE),
        evaluate("scope is deployment-wrapper only", lambda: "deployment-wrapper correction only" in identity.lower() and provenance.get("scope") == "deployment-wrapper correction only", str(provenance.get("scope"))),
        evaluate("Product Owner-only boundary is explicit", lambda: "PENDING LOCAL EXECUTION" in identity and "NOT AUTHORIZED" in identity, "Windows retest pending; production/Hasan unauthorized"),
        evaluate("no Hasan handoff document exists", lambda: not (root / "docs/HASAN-HANDOFF.md").exists(), "docs/HASAN-HANDOFF.md absent"),
        evaluate("no runtime environment is packaged", lambda: not (root / ".env").exists(), ".env absent"),
        evaluate("no runtime database is packaged", lambda: not any(p.name in {"rmr_platform.db", "rmr_platform.db-shm", "rmr_platform.db-wal"} for p in root.rglob("*") if p.is_file()), "runtime DB files absent"),
        evaluate("R2 source-change inventory passed", lambda: inventory.get("scope_inventory_status") == "passed", str(inventory.get("scope_inventory_status"))),
        evaluate("exact local field retest is pending", lambda: provenance.get("windows_docker_product_owner_retest") == "PENDING LOCAL EXECUTION", str(provenance.get("windows_docker_product_owner_retest"))),
    ]
    artifact_sha = None
    if artifact is not None:
        extra, artifact_sha = artifact_checks(artifact)
        checks.extend(extra)
    return Gate("R2-07", "Separate artifact and authorization boundaries", all(c.passed for c in checks), checks), artifact_sha


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CB1-R2 gates R2-01 through R2-07.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--artifact-zip", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    artifact = Path(args.artifact_zip).resolve() if args.artifact_zip else None
    if artifact is not None and not artifact.is_file():
        raise SystemExit(f"Artifact not found: {artifact}")

    gates = [gate_r2_01(root), gate_r2_02(root), gate_r2_03(root), gate_r2_04(root), gate_r2_05(root), gate_r2_06(root)]
    last, artifact_sha = gate_r2_07(root, artifact)
    gates.append(last)
    passed = all(g.passed for g in gates)
    result = {
        "status": "passed" if passed else "failed",
        "release": RELEASE,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "windows_docker_desktop_executed_here": False,
        "artifact": str(artifact) if artifact else "",
        "artifact_sha256": artifact_sha,
        "passed_gates": sum(g.passed for g in gates),
        "failed_gates": sum(not g.passed for g in gates),
        "passed_checks": sum(c.passed for g in gates for c in g.checks),
        "failed_checks": sum(not c.passed for g in gates for c in g.checks),
        "gates": [asdict(g) for g in gates],
    }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
