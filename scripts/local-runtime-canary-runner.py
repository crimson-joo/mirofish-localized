#!/usr/bin/env python3
"""Deterministic local-runtime canary runner for Hermes webhook handoffs.

This script keeps the LLM agent out of the fragile decision path. The webhook
agent should run this once, then summarize the generated report.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "canary-artifacts"
REPORT_PATH = ARTIFACT_DIR / "local-runtime-canary-report.md"
JSON_PATH = ARTIFACT_DIR / "local-runtime-canary-report.json"

REBUILD_PREFIXES = (
    "backend/",
    "frontend/",
    "services/",
)
REBUILD_FILES = {
    "docker-compose.yml",
    ".env.example",
    "frontend/package.json",
    "frontend/package-lock.json",
    "backend/pyproject.toml",
    "backend/uv.lock",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str], *, timeout: int = 180, check: bool = True) -> dict[str, Any]:
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    out = proc.stdout.strip()
    result = {"cmd": " ".join(shlex.quote(x) for x in cmd), "exit_code": proc.returncode, "output": out[-6000:]}
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed: {result['cmd']}\n{out[-2000:]}")
    return result


def parse_changed_files(value: str | None) -> list[str]:
    if not value:
        return []
    value = value.strip()
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        pass
    return [line.strip() for line in value.replace(",", "\n").splitlines() if line.strip()]


def should_rebuild(changed_files: list[str]) -> tuple[bool, str]:
    if not changed_files:
        return True, "changed_files payload missing; conservative rebuild"
    for item in changed_files:
        if item in REBUILD_FILES or item.startswith(REBUILD_PREFIXES):
            return True, f"runtime-affecting change: {item}"
    return False, "no backend/frontend/docker runtime paths changed"


def http_health(backend_url: str) -> dict[str, Any]:
    url = backend_url.rstrip("/") + "/health"
    with urlopen(url, timeout=30) as resp:
        body = resp.read().decode("utf-8", "replace")
        if resp.status < 200 or resp.status >= 300:
            raise RuntimeError(f"health failed {resp.status}: {body[:500]}")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body}
        return {"url": url, "status_code": resp.status, "body": parsed}


def ensure_clean_or_block(allow_dirty: bool) -> str:
    status = run(["git", "status", "--short", "--branch"], timeout=30)["output"]
    dirty_lines = [line for line in status.splitlines()[1:] if line.strip()]
    if dirty_lines and not allow_dirty:
        raise SystemExit(blocked_report(
            reason="git working tree is not clean",
            details={"git_status": status},
            recommendation="Commit/stash user work or add generated artifacts to .gitignore before rerunning.",
        ))
    return status


def blocked_report(reason: str, details: dict[str, Any], recommendation: str) -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "verdict": "BLOCKED",
        "reason": reason,
        "details": details,
        "recommendation": recommendation,
        "created_at": now(),
    }
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    REPORT_PATH.write_text(render_report(data), encoding="utf-8")
    print(REPORT_PATH.read_text(encoding="utf-8"))
    return 2


def render_report(data: dict[str, Any]) -> str:
    verdict = data.get("verdict")
    ok = verdict == "HEALTHY"
    lines = [
        f"- {'✅' if ok else '❌'} **결론**",
        f"  - **{verdict}**",
    ]
    if data.get("reason"):
        lines.append(f"  - 사유: {data['reason']}")
    lines += [
        "",
        "- **CI/webhook 상태**",
        f"  - repo: `{data.get('repo', '-')}`",
        f"  - branch: `{data.get('branch', '-')}`",
        f"  - sha: `{data.get('sha', '-')}`",
        f"  - run: `{data.get('run_id', '-')}`",
    ]
    if data.get("run_url"):
        lines.append(f"  - run_url: {data['run_url']}")
    checks = data.get("checks") or {}
    if checks:
        lines += ["", "- **로컬 런타임 검증 결과**"]
        for key in ["git_clean", "head_match", "rebuild", "backend_health", "browser_locale_canary", "report_agent_locale_e2e"]:
            if key in checks:
                item = checks[key]
                status = item.get("status", "-") if isinstance(item, dict) else str(item)
                note = item.get("note") if isinstance(item, dict) else None
                lines.append(f"  - {'✅' if status == 'PASS' else '⏭️' if status == 'SKIPPED' else '❌'} {key}: {status}{' — ' + note if note else ''}")
    locales = data.get("locales") or {}
    if locales:
        lines += ["", "- **언어별 결과(ko/en/zh)**"]
        for loc in ["ko", "en", "zh"]:
            item = locales.get(loc, {})
            lines.append(f"  - {loc}: {item.get('status', '-')}{' — ' + item.get('note', '') if item.get('note') else ''}")
    if data.get("artifacts"):
        lines += ["", "- **스크린샷/아티팩트**"]
        for item in data["artifacts"]:
            lines.append(f"  - `{item}`")
    if data.get("details"):
        lines += ["", "- **문제/차단 사유**"]
        lines.append(f"  - {json.dumps(data['details'], ensure_ascii=False)[:1200]}")
    lines += ["", "- 🔶 **추천**", f"  - {data.get('recommendation', '현재 기준선을 유지하고 다음 변경부터 동일 canary를 반복 실행하세요.')}"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="crimson-joo/mirofish-localized")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--run-id", default="manual")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:3000/")
    parser.add_argument("--backend-url", default="http://127.0.0.1:5001")
    parser.add_argument("--changed-files", default="")
    parser.add_argument("--allow-dirty", action="store_true", help="For local development only; webhook runs should not use this.")
    args = parser.parse_args()

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    changed_files = parse_changed_files(args.changed_files)
    checks: dict[str, Any] = {}
    artifacts: list[str] = []
    commands: list[dict[str, Any]] = []

    status = ensure_clean_or_block(args.allow_dirty)
    checks["git_clean"] = {"status": "PASS", "note": "working tree clean" if not args.allow_dirty else "allow-dirty dev run"}
    commands.append({"cmd": "git status --short --branch", "output": status})

    commands.append(run(["git", "fetch", "origin", args.branch], timeout=120))
    current_head = run(["git", "rev-parse", "HEAD"], timeout=30)["output"]
    if current_head != args.sha:
        if args.allow_dirty:
            checks["head_match"] = {"status": "FAIL", "note": f"current {current_head[:12]} != payload {args.sha[:12]}"}
        else:
            commands.append(run(["git", "checkout", args.branch], timeout=60))
            commands.append(run(["git", "merge", "--ff-only", f"origin/{args.branch}"], timeout=120))
            current_head = run(["git", "rev-parse", "HEAD"], timeout=30)["output"]
    if current_head != args.sha:
        return blocked_report(
            reason="local HEAD does not match payload SHA after safe sync",
            details={"current_head": current_head, "payload_sha": args.sha},
            recommendation="Ensure local main can fast-forward to the GitHub Actions payload SHA, then rerun canary.",
        )
    checks["head_match"] = {"status": "PASS", "note": args.sha[:12]}

    rebuild, rebuild_reason = should_rebuild(changed_files)
    if rebuild:
        commands.append(run(["docker", "compose", "build", "mirofish"], timeout=600))
        commands.append(run(["docker", "compose", "up", "-d", "--no-build", "mirofish"], timeout=180))
        checks["rebuild"] = {"status": "PASS", "note": rebuild_reason}
    else:
        checks["rebuild"] = {"status": "SKIPPED", "note": rebuild_reason}

    health = http_health(args.backend_url)
    checks["backend_health"] = {"status": "PASS", "note": str(health["body"].get("status", health["status_code"]))}

    browser = run(["node", "scripts/local-runtime-browser-canary.mjs", args.frontend_url, args.backend_url], timeout=240)
    commands.append(browser)
    checks["browser_locale_canary"] = {"status": "PASS", "note": "ko/en/zh browser markers passed"}

    report = run([
        "python3",
        "scripts/report-locale-e2e.py",
        args.backend_url,
        "sim_5bb6a79b6fc5",
        "local_mirofish_725a524065d34168",
    ], timeout=600)
    commands.append(report)
    checks["report_agent_locale_e2e"] = {"status": "PASS", "note": "ko/en/zh Report Agent language assertions passed"}

    for loc in ["ko", "en", "zh"]:
        p = ARTIFACT_DIR / f"local-runtime-locale-{loc}.png"
        if p.exists():
            artifacts.append(str(p.relative_to(ROOT)))
    for p in [ARTIFACT_DIR / "local-runtime-browser-canary.json", JSON_PATH, REPORT_PATH]:
        artifacts.append(str(p.relative_to(ROOT)))

    data = {
        "verdict": "HEALTHY",
        "repo": args.repo,
        "branch": args.branch,
        "sha": args.sha,
        "run_id": args.run_id,
        "run_url": args.run_url,
        "created_at": now(),
        "changed_files": changed_files,
        "checks": checks,
        "locales": {
            "ko": {"status": "PASS", "note": "browser + Report Agent Korean"},
            "en": {"status": "PASS", "note": "browser + Report Agent English"},
            "zh": {"status": "PASS", "note": "browser + Report Agent Chinese"},
        },
        "artifacts": artifacts,
        "recommendation": "현재 기준선을 유지하고, 이후 runtime-affecting 변경에서 동일 local canary를 자동 반복하세요.",
        "commands": commands,
    }
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(render_report(data), encoding="utf-8")
    print(REPORT_PATH.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(blocked_report(
            reason="canary command timed out",
            details={"cmd": exc.cmd, "timeout": exc.timeout},
            recommendation="Inspect the timed-out local service or split the canary into smaller watchdog steps.",
        ))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(blocked_report(
            reason="canary failed",
            details={"error": str(exc)},
            recommendation="Fix the failing local runtime or test dependency, then rerun the canary.",
        ))
