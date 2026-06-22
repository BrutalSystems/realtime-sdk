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


class ClosableWS(FakeWS):
    """FakeWS whose stream, once closed, stays closed.

    The base FakeWS blocks on re-iteration after the stream is drained; a real
    websockets connection raises immediately once closed. This models that so
    the reconnect loop keeps cycling (and the reader can reach its give-up
    branch) instead of hanging on a dead socket."""

    def __init__(self) -> None:
        super().__init__()
        self._stream_closed = False

    def close_stream(self) -> None:
        self._stream_closed = True
        super().close_stream()

    async def __anext__(self) -> str:
        if self._stream_closed and self._inbox.empty():
            raise StopAsyncIteration
        return await super().__anext__()


@pytest.mark.asyncio
async def test_gives_up_after_max_reconnect_attempts(monkeypatch):
    # Neutralize the real backoff sleeps so the test runs fast.
    real_sleep = asyncio.sleep

    async def fast_sleep(_):
        await real_sleep(0)

    monkeypatch.setattr("realtime_client.subscriber.asyncio.sleep", fast_sleep)

    attempts = {"n": 0}
    first = ClosableWS()

    async def fake_connect(url, subprotocols):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return first  # initial connection succeeds
        raise ConnectionError("down")  # every reconnect fails

    sub = RealtimeSubscriber(
        url="ws://x", token_provider=lambda: "tok",
        _connect=fake_connect, max_reconnect_attempts=1,
    )
    async with sub:
        await sub.subscribe(["room1"])
        first.close_stream()  # trigger the reconnect path
        # The reader must give up (task completes) rather than retry forever.
        await asyncio.wait_for(sub._reader_task, timeout=2.0)
    # 1 initial connect + exactly 1 reconnect attempt, then give up.
    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_reconnects_indefinitely_when_max_is_none(monkeypatch):
    real_sleep = asyncio.sleep

    async def fast_sleep(_):
        await real_sleep(0)

    monkeypatch.setattr("realtime_client.subscriber.asyncio.sleep", fast_sleep)

    first = ClosableWS()
    final = ClosableWS()
    attempts = {"n": 0}
    failures = 15  # well past the old hardcoded limit of 10

    async def fake_connect(url, subprotocols):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return first  # initial connection
        if attempts["n"] <= 1 + failures:
            raise ConnectionError("down")  # fail past the old limit of 10
        return final  # finally reconnect

    sub = RealtimeSubscriber(
        url="ws://x", token_provider=lambda: "tok",
        _connect=fake_connect, max_reconnect_attempts=None,
    )
    async with sub:
        await sub.subscribe(["room1"])
        first.close_stream()
        for _ in range(5000):
            if final.sent:
                break
            await asyncio.sleep(0)
        assert final.sent, "subscriber gave up instead of reconnecting forever"
        # the reconnect happened only after exceeding the old limit of 10
        assert attempts["n"] == 1 + failures + 1
        # and it resubscribed the live channel on the new connection
        assert json.loads(final.sent[0]) == {"type": "subscribe", "channel": "room1"}


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
