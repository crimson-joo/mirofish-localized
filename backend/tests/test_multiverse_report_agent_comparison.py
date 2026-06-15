import os
import tempfile
import unittest


class MultiverseReportAgentComparisonTest(unittest.TestCase):
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

        from app import create_app
        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _completed_multiverse(self):
        from app.services.multiverse_manager import MultiverseManager
        from app.services.simulation_manager import SimulationManager, SimulationStatus

        manager = MultiverseManager()
        experiment = manager.create_experiment(
            project_id="proj_compare",
            graph_id="graph_compare",
            base_requirement="AI 규제 이슈에 대한 시장과 사용자 반응 비교",
            universe_count=4,
        )
        reasonings = [
            "은행 방어 전략으로 규제 지연과 사용자 신뢰 하락이 반복된다",
            "규제 지연 속에서 은행 방어가 강화되고 사용자 신뢰가 흔들린다",
            "거래소 주도 확산과 커뮤니티 채택이 상승한다",
            "언론 프레임 변화로 사용자 신뢰와 채택 속도가 크게 갈린다",
        ]
        sim_manager = SimulationManager()
        for child, reasoning in zip(experiment.children, reasonings):
            state = sim_manager.get_simulation(child.simulation_id)
            assert state is not None
            state.status = SimulationStatus.COMPLETED
            state.config_reasoning = reasoning
            sim_manager._save_simulation_state(state)
        return manager, experiment

    def test_report_agent_answer_uses_multiverse_context_and_is_more_comparative_than_single_baseline(self):
        manager, experiment = self._completed_multiverse()

        single_baseline = manager.build_single_run_baseline_answer(
            "AI 규제 이슈에 대한 시장과 사용자 반응 비교",
            "은행 방어 전략으로 규제 지연과 사용자 신뢰 하락이 반복된다",
        )
        multiverse_answer = manager.answer_report_agent_question(
            experiment.multiverse_id,
            "단일 시뮬레이션과 비교해 멀티버스가 더 나은 점이 뭐야?",
            use_llm=False,
        )

        self.assertEqual(multiverse_answer["answer_mode"], "deterministic_multiverse_report_agent")
        self.assertIn("ensemble_frequency", multiverse_answer["response"])
        self.assertIn("민감도", multiverse_answer["response"])
        self.assertGreater(multiverse_answer["comparison"]["improvement_score"], single_baseline["comparison_score"])
        self.assertGreaterEqual(multiverse_answer["comparison"]["cluster_count"], 2)
        self.assertGreater(multiverse_answer["comparison"]["evidence_items"], single_baseline["evidence_items"])

    def test_multiverse_report_agent_chat_route_returns_comparison_shape(self):
        manager, experiment = self._completed_multiverse()

        response = self.client.post(
            f"/api/simulation/multiverse/{experiment.multiverse_id}/report-agent-chat",
            json={"message": "이전 단일 실행 대비 더 좋아진 게 맞아?", "use_llm": False},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        data = payload["data"]
        self.assertIn("ensemble_frequency", data["response"])
        self.assertIn("comparison", data)
        self.assertTrue(data["comparison"]["is_better_than_single_baseline"])

    def test_compare_single_route_returns_product_verdict(self):
        manager, experiment = self._completed_multiverse()

        response = self.client.post(
            f"/api/simulation/multiverse/{experiment.multiverse_id}/compare-single",
            json={"clustering_strategy": "semantic", "use_llm": False},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        data = payload["data"]
        self.assertEqual(data["comparison_type"], "single_vs_multiverse")
        self.assertEqual(data["judgement"]["verdict"], "PASS")
        self.assertGreater(data["multiverse"]["evidence_items"], data["single"]["evidence_items"])
        self.assertEqual(data["single"]["baseline_source"]["source_type"], "first_completed_universe")
        self.assertEqual(data["single"]["baseline_source"]["universe_id"], experiment.children[0].universe_id)
        self.assertIn("report_agent_context", data)
        suggested = data["report_agent_context"]["suggested_questions"]
        self.assertGreaterEqual(len(suggested), 5)
        self.assertTrue(all("question" in item and "reason" in item and "category" in item for item in suggested))
        self.assertIn("AI 규제 이슈", suggested[0]["question"])
        self.assertIn("Single-run vs Multiverse", data["report_markdown"])


if __name__ == "__main__":
    unittest.main()
