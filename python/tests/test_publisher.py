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
async def test_publish_injects_trace_context_when_span_active():
    """The server links publisher -> realtime -> subscriber into one trace by
    reading top-level ``traceparent``/``tracestate`` siblings off the WS frame.
    Context must be captured at publish() time (the originating span has ended by
    the time the worker sends), so assert the sent frame carries a valid W3C
    ``traceparent`` when a recording span is active."""
    pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry.sdk.trace import TracerProvider

    tracer = TracerProvider().get_tracer("test")
    fake = FakeWS()

    async def fake_connect(url, subprotocols):
        return fake

    async with RealtimePublisher(url="ws://x", token_provider=lambda: "tok", _connect=fake_connect) as pub:
        with tracer.start_as_current_span("run.started"):
            await pub.publish("room1", {"event": "msg", "payload": {}})
        await _wait(lambda: bool(fake.sent))

    frame = json.loads(fake.sent[0])
    tp = frame.get("traceparent")
    assert tp is not None, "expected traceparent injected as a top-level frame sibling"
    version, trace_id, span_id, flags = tp.split("-")
    assert (len(version), len(trace_id), len(span_id), len(flags)) == (2, 32, 16, 2)
    # Trace keys live at the top level, never inside data (realtime contract).
    assert "traceparent" not in frame["data"]


@pytest.mark.asyncio
async def test_publish_omits_trace_context_without_active_span():
    """No active span (tracing off / OTEL_SDK_DISABLED / OTel not installed) =>
    the propagator writes nothing, so the frame stays byte-identical to the
    pre-OTel wire format: no ``traceparent``/``tracestate`` keys. Guards against
    ever unconditionally stamping the frame."""
    fake = FakeWS()

    async def fake_connect(url, subprotocols):
        return fake

    async with RealtimePublisher(url="ws://x", token_provider=lambda: "tok", _connect=fake_connect) as pub:
        await pub.publish("room1", {"event": "msg", "payload": {"text": "hi"}})
        await _wait(lambda: bool(fake.sent))

    frame = json.loads(fake.sent[0])
    assert "traceparent" not in frame
    assert "tracestate" not in frame
    assert frame == {
        "type": "publish", "channel": "room1",
        "data": {"event": "msg", "payload": {"text": "hi"}},
    }


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
async def test_publish_now_sends_frame_without_worker():
    # No start() — publish_now self-manages the connection.
    fake = FakeWS()

    async def fake_connect(url, subprotocols):
        return fake

    pub = RealtimePublisher(url="ws://x", token_provider=lambda: "tok", _connect=fake_connect)
    await pub.publish_now("room1", {"event": "msg", "payload": {"text": "hi"}})
    assert json.loads(fake.sent[0]) == {
        "type": "publish", "channel": "room1",
        "data": {"event": "msg", "payload": {"text": "hi"}},
    }


@pytest.mark.asyncio
async def test_publish_now_raises_when_connect_fails():
    async def fake_connect(url, subprotocols):
        raise ConnectionError("cannot connect")

    pub = RealtimePublisher(url="ws://x", token_provider=lambda: "tok", _connect=fake_connect)
    # Strict delivery: the failure MUST propagate, not be swallowed.
    with pytest.raises(ConnectionError):
        await pub.publish_now("room1", {"n": 1})


@pytest.mark.asyncio
async def test_publish_now_raises_when_send_fails():
    class FailingWS(FakeWS):
        async def send(self, data: str) -> None:
            raise RuntimeError("socket dead")

    fake = FailingWS()

    async def fake_connect(url, subprotocols):
        return fake

    pub = RealtimePublisher(url="ws://x", token_provider=lambda: "tok", _connect=fake_connect)
    with pytest.raises(RuntimeError):
        await pub.publish_now("room1", {"n": 1})


@pytest.mark.asyncio
async def test_publish_now_mints_token_on_fresh_connect():
    mints: list[str] = []

    def minter() -> str:
        mints.append("x")
        return f"tok{len(mints)}"

    captured: list[list[str]] = []

    async def fake_connect(url, subprotocols):
        captured.append(subprotocols)
        return FakeWS()

    pub = RealtimePublisher(url="ws://x", token_provider=minter, _connect=fake_connect)
    await pub.publish_now("room1", {"n": 1})
    assert mints == ["x"]                      # minted once for the fresh connect
    assert captured[0] == ["Bearer.tok1"]      # the freshly minted token was used


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


@pytest.fixture
def _clear_rt_api_prefix(monkeypatch):
    """Isolate prefix tests from any RT_API_PREFIX in the dev/CI environment."""
    monkeypatch.delenv("RT_API_PREFIX", raising=False)


def _url_capture_client() -> tuple[dict, httpx.AsyncClient]:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"status": "published", "channel": "room1"})

    return captured, httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_rest_publish_default_prefix(_clear_rt_api_prefix):
    captured, client = _url_capture_client()
    async with client:
        await rest_publish("http://api", "room1", {"x": 1}, token="tok", client=client)
    assert captured["url"] == "http://api/api/v1/channels/room1/messages"


@pytest.mark.asyncio
async def test_rest_publish_explicit_prefix(_clear_rt_api_prefix):
    captured, client = _url_capture_client()
    async with client:
        await rest_publish(
            "http://api", "room1", {"x": 1}, token="tok", api_prefix="/api/rt/v1", client=client,
        )
    assert captured["url"] == "http://api/api/rt/v1/channels/room1/messages"


@pytest.mark.asyncio
async def test_rest_publish_prefix_from_env(monkeypatch):
    monkeypatch.setenv("RT_API_PREFIX", "/api/rt/v1")
    captured, client = _url_capture_client()
    async with client:
        await rest_publish("http://api", "room1", {"x": 1}, token="tok", client=client)
    assert captured["url"] == "http://api/api/rt/v1/channels/room1/messages"


@pytest.mark.asyncio
async def test_rest_publish_explicit_arg_overrides_env(monkeypatch):
    monkeypatch.setenv("RT_API_PREFIX", "/api/env/v1")
    captured, client = _url_capture_client()
    async with client:
        await rest_publish(
            "http://api", "room1", {"x": 1}, token="tok", api_prefix="/api/explicit/v1", client=client,
        )
    assert captured["url"] == "http://api/api/explicit/v1/channels/room1/messages"


@pytest.mark.asyncio
async def test_rest_publish_trailing_slash_normalized(_clear_rt_api_prefix):
    captured, client = _url_capture_client()
    async with client:
        await rest_publish(
            "http://api", "room1", {"x": 1}, token="tok", api_prefix="/api/rt/v1/", client=client,
        )
    assert captured["url"] == "http://api/api/rt/v1/channels/room1/messages"


@pytest.mark.asyncio
async def test_rest_publish_missing_leading_slash_rejected(_clear_rt_api_prefix):
    with pytest.raises(ValueError):
        await rest_publish("http://api", "room1", {"x": 1}, token="tok", api_prefix="api/v1")
