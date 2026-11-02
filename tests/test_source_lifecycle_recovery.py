"""Lifecycle retries preserve exact evidence and avoid duplicate revisions."""

import asyncio

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.service import MemoryService
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, CaptureSource, RememberMemoryRequest, open_builtin_runtime
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleEvent
from powercontext.builtin.scope import ScopeDraft


def test_failed_propagation_replays_after_restart(tmp_path, monkeypatch):
    async def run():
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'recovery.db'}"))
        event = SourceLifecycleEvent(node_id="root", revision=1, sequence=1, available=False, reason="withdrawn")
        async with open_builtin_runtime(config) as runtime:
            scope = await runtime.scopes.create(ScopeDraft(title="Recovery", summary="Retry", idempotency_key="retry"))
            sid = scope.scope_id
            lifecycle = runtime.lifecycle.for_scope(sid)
            source = await runtime.sources.for_scope(sid).capture(
                CaptureSource(source_id="root", content="evidence", metadata={})
            )
            await lifecycle.register_source("root", source.source_ref, revision=1)
            references = []
            for index in range(2):
                result = await runtime.memory.for_scope(sid).remember(
                    RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=f"fact {index}"),))
                )
                references.append(result.entry.citation)
                await lifecycle.register_memory(str(index), result.entry.citation, parents=("root",), policy="all")
            original = MemoryService.forget
            calls = 0

            async def fail_second(self, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("interrupted write")
                return await original(self, *args, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(MemoryService, "forget", fail_second)
                with pytest.raises(RuntimeError, match="interrupted write"):
                    await lifecycle.apply(event)
        async with open_builtin_runtime(config) as runtime:
            lifecycle = runtime.lifecycle.for_scope(sid)
            assert await lifecycle.apply(event) == []
            memory = runtime.memory.for_scope(sid)
            entries = await memory.list(include_inactive=True)
            assert all(record.state == "inactive" for record in entries.entries)
            assert await lifecycle.apply(event) == []
            assert (await memory.list(include_inactive=True)).memory_ref == entries.memory_ref
            for index, reference in enumerate(references):
                assert await lifecycle.resolve(str(index), purpose="audit") == reference

    asyncio.run(run())
