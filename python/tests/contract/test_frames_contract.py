from __future__ import annotations

import pytest

from realtime_core import (
    EventFrame,
    InboundEvent,
    parse_frame,
    parse_inbound,
    ping_frame,
    publish_frame,
    subscribe_frame,
    unsubscribe_frame,
)

_TRACE_KEYS = ("traceparent", "tracestate")


def _without_trace(frame: dict) -> dict:
    return {k: v for k, v in frame.items() if k not in _TRACE_KEYS}


def test_client_frames_match_fixture(frames_fixture):
    client = frames_fixture["client"]
    assert subscribe_frame("room1") == client["subscribe"]
    assert unsubscribe_frame("room1") == client["unsubscribe"]
    # The fixture shows a traced publish; an un-traced publish carries no trace keys (0.5.0).
    assert publish_frame("room1", {"event": "msg", "payload": {"text": "hi"}}) == _without_trace(client["publish"])
    assert ping_frame() == client["ping"]


def test_parse_inbound_message_frame(frames_fixture):
    msg = frames_fixture["server"]["message"]
    evt = parse_inbound(msg)
    assert evt == EventFrame(channel="room1", event="msg", payload={"text": "hi"}, sender_id="u1")
    # EventFrame now carries sender_id straight from the message fixture.
    assert evt is not None
    assert evt.sender_id == "u1"


def test_parse_frame_message_carries_sender_and_raw_data(frames_fixture):
    msg = frames_fixture["server"]["message"]
    evt = parse_frame(msg)
    assert evt == InboundEvent(
        kind="message",
        channel="room1",
        sender_id="u1",
        data=msg["data"],
    )
    # `data` is the RAW inner dict, not {event, payload}-unpacked.
    assert evt is not None
    assert evt.sender_id == "u1"
    assert evt.data == {"event": "msg", "payload": {"text": "hi"}}


@pytest.mark.parametrize(
    "kind",
    ["presence:state", "presence:join", "presence:leave", "presence:update"],
)
def test_parse_frame_presence_frames(frames_fixture, kind):
    msg = frames_fixture["server"][kind]
    evt = parse_frame(msg)
    assert evt is not None
    assert evt.kind == kind
    assert evt.channel == "presence-room1"
    assert evt.data == msg["data"]


def test_parse_frame_presence_state_exposes_members(frames_fixture):
    evt = parse_frame(frames_fixture["server"]["presence:state"])
    assert evt is not None
    members = evt.data["members"]
    assert members == [{"connection_id": "c1", "info": {"status": "online"}, "user_id": "u1"}]


def test_parse_frame_ignores_control_frames(frames_fixture):
    server = frames_fixture["server"]
    for key in ("pong", "subscription_succeeded", "subscription_error", "unsubscribed", "error"):
        assert parse_frame(server[key]) is None


def test_parse_inbound_ignores_non_message_frames(frames_fixture):
    # subscription_succeeded etc. are control frames, not events.
    assert parse_inbound(frames_fixture["server"]["subscription_succeeded"]) is None
    assert parse_inbound(frames_fixture["server"]["pong"]) is None


def test_publish_frame_includes_scope_when_given():
    frame = publish_frame("room1", {"x": 1}, scope="_platform")
    assert frame == {"type": "publish", "channel": "room1", "data": {"x": 1}, "scope": "_platform"}


def test_fixture_pins_trace_keys_as_top_level_siblings(frames_fixture):
    for frame in (frames_fixture["client"]["publish"], frames_fixture["server"]["message"]):
        assert frame["traceparent"].startswith("00-")
        assert "traceparent" not in frame["data"]
