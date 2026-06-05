"""
Local Simple graph memory provider.

This provider is intentionally small: it gives mirofish-localized a ZEP-free
runtime path that stores graph nodes, edges, episodes, and simulation actions on
local disk. It is the default bootstrap backend before Graphiti/Graphifi or a
real graph DB provider is wired in.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import EntityNode, FilteredEntities
from .zep_tools import (
    AgentInterview,
    EdgeInfo,
    InsightForgeResult,
    InterviewResult,
    NodeInfo,
    PanoramaResult,
    SearchResult,
)

logger = get_logger("mirofish.local_simple_graph")


def _now() -> str:
    return datetime.now().isoformat()


def _slug_uuid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _storage_root() -> Path:
    root = Path(Config.LOCAL_GRAPH_STORAGE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _graph_dir(graph_id: str) -> Path:
    path = _storage_root() / graph_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_graph(graph_id: str) -> Dict[str, Any]:
    graph = _read_json(_graph_dir(graph_id) / "graph.json", None)
    if graph is None:
        raise ValueError(f"Local graph not found: {graph_id}")
    return graph


def _save_graph(graph: Dict[str, Any]) -> None:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    graph["node_count"] = len(nodes)
    graph["edge_count"] = len(edges)
    graph["updated_at"] = _now()
    _write_json(_graph_dir(graph["graph_id"]) / "graph.json", graph)


def _node_type(node: Dict[str, Any]) -> str:
    labels = node.get("labels") or []
    return next((l for l in labels if l not in ("Entity", "Node")), "Entity")


def _node_matches_type(node: Dict[str, Any], entity_type: str) -> bool:
    return entity_type in (node.get("labels") or [])


def _node_by_type(graph: Dict[str, Any], entity_type: str) -> Optional[Dict[str, Any]]:
    for node in graph.get("nodes", []):
        if _node_matches_type(node, entity_type):
            return node
    return None


def _node_by_uuid(graph: Dict[str, Any], node_uuid: str) -> Optional[Dict[str, Any]]:
    for node in graph.get("nodes", []):
        if node.get("uuid") == node_uuid:
            return node
    return None


def _normalize_query(query: str) -> List[str]:
    return [part.lower() for part in (query or "").replace("_", " ").split() if part.strip()]


class LocalSimpleGraphBuilder:
    """ZEP-compatible enough graph builder using local JSON/JSONL storage."""

    def create_graph(self, name: str) -> str:
        graph_id = _slug_uuid("local_mirofish")
        graph = {
            "graph_id": graph_id,
            "name": name,
            "description": "Local Simple MiroFish graph",
            "nodes": [],
            "edges": [],
            "node_count": 0,
            "edge_count": 0,
            "loading_progress": 0,
            "created_at": _now(),
            "updated_at": _now(),
        }
        _save_graph(graph)
        return graph_id

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        graph = _load_graph(graph_id)
        _write_json(_graph_dir(graph_id) / "ontology.json", ontology or {})

        for entity_def in (ontology or {}).get("entity_types", []) or []:
            name = entity_def.get("name") or "Entity"
            if _node_by_type(graph, name):
                continue
            graph["nodes"].append({
                "uuid": _slug_uuid("node"),
                "name": name,
                "labels": ["Entity", name],
                "summary": entity_def.get("description") or f"Local entity type {name}",
                "attributes": {
                    "source": "local_simple_ontology",
                    "entity_type": name,
                    "ontology_attributes": entity_def.get("attributes", []),
                },
                "created_at": _now(),
            })

        for edge_def in (ontology or {}).get("edge_types", []) or []:
            edge_name = edge_def.get("name") or "RELATED_TO"
            source_targets = edge_def.get("source_targets") or []
            for source_target in source_targets:
                source_type = source_target.get("source") or "Entity"
                target_type = source_target.get("target") or "Entity"
                source = _node_by_type(graph, source_type)
                target = _node_by_type(graph, target_type)
                if not source or not target:
                    continue
                graph["edges"].append({
                    "uuid": _slug_uuid("edge"),
                    "name": edge_name,
                    "fact": edge_def.get("description") or f"{source['name']} {edge_name} {target['name']}",
                    "source_node_uuid": source["uuid"],
                    "target_node_uuid": target["uuid"],
                    "source_node_name": source["name"],
                    "target_node_name": target["name"],
                    "attributes": {"source": "local_simple_ontology"},
                    "created_at": _now(),
                    "valid_at": _now(),
                    "invalid_at": None,
                    "expired_at": None,
                })

        graph["loading_progress"] = 20
        _save_graph(graph)

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Any] = None,
    ) -> List[str]:
        graph = _load_graph(graph_id)
        episode_ids: List[str] = []
        total = max(len(chunks), 1)
        for idx, chunk in enumerate(chunks, 1):
            episode_id = _slug_uuid("episode")
            episode_ids.append(episode_id)
            _append_jsonl(_graph_dir(graph_id) / "episodes.jsonl", {
                "uuid": episode_id,
                "graph_id": graph_id,
                "text": chunk,
                "created_at": _now(),
            })
            # Keep local graph useful even before a real extractor exists: attach
            # snippets to existing ontology nodes and create a few deterministic
            # mention facts for retrieval/reporting.
            for node in graph.get("nodes", [])[:8]:
                summary = node.get("summary") or ""
                snippet = chunk[:240]
                if snippet and snippet not in summary:
                    node["summary"] = (summary + "\n" + snippet).strip()[:2000]
            if len(graph.get("nodes", [])) >= 2:
                source = graph["nodes"][(idx - 1) % len(graph["nodes"])]
                target = graph["nodes"][idx % len(graph["nodes"])]
                graph["edges"].append({
                    "uuid": _slug_uuid("edge"),
                    "name": "MENTIONED_WITH",
                    "fact": f"Local episode mentions {source['name']} with {target['name']}: {chunk[:300]}",
                    "source_node_uuid": source["uuid"],
                    "target_node_uuid": target["uuid"],
                    "source_node_name": source["name"],
                    "target_node_name": target["name"],
                    "attributes": {"source": "local_simple_episode", "episode_id": episode_id},
                    "created_at": _now(),
                    "valid_at": _now(),
                    "invalid_at": None,
                    "expired_at": None,
                })
            if progress_callback:
                progress_callback(f"Local episode stored {idx}/{total}", idx / total)
        graph["loading_progress"] = 80
        _save_graph(graph)
        return episode_ids

    def _wait_for_episodes(self, episode_uuids: List[str], progress_callback: Optional[Any] = None) -> None:
        if progress_callback:
            progress_callback("Local Simple graph processing complete", 1.0)

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        graph = _load_graph(graph_id)
        graph["node_count"] = len(graph.get("nodes", []))
        graph["edge_count"] = len(graph.get("edges", []))
        graph.setdefault("loading_progress", 100)
        return graph

    def delete_graph(self, graph_id: str) -> None:
        path = _graph_dir(graph_id)
        if path.exists():
            shutil.rmtree(path)


class LocalSimpleEntityReader:
    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        try:
            return list(_load_graph(graph_id).get("nodes", []))
        except ValueError:
            return []

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        try:
            return list(_load_graph(graph_id).get("edges", []))
        except ValueError:
            return []

    def get_node_edges(self, node_uuid: str, graph_id: Optional[str] = None) -> List[Dict[str, Any]]:
        graphs: Iterable[str]
        if graph_id:
            graphs = [graph_id]
        else:
            graphs = [p.name for p in _storage_root().iterdir() if p.is_dir()]
        related = []
        for gid in graphs:
            try:
                for edge in self.get_all_edges(gid):
                    if edge.get("source_node_uuid") == node_uuid or edge.get("target_node_uuid") == node_uuid:
                        related.append(edge)
            except Exception:
                continue
        return related

    def filter_defined_entities(
        self,
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True,
    ) -> FilteredEntities:
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id) if enrich_with_edges else []
        node_map = {n.get("uuid"): n for n in nodes}
        filtered: List[EntityNode] = []
        entity_types: Set[str] = set()
        allowed = set(defined_entity_types or [])

        for node in nodes:
            labels = node.get("labels", []) or []
            custom = [l for l in labels if l not in ("Entity", "Node")]
            if not custom:
                continue
            entity_type = custom[0]
            if allowed and entity_type not in allowed:
                continue
            related_edges = [e for e in edges if e.get("source_node_uuid") == node.get("uuid") or e.get("target_node_uuid") == node.get("uuid")]
            related_nodes = []
            for edge in related_edges:
                other_uuid = edge.get("target_node_uuid") if edge.get("source_node_uuid") == node.get("uuid") else edge.get("source_node_uuid")
                if other_uuid in node_map:
                    related_nodes.append(node_map[other_uuid])
            filtered.append(EntityNode(
                uuid=node.get("uuid", ""),
                name=node.get("name", ""),
                labels=labels,
                summary=node.get("summary", ""),
                attributes=node.get("attributes", {}) or {},
                related_edges=related_edges,
                related_nodes=related_nodes,
            ))
            entity_types.add(entity_type)

        return FilteredEntities(
            entities=filtered,
            entity_types=entity_types,
            total_count=len(nodes),
            filtered_count=len(filtered),
        )

    def get_entity_with_context(self, graph_id: str, entity_uuid: str) -> Optional[EntityNode]:
        filtered = self.filter_defined_entities(graph_id, enrich_with_edges=True)
        for entity in filtered.entities:
            if entity.uuid == entity_uuid:
                return entity
        return None

    def get_entities_by_type(self, graph_id: str, entity_type: str, enrich_with_edges: bool = True) -> List[EntityNode]:
        return self.filter_defined_entities(graph_id, [entity_type], enrich_with_edges).entities


class LocalSimpleToolsService:
    """ReportAgent-compatible tools backed by local graph JSON."""

    def __init__(self, llm_client: Optional[Any] = None):
        self.reader = LocalSimpleEntityReader()

    def _nodes(self, graph_id: str) -> List[NodeInfo]:
        return [NodeInfo(
            uuid=n.get("uuid", ""),
            name=n.get("name", ""),
            labels=n.get("labels", []) or [],
            summary=n.get("summary", ""),
            attributes=n.get("attributes", {}) or {},
        ) for n in self.reader.get_all_nodes(graph_id)]

    def _edges(self, graph_id: str) -> List[EdgeInfo]:
        return [EdgeInfo(
            uuid=e.get("uuid", ""),
            name=e.get("name", ""),
            fact=e.get("fact", ""),
            source_node_uuid=e.get("source_node_uuid", ""),
            target_node_uuid=e.get("target_node_uuid", ""),
            source_node_name=e.get("source_node_name"),
            target_node_name=e.get("target_node_name"),
            created_at=e.get("created_at"),
            valid_at=e.get("valid_at"),
            invalid_at=e.get("invalid_at"),
            expired_at=e.get("expired_at"),
        ) for e in self.reader.get_all_edges(graph_id)]

    def search_graph(self, graph_id: str, query: str, limit: int = 10, scope: str = "edges") -> SearchResult:
        terms = _normalize_query(query)
        nodes = [n.to_dict() for n in self._nodes(graph_id)]
        edges = [e.to_dict() for e in self._edges(graph_id)]

        def score(text: str) -> int:
            lowered = (text or "").lower()
            return sum(1 for term in terms if term in lowered)

        matched_edges = sorted(
            [e for e in edges if not terms or score(e.get("fact", "") + " " + e.get("name", "")) > 0],
            key=lambda e: score(e.get("fact", "") + " " + e.get("name", "")),
            reverse=True,
        )[:limit]
        matched_nodes = sorted(
            [n for n in nodes if not terms or score(n.get("name", "") + " " + n.get("summary", "")) > 0],
            key=lambda n: score(n.get("name", "") + " " + n.get("summary", "")),
            reverse=True,
        )[:limit]
        facts = [e.get("fact", "") for e in matched_edges if e.get("fact")]
        facts += [f"{n.get('name')}: {n.get('summary', '')[:300]}" for n in matched_nodes]
        facts = facts[:limit]
        return SearchResult(facts=facts, edges=matched_edges, nodes=matched_nodes, query=query, total_count=len(facts))

    def quick_search(self, graph_id: str, query: str, limit: int = 10) -> SearchResult:
        return self.search_graph(graph_id, query, limit=limit)

    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        return self._nodes(graph_id)

    def get_all_edges(self, graph_id: str, include_temporal: bool = True, include_expired: bool = True) -> List[EdgeInfo]:
        return self._edges(graph_id)

    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        for gid_path in _storage_root().iterdir():
            if not gid_path.is_dir():
                continue
            for node in self._nodes(gid_path.name):
                if node.uuid == node_uuid:
                    return node
        return None

    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        return [e for e in self._edges(graph_id) if e.source_node_uuid == node_uuid or e.target_node_uuid == node_uuid]

    def get_entities_by_type(self, graph_id: str, entity_type: str, limit: int = 20) -> List[NodeInfo]:
        return [n for n in self._nodes(graph_id) if entity_type in n.labels][:limit]

    def get_entity_summary(self, graph_id: str, entity_type: str, limit: int = 10) -> str:
        nodes = self.get_entities_by_type(graph_id, entity_type, limit)
        if not nodes:
            return f"No local entities found for type {entity_type}."
        return "\n".join(n.to_text() for n in nodes)

    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        nodes = self._nodes(graph_id)
        edges = self._edges(graph_id)
        entity_types: Dict[str, int] = {}
        relation_types: Dict[str, int] = {}
        for node in nodes:
            entity_types[_node_type(node.to_dict())] = entity_types.get(_node_type(node.to_dict()), 0) + 1
        for edge in edges:
            relation_types[edge.name] = relation_types.get(edge.name, 0) + 1
        return {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "entity_types": entity_types,
            "relation_types": relation_types,
            "provider": "local_simple",
        }

    def get_simulation_context(self, graph_id: str, simulation_requirement: str, limit: int = 30) -> Dict[str, Any]:
        result = self.quick_search(graph_id, simulation_requirement or "", limit=limit)
        stats = self.get_graph_statistics(graph_id)
        return {
            "simulation_requirement": simulation_requirement,
            "related_facts": result.facts,
            "graph_statistics": stats,
            "entities": result.nodes,
            "total_entities": stats["total_nodes"],
            "provider": "local_simple",
        }

    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_sub_queries: int = 5,
    ) -> InsightForgeResult:
        search = self.quick_search(graph_id, query or simulation_requirement, limit=20)
        nodes = self._nodes(graph_id)[:20]
        edges = self._edges(graph_id)[:20]
        return InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement,
            sub_queries=[query] if query else [simulation_requirement],
            semantic_facts=search.facts,
            entity_insights=[{"name": n.name, "type": _node_type(n.to_dict()), "summary": n.summary} for n in nodes],
            relationship_chains=[e.to_text() for e in edges],
            total_facts=len(search.facts),
            total_entities=len(nodes),
            total_relationships=len(edges),
        )

    def panorama_search(self, graph_id: str, query: str, include_expired: bool = True, limit: int = 50) -> PanoramaResult:
        nodes = self._nodes(graph_id)[:limit]
        edges = self._edges(graph_id)[:limit]
        facts = [e.fact for e in edges if e.fact]
        return PanoramaResult(
            query=query,
            all_nodes=nodes,
            all_edges=edges,
            active_facts=facts,
            historical_facts=[],
            total_nodes=len(nodes),
            total_edges=len(edges),
            active_count=len(facts),
            historical_count=0,
        )

    def interview_agents(
        self,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str = "",
        max_agents: int = 5,
        custom_questions: Optional[List[str]] = None,
    ) -> InterviewResult:
        question = (custom_questions or [interview_requirement or simulation_requirement or "What is your view?"])[0]
        interview = AgentInterview(
            agent_name="local_simple_agent",
            agent_role="Local Simple Stub",
            agent_bio="A placeholder interviewee generated before a live OASIS/Graphiti runtime is connected.",
            question=question,
            response="Local Simple mode preserves the interaction flow without ZEP. Connect Graphiti/Graphifi and live simulation runtime for real agent interviews.",
            key_quotes=["Local Simple mode is a bootstrap backend, not the final GraphRAG engine."],
        )
        return InterviewResult(
            interview_topic=interview_requirement,
            interview_questions=[question],
            selected_agents=[{"name": interview.agent_name, "role": interview.agent_role}],
            interviews=[interview],
            selection_reasoning="Local Simple provider returns a safe stub interview until live agents are available.",
            summary=interview.response,
            total_agents=1,
            interviewed_count=1,
        )


class LocalSimpleGraphMemoryUpdater:
    def __init__(self, graph_id: str):
        self.graph_id = graph_id
        self._running = False
        self._lock = threading.Lock()
        self._total_activities = 0

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def add_activity_from_dict(self, data: Dict[str, Any], platform: str) -> None:
        if "event_type" in data or data.get("action_type") == "DO_NOTHING":
            return
        with self._lock:
            self._total_activities += 1
            row = dict(data)
            row["platform"] = platform
            row["recorded_at"] = _now()
            _append_jsonl(_graph_dir(self.graph_id) / "actions.jsonl", row)
            try:
                graph = _load_graph(self.graph_id)
                nodes = graph.get("nodes", [])
                if len(nodes) >= 2:
                    source = nodes[(self._total_activities - 1) % len(nodes)]
                    target = nodes[self._total_activities % len(nodes)]
                    content = row.get("action_args", {}).get("content") or row.get("action_type", "agent action")
                    graph["edges"].append({
                        "uuid": _slug_uuid("edge"),
                        "name": row.get("action_type", "ACTION"),
                        "fact": f"[{platform}] {row.get('agent_name', 'agent')} {row.get('action_type', 'ACTION')}: {str(content)[:300]}",
                        "source_node_uuid": source["uuid"],
                        "target_node_uuid": target["uuid"],
                        "source_node_name": source["name"],
                        "target_node_name": target["name"],
                        "attributes": {"source": "local_simple_simulation_action"},
                        "created_at": _now(),
                        "valid_at": _now(),
                        "invalid_at": None,
                        "expired_at": None,
                    })
                    _save_graph(graph)
            except Exception as exc:
                logger.warning(f"Local action graph update skipped: {exc}")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "total_activities": self._total_activities,
            "batches_sent": self._total_activities,
            "items_sent": self._total_activities,
            "failed": 0,
            "provider": "local_simple",
        }


class LocalSimpleGraphMemoryManager:
    _updaters: Dict[str, LocalSimpleGraphMemoryUpdater] = {}

    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str) -> LocalSimpleGraphMemoryUpdater:
        updater = LocalSimpleGraphMemoryUpdater(graph_id)
        updater.start()
        cls._updaters[simulation_id] = updater
        return updater

    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[LocalSimpleGraphMemoryUpdater]:
        return cls._updaters.get(simulation_id)

    @classmethod
    def stop_updater(cls, simulation_id: str) -> None:
        updater = cls._updaters.pop(simulation_id, None)
        if updater:
            updater.stop()

    @classmethod
    def stop_all(cls) -> None:
        for updater in list(cls._updaters.values()):
            updater.stop()
        cls._updaters.clear()

    @classmethod
    def get_all_stats(cls) -> Dict[str, Any]:
        return {sid: updater.get_stats() for sid, updater in cls._updaters.items()}
