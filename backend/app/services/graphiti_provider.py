"""Graphiti/Graphifi-backed provider for local ZEP replacement.

The upstream Graphiti FastAPI server does not expose the exact Zep Cloud graph
API that MiroFish was written against. This provider uses Graphiti/Neo4j as the
source-of-truth runtime path and keeps an internal projection cache only for
MiroFish UI panels that still expect node/edge listing. Native Graphiti failures
are surfaced as failures; the projection cache is never used as a silent success path.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from ..utils.logger import get_logger
from .graphiti_projection_cache import (
    GraphitiProjectionEntityReader,
    GraphitiProjectionGraphBuilder,
    GraphitiProjectionGraphMemoryManager,
    GraphitiProjectionGraphMemoryUpdater,
    GraphitiProjectionToolsService,
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


def _record_graphiti_event(
    graph_id: str,
    operation: str,
    status: str,
    *,
    native_success: Optional[bool] = None,
    error: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist native-vs-fallback evidence in the MiroFish compatibility cache."""
    graph = _load_graph(graph_id)
    event: Dict[str, Any] = {
        "at": _now(),
        "operation": operation,
        "status": status,
    }
    if native_success is not None:
        event["native_success"] = native_success
    if error:
        event["error"] = error
    if details:
        event["details"] = details
    graph.setdefault("graphiti_events", []).append(event)
    status_obj = graph.setdefault("graphiti_status", {})
    status_obj.update({
        "provider": "graphiti",
        "base_url": _base_url(),
        "last_operation": operation,
        "last_status": status,
        "last_checked_at": event["at"],
        "native_ingest_state": status_obj.get("native_ingest_state", "unknown"),
        "projection_cache_enabled": True,
    })
    if operation in {"messages", "action_messages"}:
        if operation == "action_messages":
            ingest_state = (details or {}).get("native_action_ingest_state")
            state_key = "native_action_ingest_state"
        else:
            ingest_state = (details or {}).get("native_ingest_state")
            state_key = "native_ingest_state"
        if ingest_state:
            status_obj[state_key] = ingest_state
        else:
            status_obj[state_key] = "pass" if native_success else "failed"
        warnings = (details or {}).get("graphiti_warnings") or []
        if warnings:
            existing_warnings = status_obj.setdefault("warnings", [])
            existing_keys = {
                (item.get("operation"), item.get("category"), item.get("message"))
                for item in existing_warnings
            }
            graph_warning_records = graph.setdefault("graphiti_warnings", [])
            for warning in warnings:
                warning_key = (operation, warning.get("category"), warning.get("message"))
                if warning_key in existing_keys:
                    continue
                existing_keys.add(warning_key)
                record = {
                    "at": event["at"],
                    "operation": operation,
                    **warning,
                }
                existing_warnings.append(record)
                graph_warning_records.append(record)
            status_obj["native_warning_state"] = "warning"
        else:
            status_obj.setdefault("native_warning_state", "none")
    if operation == "search":
        if "failed" in status:
            status_obj["native_search_state"] = "failed"
        else:
            status_obj["native_search_state"] = "pass" if native_success else "empty"
    if error:
        graph.setdefault("graphiti_errors", []).append({
            "at": event["at"],
            "operation": operation,
            "error": error,
        })
    _save_graph(graph)


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


def _message_ingest_counts(response: Dict[str, Any]) -> Tuple[int, int, int]:
    """Parse patched Graphiti /messages native/repaired/failed counts."""
    message = str(response.get("message", ""))
    counts = {"native": 0, "repaired": 0, "failed": 0}
    for key in counts:
        match = re.search(rf"{key}=(\d+)", message)
        if match:
            counts[key] = int(match.group(1))
    return counts["native"], counts["repaired"], counts["failed"]


def _ingest_state(native_count: int, repaired_count: int, failed_count: int) -> str:
    if failed_count > 0:
        return "failed"
    if repaired_count > 0:
        return "repaired"
    if native_count > 0:
        return "pass"
    return "unknown"


