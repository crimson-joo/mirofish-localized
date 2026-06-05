import os
import tempfile
import unittest


class LocalSimpleProviderTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["GRAPH_PROVIDER"] = "local_simple"
        os.environ["LLM_API_KEY"] = "dummy"
        os.environ.pop("ZEP_API_KEY", None)
        os.environ["LOCAL_GRAPH_STORAGE_DIR"] = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_config_does_not_require_zep_key_in_local_simple_mode(self):
        from app.config import Config

        Config.GRAPH_PROVIDER = "local_simple"
        Config.LLM_API_KEY = "dummy"
        Config.ZEP_API_KEY = None

        self.assertEqual(Config.validate(), [])

    def test_local_simple_graph_roundtrip_and_entity_filter(self):
        from app.services.graph_provider import get_graph_builder, get_entity_reader

        builder = get_graph_builder()
        graph_id = builder.create_graph("smoke")
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

        reader = get_entity_reader()
        filtered = reader.filter_defined_entities(graph_id)
        self.assertGreaterEqual(filtered.filtered_count, 2)
        self.assertIn("Person", filtered.entity_types)


if __name__ == "__main__":
    unittest.main()
