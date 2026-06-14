#!/usr/bin/env python3
"""A/B harness for Graphiti native extraction hardening.

It runs the same Korean/English MiroFish scenario twice against the bundled
Graphiti service:

A. GRAPHITI_STRUCTURED_NORMALIZATION=0 -> upstream OpenAI beta-parse behavior.
B. GRAPHITI_STRUCTURED_NORMALIZATION=1 -> MiroFish schema-normalized structured output.

The script recreates only the graph-memory service so Neo4j data is preserved.
It always restores the improved mode at the end.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("GRAPHITI_AB_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SCENARIO = """한국 원화 스테이블코인 법안이 2026년에 통과된다. Crimson Bank는 예금 이탈을 우려한다. K-Exchange는 원화 스테이블코인 결제를 추진한다. Financial Services Commission는 준비금 100%와 실시간 감사 규칙을 요구한다. MiroFish agents should predict how banks, exchanges, regulators, and retail users react.""".strip()
QUERY = "Crimson Bank K-Exchange Financial Services Commission 원화 스테이블코인 준비금 감사"


def sh(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 300) -> str:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=merged_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stdout[-3000:]}")
    return proc.stdout


def request(method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 180) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode()
        return resp.status, json.loads(raw) if raw else {}


def wait_health() -> None:
    deadline = time.time() + 180
    last = None
    while time.time() < deadline:
        try:
            status, body = request("GET", "/healthcheck", timeout=8)
            if status == 200 and body.get("status") == "healthy":
                return
            last = f"{status} {body}"
        except Exception as exc:  # noqa: BLE001 - health polling should keep retrying
            last = repr(exc)
        time.sleep(3)
    raise RuntimeError(f"Graphiti health did not become ready: {last}")


def set_mode(enabled: bool) -> None:
    value = "1" if enabled else "0"
    label = "normalized" if enabled else "legacy"
    print(f"== recreate graph-memory mode={label} GRAPHITI_STRUCTURED_NORMALIZATION={value} ==")
    sh(
        ["docker", "compose", "up", "-d", "--build", "--force-recreate", "graph-memory"],
        env={"GRAPHITI_STRUCTURED_NORMALIZATION": value},
        timeout=600,
    )
    wait_health()


def parse_counts(message: str) -> dict[str, int]:
    out = {"native": 0, "repaired": 0, "failed": 0}
    for key in out:
        match = re.search(rf"{key}=(\d+)", message or "")
        if match:
            out[key] = int(match.group(1))
    return out


def run_case(label: str, normalized: bool) -> dict[str, Any]:
    set_mode(normalized)
    group_id = f"graphiti_ab_{label}_{int(time.time())}"
    payload = {
        "group_id": group_id,
        "messages": [
            {
                "uuid": f"episode_{group_id}",
                "name": f"MiroFish Graphiti A/B {label}",
                "content": SCENARIO,
                "role_type": "system",
                "role": "mirofish_ab_test",
                "timestamp": datetime.now().isoformat(),
                "source_description": f"mirofish graphiti extraction ab {label}",
            }
        ],
    }
    result: dict[str, Any] = {"label": label, "normalized": normalized, "group_id": group_id}
    try:
        status, ingest = request("POST", "/messages", payload, timeout=240)
        message = ingest.get("message", "") if isinstance(ingest, dict) else ""
        result.update({"ingest_status": status, "ingest": ingest, "counts": parse_counts(message)})
        status, search = request("POST", "/search", {"group_ids": [group_id], "query": QUERY, "max_facts": 10}, timeout=90)
        facts = [row.get("fact", "") for row in search.get("facts", [])]
        result.update({"search_status": status, "fact_count": len(facts), "facts": facts[:10]})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="ignore")
        result.update({"error": f"HTTP {exc.code} {raw[:1000]}", "counts": {"native": 0, "repaired": 0, "failed": 1}, "fact_count": 0, "facts": []})
    except Exception as exc:  # noqa: BLE001 - report comparison result, don't hide failure
        result.update({"error": repr(exc), "counts": {"native": 0, "repaired": 0, "failed": 1}, "fact_count": 0, "facts": []})
    finally:
        try:
            request("DELETE", f"/group/{group_id}", timeout=60)
            result["cleanup"] = "pass"
        except Exception as exc:  # noqa: BLE001
            result["cleanup"] = f"partial: {exc!r}"
    return result


def verdict(case: dict[str, Any]) -> str:
    counts = case.get("counts", {})
    if counts.get("failed", 0) > 0 or case.get("error"):
        return "FAILED"
    if counts.get("repaired", 0) > 0:
        return "REPAIRED"
    if counts.get("native", 0) > 0 and case.get("fact_count", 0) > 0:
        return "NATIVE_PASS"
    return "UNKNOWN"


def main() -> int:
    results: list[dict[str, Any]] = []
    try:
        results.append(run_case("A_legacy", normalized=False))
        results.append(run_case("B_normalized", normalized=True))
    finally:
        # Leave the runtime in the improved/default mode even if A fails.
        try:
            set_mode(True)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN restore normalized mode failed: {exc}")

    run_dir = ROOT / ".hermes" / "runs" / datetime.now().strftime("%Y%m%d_%H%M%S_graphiti_ab")
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / "graphiti-extraction-ab.json"
    out_path.write_text(json.dumps({"scenario": SCENARIO, "query": QUERY, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== Graphiti extraction A/B ==")
    print("case\tmode\tverdict\tnative\trepaired\tfailed\tfacts")
    for case in results:
        counts = case.get("counts", {})
        print(
            f"{case['label']}\t{'normalized' if case['normalized'] else 'legacy'}\t{verdict(case)}\t"
            f"{counts.get('native', 0)}\t{counts.get('repaired', 0)}\t{counts.get('failed', 0)}\t{case.get('fact_count', 0)}"
        )
        if case.get("error"):
            print(f"  error: {case['error'][:500]}")
        for fact in case.get("facts", [])[:3]:
            print(f"  fact: {fact}")
    print(f"artifact: {out_path}")

    improved = results[-1]
    return 0 if verdict(improved) == "NATIVE_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
