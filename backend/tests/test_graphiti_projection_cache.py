import os
import tempfile
import unittest


class GraphitiProjectionCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["LLM_API_KEY"] = "dummy"
        os.environ["LOCAL_GRAPH_STORAGE_DIR"] = self.tmpdir.name

        from app.config import Config
        Config.GRAPH_PROVIDER = "graphiti"
        Config.LLM_API_KEY = "dummy"
        Config.LOCAL_GRAPH_STORAGE_DIR = self.tmpdir.name
        Config.ZEP_API_KEY = None

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_local_simple_provider_is_no_longer_supported(self):
        from app.config import Config

        original = Config.GRAPH_PROVIDER
        try:
            Config.GRAPH_PROVIDER = "local_simple"
            self.assertTrue(any("GRAPH_PROVIDER" in error for error in Config.validate()))
        finally:
            Config.GRAPH_PROVIDER = original

    def test_graphiti_projection_cache_roundtrip_and_entity_filter(self):
        from app.services.graphiti_projection_cache import GraphitiProjectionEntityReader, GraphitiProjectionGraphBuilder

        builder = GraphitiProjectionGraphBuilder()
        graph_id = builder.create_graph("projection smoke")
        builder.set_ontology(graph_id, {
            "entity_types": [
                {"name": "Person", "description": "A simulated person", "attributes": []},
                {"name": "Organization", "description": "A simulated organization", "attributes": []},
            ],
            "edge_types": [
                {
                    "name": "supports",
                    "description": "support relationship",
                    "source_targets": [{"source": "Person", "target": "Organization"}],
                }
            ],
        })
        episodes = builder.add_text_batches(graph_id, ["Alice supports Open Research."], batch_size=1)
        builder._wait_for_episodes(episodes)
        data = builder.get_graph_data(graph_id)

        self.assertGreaterEqual(data["node_count"], 2)
        self.assertGreaterEqual(data["edge_count"], 1)

        reader = GraphitiProjectionEntityReader()
        filtered = reader.filter_defined_entities(graph_id)
        self.assertGreaterEqual(filtered.filtered_count, 2)
        self.assertIn("Person", filtered.entity_types)


if __name__ == "__main__":
    unittest.main()
