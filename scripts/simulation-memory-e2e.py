#!/usr/bin/env python3
"""E2E smoke for simulation action memory updates into Graphiti.

Usage:
  scripts/simulation-memory-e2e.py http://127.0.0.1:5001 <project_id> <graph_id>
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:5001"
PROJECT_ID = sys.argv[2] if len(sys.argv) > 2 else "proj_1b4e40c584ff"
GRAPH_ID = sys.argv[3] if len(sys.argv) > 3 else "local_mirofish_725a524065d34168"
LOCALE = sys.argv[4] if len(sys.argv) > 4 else "ko"
RUNS_DIR = Path(__file__).resolve().parents[1] / "backend" / "uploads" / "simulations"
GRAPH_DIR = Path(__file__).resolve().parents[1] / "backend" / "uploads" / "local_graphs"


def request(method: str, path: str, payload: dict | None = None, timeout: int = 300) -> dict:
    payload = dict(payload) if payload is not None else None
    if payload is not None:
        payload.setdefault("locale", LOCALE)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept-Language": LOCALE, "X-Locale": LOCALE},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            out = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"{method} {path} HTTP {exc.code}: {raw[:2000]}") from exc
    if out.get("success") is False:
        raise RuntimeError(f"{method} {path} failed: {json.dumps(out, ensure_ascii=False)[:2000]}")
    return out


def wait_prepare(simulation_id: str, task_id: str | None) -> dict:
    deadline = time.time() + 1200
    last = None
    while time.time() < deadline:
        payload = {"simulation_id": simulation_id}
        if task_id:
            payload["task_id"] = task_id
        data = request("POST", "/api/simulation/prepare/status", payload, timeout=60)["data"]
        last = data
        status = data.get("status")
        if status in {"ready", "completed"} or data.get("already_prepared"):
            return data
        if status == "failed":
            raise RuntimeError(f"prepare failed: {json.dumps(data, ensure_ascii=False)[:2000]}")
        time.sleep(5)
    raise TimeoutError(f"prepare timeout: {json.dumps(last, ensure_ascii=False)[:2000]}")


def wait_actions(simulation_id: str) -> dict:
    deadline = time.time() + 900
    last = None
    while time.time() < deadline:
        data = request("GET", f"/api/simulation/{simulation_id}/run-status/detail", timeout=60)["data"]
        last = data
        status = data.get("runner_status")
        if data.get("all_actions") or data.get("total_actions_count", 0) > 0:
            return data
        if status == "failed":
            raise RuntimeError(f"run ended unexpectedly: {json.dumps(data, ensure_ascii=False)[:2000]}")
        time.sleep(5)
    raise TimeoutError(f"action wait timeout: {json.dumps(last, ensure_ascii=False)[:2000]}")


def read_actions(simulation_id: str) -> list[dict]:
    status = request("GET", f"/api/simulation/{simulation_id}/run-status/detail", timeout=60)["data"]
    rows = [row for row in status.get("all_actions", []) if "event_type" not in row and row.get("action_type") != "DO_NOTHING"]
    if rows:
        rows.sort(key=lambda r: (r.get("timestamp", ""), r.get("round", 0)))
        return rows

    rows: list[dict] = []
    for platform in ["twitter", "reddit"]:
        path = RUNS_DIR / simulation_id / platform / "actions.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if "event_type" not in row and row.get("action_type") != "DO_NOTHING":
                row["platform"] = platform
                rows.append(row)
    rows.sort(key=lambda r: (r.get("timestamp", ""), r.get("round", 0)))
    return rows


def read_projection_memory(graph_id: str) -> list[dict]:
    rows: list[dict] = []
    path = GRAPH_DIR / graph_id / "actions.jsonl"
    if path.exists():
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    try:
        graph = request("GET", f"/api/graph/data/{graph_id}", timeout=60)["data"]
        for edge in graph.get("edges", []):
            attrs = edge.get("attributes") or {}
            if attrs.get("source") == "graphiti_projection_simulation_action":
                rows.append(edge)
    except Exception:
        pass
    return rows


def main() -> int:
    request("GET", "/health", timeout=20)
    created = request("POST", "/api/simulation/create", {"project_id": PROJECT_ID, "graph_id": GRAPH_ID, "enable_twitter": True, "enable_reddit": True})["data"]
    simulation_id = created["simulation_id"]
    print(f"CREATED simulation_id={simulation_id}")

    prepared = request("POST", "/api/simulation/prepare", {"simulation_id": simulation_id, "use_llm_for_profiles": False, "parallel_profile_count": 2, "force_regenerate": True}, timeout=60)["data"]
    wait_prepare(simulation_id, prepared.get("task_id"))
    print(f"PASS prepare simulation_id={simulation_id}")

    started = request("POST", "/api/simulation/start", {"simulation_id": simulation_id, "platform": "parallel", "max_rounds": 1, "enable_graph_memory_update": True, "force": True}, timeout=60)["data"]
    if not started.get("graph_memory_update_enabled"):
        raise AssertionError("graph memory update was not enabled")
    print(f"PASS start graph_memory_update_enabled=true graph_id={started.get('graph_id')}")

    run = wait_actions(simulation_id)
    try:
        request("POST", "/api/simulation/stop", {"simulation_id": simulation_id}, timeout=60)
    except Exception:
        pass
    actions = read_actions(simulation_id)
    memory_rows = read_projection_memory(GRAPH_ID)
    if not actions:
        raise AssertionError("no meaningful simulation actions recorded")
    if not memory_rows:
        raise AssertionError("no graph memory projection action rows recorded")

    first_ts = actions[0].get("timestamp")
    last_ts = actions[-1].get("timestamp")
    print("PASS run", json.dumps({
        "simulation_id": simulation_id,
        "runner_status": run.get("runner_status"),
        "current_round": run.get("current_round"),
        "total_rounds": run.get("total_rounds"),
        "actions": len(actions),
        "memory_rows_total_for_graph": len(memory_rows),
        "first_action_timestamp": first_ts,
        "last_action_timestamp": last_ts,
        "sample_action": {k: actions[0].get(k) for k in ["platform", "agent_name", "action_type", "timestamp", "round"]},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
