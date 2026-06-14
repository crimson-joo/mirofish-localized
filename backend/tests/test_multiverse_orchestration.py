import os
import tempfile
import unittest
from unittest.mock import patch


class MultiverseOrchestrationTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        from app.config import Config
        from app.models.project import ProjectManager
        from app.services.simulation_manager import SimulationManager
        from app.services.multiverse_manager import MultiverseManager

        Config.UPLOAD_FOLDER = self.tmpdir.name
        Config.OASIS_SIMULATION_DATA_DIR = os.path.join(self.tmpdir.name, "simulations")
        ProjectManager.PROJECTS_DIR = os.path.join(self.tmpdir.name, "projects")
        SimulationManager.SIMULATION_DATA_DIR = Config.OASIS_SIMULATION_DATA_DIR
        MultiverseManager.MULTIVERSE_DATA_DIR = os.path.join(self.tmpdir.name, "multiverses")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_prepare_experiment_applies_universe_overlay_and_marks_children_ready(self):
        from app.services.multiverse_manager import MultiverseManager, MultiverseStatus
        from app.services.simulation_manager import SimulationStatus

        manager = MultiverseManager()
        experiment = manager.create_experiment(
            project_id="proj_demo",
            graph_id="graph_demo",
            base_requirement="AI 규제 이슈",
            universe_count=3,
            rounds=24,
        )

        captured_requirements = []

        def fake_prepare(simulation_id, simulation_requirement, document_text, **kwargs):
            captured_requirements.append(simulation_requirement)
            state = manager.simulation_manager.get_simulation(simulation_id)
            assert state is not None
            state.status = SimulationStatus.READY
            state.config_generated = True
            state.config_reasoning = f"prepared {simulation_id}"
            manager.simulation_manager._save_simulation_state(state)
            return state

        with patch.object(manager.simulation_manager, "prepare_simulation", side_effect=fake_prepare):
            result = manager.prepare_experiment(
                experiment.multiverse_id,
                document_text="source document",
                use_llm_for_profiles=False,
                force=False,
            )

        self.assertEqual(result["status"], MultiverseStatus.PREPARING.value)
        self.assertEqual(result["prepared_count"], 3)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(len(captured_requirements), 3)
        self.assertTrue(all("가능세계" in item for item in captured_requirements))
        self.assertEqual(len(set(captured_requirements)), 3)

        reloaded = manager.get_experiment(experiment.multiverse_id)
        self.assertTrue(all(child.status == "ready" for child in reloaded.children))

    def test_start_queue_respects_max_parallel_and_updates_parent_status(self):
        from app.services.multiverse_manager import MultiverseManager, MultiverseStatus
        from app.services.simulation_manager import SimulationManager, SimulationStatus

        manager = MultiverseManager()
        experiment = manager.create_experiment(
            project_id="proj_demo",
            graph_id="graph_demo",
            base_requirement="AI 규제 이슈",
            universe_count=4,
            max_parallel=2,
            graph_memory_enabled=True,
        )

        sim_manager = SimulationManager()
        for child in experiment.children:
            state = sim_manager.get_simulation(child.simulation_id)
            assert state is not None
            state.status = SimulationStatus.READY
            sim_manager._save_simulation_state(state)

        started = []

        def fake_start(**kwargs):
            started.append(kwargs)
            state = sim_manager.get_simulation(kwargs["simulation_id"])
            assert state is not None
            state.status = SimulationStatus.RUNNING
            sim_manager._save_simulation_state(state)
            return type("RunState", (), {"to_dict": lambda self: {"runner_status": "running"}})()

        with patch("app.services.multiverse_manager.SimulationRunner.start_simulation", side_effect=fake_start):
            result = manager.start_experiment(experiment.multiverse_id, platform="parallel")

        self.assertEqual(result["started_count"], 2)
        self.assertEqual(result["queued_count"], 2)
        self.assertEqual([call["max_rounds"] for call in started], [24, 24])
        self.assertTrue(all(call["enable_graph_memory_update"] for call in started))
        self.assertEqual(result["status"], MultiverseStatus.RUNNING.value)

    def test_aggregate_includes_outcome_clusters_and_markdown_report(self):
        from app.services.multiverse_manager import MultiverseManager
        from app.services.simulation_manager import SimulationManager, SimulationStatus

        manager = MultiverseManager()
        experiment = manager.create_experiment(
            project_id="proj_demo",
            graph_id="graph_demo",
            base_requirement="AI 규제 이슈",
            universe_count=3,
        )

        sim_manager = SimulationManager()
        reasonings = [
            "은행권 방어 행동 강화와 사용자 신뢰 하락",
            "은행권 방어 행동 강화와 규제기관 지연",
            "거래소 주도 확산과 사용자 신뢰 상승",
        ]
        for child, reasoning in zip(experiment.children, reasonings):
            state = sim_manager.get_simulation(child.simulation_id)
            assert state is not None
            state.status = SimulationStatus.COMPLETED
            state.config_reasoning = reasoning
            sim_manager._save_simulation_state(state)

        aggregate = manager.aggregate_experiment(experiment.multiverse_id)

        self.assertIn("outcome_clusters", aggregate)
        self.assertGreaterEqual(len(aggregate["outcome_clusters"]), 1)
        self.assertIn("ensemble_report_markdown", aggregate)
        self.assertIn("ensemble_frequency", aggregate["ensemble_report_markdown"])
        self.assertIn("실제 확률", aggregate["ensemble_report_markdown"])


if __name__ == "__main__":
    unittest.main()
