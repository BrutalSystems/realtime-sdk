# python/packages/realtime-client/realtime_client/publisher.py
"""Realtime publisher.

Best-effort background publisher ported from an internal best-effort publisher
— KEEP the bounded queue with drop-oldest, the worker
task, lazy reconnect with token re-mint, and the ping_interval keepalive.
publish() never blocks the caller. `rest_publish` is a thin typed helper for
the REST endpoint — a stand-in until openapi-python-client codegen lands."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx

from realtime_core import bearer_subprotocol, publish_frame

logger = logging.getLogger(__name__)

_TRACE_KEYS = ("traceparent", "tracestate")


def _inject_trace_context(frame: dict[str, Any]) -> None:
    """Stamp the active span's W3C trace context onto a WebSocket publish frame
    as top-level ``traceparent``/``tracestate`` siblings, in place.

    The realtime server reads these as the parent of its publish/deliver spans
    and re-injects them downstream, so publisher -> realtime -> subscriber is one
    linked trace. WebSocket-only: REST publishes propagate via the HTTP
    ``traceparent`` header instead (handled by httpx instrumentation).

    OpenTelemetry is an OPTIONAL dependency of this SDK — when it isn't installed
    the import fails and this is a no-op. The configured W3C propagator also
    writes nothing for an absent/invalid span context (tracing off, no active
    span, or ``OTEL_SDK_DISABLED``), so an un-traced publish injects no keys and
    the frame stays byte-identical to the pre-OTel wire format. Must run at
    enqueue/publish time — the originating span has ended by the time the
    background worker sends."""
    try:
        from opentelemetry.propagate import inject
    except ImportError:
        return
    carrier: dict[str, str] = {}
    inject(carrier)
    for key in _TRACE_KEYS:
        if carrier.get(key):
            frame[key] = carrier[key]


# Historical default — the server mounts its REST routers here unless RT_API_PREFIX
# overrides it. Kept identical to the server's default so behavior is byte-for-byte
# unchanged when neither side configures a prefix.
_DEFAULT_API_PREFIX = "/api/v1"


def _resolve_api_prefix(api_prefix: str | None) -> str:
    """Resolve + validate the REST API prefix.

    Mirrors the server's RT_API_PREFIX handling so the client auto-aligns: an
    explicit arg wins, else the ``RT_API_PREFIX`` env var, else the historical
    default. Must start with ``/``; a trailing slash is stripped.
    """
    prefix = api_prefix if api_prefix is not None else os.environ.get("RT_API_PREFIX", _DEFAULT_API_PREFIX)
    if not prefix.startswith("/"):
        raise ValueError(f"api_prefix must start with '/': {prefix!r}")
    prefix = prefix.rstrip("/")
    if not prefix:
        raise ValueError("api_prefix must not be '/' or empty")
    return prefix

# websockets keepalive: ping every 20s so a dead socket surfaces promptly.
_PING_INTERVAL = 20


async def _default_connect(url: str, subprotocols: list[str]) -> Any:
    import websockets

    # websockets types `subprotocols` as Sequence[Subprotocol] (a NewType over
    # str); our plain list[str] is wire-identical, so cast rather than couple to
    # the websockets typing module.
    return await websockets.connect(
        url, subprotocols=cast("Any", subprotocols or None), ping_interval=_PING_INTERVAL,
    )


class RealtimePublisher:
    def __init__(
        self, *, url: str, token_provider: Callable[[], str] | None = None,
        max_queue_size: int = 1000,
        _connect: Callable[[str, list[str]], Awaitable[Any]] = _default_connect,
    ) -> None:
        self._url = url
        self._token_provider = token_provider
        self._connect = _connect
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue_size)
        self._worker_task: asyncio.Task[Any] | None = None
        self._stop = asyncio.Event()
        self._ws: Any | None = None

    async def __aenter__(self) -> RealtimePublisher:
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop()

    async def start(self) -> None:
        self._stop.clear()
        self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        self._stop.set()
        if self._worker_task is not None:
            await self._worker_task
            self._worker_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def publish(self, channel: str, data: dict[str, Any], *, scope: str | None = None) -> None:
        """Non-blocking enqueue. On a full queue, drop the OLDEST event."""
        frame = publish_frame(channel, data, scope=scope)
        _inject_trace_context(frame)
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()  # drop oldest
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(frame)
            except asyncio.QueueFull:
                logger.warning("realtime publish queue full; dropped event")

    async def publish_event(
        self, channel: str, event: str, payload: dict[str, Any], *, scope: str | None = None,
    ) -> None:
        """Convenience matching the prior internal publisher signature."""
        await self.publish(channel, {"event": event, "payload": payload}, scope=scope)

    async def publish_now(
        self, channel: str, data: dict[str, Any], *, scope: str | None = None,
    ) -> None:
        """Strict publish for delivery that must NOT be silently dropped.

        Ensures the connection (lazy connect / reconnect with a freshly minted
        token, via the same _ensure_connected path as the worker), sends the
        publish frame, and PROPAGATES any exception — no queue, no drop, no
        swallow. The caller learns immediately if delivery could not be
        attempted or sent (so it can, e.g., fail the job). Use this for command
        delivery; use publish()/publish_event() for best-effort event broadcast.

        Works WITHOUT start() — no background worker is needed; publish_now
        self-manages the connection. A given RealtimePublisher instance should
        use EITHER the best-effort queue (start() + publish/publish_event) OR
        publish_now — not both concurrently, since they share the same socket.
        """
        frame = publish_frame(channel, data, scope=scope)
        _inject_trace_context(frame)
        try:
            await self._send_one(frame)
        except Exception:
            # Drop the socket so the NEXT publish_now reconnects + re-mints
            # (same recovery as the worker), then re-raise — strict delivery
            # means the caller MUST learn that this send failed.
            if self._ws is not None:
                try:
                    await self._ws.close()
                except Exception:
                    pass
                self._ws = None
            raise

    async def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                frame = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except TimeoutError:
                continue
            try:
                await self._send_one(frame)
            except Exception as exc:
                # Best-effort: log + drop the socket; the next event reconnects
                # (and re-mints the token) via _ensure_connected.
                logger.warning("realtime publish failed: %s", exc)
                if self._ws is not None:
                    try:
                        await self._ws.close()
                    except Exception:
                        pass
                    self._ws = None

    async def _ensure_connected(self) -> None:
        if self._ws is not None:
            return
        subprotocols: list[str] = []
        if self._token_provider is not None:
            subprotocols = [bearer_subprotocol(self._token_provider())]
        self._ws = await self._connect(self._url, subprotocols)

    async def _send_one(self, frame: dict[str, Any]) -> None:
        await self._ensure_connected()
        assert self._ws is not None
        await self._ws.send(json.dumps(frame))


async def rest_publish(
    base_url: str, channel: str, data: dict[str, Any], *,
    token: str, api_prefix: str | None = None, client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    prefix = _resolve_api_prefix(api_prefix)
    url = f"{base_url}{prefix}/channels/{channel}/messages"
    headers = {"Authorization": f"Bearer {token}"}
    owns = client is None
    client = client or httpx.AsyncClient()
    try:
        resp = await client.post(url, json={"data": data}, headers=headers)
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns:
            await client.aclose()
