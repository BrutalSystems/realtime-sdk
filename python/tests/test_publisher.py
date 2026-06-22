# python/tests/test_publisher.py
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from realtime_client import RealtimePublisher, rest_publish


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True


async def _wait(predicate, timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


@pytest.mark.asyncio
async def test_publish_sends_frame_via_worker():
    fake = FakeWS()

    async def fake_connect(url, subprotocols):
        return fake

    async with RealtimePublisher(url="ws://x", token_provider=lambda: "tok", _connect=fake_connect) as pub:
        await pub.publish("room1", {"event": "msg", "payload": {"text": "hi"}})
        await _wait(lambda: bool(fake.sent))
    assert json.loads(fake.sent[0]) == {
        "type": "publish", "channel": "room1",
        "data": {"event": "msg", "payload": {"text": "hi"}},
    }


@pytest.mark.asyncio
async def test_publish_event_wraps_event_payload():
    fake = FakeWS()

    async def fake_connect(url, subprotocols):
        return fake

    async with RealtimePublisher(url="ws://x", token_provider=lambda: "tok", _connect=fake_connect) as pub:
        await pub.publish_event("room1", "msg", {"text": "hi"})
        await _wait(lambda: bool(fake.sent))
    assert json.loads(fake.sent[0])["data"] == {"event": "msg", "payload": {"text": "hi"}}


@pytest.mark.asyncio
async def test_publish_drops_oldest_when_queue_full():
    # Worker not started, so the queue fills and the drop-oldest path runs.
    pub = RealtimePublisher(url="ws://x", token_provider=lambda: "t", max_queue_size=2)
    await pub.publish("a", {"n": 1})
    await pub.publish("b", {"n": 2})
    await pub.publish("c", {"n": 3})  # full -> drops oldest ("a")
    drained = []
    while not pub._queue.empty():
        drained.append(pub._queue.get_nowait())
    assert [f["channel"] for f in drained] == ["b", "c"]  # "a" dropped


@pytest.mark.asyncio
async def test_reconnects_and_remints_after_send_failure():
    mints: list[str] = []

    def minter() -> str:
        mints.append("x")
        return f"tok{len(mints)}"

    class FailingWS(FakeWS):
        async def send(self, data: str) -> None:
            raise RuntimeError("socket dead")

    seq = [FailingWS(), FakeWS()]
    conns: list[tuple] = []

    async def fake_connect(url, subprotocols):
        ws = seq[len(conns)]
        conns.append((ws, subprotocols))
        return ws

    pub = RealtimePublisher(url="ws://x", token_provider=minter, _connect=fake_connect)
    await pub.publish("room1", {"n": 1})   # will hit the failing socket and be dropped (best-effort)
    await pub.publish("room2", {"n": 2})   # drives a reconnect to the healthy socket
    await pub.start()
    try:
        await _wait(lambda: bool(seq[1].sent))
    finally:
        await pub.stop()
    assert len(conns) >= 2                  # reconnected after the failure
    assert len(mints) >= 2                  # token re-minted on the reconnect
    assert conns[1][1] == ["Bearer.tok2"]   # the re-minted token was used


@pytest.mark.asyncio
async def test_rest_publish_posts_typed_body_with_bearer():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "published", "channel": "room1"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await rest_publish(
            "http://api", "room1", {"x": 1}, token="tok", client=client,
        )
    assert captured["url"] == "http://api/api/v1/channels/room1/messages"
    assert captured["auth"] == "Bearer tok"
    assert captured["body"] == {"data": {"x": 1}}
    assert result == {"status": "published", "channel": "room1"}
