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

    def test_semantic_clusters_use_human_readable_market_labels(self):
        from app.services.multiverse_manager import MultiverseManager

        manager = MultiverseManager()
        child_summaries = [
            {
                "universe_id": "u1",
                "status": "completed",
                "config_reasoning": "규제 명확성이 빨리 확보되면서 토큰화 국채와 머니마켓펀드가 기관 담보 시장의 기본 레일로 확산된다.",
            },
            {
                "universe_id": "u2",
                "status": "completed",
                "config_reasoning": "DeFi 수익률 하락과 스테이블코인 결제 확산이 겹치며 RWA 담보가 온체인 신용시장의 핵심 재료가 된다.",
            },
            {
                "universe_id": "u3",
                "status": "completed",
                "config_reasoning": "규제기관이 토큰화 증권을 강하게 제한하면서 허가형 네트워크 안의 파일럿만 남고 퍼블릭체인 RWA는 성장 속도가 느려진다.",
            },
        ]

        labels = {cluster["label"] for cluster in manager._build_semantic_outcome_clusters(child_summaries)}

        self.assertIn("규제 명확성 확산형", labels)
        self.assertIn("DeFi 담보 확산형", labels)
        self.assertIn("규제 제한 지연형", labels)
        self.assertNotIn("Semantic outcome cluster", labels)


if __name__ == "__main__":
    unittest.main()
