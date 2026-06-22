from __future__ import annotations

import asyncio
import json

import pytest

from realtime_client import InboundEvent, RealtimeSubscriber


class FakeWS:
    """Minimal stand-in for a websockets connection."""

    _STOP = object()

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._inbox: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def feed(self, raw: str) -> None:
        await self._inbox.put(raw)

    def close_stream(self) -> None:
        """Simulate a clean remote close so the reader falls into reconnect."""
        self._inbox.put_nowait(self._STOP)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        item = await self._inbox.get()
        if item is self._STOP:
            raise StopAsyncIteration
        return item

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_subscribe_sends_frame_eagerly_and_yields_events():
    fake = FakeWS()

    async def fake_connect(url, subprotocols):
        return fake

    sub = RealtimeSubscriber(url="ws://x", token_provider=lambda: "tok", _connect=fake_connect)
    async with sub:
        stream = await sub.subscribe(["room1"])
        # Eager: the subscribe frame was sent before we iterate.
        assert json.loads(fake.sent[0]) == {"type": "subscribe", "channel": "room1"}

        await fake.feed(json.dumps(
            {"type": "message", "channel": "room1", "data": {"event": "msg", "payload": {"text": "hi"}}}
        ))
        evt = await asyncio.wait_for(anext(stream), timeout=1.0)
        assert evt.channel == "room1"
        assert evt.event == "msg"
        assert evt.payload == {"text": "hi"}


@pytest.mark.asyncio
async def test_subscribe_message_carries_sender_id():
    fake = FakeWS()

    async def fake_connect(url, subprotocols):
        return fake

    sub = RealtimeSubscriber(url="ws://x", token_provider=lambda: "tok", _connect=fake_connect)
    async with sub:
        stream = await sub.subscribe(["room1"])
        await fake.feed(json.dumps(
            {"type": "message", "channel": "room1", "sender_id": "u1",
             "data": {"event": "msg", "payload": {"text": "hi"}}}
        ))
        evt = await asyncio.wait_for(anext(stream), timeout=1.0)
        assert evt.sender_id == "u1"
        assert evt.event == "msg"
        assert evt.payload == {"text": "hi"}


@pytest.mark.asyncio
async def test_subscribe_raw_yields_presence_and_message():
    fake = FakeWS()

    async def fake_connect(url, subprotocols):
        return fake

    sub = RealtimeSubscriber(url="ws://x", token_provider=lambda: "tok", _connect=fake_connect)
    async with sub:
        stream = await sub.subscribe_raw(["presence-room1"])
        # Eager registration: subscribe frame sent before iterating.
        assert json.loads(fake.sent[0]) == {"type": "subscribe", "channel": "presence-room1"}

        await fake.feed(json.dumps(
            {"type": "presence:join", "channel": "presence-room1",
             "data": {"user_id": "u1", "connection_id": "c1", "info": {"status": "online"}}}
        ))
        await fake.feed(json.dumps(
            {"type": "message", "channel": "presence-room1", "sender_id": "u1",
             "data": {"event": "hello", "payload": {"x": 1}}}
        ))

        first = await asyncio.wait_for(anext(stream), timeout=1.0)
        assert isinstance(first, InboundEvent)
        assert first.kind == "presence:join"
        assert first.channel == "presence-room1"
        assert first.data["user_id"] == "u1"

        second = await asyncio.wait_for(anext(stream), timeout=1.0)
        assert second.kind == "message"
        assert second.sender_id == "u1"
        assert second.data == {"event": "hello", "payload": {"x": 1}}


@pytest.mark.asyncio
async def test_subscriber_passes_bearer_subprotocol():
    captured: dict = {}

    async def fake_connect(url, subprotocols):
        captured["subprotocols"] = subprotocols
        return FakeWS()

    sub = RealtimeSubscriber(url="ws://x", token_provider=lambda: "tok", _connect=fake_connect)
    async with sub:
        pass
    assert captured["subprotocols"] == ["Bearer.tok"]


@pytest.mark.asyncio
async def test_reconnect_resubscribes_after_clean_close():
    conns: list[FakeWS] = []

    async def fake_connect(url, subprotocols):
        ws = FakeWS()
        conns.append(ws)
        return ws

    sub = RealtimeSubscriber(url="ws://x", token_provider=lambda: "tok", _connect=fake_connect)
    async with sub:
        await sub.subscribe(["room1"])
        assert len(conns) == 1
        conns[0].close_stream()  # remote closed -> reconnect path (backoff ~0.1s)
        for _ in range(60):
            if len(conns) >= 2:
                break
            await asyncio.sleep(0.05)
        assert len(conns) >= 2, "subscriber did not reconnect"
        # the NEW connection re-sent the subscribe frame for the live channel
        assert json.loads(conns[1].sent[0]) == {"type": "subscribe", "channel": "room1"}


@pytest.mark.asyncio
async def test_from_env_builds_minter(monkeypatch, rsa_keypair):
    private_pem, _ = rsa_keypair
    monkeypatch.setenv("REALTIME_URL", "ws://x")
    monkeypatch.setenv("REALTIME_JWT_ISSUER", "example-api")
    monkeypatch.setenv("REALTIME_JWT_PRIVATE_KEY", private_pem)
    sub = RealtimeSubscriber.from_env(owner_service="svc")
    assert sub._url == "ws://x"
    token = sub._token_provider()
    assert token.count(".") == 2  # a JWT
