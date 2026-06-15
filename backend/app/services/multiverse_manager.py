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
import re
import threading
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from ..config import Config
from ..utils.logger import get_logger
from .simulation_manager import SimulationManager, SimulationStatus
from .simulation_runner import RunnerStatus, SimulationRunner
from ..models.task import TaskManager, TaskStatus
from ..utils.llm_client import LLMClient

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

    def _build_child_requirement(self, experiment: MultiverseExperiment, child: UniverseChild) -> str:
        """Merge the base topic with a universe scenario/persona overlay."""
        constraints = "\n".join(f"- {item}" for item in child.persona_variation.get("constraints", []))
        return (
            f"{experiment.base_requirement}\n\n"
            f"## Multiverse Universe Overlay\n"
            f"Universe: {child.universe_id} / {child.name}\n"
            f"Scenario axis: {child.scenario_variant.get('label')} ({child.scenario_variant.get('axis')})\n"
            f"Polarity: {child.scenario_variant.get('polarity')}\n"
            f"Assumption: {child.scenario_variant.get('assumption')}\n"
            f"Prompt overlay: {child.scenario_variant.get('prompt_overlay')}\n\n"
            f"## Persona variation policy\n"
            f"Mode: {child.persona_variation.get('mode')}\n"
            f"Variance: {child.persona_variation.get('variance')}\n"
            f"Seed: {child.persona_variation.get('seed')}\n"
            f"Constraints:\n{constraints}\n"
        )

    def _build_child_document_text(self, document_text: str, child: UniverseChild) -> str:
        """Append compact universe metadata to source context for child preparation."""
        metadata = {
            "universe_id": child.universe_id,
            "scenario_variant": child.scenario_variant,
            "persona_variation": child.persona_variation,
        }
        return f"{document_text or ''}\n\n[MULTIVERSE_CONTEXT]\n{json.dumps(metadata, ensure_ascii=False)}"

    def prepare_experiment(
        self,
        multiverse_id: str,
        document_text: str = "",
        defined_entity_types: Optional[List[str]] = None,
        use_llm_for_profiles: bool = True,
        parallel_profile_count: int = 3,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Prepare child simulations sequentially with universe overlays.

        This is intentionally bounded and synchronous at the manager layer so the
        API can run it in a background task without hidden parallel LLM bursts.
        """
        experiment = self.get_experiment(multiverse_id)
        if not experiment:
            raise ValueError(f"Multiverse experiment not found: {multiverse_id}")

        experiment.status = MultiverseStatus.PREPARING
        prepared_count = 0
        skipped_count = 0
        failed: List[Dict[str, Any]] = []
        children_result: List[Dict[str, Any]] = []

        for child in experiment.children:
            state = self.simulation_manager.get_simulation(child.simulation_id)
            if not state:
                child.status = "missing"
                failed.append({"universe_id": child.universe_id, "simulation_id": child.simulation_id, "error": "missing child simulation"})
                children_result.append(child.to_dict())
                continue
            if not force and state.status == SimulationStatus.READY and state.config_generated:
                child.status = "ready"
                skipped_count += 1
                children_result.append(child.to_dict())
                continue

            child.status = "preparing"
            self._save_experiment(experiment)
            try:
                prepared_state = self.simulation_manager.prepare_simulation(
                    simulation_id=child.simulation_id,
                    simulation_requirement=self._build_child_requirement(experiment, child),
                    document_text=self._build_child_document_text(document_text, child),
                    defined_entity_types=defined_entity_types,
                    use_llm_for_profiles=use_llm_for_profiles,
                    parallel_profile_count=parallel_profile_count,
                    persona_selection_mode=experiment.persona_selection_mode,
                    max_agent_personas=experiment.max_agent_personas,
                )
                child.status = prepared_state.status.value
                if prepared_state.status == SimulationStatus.READY:
                    prepared_count += 1
            except Exception as e:
                child.status = "failed"
                failed.append({"universe_id": child.universe_id, "simulation_id": child.simulation_id, "error": str(e)})
            self._write_child_context(child, experiment)
            children_result.append(child.to_dict())

        if failed and prepared_count == 0 and skipped_count == 0:
            experiment.status = MultiverseStatus.FAILED
        elif prepared_count + skipped_count == len(experiment.children):
            experiment.status = MultiverseStatus.PREPARING
        else:
            experiment.status = MultiverseStatus.PARTIAL
        self._save_experiment(experiment)
        return {
            "multiverse_id": experiment.multiverse_id,
            "status": experiment.status.value,
            "prepared_count": prepared_count,
            "skipped_count": skipped_count,
            "failed_count": len(failed),
            "failed": failed,
            "children": children_result,
        }

    def prepare_experiment_async(
        self,
        multiverse_id: str,
        document_text: str = "",
        defined_entity_types: Optional[List[str]] = None,
        use_llm_for_profiles: bool = True,
        parallel_profile_count: int = 3,
        force: bool = False,
        use_thread: bool = True,
    ) -> Dict[str, Any]:
        """Queue multiverse preparation through TaskManager.

        The synchronous prepare_experiment method remains the implementation core;
        this wrapper exposes honest progress/result state for the UI and allows
        tests to run deterministically with use_thread=False.
        """
        experiment = self.get_experiment(multiverse_id)
        if not experiment:
            raise ValueError(f"Multiverse experiment not found: {multiverse_id}")

        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type="multiverse_prepare",
            metadata={
                "multiverse_id": multiverse_id,
                "project_id": experiment.project_id,
                "universe_count": len(experiment.children),
            },
        )

        def run_prepare() -> None:
            try:
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    progress=5,
                    message="멀티버스 prepare queue 시작",
                    progress_detail={"multiverse_id": multiverse_id, "phase": "prepare_started"},
                )
                result = self.prepare_experiment(
                    multiverse_id=multiverse_id,
                    document_text=document_text,
                    defined_entity_types=defined_entity_types,
                    use_llm_for_profiles=use_llm_for_profiles,
                    parallel_profile_count=parallel_profile_count,
                    force=force,
                )
                task_manager.complete_task(task_id, result)
                task_manager.update_task(
                    task_id,
                    message="멀티버스 prepare queue 완료",
                    progress_detail={
                        "multiverse_id": multiverse_id,
                        "prepared_count": result.get("prepared_count", 0),
                        "skipped_count": result.get("skipped_count", 0),
                        "failed_count": result.get("failed_count", 0),
                    },
                )
            except Exception as exc:  # pragma: no cover - exercised via API/ops path
                logger.error("Multiverse async prepare failed: %s", exc)
                task_manager.fail_task(task_id, str(exc))

        if use_thread:
            thread = threading.Thread(target=run_prepare, daemon=True)
            thread.start()
            status = "queued"
        else:
            run_prepare()
            status = "completed"

        return {
            "multiverse_id": multiverse_id,
            "task_id": task_id,
            "status": status,
            "message": "멀티버스 prepare task가 등록되었습니다.",
        }

    def start_experiment(
        self,
        multiverse_id: str,
        platform: str = "parallel",
        force: bool = False,
    ) -> Dict[str, Any]:
        """Start up to max_parallel ready child simulations; leave the rest queued."""
        experiment = self.get_experiment(multiverse_id)
        if not experiment:
            raise ValueError(f"Multiverse experiment not found: {multiverse_id}")
        if platform not in {"twitter", "reddit", "parallel"}:
            raise ValueError(f"Invalid platform: {platform}")

        self.refresh_status(multiverse_id)
        experiment = self.get_experiment(multiverse_id)
        assert experiment is not None

        running_now = 0
        started: List[Dict[str, Any]] = []
        queued: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []

        simulation_manager = SimulationManager()
        for child in experiment.children:
            state = simulation_manager.get_simulation(child.simulation_id)
            run_state = SimulationRunner.get_run_state(child.simulation_id)
            is_running = run_state and run_state.runner_status in [RunnerStatus.STARTING, RunnerStatus.RUNNING]
            if is_running:
                running_now += 1
                child.status = "running"
                continue
            if not state or state.status != SimulationStatus.READY:
                child.status = state.status.value if state else "missing"
                continue
            if running_now >= experiment.max_parallel:
                child.status = "queued"
                queued.append(child.to_dict())
                continue

            try:
                graph_id = state.graph_id or experiment.graph_id
                if child.graph_memory_enabled and not graph_id:
                    raise ValueError("graph_id is required when graph memory update is enabled")
                run_state = SimulationRunner.start_simulation(
                    simulation_id=child.simulation_id,
                    platform=platform,
                    max_rounds=experiment.rounds,
                    enable_graph_memory_update=child.graph_memory_enabled,
                    graph_id=graph_id if child.graph_memory_enabled else None,
                )
                state.status = SimulationStatus.RUNNING
                simulation_manager._save_simulation_state(state)
                child.status = "running"
                running_now += 1
                started.append({**child.to_dict(), "run_state": run_state.to_dict()})
            except Exception as e:
                child.status = "failed"
                failed.append({"universe_id": child.universe_id, "simulation_id": child.simulation_id, "error": str(e)})

        experiment.status = MultiverseStatus.RUNNING if (started or running_now > 0) else MultiverseStatus.PARTIAL
        self._save_experiment(experiment)
        return {
            "multiverse_id": experiment.multiverse_id,
            "status": experiment.status.value,
            "started_count": len(started),
            "running_count": running_now,
            "queued_count": len(queued),
            "failed_count": len(failed),
            "started": started,
            "queued": queued,
            "failed": failed,
        }

    def auto_advance_queue(
        self,
        multiverse_id: str,
        platform: str = "parallel",
    ) -> Dict[str, Any]:
        """Scheduler tick: fill newly opened run slots from ready/queued children."""
        result = self.start_experiment(multiverse_id=multiverse_id, platform=platform)
        result["scheduler"] = {
            "mode": "auto_advance",
            "max_parallel_observed": result.get("running_count", 0),
            "message": "열린 실행 슬롯에 다음 ready/queued universe를 자동 투입했습니다.",
        }
        return result

    def refresh_status(self, multiverse_id: str) -> Dict[str, Any]:
        """Refresh child statuses from simulation/run state and schedule more queued runs if slots are open."""
        experiment = self.get_experiment(multiverse_id)
        if not experiment:
            raise ValueError(f"Multiverse experiment not found: {multiverse_id}")

        status_counter: Counter[str] = Counter()
        simulation_manager = SimulationManager()
        for child in experiment.children:
            state = simulation_manager.get_simulation(child.simulation_id)
            run_state = SimulationRunner.get_run_state(child.simulation_id)
            if run_state and run_state.runner_status in [RunnerStatus.STARTING, RunnerStatus.RUNNING]:
                child.status = "running"
            elif run_state and run_state.runner_status == RunnerStatus.COMPLETED:
                child.status = "completed"
                if state and state.status != SimulationStatus.COMPLETED:
                    state.status = SimulationStatus.COMPLETED
                    simulation_manager._save_simulation_state(state)
            elif state:
                child.status = state.status.value
            else:
                child.status = "missing"
            status_counter[child.status] += 1

        if status_counter.get("running", 0) > 0 or status_counter.get("queued", 0) > 0:
            experiment.status = MultiverseStatus.RUNNING
        elif status_counter.get("completed", 0) == len(experiment.children) and experiment.children:
            experiment.status = MultiverseStatus.COMPLETED
        elif status_counter.get("failed", 0) == len(experiment.children) and experiment.children:
            experiment.status = MultiverseStatus.FAILED
        elif status_counter.get("completed", 0) > 0 or status_counter.get("failed", 0) > 0:
            experiment.status = MultiverseStatus.PARTIAL
        self._save_experiment(experiment)
        return {
            "multiverse_id": experiment.multiverse_id,
            "status": experiment.status.value,
            "status_frequency": dict(status_counter),
            "children": [child.to_dict() for child in experiment.children],
        }

    @staticmethod
    def _tokenize_outcome(text: str) -> Set[str]:
        raw_tokens = re.findall(r"[A-Za-z가-힣0-9]{2,}", (text or "").lower())
        stopwords = {"으로", "에서", "그리고", "with", "that", "this", "the", "and", "된다"}
        normalized: Set[str] = set()
        for token in raw_tokens:
            token = re.sub(r"(으로|에서|에게|부터|까지|이며|이고|하고|한다|된다|이다|가|이|은|는|을|를|와|과|도)$", "", token)
            if len(token) >= 2 and token not in stopwords:
                normalized.add(token)
        return normalized

    def _build_semantic_outcome_clusters(self, child_summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Lightweight semantic clustering over child outcome text.

        This is intentionally deterministic for local/runtime safety. It groups
        completed child summaries by token-overlap similarity and includes short
        evidence snippets so a later LLM/embedding implementation can replace the
        similarity function without changing the API shape.
        """
        completed = [child for child in child_summaries if child.get("status") == "completed"]
        if not completed:
            return []

        token_sets = {child["universe_id"]: self._tokenize_outcome(child.get("config_reasoning", "")) for child in completed}
        assigned: Set[str] = set()
        clusters: List[Dict[str, Any]] = []
        threshold = 0.15
        for child in completed:
            universe_id = child["universe_id"]
            if universe_id in assigned:
                continue
            cluster_children = [child]
            assigned.add(universe_id)
            base_tokens = token_sets[universe_id]
            for other in completed:
                other_id = other["universe_id"]
                if other_id in assigned:
                    continue
                other_tokens = token_sets[other_id]
                union = base_tokens | other_tokens
                similarity = (len(base_tokens & other_tokens) / len(union)) if union else 0.0
                if similarity >= threshold:
                    cluster_children.append(other)
                    assigned.add(other_id)
                    base_tokens = base_tokens | other_tokens

            common_terms = sorted(base_tokens, key=lambda token: (-sum(token in token_sets[item["universe_id"]] for item in cluster_children), token))[:6]
            evidence = [
                {
                    "universe_id": item["universe_id"],
                    "snippet": (item.get("config_reasoning", "") or "")[:160],
                }
                for item in cluster_children
            ]
            clusters.append({
                "cluster_id": f"semantic_{len(clusters) + 1}",
                "label": self._humanize_cluster_label(common_terms, evidence),
                "universe_ids": [item["universe_id"] for item in cluster_children],
                "frequency": len(cluster_children),
                "ensemble_frequency": f"{len(cluster_children)}/{len(child_summaries)}",
                "common_terms": common_terms,
                "evidence": evidence,
                "method": "deterministic_token_similarity",
            })
        return clusters


    @staticmethod
    def _humanize_cluster_label(common_terms: List[str], evidence: List[Dict[str, Any]]) -> str:
        text = " ".join(
            [" ".join(common_terms)]
            + [str(item.get("snippet", "")) for item in evidence]
        ).lower()
        label_rules = [
            ("규제 명확성 확산형", ["규제 명확", "명확성", "국채", "머니마켓", "레일"]),
            ("DeFi 담보 확산형", ["defi", "스테이블코인", "온체인", "신용시장", "오라클", "청산"]),
            ("규제 제한 지연형", ["규제기관", "강하게", "제한", "허가형", "파일럿", "접근성"]),
            ("환매·신용 리스크형", ["부동산", "사모신용", "환매", "고수익", "양극화", "투명성"]),
            ("핀테크 UX 채택형", ["핀테크", "kyc", "간편", "ux", "소액", "재방문"]),
            ("거래소·커뮤니티 확산형", ["거래소", "커뮤니티", "채택", "확산"]),
            ("언론 프레임 민감형", ["언론", "프레임", "media"]),
            ("기관 방어 전략형", ["은행", "방어", "로비", "incumbent"]),
            ("기관 주도 관망형", ["기관", "토큰화", "관망", "완만", "성장"]),
            ("사용자 신뢰 변화형", ["사용자", "신뢰", "채택"]),
        ]
        for label, keywords in label_rules:
            if any(keyword.lower() in text for keyword in keywords):
                return label
        if common_terms:
            return f"{common_terms[0]} 중심 결과형"
        return "분기 결과형"

    def _build_llm_assisted_outcome_clusters(self, child_summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Optionally ask the configured LLM to cluster outcomes; fall back safely."""
        completed = [child for child in child_summaries if child.get("status") == "completed"]
        api_key = getattr(Config, "LLM_API_KEY", "") or ""
        if not completed or not api_key or api_key.lower() in {"dummy", "placeholder", "test", "changeme"}:
            return self._build_semantic_outcome_clusters(child_summaries)
        try:
            payload = [
                {
                    "universe_id": child.get("universe_id"),
                    "summary": child.get("config_reasoning", "")[:1000],
                }
                for child in completed
            ]
            response = LLMClient().chat_json([
                {
                    "role": "system",
                    "content": (
                        "Cluster simulation outcomes. Return JSON only with key clusters. "
                        "Each cluster must include cluster_id, label, universe_ids, and one-sentence evidence."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ], temperature=0.1, max_tokens=2000)
            clusters = []
            known_ids = {child.get("universe_id") for child in completed}
            for idx, cluster in enumerate(response.get("clusters", []), start=1):
                universe_ids = [uid for uid in cluster.get("universe_ids", []) if uid in known_ids]
                if not universe_ids:
                    continue
                clusters.append({
                    "cluster_id": cluster.get("cluster_id") or f"llm_cluster_{idx}",
                    "label": cluster.get("label") or f"LLM cluster {idx}",
                    "universe_ids": universe_ids,
                    "frequency": len(universe_ids),
                    "ensemble_frequency": f"{len(universe_ids)}/{len(child_summaries)}",
                    "evidence": [cluster.get("evidence", "")],
                    "method": "llm_assisted_clustering",
                })
            return clusters or self._build_semantic_outcome_clusters(child_summaries)
        except Exception as exc:
            logger.warning("LLM-assisted multiverse clustering failed; falling back to semantic clustering: %s", exc)
            clusters = self._build_semantic_outcome_clusters(child_summaries)
            for cluster in clusters:
                cluster["llm_fallback_reason"] = str(exc)
            return clusters

    def _build_outcome_clusters(self, child_summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        keyword_families = {
            "institutional_defense": ["은행", "방어", "기관", "로비", "incumbent", "defense"],
            "regulatory_delay": ["규제", "지연", "감독", "regulatory", "delay"],
            "user_trust_shift": ["사용자", "신뢰", "채택", "adoption", "trust"],
            "exchange_led_growth": ["거래소", "확산", "시장", "exchange", "growth"],
            "media_amplification": ["언론", "프레임", "media", "frame"],
        }
        clusters: List[Dict[str, Any]] = []
        completed = [child for child in child_summaries if child.get("status") == "completed"]
        for cluster_id, keywords in keyword_families.items():
            matched = []
            for child in completed:
                text = child.get("config_reasoning", "")
                if any(keyword.lower() in text.lower() for keyword in keywords):
                    matched.append(child["universe_id"])
            if matched:
                clusters.append({
                    "cluster_id": cluster_id,
                    "label": cluster_id.replace("_", " ").title(),
                    "universe_ids": matched,
                    "frequency": len(matched),
                    "ensemble_frequency": f"{len(matched)}/{len(child_summaries)}",
                })
        if not clusters and completed:
            clusters.append({
                "cluster_id": "completed_without_classified_pattern",
                "label": "Completed branches without classified repeated pattern",
                "universe_ids": [child["universe_id"] for child in completed],
                "frequency": len(completed),
                "ensemble_frequency": f"{len(completed)}/{len(child_summaries)}",
            })
        return clusters

    @staticmethod
    def _first_sentence(text: str, limit: int = 90) -> str:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if not cleaned:
            return "결과 요약이 아직 없습니다"
        sentence = re.split(r"(?<=[.!?。！？])\s+", cleaned)[0]
        return sentence[:limit] + ("…" if len(sentence) > limit else "")

    def _select_single_baseline_source(self, experiment: MultiverseExperiment, aggregate: Dict[str, Any]) -> Dict[str, Any]:
        """Use the first completed multiverse child as the single-run baseline.

        This avoids running a duplicate single simulation while still making the
        comparison source explicit in API/UI so users know what "single" means.
        """
        for child in aggregate.get("children", []):
            if child.get("status") == "completed" and child.get("config_reasoning"):
                return {
                    "source_type": "first_completed_universe",
                    "source_label": "멀티버스 내 첫 완료 universe",
                    "universe_id": child.get("universe_id"),
                    "simulation_id": child.get("simulation_id"),
                    "axis": child.get("axis"),
                    "axis_label": child.get("label"),
                    "summary": child.get("config_reasoning", ""),
                    "reason": "추가 single run을 돌리지 않고, 같은 멀티버스 실험의 첫 완료 세계선을 단일 경로 baseline으로 사용합니다.",
                }
        return {
            "source_type": "none",
            "source_label": "완료된 단일 기준 없음",
            "summary": "",
            "reason": "아직 완료된 universe가 없어 단일 baseline을 만들 수 없습니다.",
        }

    def _build_contextual_suggested_questions(self, experiment: MultiverseExperiment, aggregate: Dict[str, Any]) -> List[Dict[str, str]]:
        topic = self._first_sentence(experiment.base_requirement, limit=120)
        clusters = aggregate.get("outcome_clusters", [])
        axes = aggregate.get("sensitivity_axes", [])
        completed = aggregate.get("completed_count", 0)
        total = aggregate.get("universe_count", 0)
        baseline = aggregate.get("single_baseline") or self._select_single_baseline_source(experiment, aggregate)

        questions: List[Dict[str, str]] = [
            {
                "category": "topic",
                "label": "주제 핵심",
                "question": f"'{topic}' 주제에서 현재 리포트가 말하는 핵심 결론은 뭐야?",
                "reason": "Report Agent가 먼저 사용자의 원래 주제와 현재 aggregate 리포트의 연결을 설명해야 합니다.",
            },
            {
                "category": "report",
                "label": "리포트 요약",
                "question": "현재 aggregate report를 의사결정자용으로 결론/근거/주의점 3단으로 요약해줘.",
                "reason": f"{completed}/{total} universe 진행 상태와 생성된 리포트를 한 번에 읽기 위한 질문입니다.",
            },
        ]

        if baseline.get("source_type") != "none":
            questions.append({
                "category": "single_vs_multiverse",
                "label": "단일 대비",
                "question": f"단일 기준({baseline.get('universe_id')})으로 봤다면 놓쳤을 멀티버스 결론은 뭐야?",
                "reason": "비교 기준이 첫 완료 universe로 정해져 있으므로, 그 단일 경로의 한계를 명시적으로 확인합니다.",
            })

        if clusters:
            strongest = max(clusters, key=lambda item: item.get("frequency", 0))
            questions.append({
                "category": "clusters",
                "label": "반복 결론",
                "question": f"가장 반복된 결론 cluster({strongest.get('ensemble_frequency')})는 왜 중요하고 근거 universe는 뭐야?",
                "reason": f"{len(clusters)}개 outcome cluster가 발견되어 반복 패턴을 검토할 가치가 있습니다.",
            })

        if axes:
            axis_labels = [axis.get("label") or axis.get("axis") for axis in axes if axis.get("label") or axis.get("axis")]
            focus_axis = axis_labels[0] if axis_labels else "가장 중요한 scenario axis"
            questions.append({
                "category": "sensitivity",
                "label": "분기/민감도",
                "question": f"'{focus_axis}' 조건이 결과를 어떻게 갈랐는지 설명해줘.",
                "reason": f"{len(axes)}개 sensitivity axis가 있어 결과가 어떤 조건에 민감한지 확인해야 합니다.",
            })

        questions.append({
            "category": "next_run",
            "label": "다음 실험",
            "question": "이 리포트 기준으로 다음 멀티버스 실행에서 바꿔볼 변수 3개를 추천해줘.",
            "reason": "현재 리포트에서 끝내지 않고 다음 실험 설계로 이어가기 위한 질문입니다.",
        })
        return questions

    def _build_report_agent_context(self, experiment: MultiverseExperiment, aggregate: Dict[str, Any]) -> Dict[str, Any]:
        baseline = aggregate.get("single_baseline") or self._select_single_baseline_source(experiment, aggregate)
        suggested_questions = self._build_contextual_suggested_questions(experiment, {**aggregate, "single_baseline": baseline})
        return {
            "context_type": "multiverse_ensemble",
            "multiverse_id": experiment.multiverse_id,
            "graph_id": experiment.graph_id,
            "base_requirement": experiment.base_requirement,
            "report_status": {
                "completed_count": aggregate.get("completed_count", 0),
                "universe_count": aggregate.get("universe_count", 0),
                "cluster_count": len(aggregate.get("outcome_clusters", [])),
                "sensitivity_axis_count": len(aggregate.get("sensitivity_axes", [])),
            },
            "single_baseline": baseline,
            "probability_caveat": aggregate.get("probability_note"),
            "outcome_clusters": aggregate.get("outcome_clusters", []),
            "sensitivity_axes": aggregate.get("sensitivity_axes", []),
            "child_simulations": [
                {
                    "universe_id": child.get("universe_id"),
                    "simulation_id": child.get("simulation_id"),
                    "status": child.get("status"),
                    "summary": child.get("config_reasoning", ""),
                }
                for child in aggregate.get("children", [])
            ],
            "suggested_questions": suggested_questions,
        }

    def build_single_run_baseline_answer(self, requirement: str, summary: str) -> Dict[str, Any]:
        """Shape a comparable baseline answer for one completed simulation."""
        evidence_items = 1 if summary else 0
        return {
            "response": (
                f"단일 시뮬레이션 기준 결론: {summary or '아직 완료된 결과가 없습니다.'}\n"
                "하나의 경로만 보기 때문에 반복성, 분기, 민감도, ensemble_frequency는 판단할 수 없습니다."
            ),
            "comparison_score": evidence_items,
            "evidence_items": evidence_items,
            "dimensions": ["single_outcome"],
            "requirement": requirement,
        }

    def _build_deterministic_multiverse_answer(
        self,
        question: str,
        aggregate: Dict[str, Any],
    ) -> Dict[str, Any]:
        clusters = aggregate.get("outcome_clusters", [])
        axes = aggregate.get("sensitivity_axes", [])
        evidence_items = sum(len(cluster.get("evidence", [])) or len(cluster.get("universe_ids", [])) for cluster in clusters)
        cluster_lines = "\n".join(
            f"- {cluster.get('label')}: {cluster.get('ensemble_frequency')} / 근거 universe {', '.join(cluster.get('universe_ids', []))}"
            for cluster in clusters[:5]
        ) or "- 아직 cluster를 만들 만큼 완료된 universe가 없습니다."
        axis_lines = "\n".join(
            f"- {axis.get('universe_id')}: {axis.get('label')} · {axis.get('polarity')} · {axis.get('status')}"
            for axis in axes[:6]
        )
        improvement_score = len(clusters) + len(axes) + evidence_items
        response = (
            "결론: 같은 주제라면 멀티버스 결과가 단일 실행보다 더 좋습니다. "
            "단일 실행은 하나의 결론만 주지만, 멀티버스는 반복 패턴과 갈리는 조건을 분리해서 보여줍니다.\n\n"
            "**반복 패턴 — ensemble_frequency**\n"
            f"{cluster_lines}\n\n"
            "**민감도/분기 축**\n"
            f"{axis_lines or '- 아직 비교 가능한 sensitivity axis가 없습니다.'}\n\n"
            "주의: ensemble_frequency는 실제 확률이 아니라 시뮬레이션 세계선 빈도입니다. "
            f"질문 `{question}`에 대해서는 공통 패턴과 분기 조건을 함께 보는 쪽이 의사결정에 더 유리합니다."
        )
        return {
            "response": response,
            "answer_mode": "deterministic_multiverse_report_agent",
            "sources": [cluster.get("cluster_id", "") for cluster in clusters],
            "tool_calls": [],
            "comparison": {
                "is_better_than_single_baseline": improvement_score > 1,
                "improvement_score": improvement_score,
                "cluster_count": len(clusters),
                "sensitivity_axis_count": len(axes),
                "evidence_items": evidence_items,
                "reason": "멀티버스는 단일 outcome 외에 반복 빈도, 분기 축, cluster evidence를 추가로 제공합니다.",
            },
            "aggregate": aggregate,
        }

    def answer_report_agent_question(
        self,
        multiverse_id: str,
        question: str,
        use_llm: bool = False,
        clustering_strategy: str = "semantic",
    ) -> Dict[str, Any]:
        """Answer a multiverse report question using aggregate context.

        LLM mode is opt-in and fails closed to deterministic context answers when
        credentials are absent or placeholder/dummy keys are configured.
        """
        aggregate = self.aggregate_experiment(multiverse_id, clustering_strategy=clustering_strategy)
        deterministic = self._build_deterministic_multiverse_answer(question, aggregate)
        if not use_llm:
            return deterministic

        api_key = getattr(Config, "LLM_API_KEY", "") or ""
        if not api_key or api_key.lower() in {"dummy", "placeholder", "test", "changeme"}:
            deterministic["answer_mode"] = "deterministic_multiverse_report_agent_no_llm_key"
            return deterministic

        try:
            context = aggregate.get("report_agent_context", {})
            prompt = (
                "You are the MiroFish Multiverse Report Agent. Answer in Korean. "
                "Use the provided multiverse context only; do not treat ensemble_frequency as real probability.\n\n"
                f"Question: {question}\n\nContext:\n{json.dumps(context, ensure_ascii=False)[:12000]}"
            )
            response = LLMClient().chat([
                {"role": "system", "content": "Answer concisely with conclusion first, evidence, and caveat."},
                {"role": "user", "content": prompt},
            ], temperature=0.2, max_tokens=1600)
            deterministic["response"] = response
            deterministic["answer_mode"] = "llm_assisted_multiverse_report_agent"
            return deterministic
        except Exception as exc:
            logger.warning("LLM-assisted multiverse answer failed; returning deterministic answer: %s", exc)
            deterministic["answer_mode"] = "deterministic_multiverse_report_agent_llm_failed"
            deterministic["llm_error"] = str(exc)
            return deterministic

    def compare_single_to_multiverse(
        self,
        multiverse_id: str,
        single_summary: str = "",
        question: str = "단일 시뮬레이션과 비교해 멀티버스가 더 나은 점이 뭐야?",
        clustering_strategy: str = "semantic",
        use_llm: bool = False,
    ) -> Dict[str, Any]:
        """Product-shaped comparison between the old single-run path and multiverse output."""
        experiment = self.get_experiment(multiverse_id)
        if not experiment:
            raise ValueError(f"Multiverse experiment not found: {multiverse_id}")

        aggregate = self.aggregate_experiment(multiverse_id, clustering_strategy=clustering_strategy)
        baseline_source = self._select_single_baseline_source(experiment, aggregate)
        if not single_summary:
            single_summary = baseline_source.get("summary", "")
        single = self.build_single_run_baseline_answer(experiment.base_requirement, single_summary)
        multiverse_answer = self.answer_report_agent_question(
            multiverse_id=multiverse_id,
            question=question,
            use_llm=use_llm,
            clustering_strategy=clustering_strategy,
        )
        comparison = multiverse_answer.get("comparison", {})
        pass_conditions = {
            "more_evidence_than_single": comparison.get("evidence_items", 0) > single.get("evidence_items", 0),
            "has_clusters": comparison.get("cluster_count", 0) >= 1,
            "has_sensitivity_axes": comparison.get("sensitivity_axis_count", 0) >= 1,
            "route_ready_answer": bool(multiverse_answer.get("response")),
        }
        judgement = "PASS" if all(pass_conditions.values()) else "WARN" if any(pass_conditions.values()) else "FAIL"
        return {
            "comparison_type": "single_vs_multiverse",
            "multiverse_id": multiverse_id,
            "topic": experiment.base_requirement,
            "single": {
                "summary": single_summary,
                "baseline_source": baseline_source,
                "comparison_score": single.get("comparison_score", 0),
                "evidence_items": single.get("evidence_items", 0),
                "limitations": ["single_outcome_only", "no_ensemble_frequency", "no_sensitivity_axes"],
            },
            "multiverse": {
                "universe_count": aggregate.get("universe_count", 0),
                "completed_count": aggregate.get("completed_count", 0),
                "cluster_count": comparison.get("cluster_count", 0),
                "sensitivity_axis_count": comparison.get("sensitivity_axis_count", 0),
                "evidence_items": comparison.get("evidence_items", 0),
                "improvement_score": comparison.get("improvement_score", 0),
                "answer_mode": multiverse_answer.get("answer_mode"),
                "answer": multiverse_answer.get("response", ""),
            },
            "judgement": {
                "verdict": judgement,
                "is_better_than_single_baseline": comparison.get("is_better_than_single_baseline", False),
                "pass_conditions": pass_conditions,
                "why": comparison.get("reason", ""),
                "caveat": "ensemble_frequency는 실제 확률이 아니라 시뮬레이션 세계선 빈도입니다.",
            },
            "aggregate": aggregate,
            "report_agent_context": aggregate.get("report_agent_context", {}),
            "report_markdown": self._build_comparison_markdown(single, multiverse_answer, aggregate, judgement),
            "generated_at": datetime.now().isoformat(),
        }

    def _build_comparison_markdown(
        self,
        single: Dict[str, Any],
        multiverse_answer: Dict[str, Any],
        aggregate: Dict[str, Any],
        judgement: str,
    ) -> str:
        comparison = multiverse_answer.get("comparison", {})
        return f"""# Single-run vs Multiverse Comparison

## Verdict
- {judgement}
- 멀티버스 개선 판단: {comparison.get('is_better_than_single_baseline', False)}

## Single-run baseline
- evidence_items: {single.get('evidence_items', 0)}
- limitations: single_outcome_only, no ensemble_frequency, no sensitivity_axes

## Multiverse
- universes: {aggregate.get('universe_count', 0)}
- completed: {aggregate.get('completed_count', 0)}
- clusters: {comparison.get('cluster_count', 0)}
- sensitivity_axes: {comparison.get('sensitivity_axis_count', 0)}
- evidence_items: {comparison.get('evidence_items', 0)}
- improvement_score: {comparison.get('improvement_score', 0)}

## Report Agent answer
{multiverse_answer.get('response', '')}

## Caveat
ensemble_frequency는 실제 확률이 아니라 시뮬레이션 세계선 빈도입니다.
"""

    def _build_ensemble_report_markdown(self, experiment: MultiverseExperiment, aggregate: Dict[str, Any]) -> str:
        clusters = aggregate.get("outcome_clusters", [])
        cluster_lines = "\n".join(
            f"- {cluster['label']}: {cluster['ensemble_frequency']} branches ({', '.join(cluster['universe_ids'])})"
            for cluster in clusters
        ) or "- 아직 분류 가능한 완료 outcome cluster가 없습니다."
        sensitivity_lines = "\n".join(
            f"- {axis['universe_id']}: {axis['label']} / {axis['polarity']} / {axis['status']}"
            for axis in aggregate.get("sensitivity_axes", [])
        )
        return f"""# Multiverse Ensemble Report

## Scope
- Topic: {experiment.base_requirement}
- Universes: {aggregate.get('universe_count', 0)}
- Completed: {aggregate.get('completed_count', 0)}

## Outcome clusters — ensemble_frequency
{cluster_lines}

## Common findings
{chr(10).join(f'- {item}' for item in aggregate.get('common_findings', [])) or '- 완료된 branch가 더 필요합니다.'}

## Divergent findings / sensitivity axes
{sensitivity_lines}

## Probability caveat
이 값은 실제 확률(calibrated real-world probability)이 아니라 simulation branch의 ensemble_frequency입니다. 보고서에서는 반복적으로 나타난 패턴과 민감한 가정을 구분하는 근거로만 사용합니다.
"""

    def aggregate_experiment(self, multiverse_id: str, clustering_strategy: str = "keyword") -> Dict[str, Any]:
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
            "running_count": status_counter.get("running", 0),
            "ready_count": status_counter.get("ready", 0),
            "queued_count": status_counter.get("queued", 0),
            "progress": {
                "completed": len(completed_children),
                "running": status_counter.get("running", 0),
                "ready": status_counter.get("ready", 0),
                "queued": status_counter.get("queued", 0),
                "failed": len(failed_children),
                "total": len(experiment.children),
                "completion_ratio": (len(completed_children) / len(experiment.children)) if experiment.children else 0,
            },
            "status_frequency": dict(status_counter),
            "clustering_strategy": clustering_strategy,
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
                "완료된 universe들에서 반복적으로 등장한 outcome cluster를 ensemble_frequency로 비교합니다."
            ] if completed_children else [],
            "divergent_findings": [
                "status/axis별 차이가 큰 universe를 우선 검토해 민감 변수를 식별합니다."
            ] if len(status_counter) > 1 else [],
            "children": child_summaries,
            "generated_at": datetime.now().isoformat(),
        }
        if clustering_strategy not in {"keyword", "semantic", "llm"}:
            clustering_strategy = "keyword"
        if clustering_strategy == "llm":
            aggregate["outcome_clusters"] = self._build_llm_assisted_outcome_clusters(child_summaries)
        elif clustering_strategy == "semantic":
            aggregate["outcome_clusters"] = self._build_semantic_outcome_clusters(child_summaries)
        else:
            aggregate["outcome_clusters"] = self._build_outcome_clusters(child_summaries)
        aggregate["single_baseline"] = self._select_single_baseline_source(experiment, aggregate)
        aggregate["report_agent_context"] = self._build_report_agent_context(experiment, aggregate)
        aggregate["ensemble_report_markdown"] = self._build_ensemble_report_markdown(experiment, aggregate)
        experiment.aggregate = aggregate
        self._save_experiment(experiment)
        return aggregate
