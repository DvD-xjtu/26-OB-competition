# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0.
"""Capture the visible events of a selected Pi session branch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel, JsonValue

from powercontext.sources.connectors import ConnectorRunCompletion, ConnectorRunSession, ConnectorRunStatus
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class PiSessionInput(BaseModel):
    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def _identity(session_id: str, event_id: str) -> str:
    value = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(value) > 256 or not session_id or not event_id:
        raise ValueError("invalid Pi event identity")  # noqa: TRY003
    return value


def _text_blocks(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for block in value:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif block.get("type") == "toolCall":
            name, call_id = block.get("name"), block.get("id")
            if isinstance(name, str) and isinstance(call_id, str):
                args = json.dumps(block.get("arguments", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                parts.append(f"[tool_call {name} {call_id}] {args}")
    return "\n".join(parts)


def _visible(record: dict) -> tuple[str, str] | None:
    event_type = record.get("type")
    if event_type in ("compaction", "branch_summary"):
        role, body = event_type, record.get("summary", "")
    elif event_type == "custom_message":
        role, body = "custom", _text_blocks(record.get("content"))
    elif event_type == "message" and isinstance(record.get("message"), dict):
        message = record["message"]
        role = message.get("role")
        body = _text_blocks(message.get("content"))
        if role == "toolResult" and body:
            body = f"[tool_result {message.get('toolName', '')} {message.get('toolCallId', '')}] {body}"
        elif role == "bashExecution":
            command, output = message.get("command", ""), message.get("output", "")
            body = f"$ {command}" + (f"\n{output}" if output else "")
    else:
        return None
    if not isinstance(role, str) or not isinstance(body, str) or not body:
        return None
    return role, f"{role}: {body}"


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:  # noqa: C901
    try:
        lines = value.content.decode("utf-8-sig").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
    except (UnicodeError, ValueError) as error:
        raise ValueError("invalid Pi session JSONL") from error  # noqa: TRY003
    if not records or not isinstance(records[0], dict):
        raise ValueError("missing Pi session header")  # noqa: TRY003
    header = records[0]
    session_id = header.get("id")
    if (
        header.get("type") != "session"
        or header.get("version") != 3
        or not isinstance(session_id, str)
        or not session_id.strip()
    ):
        raise ValueError("invalid Pi session header")  # noqa: TRY003
    nodes: dict[str, dict] = {}
    for record in records[1:]:
        if not isinstance(record, dict):
            raise ValueError("invalid Pi session record")  # noqa: TRY003, TRY004
        event_id, parent = record.get("id"), record.get("parentId")
        if (
            not isinstance(event_id, str)
            or not event_id.strip()
            or event_id in nodes
            or "parentId" not in record
            or (parent is not None and (not isinstance(parent, str) or parent not in nodes))
        ):
            raise ValueError("invalid Pi event graph")  # noqa: TRY003
        _identity(session_id, event_id)
        nodes[event_id] = record
    leaf = value.leaf_id if value.leaf_id is not None else next(reversed(nodes), None)
    if leaf is not None and leaf not in nodes:
        raise ValueError("unknown Pi session leaf")  # noqa: TRY003
    chain: list[dict] = []
    while leaf is not None:
        record = nodes[leaf]
        chain.append(record)
        leaf = record["parentId"]
    events: list[PiEventInput] = []
    for record in reversed(chain):
        visible = _visible(record)
        if visible is not None:
            role, content = visible
            events.append(
                PiEventInput(
                    session_id=session_id,
                    event_id=record["id"],
                    parent_id=record["parentId"],
                    event_type=record["type"],
                    role=role,
                    content=content,
                    record=record,
                )
            )
    return tuple(events)


class PiEventAdapter:
    name = "pi-event"
    input_class = PiEventInput
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        return PiEventSource(
            name=_identity(value.session_id, value.event_id),
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(**source.model_dump(include=set(PiEventInput.model_fields)))


class PiEventProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type="pi-event",
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(PiEventAdapter(), version="1", projections=(PiEventProjection(),))


class PiSessionConnector:
    name = "pi-session-history"
    version = "1"
    source_definitions = frozenset({"pi-event"})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        events = parse_pi_session(PiSessionInput(content=self.path.read_bytes(), leaf_id=self.leaf_id))
        old = session.checkpoint
        if old is not None and (not isinstance(old, dict) or not isinstance(old.get("events"), dict)):
            raise ValueError("invalid Pi checkpoint")  # noqa: TRY003
        previous = dict(old["events"]) if isinstance(old, dict) else {}
        pending: list[tuple[PiEventInput, str, str]] = []
        for event in events:
            identity = _identity(event.session_id, event.event_id)
            payload = json.dumps(event.record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            if identity in previous and previous[identity] != digest:
                raise ValueError("a previously captured Pi event changed")  # noqa: TRY003
            if identity not in previous:
                pending.append((event, identity, digest))
        for event, identity, digest in pending:
            await session.submit(identity, "pi-event", event)
            previous[identity] = digest
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint={"events": previous})
