"""Event-loop-local embedding coalescing and a bounded success cache."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict

from powercontext.builtin.inference import EmbeddingModel, EmbeddingResult, EmbeddingVector, InferenceUsage


class CoalescingEmbeddingModel:
    """Share pending texts without coupling the lifetime of their callers."""

    def __init__(
        self, model: EmbeddingModel, *, max_batch_size: int = 64, coalesce_ms: float = 5.0, cache_size: int = 1024
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size <= 0:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache_size must be a nonnegative integer")  # noqa: TRY003
        if not math.isfinite(coalesce_ms) or coalesce_ms < 0:
            raise ValueError("coalesce_ms must be finite and nonnegative")  # noqa: TRY003
        self.profile = model.profile
        self._model = model
        self._max_batch_size = max_batch_size
        self._delay = coalesce_ms / 1000
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._pending: dict[str, asyncio.Future] = {}
        self._queued: list[str] = []
        self._scheduled = False
        self._tasks: set[asyncio.Task] = set()

    def _launch(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def embed(self, texts: tuple[str, ...]) -> EmbeddingResult:
        """Restore input order and count each awaited provider batch once."""
        loop = asyncio.get_running_loop()
        waiting: dict[str, asyncio.Future] = {}
        vectors = {}
        for text in texts:
            if text in self._cache:
                self._cache.move_to_end(text)
                vectors[text] = self._cache[text]
            else:
                if text not in self._pending:
                    future = loop.create_future()
                    # A cancelled caller may leave a failed shared request unobserved.
                    future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
                    self._pending[text] = future
                    self._queued.append(text)
                waiting[text] = self._pending[text]
        if self._queued and not self._scheduled:
            self._scheduled = True
            self._launch(self._dispatch())
        usages: dict[object, InferenceUsage] = {}
        if waiting:
            results = await asyncio.gather(*(asyncio.shield(future) for future in waiting.values()))
            for text, (vector, batch, usage) in zip(waiting, results, strict=True):
                vectors[text] = vector
                usages[batch] = usage
        input_tokens = [usage.input_tokens for usage in usages.values() if usage.input_tokens is not None]
        output_tokens = [usage.output_tokens for usage in usages.values() if usage.output_tokens is not None]
        return EmbeddingResult(
            vectors=tuple(vectors[text] for text in texts),
            usage=InferenceUsage(
                requests=sum(usage.requests for usage in usages.values()),
                input_tokens=sum(input_tokens) if input_tokens else None,
                output_tokens=sum(output_tokens) if output_tokens else None,
            ),
        )

    async def _dispatch(self) -> None:
        await asyncio.sleep(self._delay)
        queued, self._queued = self._queued, []
        self._scheduled = False
        for start in range(0, len(queued), self._max_batch_size):
            self._launch(self._execute(tuple(queued[start : start + self._max_batch_size])))

    async def _execute(self, texts: tuple[str, ...]) -> None:
        batch = object()
        try:
            result = await self._model.embed(texts)
            if len(result.vectors) != len(texts):
                raise ValueError("provider returned a different vector count")  # noqa: TRY003
        except (Exception, asyncio.CancelledError) as exc:
            for text in texts:
                future = self._pending.pop(text)
                if isinstance(exc, asyncio.CancelledError):
                    future.cancel()
                else:
                    future.set_exception(exc)
        else:
            for text, vector in zip(texts, result.vectors, strict=True):
                if self._cache_size:
                    self._cache[text] = vector
                    self._cache.move_to_end(text)
                    while len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
                self._pending.pop(text).set_result((vector, batch, result.usage))
