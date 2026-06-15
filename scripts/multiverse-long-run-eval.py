#!/usr/bin/env python3
"""Product-grade single-run vs multiverse evaluation runner.

Default mode is `bounded`: it exercises the real backend managers/API and writes
JSON/Markdown artifacts without paying for a long OASIS+LLM run. `live` mode is
reserved for a full local runtime run and intentionally fails closed until the
operator provides a real runtime harness.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

TOPIC = "AI 규제 이슈에 대한 시장과 사용자 반응 비교"
SINGLE_SUMMARY = "은행 방어 전략으로 규제 지연과 사용자 신뢰 하락이 반복된다"
UNIVERSE_SUMMARIES = [
    SINGLE_SUMMARY,
    "규제 지연 속에서 은행 방어가 강화되고 사용자 신뢰가 흔들린다",
    "거래소 주도 확산과 커뮤니티 채택이 상승한다",
    "언론 프레임 변화로 사용자 신뢰와 채택 속도가 크게 갈린다",
]


def write_artifacts(repo_root: Path, run_id: str, result: dict[str, Any]) -> dict[str, str]:
    artifact_dir = repo_root / ".hermes" / "runs" / "multiverse-long-run-eval" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    comparison_json = artifact_dir / "comparison.json"
    comparison_md = artifact_dir / "comparison.md"
    run_log = artifact_dir / "run-log.json"
    single_report = artifact_dir / "single-report.md"
    multiverse_report = artifact_dir / "multiverse-report.md"

    comparison_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    comparison_md.write_text(result.get("comparison", {}).get("report_markdown", ""), encoding="utf-8")
    single_report.write_text(result.get("single_report", ""), encoding="utf-8")
    multiverse_report.write_text(result.get("multiverse_report", ""), encoding="utf-8")
    run_log.write_text(json.dumps(result.get("run_log", {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "artifact_dir": str(artifact_dir),
        "comparison_json": str(comparison_json),
        "comparison_md": str(comparison_md),
        "single_report": str(single_report),
        "multiverse_report": str(multiverse_report),
        "run_log": str(run_log),
    }


def run_bounded(repo_root: Path, *, universe_count: int, rounds: int, max_parallel: int, clustering_strategy: str) -> dict[str, Any]:
    backend_dir = repo_root / "backend"
    os.chdir(backend_dir)
    sys.path.insert(0, str(backend_dir))

    from app import create_app
    from app.config import Config
    from app.models.project import ProjectManager, ProjectStatus
    from app.models.task import TaskManager
    from app.services.multiverse_manager import MultiverseManager
    from app.services.simulation_manager import SimulationManager, SimulationStatus

    tmp = tempfile.TemporaryDirectory()
    Config.UPLOAD_FOLDER = tmp.name
    Config.OASIS_SIMULATION_DATA_DIR = os.path.join(tmp.name, "simulations")
    ProjectManager.PROJECTS_DIR = os.path.join(tmp.name, "projects")
    SimulationManager.SIMULATION_DATA_DIR = Config.OASIS_SIMULATION_DATA_DIR
    MultiverseManager.MULTIVERSE_DATA_DIR = os.path.join(tmp.name, "multiverses")
    TaskManager()._tasks.clear()

    project = ProjectManager.create_project("multiverse long-run bounded eval")
    project.status = ProjectStatus.GRAPH_COMPLETED
    project.graph_id = "graph_longrun_eval"
    project.simulation_requirement = TOPIC
    ProjectManager.save_project(project)

    manager = MultiverseManager()
    experiment = manager.create_experiment(
        project_id=project.project_id,
        graph_id=project.graph_id,
        base_requirement=TOPIC,
        universe_count=universe_count,
        max_parallel=max_parallel,
        rounds=rounds,
        graph_memory_enabled=True,
    )

    sim_manager = SimulationManager()
    summaries = (UNIVERSE_SUMMARIES * ((universe_count // len(UNIVERSE_SUMMARIES)) + 1))[:universe_count]
    child_ids = []
    for child, summary in zip(experiment.children, summaries):
        state = sim_manager.get_simulation(child.simulation_id)
        assert state is not None
        state.status = SimulationStatus.COMPLETED
        state.config_generated = True
        state.config_reasoning = summary
        sim_manager._save_simulation_state(state)
        child_ids.append(child.simulation_id)

    app = create_app()
    client = app.test_client()
    compare_response = client.post(
        f"/api/simulation/multiverse/{experiment.multiverse_id}/compare-single",
        json={
            "single_summary": SINGLE_SUMMARY,
            "question": "단일 시뮬레이션과 비교해 멀티버스가 더 나은 점이 뭐야?",
            "clustering_strategy": clustering_strategy,
            "use_llm": False,
        },
    )
    compare_payload = compare_response.get_json() or {}
    comparison = compare_payload.get("data", {})
    verdict = comparison.get("judgement", {}).get("verdict", "FAIL") if compare_response.status_code == 200 else "FAIL"

    result = {
        "status": verdict,
        "mode": "bounded-real-backend",
        "generated_at": datetime.now().isoformat(),
        "topic": TOPIC,
        "project_id": project.project_id,
        "graph_id": project.graph_id,
        "multiverse_id": experiment.multiverse_id,
        "child_simulation_ids": child_ids,
        "settings": {
            "universe_count": universe_count,
            "rounds": rounds,
            "max_parallel": max_parallel,
            "graph_memory_enabled": True,
            "clustering_strategy": clustering_strategy,
        },
        "comparison": comparison,
        "single_report": f"# Single-run baseline\n\n{SINGLE_SUMMARY}\n",
        "multiverse_report": comparison.get("aggregate", {}).get("ensemble_report_markdown", ""),
        "run_log": {
            "compare_route_status_code": compare_response.status_code,
            "compare_route_success": bool(compare_payload.get("success")),
            "note": "Bounded eval uses deterministic completed child states; use live mode for full OASIS runtime cost/latency evaluation.",
        },
    }
    tmp.cleanup()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["bounded", "live"], default="bounded")
    parser.add_argument("--universe-count", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=24)
    parser.add_argument("--max-parallel", type=int, default=2)
    parser.add_argument("--clustering-strategy", choices=["keyword", "semantic", "llm"], default="semantic")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    if args.mode == "live":
        result = {
            "status": "BLOCKED",
            "mode": "live",
            "generated_at": datetime.now().isoformat(),
            "reason": "Full OASIS long-run harness needs real local model/runtime credentials and may incur high latency/cost; bounded runner is the release gate.",
            "recommendation": "Run bounded mode for CI and schedule live mode as an explicit cost/time canary once local runtime endpoints are confirmed.",
        }
    else:
        result = run_bounded(
            repo_root,
            universe_count=args.universe_count,
            rounds=args.rounds,
            max_parallel=args.max_parallel,
            clustering_strategy=args.clustering_strategy,
        )

    artifacts = write_artifacts(repo_root, run_id, result)
    result["artifacts"] = artifacts
    (Path(artifacts["comparison_json"])).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"PASS", "WARN"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
