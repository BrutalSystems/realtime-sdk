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
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from realtime_core import bearer_subprotocol, publish_frame

logger = logging.getLogger(__name__)

# websockets keepalive: ping every 20s so a dead socket surfaces promptly.
_PING_INTERVAL = 20


async def _default_connect(url: str, subprotocols: list[str]) -> Any:
    import websockets

    return await websockets.connect(
        url, subprotocols=subprotocols or None, ping_interval=_PING_INTERVAL,
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
    token: str, client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    url = f"{base_url}/api/v1/channels/{channel}/messages"
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
