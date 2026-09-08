#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "qa" / "V51RC3-UPGRADE-RELIABILITY-RESULTS.json"
checks: list[dict[str, object]] = []


def record(name: str, ok: bool, detail: object = "") -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    if not ok:
        raise AssertionError(f"{name}: {detail}")


def powershell_balance(source: str) -> tuple[bool, str]:
    """Conservative delimiter/quote check; not a substitute for Windows execution."""
    stack: list[tuple[str, int]] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    opening = set(pairs.values())
    single = False
    double = False
    i = 0
    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""
        if not single and not double and ch == "#":
            end = source.find("\n", i)
            if end == -1:
                break
            i = end + 1
            continue
        if ch == "`" and double:
            i += 2
            continue
        if ch == "'" and not double:
            if single and nxt == "'":
                i += 2
                continue
            single = not single
            i += 1
            continue
        if ch == '"' and not single:
            double = not double
            i += 1
            continue
        if not single and not double:
            if ch in opening:
                stack.append((ch, i))
            elif ch in pairs:
                if not stack or stack[-1][0] != pairs[ch]:
                    return False, f"unmatched {ch} at {i}"
                stack.pop()
        i += 1
    if single or double:
        return False, "unterminated quote"
    if stack:
        return False, f"unclosed delimiters: {stack[-5:]}"
    return True, "balanced"


def comparable_version(version: str) -> str:
    value = (version or "").strip()
    if value in {"5.0.0-rc1", "5.0.0-rc.1"}:
        return "5.0.0-rc1"
    return value


def versions_compatible(actual: str, expected: str) -> bool:
    if not expected:
        return True
    return comparable_version(actual) == comparable_version(expected)


def readiness_model(states: list[dict[str, object]], expected: str) -> tuple[bool, int]:
    for index, state in enumerate(states, start=1):
        if state.get("status") in {"exited", "dead"}:
            return False, index
        ready = all(
            [
                state.get("running") is True,
                state.get("restarting") is not True,
                state.get("host_ok") is True,
                state.get("internal_ok") is True,
                versions_compatible(str(state.get("host_version") or ""), expected),
                versions_compatible(str(state.get("internal_version") or ""), expected),
                comparable_version(str(state.get("host_version") or "")) == comparable_version(str(state.get("internal_version") or "")),
                state.get("docker_health") in {"healthy", "none"},
            ]
        )
        if ready:
            return True, index
    return False, len(states)


