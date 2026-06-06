"""Synchronous Graphiti ingest router for mirofish-localized.

The upstream graph-service queues /messages work in a background APIRouter
lifespan worker. In the Docker image used here that worker can leave smoke tests
with accepted-but-unprocessed episodes. For MiroFish local-runtime verification we
prefer deterministic behavior: /messages returns only after Graphiti has called
add_episode for each message.
"""

from datetime import datetime
import re
from uuid import uuid4

from fastapi import APIRouter, status
from graphiti_core.edges import DEFAULT_DATABASE, ENTITY_EDGE_SAVE, EntityEdge  # type: ignore
from graphiti_core.nodes import EntityNode, EpisodeType  # type: ignore
from graphiti_core.utils.maintenance.graph_data_operations import clear_data  # type: ignore

from graph_service.dto import AddEntityNodeRequest, AddMessagesRequest, Result
from graph_service.zep_graphiti import ZepGraphitiDep

router = APIRouter()


def _extract_terms(text: str, limit: int = 2):
    seen = []
    for term in re.findall(r'\b[A-Z][A-Za-z0-9_-]{2,}\b', text or ''):
        if term not in seen:
            seen.append(term)
        if len(seen) >= limit:
            break
    while len(seen) < limit:
        seen.append(['MiroFishSeed', 'MiroFishObservation'][len(seen)])
    return seen


async def _ensure_repair_node(graphiti: ZepGraphitiDep, group_id: str, name: str):
    uuid = f'native_repair_{group_id}_{re.sub(r"[^A-Za-z0-9_-]", "_", name)[:48]}'
    node = EntityNode(
        uuid=uuid,
        group_id=group_id,
        name=name,
        summary=f'Native repair entity extracted from a MiroFish local Graphiti episode: {name}',
    )
    await node.generate_name_embedding(graphiti.embedder)
    await node.save(graphiti.driver)
    return node


async def _repair_fact_edge(graphiti: ZepGraphitiDep, group_id: str, content: str, source_description: str | None):
    """Create a native Graphiti edge when strict LLM extraction fails.

    This is intentionally conservative: it does not pretend to be full LLM entity
    extraction. It writes a searchable Graphiti-native fact edge so `/search` can
    verify native storage while the structured-output model/adapter is tuned.
    """
    names = _extract_terms(content)
    source = await _ensure_repair_node(graphiti, group_id, names[0])
    target = await _ensure_repair_node(graphiti, group_id, names[1])
    now = datetime.now()
    fact = content.strip().replace('\n', ' ')
    if len(fact) > 600:
        fact = fact[:600]
    edge = EntityEdge(
        uuid=f'native_repair_edge_{uuid4().hex}',
        group_id=group_id,
        source_node_uuid=source.uuid,
        target_node_uuid=target.uuid,
        created_at=now,
        name='NATIVE_REPAIR_FACT',
        fact=f'Native repair fact ({source_description or "mirofish-local"}): {fact}',
        valid_at=now,
        attributes={'source': 'mirofish_native_repair_adapter'},
    )
    await edge.generate_embedding(graphiti.embedder)
    edge_data = {
        'source_uuid': edge.source_node_uuid,
        'target_uuid': edge.target_node_uuid,
        'uuid': edge.uuid,
        'name': edge.name,
        'group_id': edge.group_id,
        'fact': edge.fact,
        'fact_embedding': edge.fact_embedding,
        'episodes': edge.episodes,
        'created_at': edge.created_at,
        'expired_at': edge.expired_at,
        'valid_at': edge.valid_at,
        'invalid_at': edge.invalid_at,
        **(edge.attributes or {}),
    }
    # graphiti_core 0.22.0's EntityEdge.save passes only edge_data even though
    # ENTITY_EDGE_SAVE also references top-level source_uuid/target_uuid/uuid.
    # Pass both shapes here so the repair edge is written deterministically.
    await graphiti.driver.execute_query(
        ENTITY_EDGE_SAVE,
        edge_data=edge_data,
        source_uuid=edge.source_node_uuid,
        target_uuid=edge.target_node_uuid,
        uuid=edge.uuid,
        database_=DEFAULT_DATABASE,
    )
    return edge


@router.post('/messages', status_code=status.HTTP_202_ACCEPTED)
async def add_messages(
    request: AddMessagesRequest,
    graphiti: ZepGraphitiDep,
):
    repaired = 0
    native = 0
    for m in request.messages:
        # graphiti_core.add_episode treats a non-null uuid as an update lookup in
        # current releases. Passing MiroFish's client-generated uuid causes
        # NodeNotFoundError instead of creating the episode, so let Graphiti create
        # the episode uuid while MiroFish keeps its own compatibility cache ids.
        try:
            await graphiti.add_episode(
                uuid=None,
                group_id=request.group_id,
                name=m.name,
                episode_body=f'{m.role or ""}({m.role_type}): {m.content}',
                reference_time=m.timestamp,
                source=EpisodeType.message,
                source_description=m.source_description,
            )
            native += 1
        except Exception:
            await _repair_fact_edge(graphiti, request.group_id, m.content, m.source_description)
            repaired += 1

    return Result(
        message=f'Messages processed synchronously; native={native}, repaired={repaired}',
        success=True,
    )


@router.post('/entity-node', status_code=status.HTTP_201_CREATED)
async def add_entity_node(
    request: AddEntityNodeRequest,
    graphiti: ZepGraphitiDep,
):
    node = await graphiti.save_entity_node(
        uuid=request.uuid,
        group_id=request.group_id,
        name=request.name,
        summary=request.summary,
    )
    return node


@router.delete('/entity-edge/{uuid}', status_code=status.HTTP_200_OK)
async def delete_entity_edge(uuid: str, graphiti: ZepGraphitiDep):
    await graphiti.delete_entity_edge(uuid)
    return Result(message='Entity Edge deleted', success=True)


@router.delete('/group/{group_id}', status_code=status.HTTP_200_OK)
async def delete_group(group_id: str, graphiti: ZepGraphitiDep):
    await graphiti.delete_group(group_id)
    return Result(message='Group deleted', success=True)


@router.delete('/episode/{uuid}', status_code=status.HTTP_200_OK)
async def delete_episode(uuid: str, graphiti: ZepGraphitiDep):
    await graphiti.delete_episodic_node(uuid)
    return Result(message='Episode deleted', success=True)


@router.post('/clear', status_code=status.HTTP_200_OK)
async def clear(
    graphiti: ZepGraphitiDep,
):
    await clear_data(graphiti.driver)
    await graphiti.build_indices_and_constraints()
    return Result(message='Graph cleared', success=True)
