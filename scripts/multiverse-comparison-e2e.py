#!/usr/bin/env python3
"""Single-run vs multiverse comparison E2E smoke.

This bounded E2E uses the real backend managers/routes with deterministic completed
child states, avoiding long OASIS/LLM runtime while proving the comparison layer
that users see after reports are available.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    backend_dir = repo_root / "backend"
    os.chdir(backend_dir)
    sys.path.insert(0, str(backend_dir))

    from app.config import Config
    from app import create_app
    from app.models.project import ProjectManager, ProjectStatus
    from app.models.task import TaskManager
    from app.services.simulation_manager import SimulationManager, SimulationStatus
    from app.services.multiverse_manager import MultiverseManager

    tmp = tempfile.TemporaryDirectory()
    Config.UPLOAD_FOLDER = tmp.name
    Config.OASIS_SIMULATION_DATA_DIR = os.path.join(tmp.name, "simulations")
    ProjectManager.PROJECTS_DIR = os.path.join(tmp.name, "projects")
    SimulationManager.SIMULATION_DATA_DIR = Config.OASIS_SIMULATION_DATA_DIR
    MultiverseManager.MULTIVERSE_DATA_DIR = os.path.join(tmp.name, "multiverses")
    TaskManager()._tasks.clear()

    topic = "AI 규제 이슈에 대한 시장과 사용자 반응 비교"
    single_summary = "은행 방어 전략으로 규제 지연과 사용자 신뢰 하락이 반복된다"
    universe_summaries = [
        single_summary,
        "규제 지연 속에서 은행 방어가 강화되고 사용자 신뢰가 흔들린다",
        "거래소 주도 확산과 커뮤니티 채택이 상승한다",
        "언론 프레임 변화로 사용자 신뢰와 채택 속도가 크게 갈린다",
    ]

    project = ProjectManager.create_project("multiverse comparison e2e")
    project.status = ProjectStatus.GRAPH_COMPLETED
    project.graph_id = "graph_compare_e2e"
    project.simulation_requirement = topic
    ProjectManager.save_project(project)

    manager = MultiverseManager()
    single_baseline = manager.build_single_run_baseline_answer(topic, single_summary)
    experiment = manager.create_experiment(
        project_id=project.project_id,
        graph_id=project.graph_id,
        base_requirement=topic,
        universe_count=len(universe_summaries),
        max_parallel=2,
        rounds=24,
        graph_memory_enabled=True,
    )

    sim_manager = SimulationManager()
    for child, summary in zip(experiment.children, universe_summaries):
        state = sim_manager.get_simulation(child.simulation_id)
        assert state is not None
        state.status = SimulationStatus.COMPLETED
        state.config_generated = True
        state.config_reasoning = summary
        sim_manager._save_simulation_state(state)

    aggregate = manager.aggregate_experiment(experiment.multiverse_id, clustering_strategy="semantic")
    answer = manager.answer_report_agent_question(
        experiment.multiverse_id,
        "단일 시뮬레이션과 비교해 멀티버스가 더 나은 점이 뭐야?",
        use_llm=False,
    )

    app = create_app()
    client = app.test_client()
    route_response = client.post(
        f"/api/simulation/multiverse/{experiment.multiverse_id}/report-agent-chat",
        json={"message": "단일 실행 대비 더 좋아진 게 맞아?", "use_llm": False},
    )
    route_json = route_response.get_json()

    result = {
        "status": "PASS" if route_response.status_code == 200 and answer["comparison"]["is_better_than_single_baseline"] else "FAIL",
        "generated_at": datetime.now().isoformat(),
        "topic": topic,
        "single_run": {
            "summary": single_summary,
            "comparison_score": single_baseline["comparison_score"],
            "evidence_items": single_baseline["evidence_items"],
            "limitations": ["single_outcome_only", "no_ensemble_frequency", "no_sensitivity_axes"],
        },
        "multiverse": {
            "multiverse_id": experiment.multiverse_id,
            "universe_count": aggregate["universe_count"],
            "cluster_count": len(aggregate["outcome_clusters"]),
            "sensitivity_axis_count": len(aggregate["sensitivity_axes"]),
            "evidence_items": answer["comparison"]["evidence_items"],
            "improvement_score": answer["comparison"]["improvement_score"],
            "report_agent_answer_mode": answer["answer_mode"],
            "route_status_code": route_response.status_code,
        },
        "judgement": {
            "is_better_than_single_baseline": answer["comparison"]["is_better_than_single_baseline"],
            "why": answer["comparison"]["reason"],
            "caveat": "ensemble_frequency는 실제 확률이 아니라 시뮬레이션 세계선 빈도입니다.",
        },
        "route_response_success": bool(route_json and route_json.get("success")),
    }

    artifact_dir = repo_root / ".hermes" / "runs" / "multiverse-comparison-e2e"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = artifact_dir / f"comparison-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    artifact.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["artifact"] = str(artifact)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    tmp.cleanup()
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
