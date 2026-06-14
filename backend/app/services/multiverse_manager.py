"""Multiverse/ensemble simulation orchestration.

A multiverse experiment is a light-weight parent object that fans one topic/graph
out into several child simulations.  Each child keeps normal SimulationManager
state, while this manager stores the worldline metadata needed for ensemble
reporting: scenario axis, persona variation, queue/parallel limits, and a safe
aggregation vocabulary that treats frequencies as simulation evidence rather
than real-world probabilities.
"""

from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from ..config import Config
from ..utils.logger import get_logger
from .simulation_manager import SimulationManager

logger = get_logger("mirofish.multiverse")


class MultiverseStatus(str, Enum):
    """Experiment lifecycle status."""

    CREATED = "created"
    PREPARING = "preparing"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class UniverseChild:
    """A single worldline inside an ensemble experiment."""

    universe_id: str
    simulation_id: str
    index: int
    name: str
    scenario_variant: Dict[str, Any]
    persona_variation: Dict[str, Any]
    graph_memory_enabled: bool = True
    status: str = "created"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "universe_id": self.universe_id,
            "simulation_id": self.simulation_id,
            "index": self.index,
            "name": self.name,
            "scenario_variant": self.scenario_variant,
            "persona_variation": self.persona_variation,
            "graph_memory_enabled": self.graph_memory_enabled,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UniverseChild":
        return cls(
            universe_id=data["universe_id"],
            simulation_id=data["simulation_id"],
            index=data.get("index", 0),
            name=data.get("name", data.get("universe_id", "Universe")),
            scenario_variant=data.get("scenario_variant", {}),
            persona_variation=data.get("persona_variation", {}),
            graph_memory_enabled=data.get("graph_memory_enabled", True),
            status=data.get("status", "created"),
            created_at=data.get("created_at", datetime.now().isoformat()),
        )


@dataclass
class MultiverseExperiment:
    """Parent record for a scenario ensemble."""

    multiverse_id: str
    project_id: str
    graph_id: str
    base_requirement: str
    universe_count: int
    max_parallel: int = 2
    rounds: int = 24
    variation_mode: str = "realistic"
    persona_selection_mode: str = "core"
    max_agent_personas: int = 30
    graph_memory_enabled: bool = True
    status: MultiverseStatus = MultiverseStatus.CREATED
    children: List[UniverseChild] = field(default_factory=list)
    aggregate: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "multiverse_id": self.multiverse_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "base_requirement": self.base_requirement,
            "universe_count": self.universe_count,
            "max_parallel": self.max_parallel,
            "rounds": self.rounds,
            "variation_mode": self.variation_mode,
            "persona_selection_mode": self.persona_selection_mode,
            "max_agent_personas": self.max_agent_personas,
            "graph_memory_enabled": self.graph_memory_enabled,
            "status": self.status.value if isinstance(self.status, MultiverseStatus) else self.status,
            "children": [child.to_dict() for child in self.children],
            "aggregate": self.aggregate,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MultiverseExperiment":
        status = data.get("status", MultiverseStatus.CREATED.value)
        if isinstance(status, str):
            status = MultiverseStatus(status)
        return cls(
            multiverse_id=data["multiverse_id"],
            project_id=data["project_id"],
            graph_id=data["graph_id"],
            base_requirement=data.get("base_requirement", ""),
            universe_count=data.get("universe_count", 0),
            max_parallel=data.get("max_parallel", 2),
            rounds=data.get("rounds", 24),
            variation_mode=data.get("variation_mode", "realistic"),
            persona_selection_mode=data.get("persona_selection_mode", "core"),
            max_agent_personas=data.get("max_agent_personas", 30),
            graph_memory_enabled=data.get("graph_memory_enabled", True),
            status=status,
            children=[UniverseChild.from_dict(child) for child in data.get("children", [])],
            aggregate=data.get("aggregate", {}),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            error=data.get("error"),
        )


