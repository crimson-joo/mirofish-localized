import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _install_module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_zep_graphiti_module():
    class Dummy:
        pass

    _install_module("fastapi", Depends=lambda *a, **k: None, HTTPException=Exception)
    _install_module("graphiti_core", Graphiti=Dummy)
    _install_module("graphiti_core.embedder", OpenAIEmbedder=Dummy, OpenAIEmbedderConfig=Dummy)
    _install_module("graphiti_core.embedder.openai", OpenAIEmbedder=Dummy, OpenAIEmbedderConfig=Dummy)
    _install_module("graphiti_core.edges", EntityEdge=Dummy)
    _install_module(
        "graphiti_core.errors",
        EdgeNotFoundError=Exception,
        GroupsEdgesNotFoundError=Exception,
        NodeNotFoundError=Exception,
    )
    _install_module("graphiti_core.llm_client", LLMClient=Dummy)
    _install_module("graphiti_core.llm_client.config", LLMConfig=Dummy)
    _install_module("graphiti_core.llm_client.openai_client", OpenAIClient=Dummy)
    _install_module("graphiti_core.nodes", EntityNode=Dummy, EpisodicNode=Dummy)
    _install_module("graph_service", config=types.ModuleType("graph_service.config"), dto=types.ModuleType("graph_service.dto"))
    _install_module("graph_service.config", ZepEnvDep=Dummy)
    _install_module("graph_service.dto", FactResult=Dummy)

    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "services" / "graphiti-patched" / "zep_graphiti.py"
    spec = importlib.util.spec_from_file_location("zep_graphiti_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExtractedEdges:
    pass


class NodeResolutions:
    pass


class GraphitiStructuredNormalizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_zep_graphiti_module()

    def test_extracted_edges_dedupes_canonical_fact_and_drops_invalid_self_edges(self):
        payload = {
            "edges": [
                {"subject_id": 1, "object_id": 2, "relation": "related-to", "fact": "Alice   influences Bob"},
                {"source_entity_id": "1", "target_entity_id": "2", "relation_type": "Related To", "fact": "alice influences bob"},
                {"source_entity_id": 3, "target_entity_id": 3, "relation_type": "mentions", "fact": "self edge"},
                {"source_entity_id": "bad", "target_entity_id": 4, "relation_type": "mentions", "fact": "bad source"},
            ]
        }

        result = self.module._normalize_structured_payload(payload, ExtractedEdges)

        self.assertEqual(len(result["edges"]), 1)
        edge = result["edges"][0]
        self.assertEqual(edge["relation_type"], "RELATED_TO")
        self.assertEqual(edge["source_entity_id"], 1)
        self.assertEqual(edge["target_entity_id"], 2)
        self.assertEqual(edge["fact"], "Alice influences Bob")

    def test_node_resolutions_drops_self_duplicate_and_normalizes_additional_duplicates(self):
        payload = {
            "resolutions": [
                {"id": 2, "duplicate_idx": 2, "name": "Alice", "additional_duplicates": ["1", 1, "bad", -1, 2]},
            ]
        }

        result = self.module._normalize_structured_payload(payload, NodeResolutions)

        row = result["entity_resolutions"][0]
        self.assertEqual(row["duplicate_idx"], -1)
        self.assertEqual(row["additional_duplicates"], [1])


if __name__ == "__main__":
    unittest.main()
