import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer


class _GraphitiStub(BaseHTTPRequestHandler):
    calls = []

    def _send(self, status=200, payload=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload or {}).encode())

    def do_GET(self):
        if self.path == "/healthcheck":
            self._send(200, {"status": "healthy"})
        else:
            self._send(404, {"error": self.path})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode() or "{}")
        type(self).calls.append(("POST", self.path, payload))
        if self.path == "/search":
            self._send(200, {"facts": [{"uuid": "fact1", "name": "RELATES_TO", "fact": "Alice influences Bob", "valid_at": None, "invalid_at": None, "created_at": "2026-01-01T00:00:00Z", "expired_at": None}]})
        else:
            self._send(202, {"success": True})

    def do_DELETE(self):
        type(self).calls.append(("DELETE", self.path, {}))
        self._send(200, {"success": True})

    def log_message(self, format, *args):
        return


class GraphitiProviderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _GraphitiStub)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=2)

    def setUp(self):
        _GraphitiStub.calls.clear()
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["GRAPH_PROVIDER"] = "graphiti"
        os.environ["GRAPHITI_BASE_URL"] = self.url
        os.environ["GRAPH_MEMORY_BASE_URL"] = self.url
        os.environ["LLM_API_KEY"] = "dummy"
        os.environ.pop("ZEP_API_KEY", None)
        os.environ["LOCAL_GRAPH_STORAGE_DIR"] = self.tmpdir.name
        from app.config import Config
        Config.GRAPH_PROVIDER = "graphiti"
        Config.GRAPHITI_BASE_URL = self.url
        Config.GRAPH_MEMORY_BASE_URL = self.url
        Config.LOCAL_GRAPH_STORAGE_DIR = self.tmpdir.name
        Config.LLM_API_KEY = "dummy"
        Config.ZEP_API_KEY = None

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_graphiti_provider_posts_episodes_and_searches_facts(self):
        from app.services.graph_provider import get_graph_builder, get_graph_tools

        builder = get_graph_builder()
        graph_id = builder.create_graph("graphiti smoke")
        builder.set_ontology(graph_id, {"entity_types": [{"name": "Person", "description": "person"}], "edge_types": []})
        builder.add_text_batches(graph_id, ["Alice influences Bob."])

        paths = [call[1] for call in _GraphitiStub.calls]
        self.assertIn("/entity-node", paths)
        self.assertIn("/messages", paths)

        result = get_graph_tools().quick_search(graph_id, "Alice", limit=5)
        self.assertGreaterEqual(result.total_count, 1)
        self.assertIn("Alice influences Bob", "\n".join(result.facts))

        graph_data = get_graph_builder().get_graph_data(graph_id)
        self.assertEqual(graph_data["graphiti_status"]["native_ingest_state"], "pass")
        self.assertEqual(graph_data["graphiti_status"]["native_search_state"], "pass")
        self.assertFalse(graph_data["graphiti_status"]["fallback_cache_enabled"])
        self.assertTrue(graph_data["graphiti_status"]["compatibility_cache_enabled"])

    def test_graphiti_provider_fails_closed_when_native_messages_fail(self):
        from app.services.graph_provider import get_graph_builder, get_graph_tools

        original_do_post = _GraphitiStub.do_POST

        def failing_do_post(self):
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode() or "{}")
            type(self).calls.append(("POST", self.path, payload))
            if self.path == "/messages":
                self._send(500, {"error": "structured output schema mismatch"})
            elif self.path == "/search":
                self._send(200, {"facts": []})
            else:
                self._send(202, {"success": True})

        _GraphitiStub.do_POST = failing_do_post
        try:
            builder = get_graph_builder()
            graph_id = builder.create_graph("graphiti fallback smoke")
            builder.set_ontology(graph_id, {"entity_types": [{"name": "Person", "description": "person"}], "edge_types": []})
            with self.assertRaises(RuntimeError):
                builder.add_text_batches(graph_id, ["Alice influences Bob when native extraction fails."])

            graph_data = builder.get_graph_data(graph_id)
            self.assertEqual(graph_data["graphiti_status"]["native_ingest_state"], "blocked")
            self.assertFalse(graph_data["graphiti_status"]["fallback_cache_enabled"])
            self.assertTrue(graph_data["graphiti_errors"])
            self.assertEqual(graph_data["native_graph_memory_state"], "blocked")

            result = get_graph_tools().quick_search(graph_id, "Alice", limit=5)
            self.assertEqual(result.total_count, 0)
            self.assertEqual(result.facts, [])
        finally:
            _GraphitiStub.do_POST = original_do_post

    def test_graphiti_search_fails_closed_without_local_cache_fallback(self):
        from app.services.graph_provider import get_graph_builder, get_graph_tools

        original_do_post = _GraphitiStub.do_POST

        def failing_search(self):
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode() or "{}")
            type(self).calls.append(("POST", self.path, payload))
            if self.path == "/search":
                self._send(500, {"error": "neo4j unavailable"})
            else:
                self._send(202, {"success": True})

        _GraphitiStub.do_POST = failing_search
        try:
            builder = get_graph_builder()
            graph_id = builder.create_graph("graphiti search fail smoke")
            builder.set_ontology(graph_id, {"entity_types": [{"name": "Person", "description": "person"}], "edge_types": []})
            builder.add_text_batches(graph_id, ["Alice influences Bob."])

            with self.assertRaises(RuntimeError):
                get_graph_tools().quick_search(graph_id, "Alice", limit=5)

            graph_data = builder.get_graph_data(graph_id)
            self.assertIn("native_search_failed", [e["status"] for e in graph_data["graphiti_events"]])
        finally:
            _GraphitiStub.do_POST = original_do_post

    def test_graphiti_delete_calls_group_cleanup_and_removes_local_cache(self):
        from app.services.graph_provider import get_graph_builder

        builder = get_graph_builder()
        graph_id = builder.create_graph("cleanup smoke")
        builder.delete_graph(graph_id)

        self.assertIn(("DELETE", f"/group/{graph_id}", {}), _GraphitiStub.calls)
        with self.assertRaises(Exception):
            builder.get_graph_data(graph_id)


if __name__ == "__main__":
    unittest.main()


