"""Graph provider factory for Graphiti and legacy Zep backends.

Graphiti is the local/ZEP-free runtime. The old local_simple provider is no
longer selectable as a product runtime; Graphiti projection cache is internal
UI/read-model scaffolding only.
"""

from __future__ import annotations

from typing import Any, Optional

from ..config import Config


def provider_name() -> str:
    return (Config.GRAPH_PROVIDER or "graphiti").lower()


def is_zep_provider() -> bool:
    return provider_name() == "zep"


def is_graphiti_provider() -> bool:
    return provider_name() == "graphiti"


def get_graph_builder() -> Any:
    if is_graphiti_provider():
        from .graphiti_provider import GraphitiGraphBuilder
        return GraphitiGraphBuilder()
    from .graph_builder import GraphBuilderService
    return GraphBuilderService(api_key=Config.ZEP_API_KEY)


def get_entity_reader() -> Any:
    if is_graphiti_provider():
        from .graphiti_provider import GraphitiEntityReader
        return GraphitiEntityReader()
    from .zep_entity_reader import ZepEntityReader
    return ZepEntityReader(api_key=Config.ZEP_API_KEY)


def get_graph_tools(llm_client: Optional[Any] = None) -> Any:
    if is_graphiti_provider():
        from .graphiti_provider import GraphitiToolsService
        return GraphitiToolsService(llm_client=llm_client)
    from .zep_tools import ZepToolsService
    return ZepToolsService(api_key=Config.ZEP_API_KEY, llm_client=llm_client)


def get_graph_memory_manager() -> Any:
    if is_graphiti_provider():
        from .graphiti_provider import GraphitiGraphMemoryManager
        return GraphitiGraphMemoryManager
    from .zep_graph_memory_updater import ZepGraphMemoryManager
    return ZepGraphMemoryManager