def main() -> int:
    started = time.time()
    module = (ROOT / "scripts" / "RmrDeployment.psm1").read_text(encoding="utf-8")
    health = (ROOT / "HEALTH-CHECK.ps1").read_text(encoding="utf-8")
    upgrade = (ROOT / "UPGRADE-FROM-V5.0.ps1").read_text(encoding="utf-8")
    batch = (ROOT / "UPGRADE-FROM-V5.0.bat").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    collector = (ROOT / "COLLECT-DIAGNOSTICS.ps1").read_text(encoding="utf-8")

    for path in sorted([*ROOT.glob("*.ps1"), *(ROOT / "scripts").glob("*.psm1")]):
        ok, detail = powershell_balance(path.read_text(encoding="utf-8"))
        record(f"PowerShell conservative structure: {path.relative_to(ROOT)}", ok, detail)
        bad_continuations = [i for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1) if re.search(r"`\s+$", line) and not line.endswith("`")]
        record(f"PowerShell continuation whitespace: {path.relative_to(ROOT)}", not bad_continuations, bad_continuations)

    record("Bounded readiness polling is implemented", "while (((Get-Date) - $started).TotalSeconds -lt $MaxWaitSeconds)" in module and "Start-Sleep -Seconds $PollSeconds" in module, "RmrDeployment.psm1")
    record("Container started is distinguished from application ready", all(token in module for token in ["Get-RmrContainerState", "Test-RmrHostHealth", "Test-RmrInternalHealth", "$dockerHealthOk", "$versionOk"]), "container + host + internal + Docker health + version")
    record("Compose warning lines cannot be mistaken for the container ID", "^[0-9a-fA-F]{12,64}$" in module and "ForEach-Object { $_.Trim() }" in module, "warning-safe container ID parsing")
    record("Transient Windows HTTP failures are retried", all(token in module for token in ["System.Net.Http.HttpClient", "UseProxy = $false", "ConnectionClose = $true", "catch", "while"]), "HttpClient polling")
    record("Version compatibility helper is used for readiness", "Test-RmrVersionCompatible -ActualVersion $hostHealth.Version -ExpectedVersion $expectedVersion" in module and "Test-RmrVersionCompatible -ActualVersion $internalHealth.Version -ExpectedVersion $expectedVersion" in module, "known v5.0 alias + exact current-release verification")
    record("Restart loops and stopped containers are detected", all(token in module for token in ["$state.Restarting", "$state.RestartCount", "@('exited','dead')"]), "container failure gates")
    record("Failure diagnostics include compose state and logs", all(token in module for token in ["compose','ps','-a", "compose','logs'", "APPLICATION CONTAINER LOGS", "APPLICATION STATUS COMMAND"]), "diagnostic content")
    record("Diagnostic environment summary omits secrets", "RMR_SECRET_KEY" not in re.search(r"\$keys = @\((.*?)\)", module, re.S).group(1) and "RMR_SETUP_TOKEN" not in re.search(r"\$keys = @\((.*?)\)", module, re.S).group(1), "safe key allowlist")
    record("Manual diagnostic collector is included", collector and (ROOT / "COLLECT-DIAGNOSTICS.bat").exists() and (ROOT / "COLLECT-DIAGNOSTICS.sh").exists(), "collectors")
    record("Upgrade validates existing v5 before stopping it", "preflight-v50" in upgrade and "Wait-RmrPlatformReady -InstallPath $ExistingInstall" in upgrade, "preflight")
    record("Upgrade uses 240-second RC3 readiness gate", "-MaxWaitSeconds 240" in upgrade and "upgrade-v51rc3" in upgrade, "bounded readiness")
    record("Upgrade uses explicit migration entrypoint", "'--entrypoint','python'" in upgrade, "avoids duplicate entrypoint startup")
    record("Upgrade captures diagnostics before rollback", "Write-RmrDiagnostics" in upgrade and "Diagnostic file to send to RMR/ChatGPT" in upgrade, "diagnostics")
    record("Known v5.0 rc1/rc.1 metadata mismatch is normalized", all(token in module for token in ["5.0.0-rc1","5.0.0-rc.1","ConvertTo-RmrComparableVersion","Test-RmrVersionCompatible"]), "field evidence regression")
    record("Upgrade verifies restored v5 health", "rollback-v50" in upgrade and "-MaxWaitSeconds 180" in upgrade, "rollback verification")
    record("Upgrade writes machine-readable result", "LAST-UPGRADE-RESULT.json" in upgrade and "v5.0-restored-and-healthy" in upgrade, "result record")
    record("Batch launcher explains success/failure and pauses", all(token in batch for token in ["LAST-UPGRADE-RESULT.json", "previous v5.0 installation", "pause"]), "batch UX")
    record("Compose health cadence supports timely readiness", "interval: 10s" in compose and "start_period: 20s" in compose and "retries: 12" in compose, "compose health")

    transient = [
        {"status":"running","running":True,"restarting":False,"docker_health":"starting","host_ok":False,"internal_ok":False,"host_version":"","internal_version":""},
        {"status":"running","running":True,"restarting":False,"docker_health":"starting","host_ok":True,"internal_ok":True,"host_version":"5.3.1-final-production-corrections-po1","internal_version":"5.3.1-final-production-corrections-po1"},
        {"status":"running","running":True,"restarting":False,"docker_health":"healthy","host_ok":True,"internal_ok":True,"host_version":"5.3.1-final-production-corrections-po1","internal_version":"5.3.1-final-production-corrections-po1"},
    ]
    ok, attempt = readiness_model(transient, "5.3.1-final-production-corrections-po1")
    record("Modeled transient connection closes do not fail first attempt", ok and attempt == 3, {"success":ok,"accepted_attempt":attempt})

    field_v50 = [{"status":"running","running":True,"restarting":False,"docker_health":"healthy","host_ok":True,"internal_ok":True,"host_version":"5.0.0-rc.1","internal_version":"5.0.0-rc.1"}]
    ok, attempt = readiness_model(field_v50, "5.0.0-rc1")
    record("Exact RC2 field failure now passes v5.0 preflight", ok and attempt == 1, {"expected":"5.0.0-rc1","reported":"5.0.0-rc.1","accepted_attempt":attempt})

    inverse_v50 = [{"status":"running","running":True,"restarting":False,"docker_health":"healthy","host_ok":True,"internal_ok":True,"host_version":"5.0.0-rc1","internal_version":"5.0.0-rc1"}]
    ok, attempt = readiness_model(inverse_v50, "5.0.0-rc.1")
    record("Known v5.0 alias is symmetric", ok and attempt == 1, {"expected":"5.0.0-rc.1","reported":"5.0.0-rc1"})

    unrelated_alias = [{"status":"running","running":True,"restarting":False,"docker_health":"healthy","host_ok":True,"internal_ok":True,"host_version":"5.1.0-rc.3","internal_version":"5.1.0-rc.3"}]
    ok, _ = readiness_model(unrelated_alias, "5.3.1-final-production-corrections-po1")
    record("Version normalization is not generalized to RC3", not ok, {"expected":"5.3.1-final-production-corrections-po1","reported":"5.1.0-rc.3"})

    wrong_version = [{"status":"running","running":True,"restarting":False,"docker_health":"healthy","host_ok":True,"internal_ok":True,"host_version":"5.0.0-rc1","internal_version":"5.0.0-rc1"}]
    ok, _ = readiness_model(wrong_version, "5.3.1-final-production-corrections-po1")
    record("Modeled stale v5 response is rejected", not ok, wrong_version)

    exited = [{"status":"exited","running":False,"restarting":False,"docker_health":"unhealthy","host_ok":False,"internal_ok":False,"host_version":"","internal_version":""}]
    ok, attempt = readiness_model(exited, "5.3.1-final-production-corrections-po1")
    record("Modeled stopped container fails deterministically", not ok and attempt == 1, exited)

    result = {
        "status": "passed",
        "release": "5.3.1-final-production-corrections-po1",
        "scope": "RC3 Windows/Docker preflight version compatibility correction plus inherited readiness, diagnostics, and rollback controls",
        "windows_docker_desktop_executed_here": False,
        "passed": sum(1 for item in checks if item["ok"]),
        "failed": sum(1 for item in checks if not item["ok"]),
        "duration_seconds": round(time.time() - started, 2),
        "checks": checks,
    }
    REPORT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ["status","passed","failed","duration_seconds","windows_docker_desktop_executed_here"]}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        REPORT.write_text(json.dumps({"status":"failed","release":"5.3.1-final-production-corrections-po1","error":str(exc),"checks":checks}, indent=2), encoding="utf-8")
        raise
