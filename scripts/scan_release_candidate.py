"""Offline candidate inventory/secret scan. No Git initialization or secret output.

Requires requirements-dev.txt. Heuristics flag possible secrets for review; a
clean result is not proof that credentials can never exist. Local ignored files
are identified by category, never opened. Maintained tests/demo fixtures remain.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from pathspec import GitIgnoreSpec

STRONG = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    "OpenAI API key": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "JWT token": re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,})"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
}
ASSIGN = re.compile(r'''(?im)\b(?:[A-Z_]*(?:PASSWORD|SECRET|TOKEN|API_KEY|ENCRYPTION_KEY)[A-Z_]*)["']?[ \t]*[:=][ \t]*["']([^\r\n"']{8,})["']''')
ENV_ASSIGN = re.compile(r'''(?m)^[A-Z_]*(?:PASSWORD|SECRET|TOKEN|API_KEY|ENCRYPTION_KEY)[A-Z_]*=([^\r\n]{8,})$''')
DSN = re.compile(r"(?:postgres(?:ql)?(?:\+psycopg)?|mysql|redis)://[^:/\s]+:([^@/\s]+)@")
SAFE_MARKERS = ("replace", "placeholder", "example", "test", "demo", "mock", "configure", "change-me", "change_me", "installer")


def classify_private(path):
    name = path.name.lower()
    if name == ".env" or name.startswith(".env.") and name != ".env.example": return "populated environment file"
    if "demo-credentials" in name: return "private demo credential file"
    if re.search(r"\.(?:db|sqlite3?)(?:-|$)", name): return "local database (may contain credentials)"
    return None


def scan(root):
    spec = GitIgnoreSpec.from_lines((root / ".gitignore").read_text().splitlines())
    review_file = root / "docs/security/reviewed-nonsecret-fingerprints.json"
    reviews = json.loads(review_file.read_text()) if review_file.exists() else []
    reviewed = {(row["path"], row["sha256"]) for row in reviews}
    findings, candidates, ignored = [], [], []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.relative_to(root).parts: continue
        rel = path.relative_to(root).as_posix()
        category = classify_private(path)
        if spec.match_file(rel):
            ignored.append(rel)
            if category: findings.append({"path": rel, "category": category, "status": "SAFE: excluded"})
            continue
        candidates.append(rel)
        if category:
            findings.append({"path": rel, "category": category, "status": "NOT SAFE"})
            continue
        data = path.read_bytes()
        if b"\0" in data: continue  # binary assets are inventoried, not decoded
        text = data.decode("utf-8", errors="replace")
        for label, pattern in STRONG.items():
            if pattern.search(text): findings.append({"path": rel, "category": label, "status": "NOT SAFE"})
        patterns = [(ASSIGN, "credential assignment"), (DSN, "database password")]
        if path.name.startswith(".env"):
            patterns.append((ENV_ASSIGN, "environment credential"))
        for pattern, label in patterns:
            values = [m.group(1) for m in pattern.finditer(text)]
            suspicious = [v for v in values if not any(marker in v.lower() for marker in SAFE_MARKERS)
                          and not v.startswith(("os.", "settings.", "self.", "payload.", "request.", "user.", "secrets.", "hash_", "${", "$", "<"))]
            unreviewed = [v for v in suspicious if (rel, hashlib.sha256(v.encode()).hexdigest()) not in reviewed]
            if unreviewed:
                findings.append({"path": rel, "category": label, "status": "REVIEW"})
            elif suspicious:
                findings.append({"path": rel, "category": label, "status": "SAFE: reviewed non-secret/demo/test literal"})
    return {"candidate_count": len(candidates), "excluded_count": len(ignored),
            "findings": findings, "candidates": candidates}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = scan(args.root.resolve())
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if any(row["status"] in {"NOT SAFE", "REVIEW"} for row in result["findings"]) else 0)
