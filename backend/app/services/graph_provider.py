"""Graph provider factory for ZEP-free/local and future Graphiti backends."""

from __future__ import annotations

from typing import Any, Optional

from ..config import Config


def provider_name() -> str:
    return (Config.GRAPH_PROVIDER or "zep").lower()


def is_zep_provider() -> bool:
    return provider_name() == "zep"


def is_local_simple_provider() -> bool:
    return provider_name() == "local_simple"


def get_graph_builder() -> Any:
    if is_local_simple_provider():
        from .local_simple_graph import LocalSimpleGraphBuilder
        return LocalSimpleGraphBuilder()
    from .graph_builder import GraphBuilderService
    return GraphBuilderService(api_key=Config.ZEP_API_KEY)


def get_entity_reader() -> Any:
    if is_local_simple_provider():
        from .local_simple_graph import LocalSimpleEntityReader
        return LocalSimpleEntityReader()
    from .zep_entity_reader import ZepEntityReader
    return ZepEntityReader(api_key=Config.ZEP_API_KEY)


def get_graph_tools(llm_client: Optional[Any] = None) -> Any:
    if is_local_simple_provider():
        from .local_simple_graph import LocalSimpleToolsService
        return LocalSimpleToolsService(llm_client=llm_client)
    from .zep_tools import ZepToolsService
    return ZepToolsService(api_key=Config.ZEP_API_KEY, llm_client=llm_client)


def get_graph_memory_manager() -> Any:
    if is_local_simple_provider():
        from .local_simple_graph import LocalSimpleGraphMemoryManager
        return LocalSimpleGraphMemoryManager
    from .zep_graph_memory_updater import ZepGraphMemoryManager
    return ZepGraphMemoryManager
