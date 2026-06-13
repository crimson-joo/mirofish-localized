import unittest

from app.services.simulation_manager import SimulationManager
from app.services.zep_entity_reader import EntityNode


def entity(uuid, entity_type, edge_count=0, node_count=0, summary=""):
    return EntityNode(
        uuid=uuid,
        name=uuid,
        labels=["Entity", entity_type],
        summary=summary or uuid,
        attributes={},
        related_edges=[{"uuid": f"edge-{uuid}-{i}"} for i in range(edge_count)],
        related_nodes=[{"uuid": f"node-{uuid}-{i}"} for i in range(node_count)],
    )


class PersonaSelectionTest(unittest.TestCase):
    def test_all_mode_keeps_every_entity(self):
        entities = [entity("a", "Person"), entity("b", "Organization")]

        selected = SimulationManager._select_entities_for_personas(
            entities,
            mode="all",
            max_agent_personas=1,
        )

        self.assertEqual([item.uuid for item in selected], ["a", "b"])

    def test_core_mode_caps_and_preserves_type_diversity(self):
        entities = [
            entity("person-low", "Person", edge_count=1),
            entity("person-high", "Person", edge_count=5),
            entity("org-high", "Organization", edge_count=4),
            entity("agency", "RegulatoryAgency", edge_count=2),
        ]

        selected = SimulationManager._select_entities_for_personas(
            entities,
            mode="core",
            max_agent_personas=3,
        )

        selected_ids = [item.uuid for item in selected]
        selected_types = {item.get_entity_type() for item in selected}
        self.assertEqual(len(selected), 3)
        self.assertIn("person-high", selected_ids)
        self.assertNotIn("person-low", selected_ids)
        self.assertEqual(selected_types, {"Person", "Organization", "RegulatoryAgency"})


if __name__ == "__main__":
    unittest.main()
