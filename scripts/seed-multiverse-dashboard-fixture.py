#!/usr/bin/env python3
"""Seed a deterministic multiverse dashboard fixture in the local default backend storage."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.models.project import ProjectManager, ProjectStatus  # noqa: E402
from app.services.multiverse_manager import MultiverseManager  # noqa: E402
from app.services.simulation_manager import SimulationManager, SimulationStatus  # noqa: E402

TOPIC = "AI 규제 이슈에 대한 시장과 사용자 반응 비교"
SUMMARIES = [
    "은행 방어 전략으로 규제 지연과 사용자 신뢰 하락이 반복된다",
    "규제 지연 속에서 은행 방어가 강화되고 사용자 신뢰가 흔들린다",
    "거래소 주도 확산과 커뮤니티 채택이 상승한다",
    "언론 프레임 변화로 사용자 신뢰와 채택 속도가 크게 갈린다",
]

project = ProjectManager.create_project("multiverse dashboard browser fixture")
project.status = ProjectStatus.GRAPH_COMPLETED
project.graph_id = "graph_dashboard_fixture"
project.simulation_requirement = TOPIC
ProjectManager.save_project(project)

manager = MultiverseManager()
experiment = manager.create_experiment(
    project_id=project.project_id,
    graph_id=project.graph_id,
    base_requirement=TOPIC,
    universe_count=4,
    max_parallel=2,
    rounds=24,
    graph_memory_enabled=True,
)
sim_manager = SimulationManager()
for child, summary in zip(experiment.children, SUMMARIES):
    state = sim_manager.get_simulation(child.simulation_id)
    assert state is not None
    state.status = SimulationStatus.COMPLETED
    state.config_generated = True
    state.config_reasoning = summary
    sim_manager._save_simulation_state(state)
manager.compare_single_to_multiverse(experiment.multiverse_id, single_summary=SUMMARIES[0])
print(json.dumps({
    "status": "PASS",
    "project_id": project.project_id,
    "multiverse_id": experiment.multiverse_id,
    "dashboard_path": f"/multiverse/{experiment.multiverse_id}",
}, ensure_ascii=False))
