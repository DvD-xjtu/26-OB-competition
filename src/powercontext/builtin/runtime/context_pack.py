"""Portable UTF-8 context packs and verified prefix deltas."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass

PACK_SCHEMA = "powercontext.context-pack.v1"
DELTA_SCHEMA = "powercontext.context-pack-delta.v1"


class ContextPackError(ValueError):
    """Invalid context pack, delta or chunk boundary."""


def _wire(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _encode(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode(values: object) -> tuple[bytes, ...]:
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ContextPackError("invalid chunk array")
    try:
        items = tuple(base64.b64decode(value, validate=True) for value in values)
    except (ValueError, binascii.Error) as exc:
        raise ContextPackError("invalid Base64") from exc
    if _encode(items) != values:
        raise ContextPackError("nonstandard Base64")
    _validate_items(items)
    return items


def _validate_items(items: tuple[bytes, ...]) -> None:
    if not isinstance(items, tuple) or any(not isinstance(item, bytes) for item in items):
        raise ContextPackError("chunks must be a bytes tuple")
    try:
        for item in items:
            item.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContextPackError("invalid UTF-8 chunk") from exc


def _digest(value: object) -> None:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ContextPackError("invalid digest")


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContextPackError("duplicate field")
        result[key] = value
    return result


def _parse(data: bytes, schema: str, fields: set[str]) -> dict:
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_fields)
    except (ValueError, AttributeError) as exc:
        raise ContextPackError("invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != fields or value["schema"] != schema:
        raise ContextPackError("invalid protocol fields")
    return value


@dataclass(frozen=True, slots=True)
class ContextPack:
    """Complete context, including its canonical wire length."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        _validate_items(items)
        payload = {"schema": PACK_SCHEMA, "items": _encode(items)}
        digest = "sha256:" + hashlib.sha256(_wire(payload)).hexdigest()
        payload["digest"] = digest
        count = 0
        while True:
            payload["byte_count"] = count
            size = len(_wire(payload))
            if size == count:
                return cls(items, digest, count)
            count = size

    @classmethod
    def from_content(cls, content: str | None, *, chunk_bytes: int = 512) -> ContextPack:
        if type(chunk_bytes) is not int or chunk_bytes <= 0:
            raise ContextPackError("chunk_bytes must be a positive integer")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise ContextPackError("content must be text")
        chunks: list[bytes] = []
        chunk = bytearray()
        try:
            for char in content:
                encoded = char.encode("utf-8")
                if len(encoded) > chunk_bytes:
                    raise ContextPackError("chunk limit cannot hold a UTF-8 character")
                if len(chunk) + len(encoded) > chunk_bytes:
                    chunks.append(bytes(chunk))
                    chunk.clear()
                chunk.extend(encoded)
            if chunk:
                chunks.append(bytes(chunk))
        except UnicodeEncodeError as exc:
            raise ContextPackError("invalid Unicode text") from exc
        return cls.build(tuple(chunks))

    def to_bytes(self) -> bytes:
        return _wire({
            "schema": PACK_SCHEMA,
            "items": _encode(self.items),
            "digest": self.digest,
            "byte_count": self.byte_count,
        })

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        payload = _parse(data, PACK_SCHEMA, {"schema", "items", "digest", "byte_count"})
        pack = cls.build(_decode(payload["items"]))
        if type(payload["byte_count"]) is not int or payload["byte_count"] != pack.byte_count:
            raise ContextPackError("incorrect byte count")
        if payload["digest"] != pack.digest:
            raise ContextPackError("incorrect pack digest")
        return pack


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """Retained base prefix followed by new target chunks."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        _digest(self.base_digest)
        _digest(self.target_digest)
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("invalid prefix count")
        _validate_items(self.appended)

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        _validate_pack(base)
        _validate_pack(target)
        prefix = 0
        for left, right in zip(base.items, target.items):
            if left != right:
                break
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    def to_bytes(self) -> bytes:
        return _wire({
            "schema": DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encode(self.appended),
        })

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        payload = _parse(data, DELTA_SCHEMA, {"schema", "base_digest", "target_digest", "prefix_items", "appended"})
        return cls(
            payload["base_digest"], payload["target_digest"], payload["prefix_items"], _decode(payload["appended"])
        )


def _validate_pack(pack: ContextPack) -> None:
    if not isinstance(pack, ContextPack) or ContextPack.build(pack.items) != pack:
        raise ContextPackError("invalid base or target pack")


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Reconstruct independently and verify both endpoint identities."""
    _validate_pack(base)
    if base.digest != delta.base_digest or delta.prefix_items > len(base.items):
        raise ContextPackError("base mismatch or prefix out of bounds")
    target = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        raise ContextPackError("incorrect target digest")
    return target
