import os
import tempfile
import unittest


class RouteSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["GRAPH_PROVIDER"] = "local_simple"
        os.environ["LOCAL_GRAPH_STORAGE_DIR"] = self.tmpdir.name
        os.environ["LLM_API_KEY"] = "dummy"
        os.environ.pop("ZEP_API_KEY", None)

        from app.config import Config
        Config.GRAPH_PROVIDER = "local_simple"
        Config.LOCAL_GRAPH_STORAGE_DIR = self.tmpdir.name
        Config.LLM_API_KEY = "dummy"
        Config.ZEP_API_KEY = None

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

    def test_graph_data_route_exposes_runtime_shape(self):
        from app.services.graph_provider import get_graph_builder

        builder = get_graph_builder()
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


if __name__ == "__main__":
    unittest.main()
