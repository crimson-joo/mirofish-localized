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
        tokens = set(re.findall(r"[A-Za-z가-힣0-9]{2,}", (text or "").lower()))
        stopwords = {"으로", "에서", "그리고", "with", "that", "this", "the", "and", "된다", "된다"}
        return {token for token in tokens if token not in stopwords}

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
        threshold = 0.22
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
                "label": "Semantic outcome cluster",
                "universe_ids": [item["universe_id"] for item in cluster_children],
                "frequency": len(cluster_children),
                "ensemble_frequency": f"{len(cluster_children)}/{len(child_summaries)}",
                "common_terms": common_terms,
                "evidence": evidence,
                "method": "deterministic_token_similarity",
            })
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

    def _build_report_agent_context(self, experiment: MultiverseExperiment, aggregate: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "context_type": "multiverse_ensemble",
            "multiverse_id": experiment.multiverse_id,
            "graph_id": experiment.graph_id,
            "base_requirement": experiment.base_requirement,
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
            "suggested_questions": [
                "질문: 어떤 universe들이 같은 결론으로 묶였고 근거는 무엇인가?",
                "질문: 결과가 가장 크게 갈린 scenario axis는 무엇인가?",
                "질문: ensemble_frequency를 실제 확률이 아닌 시뮬레이션 빈도로 어떻게 해석해야 하는가?",
            ],
        }

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
        if clustering_strategy not in {"keyword", "semantic"}:
            clustering_strategy = "keyword"
        aggregate["outcome_clusters"] = (
            self._build_semantic_outcome_clusters(child_summaries)
            if clustering_strategy == "semantic"
            else self._build_outcome_clusters(child_summaries)
        )
        aggregate["report_agent_context"] = self._build_report_agent_context(experiment, aggregate)
        aggregate["ensemble_report_markdown"] = self._build_ensemble_report_markdown(experiment, aggregate)
        experiment.aggregate = aggregate
        self._save_experiment(experiment)
        return aggregate
