#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "RmrDeployment.psm1"
QA_OUT = ROOT / "qa" / "CB1-R2-WRAPPER-MODEL-RESULTS.json"
EVIDENCE_OUT = ROOT / "evidence" / "cb1-r2" / "correction" / "wrapper-behavior-model.json"


def migration_function(text: str) -> str:
    start = text.index("function Invoke-RmrCapturedMigration")
    end = text.index("function Get-RmrContainerState", start)
    return text[start:end]


def modeled_wrapper_exit(*, launched: bool, native_exit: int, stderr: str) -> int:
    # CB1-R2's contract: stderr is evidence; the launched native process exit code
    # is authoritative. A launch exception is a wrapper failure.
    if not launched:
        return 1
    return int(native_exit)


def main() -> int:
    body = migration_function(MODULE.read_text(encoding="utf-8-sig"))
    checks: list[dict[str, object]] = []

    def check(name: str, condition: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(condition), "detail": detail})
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    check("uses Start-Process for migration Docker invocation", "Start-Process -FilePath 'docker'" in body, "Start-Process is present")
    check("waits and returns process object", "-Wait -PassThru" in body, "Wait and PassThru are present")
    check("preserves separate stdout", "-RedirectStandardOutput $stdoutPath" in body, "stdout redirect is present")
    check("preserves separate stderr", "-RedirectStandardError $stderrPath" in body, "stderr redirect is present")
    check("native process exit code is authoritative", "$exitCode = [int]$process.ExitCode" in body, "Process.ExitCode assignment is present")
    check("migration function no longer relies on LASTEXITCODE", "$LASTEXITCODE" not in body, "LASTEXITCODE is absent from the migration function")
    check("launch exception remains failure", "$exitCode = 1" in body and "catch" in body, "catch retains exit code 1")

    scenarios = [
        {
            "name": "successful Docker migration with ordinary Compose stderr",
            "launched": True,
            "native_exit": 0,
            "stderr": "Network rmr-software_default Creating",
            "expected_wrapper_exit": 0,
        },
        {
            "name": "genuine Docker migration failure with stderr",
            "launched": True,
            "native_exit": 1,
            "stderr": "migration failed",
            "expected_wrapper_exit": 1,
        },
        {
            "name": "Docker process launch exception",
            "launched": False,
            "native_exit": 0,
            "stderr": "docker executable unavailable",
            "expected_wrapper_exit": 1,
        },
    ]
    for scenario in scenarios:
        actual = modeled_wrapper_exit(
            launched=bool(scenario["launched"]),
            native_exit=int(scenario["native_exit"]),
            stderr=str(scenario["stderr"]),
        )
        scenario["actual_wrapper_exit"] = actual
        scenario["passed"] = actual == scenario["expected_wrapper_exit"]
        check(scenario["name"], bool(scenario["passed"]), json.dumps(scenario, sort_keys=True))

    result = {
        "status": "passed",
        "release": "5.3.1-final-production-corrections-po1",
        "windows_powershell_5_1_executed_here": False,
        "model_boundary": "Static contract and behavior model only; exact Windows PowerShell 5.1 + Docker Desktop field retest remains required.",
        "passed": len(checks),
        "failed": 0,
        "checks": checks,
        "scenarios": scenarios,
    }
    QA_OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    EVIDENCE_OUT.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "passed", "failed", "windows_powershell_5_1_executed_here")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
