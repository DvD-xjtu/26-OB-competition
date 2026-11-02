"""HTTP scoring with globally stable, identity-preserving selection."""

from __future__ import annotations

import math

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage


class HTTPMemoryReranker:
    """Score bounded batches using a caller-owned HTTP client."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        self.policy_id = policy_id
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size

    async def rerank(self, query: str, candidates: tuple[MemoryHit, ...], limit: int, /) -> MemoryRerankDecision:
        """Validate each batch, then select by score and original global rank."""
        if not candidates or type(limit) is not int or not 1 <= limit <= len(candidates):
            raise ValueError("limit must be within the nonempty candidate pool")  # noqa: TRY003
        scores: dict[int, float] = {}
        requests = 0
        for start in range(0, len(candidates), self._batch_size):
            batch = candidates[start : start + self._batch_size]
            expected = set(range(start + 1, start + len(batch) + 1))
            response = await self._client.post(
                self._endpoint,
                json={
                    "query": query,
                    "candidates": [
                        {"rank": rank, "text": candidate.text} for rank, candidate in enumerate(batch, start=start + 1)
                    ],
                },
            )
            requests += 1
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or set(payload) != {"scores"} or not isinstance(payload["scores"], list):
                raise ValueError("invalid scoring response")  # noqa: TRY003
            for item in payload["scores"]:
                if not isinstance(item, dict) or set(item) != {"rank", "score"}:
                    raise ValueError("invalid score fields")  # noqa: TRY003
                rank, score = item["rank"], item["score"]
                if type(rank) is not int or rank not in expected:
                    raise ValueError("duplicate or foreign candidate rank")  # noqa: TRY003
                if type(score) not in (int, float):
                    raise ValueError("score must be finite numeric data")  # noqa: TRY003
                try:
                    numeric = float(score)
                except OverflowError as exc:
                    raise ValueError("score is out of range") from exc  # noqa: TRY003
                if not math.isfinite(numeric):
                    raise ValueError("score must be finite")  # noqa: TRY003
                expected.remove(rank)
                scores[rank] = numeric
            if expected:
                raise ValueError("missing candidate scores")  # noqa: TRY003
        selected = sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit]
        return MemoryRerankDecision(selected_ranks=tuple(selected), usage=InferenceUsage(requests=requests))
