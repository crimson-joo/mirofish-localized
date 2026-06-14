import os
import tempfile
import unittest


class MultiverseManagerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        from app.config import Config
        from app.models.project import ProjectManager
        from app.services.simulation_manager import SimulationManager

        Config.UPLOAD_FOLDER = self.tmpdir.name
        Config.OASIS_SIMULATION_DATA_DIR = os.path.join(self.tmpdir.name, "simulations")
        ProjectManager.PROJECTS_DIR = os.path.join(self.tmpdir.name, "projects")
        SimulationManager.SIMULATION_DATA_DIR = Config.OASIS_SIMULATION_DATA_DIR

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_create_experiment_spawns_distinct_child_simulations_and_universe_configs(self):
        from app.services.multiverse_manager import MultiverseManager, MultiverseStatus

        manager = MultiverseManager()
        experiment = manager.create_experiment(
            project_id="proj_demo",
            graph_id="graph_demo",
            base_requirement="원화 스테이블코인 법안 통과 후 시장 반응",
            universe_count=5,
            max_parallel=2,
            rounds=24,
            persona_selection_mode="core",
            max_agent_personas=30,
            graph_memory_enabled=True,
        )

        self.assertEqual(experiment.status, MultiverseStatus.CREATED)
        self.assertEqual(experiment.universe_count, 5)
        self.assertEqual(experiment.max_parallel, 2)
        self.assertEqual(len(experiment.children), 5)
        self.assertEqual(len({child.simulation_id for child in experiment.children}), 5)
        self.assertEqual(len({child.scenario_variant["axis"] for child in experiment.children}), 5)
        self.assertTrue(all(child.persona_variation["mode"] == "realistic" for child in experiment.children))
        self.assertTrue(all(child.graph_memory_enabled for child in experiment.children))

        reloaded = manager.get_experiment(experiment.multiverse_id)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.to_dict(), experiment.to_dict())

    def test_aggregate_reports_frequency_and_sensitivity_without_overstating_probability(self):
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
        for child, status in zip(
            experiment.children,
            [SimulationStatus.COMPLETED, SimulationStatus.COMPLETED, SimulationStatus.FAILED],
        ):
            state = sim_manager.get_simulation(child.simulation_id)
            assert state is not None
            state.status = status
            state.config_reasoning = f"{child.scenario_variant['label']} outcome"
            sim_manager._save_simulation_state(state)

        aggregate = manager.aggregate_experiment(experiment.multiverse_id)

        self.assertEqual(aggregate["universe_count"], 3)
        self.assertEqual(aggregate["completed_count"], 2)
        self.assertEqual(aggregate["failed_count"], 1)
        self.assertEqual(aggregate["status_frequency"]["completed"], 2)
        self.assertEqual(aggregate["status_frequency"]["failed"], 1)
        self.assertIn("ensemble_frequency", aggregate["probability_note"])
        self.assertEqual(len(aggregate["sensitivity_axes"]), 3)
        self.assertIn("common_findings", aggregate)


if __name__ == "__main__":
    unittest.main()
