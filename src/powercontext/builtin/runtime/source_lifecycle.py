"""Persisted source dependency graphs with retryable native Memory transitions."""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import insert, select, update

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_TABLE
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.builtin.scope.models import validate_scope_id
from powercontext.sources import SourceRef


class SourceLifecycleError(ValueError):
    """Invalid binding, event, or use of unavailable evidence."""


class SourceLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    node_id: str
    reason: str
    revision: int = Field(gt=0)
    sequence: int = Field(gt=0)
    available: bool

    @field_validator("node_id", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")  # noqa: TRY003
        return value


class SourceLifecycleApplication:
    def __init__(self, runtime) -> None:
        self._runtime = runtime
        self._locks: dict[str, asyncio.Lock] = {}

    def for_scope(self, scope_id: str):
        scope_id = validate_scope_id(scope_id)
        return ScopedSourceLifecycle(self._runtime, scope_id, self._locks.setdefault(scope_id, asyncio.Lock()))


def _active(graph: dict) -> set[str]:
    active: set[str] = set()
    pending = dict(graph)
    while pending:
        progressed = False
        for node_id, node in list(pending.items()):
            parents = node["parents"]
            if any(parent in pending for parent in parents):
                continue
            if any(parent not in graph for parent in parents):
                raise SourceLifecycleError("unknown parent")
            available = (
                (node.get("event") or {}).get("available", True)
                if node["kind"] == "source"
                else (
                    all(parent in active for parent in parents)
                    if node["policy"] == "all"
                    else any(parent in active for parent in parents)
                )
            )
            if available:
                active.add(node_id)
            del pending[node_id]
            progressed = True
        if not progressed:
            raise SourceLifecycleError("cyclic graph")
    return active


def _reference(node):
    cls = {"source": SourceRef, "memory": MemoryCitation, "topic": ArtifactRef}[node["kind"]]
    return cls.model_validate(node["reference"])


class ScopedSourceLifecycle:
    def __init__(self, runtime, scope_id: str, lock: asyncio.Lock) -> None:
        self._runtime, self.scope_id, self._lock = runtime, scope_id, lock

    async def _load(self) -> dict:
        async with self._runtime._provider.database.transaction() as connection:
            raw = await connection.scalar(
                select(SOURCE_LIFECYCLE_TABLE.c.graph).where(SOURCE_LIFECYCLE_TABLE.c.scope_id == self.scope_id)
            )
        return {} if raw is None else json.loads(raw)

    async def _save(self, graph: dict) -> None:
        table = SOURCE_LIFECYCLE_TABLE
        async with self._runtime._provider.database.transaction() as connection:
            exists = await connection.scalar(select(table.c.scope_id).where(table.c.scope_id == self.scope_id))
            payload = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
            if exists is None:
                await connection.execute(insert(table).values(scope_id=self.scope_id, graph=payload))
            else:
                await connection.execute(update(table).where(table.c.scope_id == self.scope_id).values(graph=payload))

    async def register_source(self, node_id: str, source_ref: SourceRef, *, revision: int) -> None:
        if type(revision) is not int or revision <= 0:
            raise SourceLifecycleError("invalid lifecycle revision")
        await self._register(node_id, "source", source_ref, (), "all", revision)

    async def register_memory(
        self, node_id: str, citation: MemoryCitation, *, parents: tuple[str, ...], policy: str
    ) -> None:
        await self._register(node_id, "memory", citation, parents, policy, None)

    async def register_topic(
        self, node_id: str, artifact_ref: ArtifactRef, *, parents: tuple[str, ...], policy: str
    ) -> None:
        await self._register(node_id, "topic", artifact_ref, parents, policy, None)

    async def _register(self, node_id, kind, reference, parents, policy, revision):
        if not isinstance(node_id, str) or not node_id.strip():
            raise SourceLifecycleError("invalid node ID")
        if policy not in ("all", "any") or (kind != "source" and not parents):
            raise SourceLifecycleError("invalid dependency policy")
        if any(not isinstance(parent, str) for parent in parents) or len(set(parents)) != len(parents):
            raise SourceLifecycleError("invalid parents")
        expected_type = {"source": SourceRef, "memory": MemoryCitation, "topic": ArtifactRef}[kind]
        if not isinstance(reference, expected_type):
            raise SourceLifecycleError("invalid reference type")
        binding = {
            "kind": kind,
            "reference": reference.model_dump(mode="json"),
            "parents": list(parents),
            "policy": policy,
            "revision": revision,
        }
        async with self._lock:
            graph = await self._load()
            if any(parent == node_id or parent not in graph for parent in parents):
                raise SourceLifecycleError("missing or self parent")
            if node_id in graph:
                if {key: value for key, value in graph[node_id].items() if key != "event"} != binding:
                    raise SourceLifecycleError("conflicting registration")
                await self._propagate(graph)
                return
            try:
                if kind == "source":
                    await self._runtime.records.for_scope(self.scope_id).get_source(
                        reference.source_type, reference.source_id
                    )
                elif kind == "memory":
                    await self._runtime.memory.for_scope(self.scope_id).get(GetMemoryEntryRequest(citation=reference))
                else:
                    if reference.family != "topic-memory":
                        raise SourceLifecycleError("expected Topic Memory")
                    await self._runtime.records.for_scope(self.scope_id).get_artifact_revision(
                        reference.family, reference.artifact_id, reference.revision
                    )
            except Exception as exc:
                raise SourceLifecycleError("reference is not readable in this scope") from exc
            graph[node_id] = binding
            _active(graph)
            await self._save(graph)
            await self._propagate(graph)

    async def apply(self, event: SourceLifecycleEvent) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("invalid event")
        async with self._lock:
            graph = await self._load()
            node = graph.get(event.node_id)
            if node is None or node["kind"] != "source" or node["revision"] != event.revision:
                raise SourceLifecycleError("unknown source or lifecycle revision")
            previous = node.get("event")
            incoming = event.model_dump(mode="json")
            if previous and (
                event.sequence < previous["sequence"]
                or (event.sequence == previous["sequence"] and incoming != previous)
            ):
                raise SourceLifecycleError("stale or conflicting event")
            if previous != incoming:
                node["event"] = incoming
                # Persist intent before native writes: retries reconcile from actual current state.
                await self._save(graph)
            await self._propagate(graph)
            return sorted(_active(graph))

    async def _propagate(self, graph: dict) -> None:
        active = _active(graph)
        async with self._runtime._context(self.scope_id) as context, self._runtime._locked(self.scope_id):
            service = context.artifacts.memory
            memory_nodes = [(node_id, node) for node_id, node in graph.items() if node["kind"] == "memory"]
            if not memory_nodes:
                return
            current = await service.head(context.artifacts.memory_artifact_id)
            entries = {entry.entry_id: entry for entry in await service.entries(current)}
            for node_id, node in memory_nodes:
                citation = _reference(node)
                entry = entries.get(citation.entry_id)
                if entry is None or entry.entry_version_id != citation.entry_version_id:
                    raise SourceLifecycleError("bound Memory version changed")
                desired = node_id in active
                state = next(item.state for item in current.content.manifest.entries if item.entry_id == entry.entry_id)
                if (state == "active") != desired:
                    operation = service.reactivate if desired else service.forget
                    current = await operation(current, entries=(entry,), reason="source lifecycle")
                    entries = {entry.entry_id: entry for entry in await service.entries(current)}

    async def resolve(self, node_id: str, *, purpose: Literal["generation", "audit"]):
        if purpose not in ("generation", "audit"):
            raise SourceLifecycleError("unknown purpose")
        graph = await self._load()
        if node_id not in graph or (purpose == "generation" and node_id not in _active(graph)):
            raise SourceLifecycleError("unknown or unavailable node")
        return _reference(graph[node_id])

    async def unavailable_topics(self) -> set[str]:
        graph = await self._load()
        active = _active(graph)
        return {
            node["reference"]["artifact_id"]
            for node_id, node in graph.items()
            if node["kind"] == "topic" and node_id not in active
        }
