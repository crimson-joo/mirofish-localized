"""Graphiti/Graphifi-backed provider for local ZEP replacement.

The upstream Graphiti FastAPI server does not expose the exact Zep Cloud graph
API that MiroFish was written against. This provider therefore uses Graphiti for
real episode ingestion and fact search while keeping a small local JSON cache for
node/edge listing that the existing MiroFish frontend expects.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import Config
from ..utils.logger import get_logger
from .local_simple_graph import (
    LocalSimpleEntityReader,
    LocalSimpleGraphBuilder,
    LocalSimpleGraphMemoryManager,
    LocalSimpleGraphMemoryUpdater,
    LocalSimpleToolsService,
    _graph_dir,
    _load_graph,
    _now,
    _save_graph,
    _slug_uuid,
)
from .zep_tools import EdgeInfo, SearchResult

logger = get_logger("mirofish.graphiti_provider")


def _base_url() -> str:
    return (Config.GRAPHITI_BASE_URL or Config.GRAPH_MEMORY_BASE_URL or "http://localhost:8000").rstrip("/")


def _json_request(method: str, path: str, payload: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Dict[str, Any]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(f"{_base_url()}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        raise RuntimeError(f"Graphiti {method} {path} failed: HTTP {exc.code} {detail}") from exc


class GraphitiGraphBuilder(LocalSimpleGraphBuilder):
    """Graph builder that mirrors MiroFish graph operations to Graphiti."""

    def create_graph(self, name: str) -> str:
        graph_id = super().create_graph(name)
        graph = _load_graph(graph_id)
        graph["provider"] = "graphiti"
        graph["graphiti_base_url"] = _base_url()
        _save_graph(graph)
        return graph_id

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        super().set_ontology(graph_id, ontology)
        graph = _load_graph(graph_id)
        # Persist ontology entity types as Graphiti entity nodes so search has
        # anchors even before async extraction finishes.
        for node in graph.get("nodes", []):
            try:
                _json_request("POST", "/entity-node", {
                    "uuid": node.get("uuid"),
                    "group_id": graph_id,
                    "name": node.get("name"),
                    "summary": node.get("summary", ""),
                }, timeout=20.0)
            except Exception as exc:
                logger.warning(f"Graphiti entity-node mirror failed for {node.get('name')}: {exc}")

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Any] = None,
    ) -> List[str]:
        episode_ids = super().add_text_batches(graph_id, chunks, batch_size, progress_callback)
        messages = []
        for episode_id, chunk in zip(episode_ids, chunks):
            messages.append({
                "uuid": episode_id,
                "name": f"MiroFish seed episode {episode_id[-8:]}",
                "content": chunk,
                "role_type": "system",
                "role": "mirofish_seed",
                "timestamp": datetime.now().isoformat(),
                "source_description": "mirofish-localized graph build seed",
            })
        if messages:
            try:
                _json_request("POST", "/messages", {"group_id": graph_id, "messages": messages}, timeout=180.0)
            except Exception as exc:
                # Keep Graphiti mode usable even when the selected local LLM endpoint
                # cannot satisfy Graphiti's strict structured-output schemas. The
                # local compatibility cache still contains episodes/nodes/edges/search
                # so the MiroFish product flow can complete while the richer Graphiti
                # extraction backend is tuned or swapped via env.
                graph = _load_graph(graph_id)
                graph.setdefault("graphiti_errors", []).append({
                    "at": _now(),
                    "operation": "messages",
                    "error": str(exc),
                })
                _save_graph(graph)
                logger.warning(f"Graphiti message mirror failed; continuing with local compatibility cache: {exc}")
        return episode_ids

    def delete_graph(self, graph_id: str) -> None:
        try:
            _json_request("DELETE", f"/group/{graph_id}", timeout=60.0)
        except Exception as exc:
            logger.warning(f"Graphiti group delete failed for {graph_id}; deleting local cache anyway: {exc}")
        super().delete_graph(graph_id)


class GraphitiEntityReader(LocalSimpleEntityReader):
    """Graphiti node/edge listing backed by local MiroFish compatibility cache."""


class GraphitiToolsService(LocalSimpleToolsService):
    def search_graph(self, graph_id: str, query: str, limit: int = 10, scope: str = "edges") -> SearchResult:
        try:
            response = _json_request("POST", "/search", {
                "group_ids": [graph_id],
                "query": query,
                "max_facts": limit,
            }, timeout=45.0)
            fact_rows = response.get("facts", []) or []
            facts = [row.get("fact", "") for row in fact_rows if row.get("fact")]
            edges = []
            for row in fact_rows:
                edges.append({
                    "uuid": row.get("uuid", ""),
                    "name": row.get("name", "GraphitiFact"),
                    "fact": row.get("fact", ""),
                    "source_node_uuid": "",
                    "target_node_uuid": "",
                    "attributes": {"provider": "graphiti"},
                    "created_at": row.get("created_at"),
                    "valid_at": row.get("valid_at"),
                    "invalid_at": row.get("invalid_at"),
                    "expired_at": row.get("expired_at"),
                })
            local = super().search_graph(graph_id, query, limit=limit, scope=scope)
            merged_facts = (facts + local.facts)[:limit]
            merged_edges = (edges + local.edges)[:limit]
            return SearchResult(
                facts=merged_facts,
                edges=merged_edges,
                nodes=local.nodes,
                query=query,
                total_count=len(merged_facts),
            )
        except Exception as exc:
            logger.warning(f"Graphiti search failed; falling back to local cache: {exc}")
            return super().search_graph(graph_id, query, limit=limit, scope=scope)

    def get_all_edges(self, graph_id: str, include_temporal: bool = True, include_expired: bool = True) -> List[EdgeInfo]:
        # Graphiti server currently exposes fact search but not full edge list in
        # the server API, so MiroFish graph panels use the local compatibility cache.
        return super().get_all_edges(graph_id, include_temporal=include_temporal, include_expired=include_expired)


class GraphitiGraphMemoryUpdater(LocalSimpleGraphMemoryUpdater):
    def add_activity_from_dict(self, data: Dict[str, Any], platform: str) -> None:
        super().add_activity_from_dict(data, platform)
        if "event_type" in data or data.get("action_type") == "DO_NOTHING":
            return
        content = data.get("action_args", {}).get("content") or data.get("content") or data.get("action_type", "")
        message = {
            "uuid": _slug_uuid("action_episode"),
            "name": f"{platform} {data.get('action_type', 'ACTION')}",
            "content": f"agent={data.get('agent_name', 'agent')} platform={platform} action={data.get('action_type', 'ACTION')} content={content}",
            "role_type": "assistant",
            "role": data.get("agent_name") or platform,
            "timestamp": datetime.now().isoformat(),
            "source_description": "mirofish-localized simulation action",
        }
        try:
            _json_request("POST", "/messages", {"group_id": self.graph_id, "messages": [message]}, timeout=30.0)
        except Exception as exc:
            logger.warning(f"Graphiti action episode mirror failed: {exc}")

    def get_stats(self) -> Dict[str, Any]:
        stats = super().get_stats()
        stats["provider"] = "graphiti"
        stats["graphiti_base_url"] = _base_url()
        return stats


class GraphitiGraphMemoryManager(LocalSimpleGraphMemoryManager):
    _updaters: Dict[str, GraphitiGraphMemoryUpdater] = {}

    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str) -> GraphitiGraphMemoryUpdater:
        updater = GraphitiGraphMemoryUpdater(graph_id)
        updater.start()
        cls._updaters[simulation_id] = updater
        return updater