class MultiverseManager:
    """Creates, persists, and summarizes multiverse experiments."""

    MULTIVERSE_DATA_DIR = os.path.join(Config.UPLOAD_FOLDER, "multiverses")

    SCENARIO_AXES = [
        {
            "axis": "regulatory_posture",
            "label": "Regulatory posture",
            "assumption": "규제기관 반응의 강도와 속도가 달라진다.",
            "variable_profile": {"regulatory_pressure": "high", "institutional_latency": "medium"},
        },
        {
            "axis": "media_framing",
            "label": "Media framing",
            "assumption": "언론 프레임이 긍정/부정/위험 중심으로 달라진다.",
            "variable_profile": {"media_amplification": "high", "trust_volatility": "medium"},
        },
        {
            "axis": "market_shock",
            "label": "Market shock",
            "assumption": "외부 시장 충격 또는 유동성 변화가 참여자 행동을 흔든다.",
            "variable_profile": {"liquidity_stress": "high", "user_attention": "high"},
        },
        {
            "axis": "institutional_strategy",
            "label": "Institutional strategy",
            "assumption": "은행/거래소/대형 조직의 방어·공격 전략이 갈린다.",
            "variable_profile": {"incumbent_defense": "high", "challenger_aggression": "medium"},
        },
        {
            "axis": "grassroots_adoption",
            "label": "Grassroots adoption",
            "assumption": "일반 사용자와 커뮤니티의 초기 채택 의지가 달라진다.",
            "variable_profile": {"community_adoption": "high", "skepticism": "medium"},
        },
        {
            "axis": "expert_validation",
            "label": "Expert validation",
            "assumption": "전문가/학계/오피니언 리더의 검증 신호가 다르게 유입된다.",
            "variable_profile": {"expert_confidence": "high", "controversy": "medium"},
        },
    ]

    def __init__(self):
        os.makedirs(self.MULTIVERSE_DATA_DIR, exist_ok=True)
        self.simulation_manager = SimulationManager()

    def _get_experiment_dir(self, multiverse_id: str) -> str:
        experiment_dir = os.path.join(self.MULTIVERSE_DATA_DIR, multiverse_id)
        os.makedirs(experiment_dir, exist_ok=True)
        return experiment_dir

    def _get_experiment_path(self, multiverse_id: str) -> str:
        return os.path.join(self._get_experiment_dir(multiverse_id), "experiment.json")

    def _save_experiment(self, experiment: MultiverseExperiment) -> None:
        experiment.updated_at = datetime.now().isoformat()
        with open(self._get_experiment_path(experiment.multiverse_id), "w", encoding="utf-8") as f:
            json.dump(experiment.to_dict(), f, ensure_ascii=False, indent=2)

    def get_experiment(self, multiverse_id: str) -> Optional[MultiverseExperiment]:
        path = self._get_experiment_path(multiverse_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return MultiverseExperiment.from_dict(json.load(f))

    def list_experiments(self, project_id: Optional[str] = None, limit: int = 50) -> List[MultiverseExperiment]:
        if not os.path.exists(self.MULTIVERSE_DATA_DIR):
            return []
        experiments: List[MultiverseExperiment] = []
        for multiverse_id in os.listdir(self.MULTIVERSE_DATA_DIR):
            if multiverse_id.startswith("."):
                continue
            experiment = self.get_experiment(multiverse_id)
            if experiment and (project_id is None or experiment.project_id == project_id):
                experiments.append(experiment)
        experiments.sort(key=lambda item: item.created_at, reverse=True)
        return experiments[:limit]

    @staticmethod
    def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    def _build_scenario_variant(self, index: int, base_requirement: str) -> Dict[str, Any]:
        axis = self.SCENARIO_AXES[index % len(self.SCENARIO_AXES)]
        polarity = ["baseline", "optimistic", "defensive", "volatile", "delayed"][index % 5]
        return {
            "axis": axis["axis"],
            "label": axis["label"],
            "polarity": polarity,
            "assumption": axis["assumption"],
            "variable_profile": axis["variable_profile"],
            "prompt_overlay": (
                f"가능세계 U{index + 1}: '{base_requirement}' 주제를 유지하되 "
                f"{axis['assumption']} 이 조건에서 참여자 반응을 시뮬레이션한다."
            ),
        }

    def _build_persona_variation(self, index: int, variation_mode: str) -> Dict[str, Any]:
        variance = ["low", "medium", "medium-high", "low-medium"][index % 4]
        return {
            "mode": variation_mode,
            "variance": variance,
            "seed": 10_000 + index,
            "constraints": [
                "기관/공식 주체는 법적·조직적 제약을 벗어나지 않는다.",
                "개인/커뮤니티 주체는 정서·활동량 변동 폭을 더 넓게 허용한다.",
                "같은 graph entity 정체성은 유지하고 stance/activity/sentiment만 현실 범위에서 변형한다.",
            ],
        }

    def _write_child_context(self, child: UniverseChild, experiment: MultiverseExperiment) -> None:
        sim_dir = self.simulation_manager._get_simulation_dir(child.simulation_id)
        context = {
            "multiverse_id": experiment.multiverse_id,
            "universe_id": child.universe_id,
            "base_requirement": experiment.base_requirement,
            "scenario_variant": child.scenario_variant,
            "persona_variation": child.persona_variation,
            "rounds": experiment.rounds,
            "graph_memory_enabled": child.graph_memory_enabled,
            "persona_selection_mode": experiment.persona_selection_mode,
            "max_agent_personas": experiment.max_agent_personas,
        }
        with open(os.path.join(sim_dir, "multiverse_context.json"), "w", encoding="utf-8") as f:
            json.dump(context, f, ensure_ascii=False, indent=2)

    def create_experiment(
        self,
        project_id: str,
        graph_id: str,
        base_requirement: str,
        universe_count: int = 5,
        max_parallel: int = 2,
        rounds: int = 24,
        variation_mode: str = "realistic",
        persona_selection_mode: str = "core",
        max_agent_personas: int = 30,
        graph_memory_enabled: bool = True,
        enable_twitter: bool = True,
        enable_reddit: bool = True,
    ) -> MultiverseExperiment:
        """Create a parent experiment and N child simulation shells."""

        normalized_count = self._clamp_int(universe_count, default=5, minimum=1, maximum=20)
        normalized_parallel = self._clamp_int(max_parallel, default=2, minimum=1, maximum=normalized_count)
        normalized_rounds = self._clamp_int(rounds, default=24, minimum=1, maximum=240)
        normalized_personas = self._clamp_int(max_agent_personas, default=30, minimum=1, maximum=500)
        if persona_selection_mode not in {"core", "all"}:
            persona_selection_mode = "core"
        if variation_mode not in {"realistic", "conservative", "exploratory"}:
            variation_mode = "realistic"

        multiverse_id = f"mv_{uuid.uuid4().hex[:12]}"
        experiment = MultiverseExperiment(
            multiverse_id=multiverse_id,
            project_id=project_id,
            graph_id=graph_id,
            base_requirement=base_requirement,
            universe_count=normalized_count,
            max_parallel=normalized_parallel,
            rounds=normalized_rounds,
            variation_mode=variation_mode,
            persona_selection_mode=persona_selection_mode,
            max_agent_personas=normalized_personas,
            graph_memory_enabled=graph_memory_enabled,
        )

        for index in range(normalized_count):
            state = self.simulation_manager.create_simulation(
                project_id=project_id,
                graph_id=graph_id,
                enable_twitter=enable_twitter,
                enable_reddit=enable_reddit,
            )
            child = UniverseChild(
                universe_id=f"u{index + 1}",
                simulation_id=state.simulation_id,
                index=index + 1,
                name=f"Universe {index + 1}",
                scenario_variant=self._build_scenario_variant(index, base_requirement),
                persona_variation=self._build_persona_variation(index, variation_mode),
                graph_memory_enabled=graph_memory_enabled,
                status=state.status.value,
            )
            experiment.children.append(child)
            self._write_child_context(child, experiment)

        self._save_experiment(experiment)
        logger.info(
            "Created multiverse experiment: %s project=%s graph=%s universes=%s",
            multiverse_id,
            project_id,
            graph_id,
            normalized_count,
        )
        return experiment

    def aggregate_experiment(self, multiverse_id: str) -> Dict[str, Any]:
        """Summarize child simulation states into ensemble-frequency evidence."""

        experiment = self.get_experiment(multiverse_id)
        if not experiment:
            raise ValueError(f"Multiverse experiment not found: {multiverse_id}")

        status_counter: Counter[str] = Counter()
        completed_children: List[Dict[str, Any]] = []
        failed_children: List[Dict[str, Any]] = []
        child_summaries: List[Dict[str, Any]] = []

        # Use a fresh SimulationManager so aggregation reflects child state files
        # updated by runners/API calls outside this manager instance.
        simulation_manager = SimulationManager()
        for child in experiment.children:
            state = simulation_manager.get_simulation(child.simulation_id)
            status = state.status.value if state else "missing"
            status_counter[status] += 1
            child.status = status
            summary = {
                "universe_id": child.universe_id,
                "simulation_id": child.simulation_id,
                "axis": child.scenario_variant.get("axis"),
                "label": child.scenario_variant.get("label"),
                "status": status,
                "config_reasoning": state.config_reasoning if state else "",
            }
            child_summaries.append(summary)
            if status == "completed":
                completed_children.append(summary)
            if status in {"failed", "missing"}:
                failed_children.append(summary)

        if completed_children and len(completed_children) == len(experiment.children):
            experiment.status = MultiverseStatus.COMPLETED
        elif completed_children:
            experiment.status = MultiverseStatus.PARTIAL
        elif failed_children and len(failed_children) == len(experiment.children):
            experiment.status = MultiverseStatus.FAILED

        aggregate = {
            "multiverse_id": experiment.multiverse_id,
            "universe_count": len(experiment.children),
            "completed_count": len(completed_children),
            "failed_count": len(failed_children),
            "status_frequency": dict(status_counter),
            "probability_note": (
                "Values are ensemble_frequency from simulated worldlines, not calibrated "
                "real-world probabilities. Treat them as evidence for robust vs sensitive outcomes."
            ),
            "sensitivity_axes": [
                {
                    "universe_id": child.universe_id,
                    "axis": child.scenario_variant.get("axis"),
                    "label": child.scenario_variant.get("label"),
                    "polarity": child.scenario_variant.get("polarity"),
                    "status": child.status,
                }
                for child in experiment.children
            ],
            "common_findings": [
                "결과가 완료된 universe들에서 반복되는 outcome cluster를 보고서 단계에서 비교한다."
            ] if completed_children else [],
            "divergent_findings": [
                "status/axis별 차이가 큰 universe를 우선 검토해 민감 변수를 식별한다."
            ] if len(status_counter) > 1 else [],
            "children": child_summaries,
            "generated_at": datetime.now().isoformat(),
        }
        experiment.aggregate = aggregate
        self._save_experiment(experiment)
        return aggregate
