import ast
import json
import logging
import re
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from graphiti_core import Graphiti  # type: ignore
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig  # type: ignore
import os
from graphiti_core.edges import EntityEdge  # type: ignore
from graphiti_core.errors import EdgeNotFoundError, GroupsEdgesNotFoundError, NodeNotFoundError
from graphiti_core.llm_client import LLMClient  # type: ignore
from graphiti_core.llm_client.config import LLMConfig  # type: ignore
from graphiti_core.llm_client.openai_client import OpenAIClient  # type: ignore
from graphiti_core.nodes import EntityNode, EpisodicNode  # type: ignore

from graph_service.config import ZepEnvDep
from graph_service.dto import FactResult

logger = logging.getLogger(__name__)


def _json_from_completion(response: Any) -> dict[str, Any]:
    content = (response.choices[0].message.content or '{}').strip()
    if content.startswith('```'):
        content = re.sub(r'^```(?:json|python)?\s*', '', content)
        content = re.sub(r'\s*```$', '', content).strip()
    try:
        return json.loads(content)
    except Exception:
        # Some local OpenAI-compatible gateways return Python-literal-looking
        # dicts/lists despite JSON mode. Accept that shape and normalize it
        # before Graphiti validates the Pydantic response model.
        try:
            parsed = ast.literal_eval(content)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {'_list': parsed}
        except Exception:
            pass
        match = re.search(r'(\{.*\}|\[.*\])', content, flags=re.S)
        if match:
            snippet = match.group(1)
            try:
                return json.loads(snippet)
            except Exception:
                parsed = ast.literal_eval(snippet)
                if isinstance(parsed, dict):
                    return parsed
                if isinstance(parsed, list):
                    return {'_list': parsed}
        raise


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_structured_payload(payload: Any, response_model: type[Any], entity_names: dict[int, str] | None = None) -> dict[str, Any]:
    """Normalize common OpenAI-compatible JSON shapes into Graphiti schemas.

    Some local/OpenAI-compatible endpoints acknowledge JSON mode but ignore the
    beta structured-output parser. They often return semantically correct JSON
    with wrapper/key variants such as `entities` instead of
    `extracted_entities`, or `subject_id`/`object_id` instead of
    Graphiti's `source_entity_id`/`target_entity_id`. This adapter keeps the
    Graphiti native add_episode path alive without falling back to the MiroFish
    projection cache.
    """
    model_name = getattr(response_model, '__name__', '')
    if isinstance(payload, str):
        payload = json.loads(payload)

    if model_name == 'ExtractedEntities':
        rows = payload
        if isinstance(payload, dict):
            rows = payload.get('extracted_entities') or payload.get('entities') or payload.get('nodes') or payload.get('_list') or []
        normalized = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name = row.get('name') or row.get('entity') or row.get('label')
            if not name:
                continue
            normalized.append({
                'name': str(name),
                'entity_type_id': _coerce_int(row.get('entity_type_id') or row.get('entity_type') or row.get('type_id'), 0),
            })
        return {'extracted_entities': normalized}

    if model_name == 'NodeResolutions':
        rows = payload
        if isinstance(payload, dict):
            rows = payload.get('entity_resolutions') or payload.get('resolutions') or payload.get('nodes') or payload.get('_list') or []
        normalized = []
        for idx, row in enumerate(rows if isinstance(rows, list) else []):
            if not isinstance(row, dict):
                continue
            normalized.append({
                'id': _coerce_int(row.get('id'), idx),
                'duplicate_idx': _coerce_int(row.get('duplicate_idx') if row.get('duplicate_idx') is not None else row.get('duplicate_id'), -1),
                'name': str(row.get('name') or row.get('entity') or f'entity_{idx}'),
                'additional_duplicates': row.get('additional_duplicates') if isinstance(row.get('additional_duplicates'), list) else [],
            })
        return {'entity_resolutions': normalized}

    if model_name == 'ExtractedEdges':
        rows = payload
        if isinstance(payload, dict):
            rows = payload.get('edges') or payload.get('facts') or payload.get('relations') or payload.get('_list') or []
        normalized = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            source_id = row.get('source_entity_id') if row.get('source_entity_id') is not None else row.get('subject_id')
            target_id = row.get('target_entity_id') if row.get('target_entity_id') is not None else row.get('object_id')
            relation = row.get('relation_type') or row.get('predicate') or row.get('relation') or row.get('type') or 'RELATED_TO'
            relation = re.sub(r'[^A-Za-z0-9]+', '_', str(relation)).strip('_').upper() or 'RELATED_TO'
            fact = row.get('fact') or row.get('description') or row.get('statement')
            if not fact:
                source_name = (entity_names or {}).get(_coerce_int(source_id, 0), f'entity {source_id}')
                target_name = (entity_names or {}).get(_coerce_int(target_id, 0), f'entity {target_id}')
                fact = f"{source_name} {relation.replace('_', ' ').lower()} {target_name}"
            normalized.append({
                'relation_type': relation,
                'source_entity_id': _coerce_int(source_id, 0),
                'target_entity_id': _coerce_int(target_id, 0),
                'fact': str(fact),
                'valid_at': row.get('valid_at'),
                'invalid_at': row.get('invalid_at'),
            })
        return {'edges': normalized}

    if isinstance(payload, dict):
        return payload
    return {}


