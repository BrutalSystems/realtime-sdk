"""WebSocket frame encoders + inbound parser for the realtime service.

Mirrors the realtime server's protocol message definitions. Server-published events arrive as
{"type": "message", "channel": str, "data": {"event": str, "payload": dict}}
— the frame `type` is "message" (ServerMessageType.MESSAGE), NOT "event".
The inner data.event is the app-level event name (e.g. "run.succeeded")."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def subscribe_frame(channel: str, *, scope: str | None = None, msg_id: str | None = None) -> dict[str, Any]:
    frame: dict[str, Any] = {"type": "subscribe", "channel": channel}
    if scope is not None:
        frame["scope"] = scope
    if msg_id is not None:
        frame["id"] = msg_id
    return frame


def unsubscribe_frame(channel: str) -> dict[str, Any]:
    return {"type": "unsubscribe", "channel": channel}


def publish_frame(channel: str, data: dict[str, Any], *, scope: str | None = None) -> dict[str, Any]:
    frame: dict[str, Any] = {"type": "publish", "channel": channel, "data": data}
    if scope is not None:
        frame["scope"] = scope
    return frame


def ping_frame() -> dict[str, Any]:
    return {"type": "ping"}


@dataclass(frozen=True)
class EventFrame:
    channel: str
    event: str
    payload: dict[str, Any]
    sender_id: str = ""


def parse_inbound(msg: dict[str, Any]) -> EventFrame | None:
    if msg.get("type") != "message":
        return None
    channel = msg.get("channel")
    if not channel:
        return None
    data = msg.get("data") or {}
    return EventFrame(
        channel=channel,
        event=data.get("event", ""),
        payload=data.get("payload") or {},
        sender_id=msg.get("sender_id", ""),
    )


# Inbound frame `type` values that carry channel data the SDK surfaces:
# application messages plus the full presence lifecycle.
_INBOUND_FRAME_TYPES = frozenset(
    {"message", "presence:state", "presence:join", "presence:leave", "presence:update"}
)


@dataclass(frozen=True)
class InboundEvent:
    """A raw inbound frame the SDK surfaces verbatim.

    `kind` is the frame `type` ("message" or any "presence:*"); `data` is the
    RAW inner data dict, NOT assumed to be {event, payload}."""

    kind: str
    channel: str
    sender_id: str
    data: dict[str, Any]


def parse_frame(msg: dict[str, Any]) -> InboundEvent | None:
    """Parse any surfaced inbound frame (message + presence) into an InboundEvent.

    Returns None for control/transport frames (pong, subscription_succeeded,
    errors, etc.)."""
    kind = msg.get("type")
    if kind not in _INBOUND_FRAME_TYPES:
        return None
    return InboundEvent(
        kind=kind,
        channel=msg.get("channel", ""),
        sender_id=msg.get("sender_id", ""),
        data=msg.get("data") or {},
    )
