import os
import tempfile
import unittest
from unittest.mock import patch


class RouteSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["GRAPH_PROVIDER"] = "graphiti"
        os.environ["GRAPHITI_BASE_URL"] = "http://127.0.0.1:1"
        os.environ["LOCAL_GRAPH_STORAGE_DIR"] = self.tmpdir.name
        os.environ["LLM_API_KEY"] = "dummy"
        os.environ.pop("ZEP_API_KEY", None)

        from app.config import Config
        Config.GRAPH_PROVIDER = "graphiti"
        Config.GRAPHITI_BASE_URL = "http://127.0.0.1:1"
        Config.LOCAL_GRAPH_STORAGE_DIR = self.tmpdir.name
        Config.UPLOAD_FOLDER = self.tmpdir.name
        Config.OASIS_SIMULATION_DATA_DIR = os.path.join(self.tmpdir.name, "simulations")
        Config.LLM_API_KEY = "dummy"
        Config.ZEP_API_KEY = None

        from app.models.project import ProjectManager
        from app.services.simulation_manager import SimulationManager
        from app.services.multiverse_manager import MultiverseManager
        ProjectManager.PROJECTS_DIR = os.path.join(self.tmpdir.name, "projects")
        SimulationManager.SIMULATION_DATA_DIR = Config.OASIS_SIMULATION_DATA_DIR
        MultiverseManager.MULTIVERSE_DATA_DIR = os.path.join(self.tmpdir.name, "multiverses")

        from app import create_app
        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_health_and_graph_tasks_routes(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

        response = self.client.get("/api/graph/tasks")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertIn("data", payload)
        self.assertIn("count", payload)

    def test_graph_tasks_route_handles_dict_tasks(self):
        persisted_task = {
            "task_id": "task_dict",
            "task_type": "report_generate",
            "status": "processing",
        }
        with patch("app.api.graph.TaskManager") as task_manager_cls:
            task_manager_cls.return_value.list_tasks.return_value = [persisted_task]
            response = self.client.get("/api/graph/tasks")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"], [persisted_task])

    def test_graph_data_route_exposes_runtime_shape(self):
        from app.services.graphiti_projection_cache import GraphitiProjectionGraphBuilder

        builder = GraphitiProjectionGraphBuilder()
        graph_id = builder.create_graph("route smoke")
        builder.set_ontology(graph_id, {"entity_types": [{"name": "Person", "description": "person"}], "edge_types": []})
        builder.add_text_batches(graph_id, ["Alice influences Bob."])

        response = self.client.get(f"/api/graph/data/{graph_id}")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        data = payload["data"]
        self.assertEqual(data["graph_id"], graph_id)
        self.assertIn("nodes", data)
        self.assertIn("edges", data)
        self.assertIn("node_count", data)
        self.assertIn("edge_count", data)

    def test_simulation_history_and_report_list_routes(self):
        response = self.client.get("/api/simulation/history?limit=1")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])

        response = self.client.get("/api/report/list")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])

    def test_multiverse_create_get_list_and_aggregate_routes(self):
        from app.models.project import ProjectManager
        from app.models.project import ProjectStatus
        from app.services.simulation_manager import SimulationManager, SimulationStatus

        project = ProjectManager.create_project("multiverse route smoke")
        project.status = ProjectStatus.GRAPH_COMPLETED
        project.graph_id = "graph_route_demo"
        project.simulation_requirement = "원화 스테이블코인 법안 통과 후 시장 반응"
        ProjectManager.save_project(project)

        response = self.client.post("/api/simulation/multiverse/create", json={
            "project_id": project.project_id,
            "universe_count": 2,
            "max_parallel": 2,
            "rounds": 24,
            "persona_selection_mode": "core",
            "graph_memory_enabled": True,
        })
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        experiment = payload["data"]
        self.assertEqual(experiment["universe_count"], 2)
        self.assertEqual(len(experiment["children"]), 2)

        get_response = self.client.get(f"/api/simulation/multiverse/{experiment['multiverse_id']}")
        self.assertEqual(get_response.status_code, 200)
        self.assertTrue(get_response.get_json()["success"])

        list_response = self.client.get(f"/api/simulation/multiverse/list?project_id={project.project_id}")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.get_json()["count"], 1)

        sim_manager = SimulationManager()
        for child in experiment["children"]:
            state = sim_manager.get_simulation(child["simulation_id"])
            assert state is not None
            state.status = SimulationStatus.COMPLETED
            sim_manager._save_simulation_state(state)

        aggregate_response = self.client.post(f"/api/simulation/multiverse/{experiment['multiverse_id']}/aggregate")
        self.assertEqual(aggregate_response.status_code, 200)
        aggregate = aggregate_response.get_json()["data"]["aggregate"]
        self.assertEqual(aggregate["completed_count"], 2)
        self.assertIn("ensemble_frequency", aggregate["probability_note"])

    def test_multiverse_prepare_start_status_and_report_routes(self):
        from app.models.project import ProjectManager, ProjectStatus
        from app.services.simulation_manager import SimulationManager, SimulationStatus

        project = ProjectManager.create_project("multiverse orchestration route")
        project.status = ProjectStatus.GRAPH_COMPLETED
        project.graph_id = "graph_route_demo"
        project.simulation_requirement = "AI 규제 이슈"
        ProjectManager.save_project(project)

        create_response = self.client.post("/api/simulation/multiverse/create", json={
            "project_id": project.project_id,
            "universe_count": 3,
            "max_parallel": 2,
            "graph_memory_enabled": True,
        })
        experiment = create_response.get_json()["data"]
        mv_id = experiment["multiverse_id"]

        def fake_prepare(self, simulation_id, simulation_requirement, document_text, **kwargs):
            state = self.get_simulation(simulation_id)
            assert state is not None
            state.status = SimulationStatus.READY
            state.config_generated = True
            state.config_reasoning = simulation_requirement
            self._save_simulation_state(state)
            return state

        with patch("app.services.simulation_manager.SimulationManager.prepare_simulation", fake_prepare):
            prepare_response = self.client.post(f"/api/simulation/multiverse/{mv_id}/prepare", json={
                "document_text": "source",
                "use_llm_for_profiles": False,
                "async": True,
                "use_thread": False,
            })
        self.assertEqual(prepare_response.status_code, 200)
        prepare_payload = prepare_response.get_json()["data"]
        self.assertIn("task_id", prepare_payload)
        self.assertEqual(prepare_payload["status"], "completed")

        task_response = self.client.get(f"/api/simulation/multiverse/{mv_id}/prepare/status", query_string={"task_id": prepare_payload["task_id"]})
        self.assertEqual(task_response.status_code, 200)
        self.assertEqual(task_response.get_json()["data"]["status"], "completed")

        sim_manager = SimulationManager()

        def fake_start(**kwargs):
            state = sim_manager.get_simulation(kwargs["simulation_id"])
            assert state is not None
            state.status = SimulationStatus.RUNNING
            sim_manager._save_simulation_state(state)
            return type("RunState", (), {"to_dict": lambda self: {"runner_status": "running"}})()

        with patch("app.services.multiverse_manager.SimulationRunner.start_simulation", side_effect=fake_start):
            start_response = self.client.post(f"/api/simulation/multiverse/{mv_id}/start", json={"platform": "parallel"})
        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(start_response.get_json()["data"]["started_count"], 2)
        self.assertEqual(start_response.get_json()["data"]["queued_count"], 1)

        with patch("app.services.multiverse_manager.SimulationRunner.start_simulation", side_effect=fake_start):
            advance_response = self.client.post(f"/api/simulation/multiverse/{mv_id}/advance", json={"platform": "parallel"})
        self.assertEqual(advance_response.status_code, 200)
        self.assertEqual(advance_response.get_json()["data"]["scheduler"]["mode"], "auto_advance")

        status_response = self.client.get(f"/api/simulation/multiverse/{mv_id}/status")
        self.assertEqual(status_response.status_code, 200)
        self.assertTrue(status_response.get_json()["success"])

        for child in experiment["children"]:
            state = sim_manager.get_simulation(child["simulation_id"])
            assert state is not None
            state.status = SimulationStatus.COMPLETED
            state.config_reasoning = "은행권 방어 행동 강화"
            sim_manager._save_simulation_state(state)

        report_response = self.client.post(f"/api/simulation/multiverse/{mv_id}/report", json={"clustering_strategy": "semantic"})
        self.assertEqual(report_response.status_code, 200)
        report_payload = report_response.get_json()["data"]
        report = report_payload["report_markdown"]
        self.assertIn("ensemble_frequency", report)
        self.assertIn("실제 확률", report)
        self.assertEqual(report_payload["aggregate"]["clustering_strategy"], "semantic")
        self.assertIn("report_agent_context", report_payload["aggregate"])

        context_response = self.client.get(f"/api/simulation/multiverse/{mv_id}/report-agent-context")
        self.assertEqual(context_response.status_code, 200)
        self.assertEqual(context_response.get_json()["data"]["context_type"], "multiverse_ensemble")


if __name__ == "__main__":
    unittest.main()