class MiroFishStructuredOpenAIClient(OpenAIClient):
    """OpenAI-compatible client with Graphiti schema normalization.

    It preserves Graphiti's native `add_episode` pipeline, but avoids the SDK beta
    parser for providers that do not implement strict structured outputs.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mirofish_entity_names: dict[int, str] = {}

    async def _create_structured_completion(self, model, messages, temperature, max_tokens, response_model):
        return await self._create_completion(model, messages, temperature, max_tokens, response_model)

    def _handle_structured_response(self, response: Any) -> dict[str, Any]:
        # This method is kept for compatibility; `_generate_response` below uses
        # response_model-aware validation directly.
        return _json_from_completion(response)

    async def _generate_response(self, messages, response_model=None, max_tokens=8192, model_size=None):
        if response_model is None:
            return await super()._generate_response(messages, response_model, max_tokens, model_size)
        openai_messages = self._convert_messages_to_openai_format(messages)
        model = self._get_model_for_size(model_size)
        response = await self._create_completion(
            model=model,
            messages=openai_messages,
            temperature=self.temperature,
            max_tokens=max_tokens or self.max_tokens,
            response_model=response_model,
        )
        payload = _json_from_completion(response)
        normalized = _normalize_structured_payload(payload, response_model, self._mirofish_entity_names)
        if getattr(response_model, '__name__', '') == 'ExtractedEntities':
            self._mirofish_entity_names = {
                idx: row.get('name', '')
                for idx, row in enumerate(normalized.get('extracted_entities', []))
                if row.get('name')
            }
        return response_model.model_validate(normalized).model_dump()


def _structured_normalization_enabled() -> bool:
    return os.environ.get('GRAPHITI_STRUCTURED_NORMALIZATION', '1').lower() not in {'0', 'false', 'no', 'off'}


def _openai_llm_client(settings: ZepEnvDep) -> OpenAIClient:
    """Build Graphiti's extraction LLM client from explicit graph-memory env.

    Graphiti native extraction is stricter than MiroFish chat completion usage.
    Keeping this client explicit makes it possible to point Graphiti at a
    stronger structured-output model without changing the app-facing LLM.
    `GRAPHITI_STRUCTURED_NORMALIZATION=0` intentionally restores upstream
    beta-parse behavior so the A/B harness can compare old vs improved paths.
    """
    config = LLMConfig(
        api_key=os.environ.get('GRAPH_MEMORY_OPENAI_API_KEY') or settings.openai_api_key,
        base_url=os.environ.get('GRAPH_MEMORY_OPENAI_BASE_URL') or settings.openai_base_url,
        model=os.environ.get('GRAPH_MEMORY_MODEL_NAME') or settings.model_name,
        small_model=os.environ.get('GRAPH_MEMORY_SMALL_MODEL_NAME') or os.environ.get('GRAPH_MEMORY_MODEL_NAME') or settings.model_name,
    )
    if not _structured_normalization_enabled():
        return OpenAIClient(config=config)
    return MiroFishStructuredOpenAIClient(config=config)


class ZepGraphiti(Graphiti):
    def __init__(self, uri: str, user: str, password: str, llm_client: LLMClient | None = None, embedder=None):
        super().__init__(uri, user, password, llm_client=llm_client, embedder=embedder)

    async def save_entity_node(self, name: str, uuid: str, group_id: str, summary: str = ''):
        new_node = EntityNode(
            name=name,
            uuid=uuid,
            group_id=group_id,
            summary=summary,
        )
        await new_node.generate_name_embedding(self.embedder)
        await new_node.save(self.driver)
        return new_node

    async def get_entity_edge(self, uuid: str):
        try:
            edge = await EntityEdge.get_by_uuid(self.driver, uuid)
            return edge
        except EdgeNotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e

    async def delete_group(self, group_id: str):
        try:
            edges = await EntityEdge.get_by_group_ids(self.driver, [group_id])
        except GroupsEdgesNotFoundError:
            logger.warning(f'No edges found for group {group_id}')
            edges = []

        nodes = await EntityNode.get_by_group_ids(self.driver, [group_id])

        episodes = await EpisodicNode.get_by_group_ids(self.driver, [group_id])

        for edge in edges:
            await edge.delete(self.driver)

        for node in nodes:
            await node.delete(self.driver)

        for episode in episodes:
            await episode.delete(self.driver)

    async def delete_entity_edge(self, uuid: str):
        try:
            edge = await EntityEdge.get_by_uuid(self.driver, uuid)
            await edge.delete(self.driver)
        except EdgeNotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e

    async def delete_episodic_node(self, uuid: str):
        try:
            episode = await EpisodicNode.get_by_uuid(self.driver, uuid)
            await episode.delete(self.driver)
        except NodeNotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e


async def get_graphiti(settings: ZepEnvDep):
    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key=os.environ.get('EMBEDDING_API_KEY') or settings.openai_api_key,
            base_url=os.environ.get('EMBEDDING_BASE_URL') or settings.openai_base_url,
            embedding_model=os.environ.get('EMBEDDING_MODEL_NAME') or settings.embedding_model_name or 'text-embedding-3-small',
            embedding_dim=int(os.environ.get('EMBEDDING_DIM', '1536')),
        )
    )
    client = ZepGraphiti(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        llm_client=_openai_llm_client(settings),
        embedder=embedder,
    )

    try:
        yield client
    finally:
        await client.close()


async def initialize_graphiti(settings: ZepEnvDep):
    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key=os.environ.get('EMBEDDING_API_KEY') or settings.openai_api_key,
            base_url=os.environ.get('EMBEDDING_BASE_URL') or settings.openai_base_url,
            embedding_model=os.environ.get('EMBEDDING_MODEL_NAME') or settings.embedding_model_name or 'text-embedding-3-small',
            embedding_dim=int(os.environ.get('EMBEDDING_DIM', '1536')),
        )
    )
    client = ZepGraphiti(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        llm_client=_openai_llm_client(settings),
        embedder=embedder,
    )
    await client.build_indices_and_constraints()


def get_fact_result_from_edge(edge: EntityEdge):
    return FactResult(
        uuid=edge.uuid,
        name=edge.name,
        fact=edge.fact,
        valid_at=edge.valid_at,
        invalid_at=edge.invalid_at,
        created_at=edge.created_at,
        expired_at=edge.expired_at,
    )


ZepGraphitiDep = Annotated[ZepGraphiti, Depends(get_graphiti)]