def _extract_graphiti_warnings(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize non-blocking Graphiti warnings into durable status records.

    Graphiti can accept /messages successfully while logging validation warnings,
    especially duplicate edge retries. Keep those separate from native ingest
    failure so future canaries can distinguish PASS-with-warning from FAILED.
    """
    raw_parts: List[str] = []
    for key in ("warning", "warnings", "message", "detail"):
        value = response.get(key)
        if isinstance(value, list):
            raw_parts.extend(str(item) for item in value)
        elif value:
            raw_parts.append(str(value))

    warnings: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    for raw in raw_parts:
        lowered = raw.lower()
        category: Optional[str] = None
        if "edgeduplicate" in lowered or "duplicate edge" in lowered:
            category = "duplicate_edge"
        elif "warning" in lowered:
            category = "graphiti_warning"
        if not category:
            continue
        key = (category, raw)
        if key in seen:
            continue
        seen.add(key)
        warnings.append({
            "category": category,
            "message": raw,
        })
    return warnings


class GraphitiGraphBuilder(GraphitiProjectionGraphBuilder):
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
        failures = []
        for node in graph.get("nodes", []):
            try:
                _json_request("POST", "/entity-node", {
                    "uuid": node.get("uuid"),
                    "group_id": graph_id,
                    "name": node.get("name"),
                    "summary": node.get("summary", ""),
                }, timeout=20.0)
            except Exception as exc:
                failures.append(f"{node.get('name')}: {exc}")
        if failures:
            _record_graphiti_event(
                graph_id,
                "entity-node",
                "native_entity_node_failed",
                native_success=False,
                error="; ".join(failures),
            )
            raise RuntimeError(f"Graphiti entity-node mirror failed for group {graph_id}: {'; '.join(failures)}")

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Any] = None,
    ) -> List[str]:
        messages = []
        for chunk in chunks:
            episode_id = _slug_uuid("graphiti_episode")
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
            native_total = 0
            repaired_total = 0
            failed_total = 0
            responses = []
            try:
                for index, message in enumerate(messages, start=1):
                    response = _json_request(
                        "POST",
                        "/messages",
                        {"group_id": graph_id, "messages": [message]},
                        timeout=180.0,
                    )
                    native_count, repaired_count, failed_count = _message_ingest_counts(response)
                    native_total += native_count
                    repaired_total += repaired_count
                    failed_total += failed_count
                    responses.append(response)
                    if progress_callback:
                        progress_callback(f"Graphiti ingest {index}/{len(messages)}", index / len(messages))
                    if failed_count > 0 or response.get("success") is False:
                        raise RuntimeError(response.get("message") or "Graphiti patched /messages reported failure")
                ingest_state = _ingest_state(native_total, repaired_total, failed_total)
                graphiti_warnings = []
                warning_keys = set()
                for response in responses:
                    for warning in _extract_graphiti_warnings(response):
                        warning_key = (warning.get("category"), warning.get("message"))
                        if warning_key in warning_keys:
                            continue
                        warning_keys.add(warning_key)
                        graphiti_warnings.append(warning)
                _record_graphiti_event(
                    graph_id,
                    "messages",
                    f"native_ingest_{ingest_state}",
                    native_success=failed_total == 0,
                    details={
                        "message_count": len(messages),
                        "native_count": native_total,
                        "repaired_count": repaired_total,
                        "failed_count": failed_total,
                        "native_ingest_state": ingest_state,
                        "graphiti_warnings": graphiti_warnings,
                        "responses": responses[-3:],
                    },
                )
            except Exception as exc:
                _record_graphiti_event(
                    graph_id,
                    "messages",
                    "native_ingest_failed",
                    native_success=False,
                    error=str(exc),
                    details={
                        "message_count": len(messages),
                        "native_count": native_total,
                        "repaired_count": repaired_total,
                        "failed_count": failed_total,
                        "native_ingest_state": "failed",
                        "batch_size": 1,
                    },
                )
                raise RuntimeError(f"Graphiti native message ingest failed for group {graph_id}: {exc}") from exc
        # Compatibility cache is populated only after Graphiti accepts every small batch.
        return super().add_text_batches(graph_id, chunks, batch_size, progress_callback)

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        graph = super().get_graph_data(graph_id)
        status_obj = graph.setdefault("graphiti_status", {})
        status_obj.setdefault("provider", "graphiti")
        status_obj.setdefault("base_url", _base_url())
        status_obj.setdefault("projection_cache_enabled", True)
        status_obj.setdefault("native_ingest_state", "unknown")
        status_obj["projection_cache"] = {
            "node_count": len(graph.get("nodes", [])),
            "edge_count": len(graph.get("edges", [])),
            "episode_count": len(graph.get("episodes", [])),
        }
        graph["native_graph_memory_state"] = status_obj.get("native_ingest_state", "unknown")
        return graph

    def delete_graph(self, graph_id: str) -> None:
        try:
            _json_request("DELETE", f"/group/{graph_id}", timeout=60.0)
        except Exception as exc:
            logger.warning(f"Graphiti group delete failed for {graph_id}; deleting projection cache anyway: {exc}")
        super().delete_graph(graph_id)


class GraphitiEntityReader(GraphitiProjectionEntityReader):
    """Graphiti node/edge listing backed by Graphiti projection cache."""


class GraphitiToolsService(GraphitiProjectionToolsService):
    def search_graph(self, graph_id: str, query: str, limit: int = 10, scope: str = "edges") -> SearchResult:
        try:
            response = _json_request("POST", "/search", {
                "group_ids": [graph_id],
                "query": query,
                "max_facts": limit,
            }, timeout=45.0)
            fact_rows = response.get("facts", []) or []
            facts = [row.get("fact", "") for row in fact_rows if row.get("fact")]
            native_success = bool(facts)
            _record_graphiti_event(
                graph_id,
                "search",
                "native_search_pass" if native_success else "native_search_empty",
                native_success=native_success,
                details={"query": query, "native_fact_count": len(facts), "limit": limit},
            )
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
            local_nodes = super().get_all_nodes(graph_id)
            return SearchResult(
                facts=facts[:limit],
                edges=edges[:limit],
                nodes=[node.to_dict() for node in local_nodes],
                query=query,
                total_count=len(facts[:limit]),
            )
        except Exception as exc:
            try:
                _record_graphiti_event(
                    graph_id,
                    "search",
                    "native_search_failed",
                    native_success=False,
                    error=str(exc),
                    details={"query": query, "limit": limit},
                )
            except Exception:
                pass
            raise RuntimeError(f"Graphiti native search failed for group {graph_id}: {exc}") from exc

    def get_all_edges(self, graph_id: str, include_temporal: bool = True, include_expired: bool = True) -> List[EdgeInfo]:
        # Graphiti server currently exposes fact search but not full edge list in
        # the server API, so MiroFish graph panels use the projection cache.
        return super().get_all_edges(graph_id, include_temporal=include_temporal, include_expired=include_expired)


class GraphitiGraphMemoryUpdater(GraphitiProjectionGraphMemoryUpdater):
    def add_activity_from_dict(self, data: Dict[str, Any], platform: str) -> None:
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
        response: Dict[str, Any] = {}
        try:
            response = _json_request("POST", "/messages", {"group_id": self.graph_id, "messages": [message]}, timeout=90.0)
            native_count, repaired_count, failed_count = _message_ingest_counts(response)
            ingest_state = _ingest_state(native_count, repaired_count, failed_count)
            graphiti_warnings = _extract_graphiti_warnings(response)
            if failed_count > 0 or response.get("success") is False:
                raise RuntimeError(response.get("message") or "Graphiti patched /messages reported action ingest failure")
            _record_graphiti_event(
                self.graph_id,
                "action_messages",
                f"native_action_ingest_{ingest_state}",
                native_success=True,
                details={
                    "simulation_action": True,
                    "platform": platform,
                    "native_count": native_count,
                    "repaired_count": repaired_count,
                    "failed_count": failed_count,
                    "native_action_ingest_state": ingest_state,
                    "graphiti_warnings": graphiti_warnings,
                },
            )
        except Exception as exc:
            try:
                _record_graphiti_event(
                    self.graph_id,
                    "action_messages",
                    "native_action_ingest_failed",
                    native_success=False,
                    error=str(exc),
                    details={
                        "simulation_action": True,
                        "platform": platform,
                        "native_action_ingest_state": "failed",
                        "response": response,
                    },
                )
            except Exception:
                pass
            raise RuntimeError(f"Graphiti action episode ingest failed for group {self.graph_id}: {exc}") from exc
        super().add_activity_from_dict(data, platform)

    def get_stats(self) -> Dict[str, Any]:
        stats = super().get_stats()
        stats["provider"] = "graphiti"
        stats["graphiti_base_url"] = _base_url()
        return stats


class GraphitiGraphMemoryManager(GraphitiProjectionGraphMemoryManager):
    _updaters: Dict[str, GraphitiGraphMemoryUpdater] = {}

    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str) -> GraphitiGraphMemoryUpdater:
        updater = GraphitiGraphMemoryUpdater(graph_id)
        updater.start()
        cls._updaters[simulation_id] = updater
        return updater


