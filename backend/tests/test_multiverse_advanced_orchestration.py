import os
import tempfile
import unittest
from unittest.mock import patch


class MultiverseAdvancedOrchestrationTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        from app.config import Config
        from app.models.project import ProjectManager
        from app.models.task import TaskManager
        from app.services.simulation_manager import SimulationManager
        from app.services.multiverse_manager import MultiverseManager

        Config.UPLOAD_FOLDER = self.tmpdir.name
        Config.OASIS_SIMULATION_DATA_DIR = os.path.join(self.tmpdir.name, "simulations")
        ProjectManager.PROJECTS_DIR = os.path.join(self.tmpdir.name, "projects")
        SimulationManager.SIMULATION_DATA_DIR = Config.OASIS_SIMULATION_DATA_DIR
        MultiverseManager.MULTIVERSE_DATA_DIR = os.path.join(self.tmpdir.name, "multiverses")
        TaskManager()._tasks.clear()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_auto_advance_starts_next_ready_child_after_slot_frees(self):
        from app.services.multiverse_manager import MultiverseManager
        from app.services.simulation_manager import SimulationManager, SimulationStatus
        from app.services.simulation_runner import RunnerStatus

        manager = MultiverseManager()
        experiment = manager.create_experiment(
            project_id="proj_demo",
            graph_id="graph_demo",
            base_requirement="AI 규제 이슈",
            universe_count=3,
            max_parallel=2,
        )
        sim_manager = SimulationManager()
        for child in experiment.children:
            state = sim_manager.get_simulation(child.simulation_id)
            state.status = SimulationStatus.READY
            sim_manager._save_simulation_state(state)

        started = []

        def fake_get_run_state(simulation_id):
            if simulation_id == experiment.children[0].simulation_id:
                return type("RunState", (), {"runner_status": RunnerStatus.COMPLETED})()
            if simulation_id == experiment.children[1].simulation_id:
                return type("RunState", (), {"runner_status": RunnerStatus.RUNNING})()
            return None

        def fake_start(**kwargs):
            started.append(kwargs["simulation_id"])
            return type("RunState", (), {"to_dict": lambda self: {"runner_status": "running"}})()

        with patch("app.services.multiverse_manager.SimulationRunner.get_run_state", side_effect=fake_get_run_state), \
             patch("app.services.multiverse_manager.SimulationRunner.start_simulation", side_effect=fake_start):
            result = manager.auto_advance_queue(experiment.multiverse_id, platform="parallel")

        self.assertEqual(result["started_count"], 1)
        self.assertEqual(started, [experiment.children[2].simulation_id])
        self.assertEqual(result["scheduler"]["mode"], "auto_advance")
        self.assertEqual(result["running_count"], 2)

    def test_prepare_async_task_records_progress_and_result(self):
        from app.models.task import TaskManager, TaskStatus
        from app.services.multiverse_manager import MultiverseManager
        from app.services.simulation_manager import SimulationStatus

        manager = MultiverseManager()
        experiment = manager.create_experiment(
            project_id="proj_demo",
            graph_id="graph_demo",
            base_requirement="AI 규제 이슈",
            universe_count=2,
        )

        def fake_prepare(simulation_id, **kwargs):
            state = manager.simulation_manager.get_simulation(simulation_id)
            state.status = SimulationStatus.READY
            state.config_generated = True
            manager.simulation_manager._save_simulation_state(state)
            return state

        with patch.object(manager.simulation_manager, "prepare_simulation", side_effect=fake_prepare):
            result = manager.prepare_experiment_async(
                experiment.multiverse_id,
                document_text="source",
                use_thread=False,
            )

        task = TaskManager().get_task(result["task_id"])
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.progress, 100)
        self.assertEqual(task.result["prepared_count"], 2)
        self.assertEqual(task.metadata["multiverse_id"], experiment.multiverse_id)

    def test_semantic_clusters_group_similar_child_outcomes_with_evidence(self):
        from app.services.multiverse_manager import MultiverseManager
        from app.services.simulation_manager import SimulationManager, SimulationStatus

        manager = MultiverseManager()
        experiment = manager.create_experiment(
            project_id="proj_demo",
            graph_id="graph_demo",
            base_requirement="AI 규제 이슈",
            universe_count=4,
        )
        sim_manager = SimulationManager()
        reasonings = [
            "은행 방어 전략으로 규제 지연과 사용자 신뢰 하락이 반복된다",
            "규제 지연 속에서 은행 방어가 강화되고 사용자 신뢰가 흔들린다",
            "거래소 주도 확산과 커뮤니티 채택이 상승한다",
            "거래소와 커뮤니티 중심 채택 확산이 강해진다",
        ]
        for child, reasoning in zip(experiment.children, reasonings):
            state = sim_manager.get_simulation(child.simulation_id)
            state.status = SimulationStatus.COMPLETED
            state.config_reasoning = reasoning
            sim_manager._save_simulation_state(state)

        aggregate = manager.aggregate_experiment(experiment.multiverse_id, clustering_strategy="semantic")

        self.assertEqual(aggregate["clustering_strategy"], "semantic")
        semantic_clusters = [cluster for cluster in aggregate["outcome_clusters"] if cluster["cluster_id"].startswith("semantic_")]
        self.assertGreaterEqual(len(semantic_clusters), 2)
        self.assertTrue(all(cluster.get("evidence") for cluster in semantic_clusters))
        self.assertIn("report_agent_context", aggregate)
        self.assertIn("질문", aggregate["report_agent_context"]["suggested_questions"][0])


if __name__ == "__main__":
    unittest.main()
