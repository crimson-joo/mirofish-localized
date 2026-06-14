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


if __name__ == "__main__":
    unittest.main()
