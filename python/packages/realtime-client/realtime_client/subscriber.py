"""Realtime WebSocket subscriber.

Single WS connection multiplexed across subscribe() calls; each subscribe()
returns an async iterator filtered to its channel(s). Ported from an internal
realtime client — KEEP the reconnect/backoff/resubscribe
behavior and the eager subscribe() semantics. `_connect` is injectable for
tests; the env-var names in from_env are generic (not service-specific)."""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, cast

import websockets

from realtime_core import (
    EventFrame,
    InboundEvent,
    TokenMinter,
    bearer_subprotocol,
    parse_frame,
    subscribe_frame,
)

_BACKOFF_SECONDS = (0.1, 0.5, 1.0, 2.0, 5.0)


async def _default_connect(url: str, subprotocols: list[str]) -> Any:
    # websockets types `subprotocols` as Sequence[Subprotocol] (a NewType over
    # str); our plain list[str] is wire-identical, so cast rather than couple to
    # the websockets typing module.
    return await websockets.connect(url, subprotocols=cast("Any", subprotocols))


class RealtimeSubscriber:
    def __init__(
        self, *, url: str, token_provider: Callable[[], str],
        max_reconnect_attempts: int | None = 10,
        _connect: Callable[[str, list[str]], Awaitable[Any]] = _default_connect,
    ) -> None:
        self._url = url
        self._token_provider = token_provider
        self._max_reconnect_attempts = max_reconnect_attempts
        """Number of reconnect attempts before the reader gives up; ``None``
        reconnects indefinitely (right for a long-running daemon consumer that
        must never go permanently offline). Default 10 preserves prior
        behavior."""
        self._connect = _connect
        self._ws: Any | None = None
        self._queues: dict[str, asyncio.Queue[InboundEvent]] = {}
        self._reader_task: asyncio.Task[Any] | None = None

    @classmethod
    def from_env(cls, *, owner_service: str, tenant_id: str = "_org") -> RealtimeSubscriber:
        """Build a TokenMinter from generic env vars (REALTIME_URL,
        REALTIME_JWT_ISSUER, REALTIME_JWT_PRIVATE_KEY). The names are generic
        on purpose — a public SDK must not hardcode a single consumer's
        identity; each consumer wires its own env (or passes an explicit
        token_provider)."""
        url = os.environ.get("REALTIME_URL")
        issuer = os.environ.get("REALTIME_JWT_ISSUER")
        private_key = os.environ.get("REALTIME_JWT_PRIVATE_KEY")
        missing = [n for n, v in
                   (("REALTIME_URL", url), ("REALTIME_JWT_ISSUER", issuer),
                    ("REALTIME_JWT_PRIVATE_KEY", private_key)) if not v]
        if missing:
            raise RuntimeError(f"missing env vars for from_env: {', '.join(missing)}")
        assert url and issuer and private_key  # narrowed by the `missing` check above
        minter = TokenMinter(
            private_key=private_key, issuer=issuer,
            subject=owner_service, tenant_id=tenant_id,
        )
        return cls(url=url, token_provider=minter)

    async def __aenter__(self) -> RealtimeSubscriber:
        token = self._token_provider()
        self._ws = await self._connect(self._url, [bearer_subprotocol(token)])
        self._reader_task = asyncio.create_task(self._reader())
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except BaseException:
                pass
        if self._ws is not None:
            await self._ws.close()

    async def _reader(self) -> None:
        backoff_idx = 0
        while True:
            try:
                assert self._ws is not None
                async for raw in self._ws:
                    msg = json.loads(raw)
                    evt = parse_frame(msg)
                    if evt is None:
                        continue
                    q = self._queues.get(evt.channel)
                    if q is not None:
                        await q.put(evt)
                # remote closed cleanly — fall through to reconnect
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

            # reconnect path (ported verbatim)
            delay = _BACKOFF_SECONDS[min(backoff_idx, len(_BACKOFF_SECONDS) - 1)]
            backoff_idx += 1
            if (
                self._max_reconnect_attempts is not None
                and backoff_idx > self._max_reconnect_attempts
            ):
                return
            await asyncio.sleep(delay)
            new_ws = None
            try:
                token = self._token_provider()
                new_ws = await self._connect(self._url, [bearer_subprotocol(token)])
                for ch in list(self._queues.keys()):
                    await new_ws.send(json.dumps(subscribe_frame(ch)))
                self._ws = new_ws
                backoff_idx = 0
            except Exception:
                if new_ws is not None:
                    try:
                        await new_ws.close()
                    except BaseException:
                        pass
                continue

    async def _register(self, channels: list[str]) -> asyncio.Queue[InboundEvent]:
        """Install a queue for `channels` and send the subscribe frames.

        EAGER: the queue is installed and the subscribe frame is sent before
        this returns, so a caller can subscribe, trigger work, then iterate
        without losing an event published in between. The subscribe* methods
        must NOT be lazy generators (a generator body runs only on first
        __anext__, deferring registration)."""
        assert self._ws is not None
        queue: asyncio.Queue[InboundEvent] = asyncio.Queue()
        for ch in channels:
            self._queues[ch] = queue
            await self._ws.send(json.dumps(subscribe_frame(ch)))
        return queue

    async def subscribe(self, channels: list[str]) -> AsyncIterator[EventFrame]:
        """Register `channels` eagerly and iterate `message` frames as EventFrame.

        Message-only (presence and other inbound frames are dropped); use
        subscribe_raw for the full inbound protocol."""
        queue = await self._register(channels)
        return self._drain_events(channels, queue)

    async def subscribe_raw(self, channels: list[str]) -> AsyncIterator[InboundEvent]:
        """Register `channels` eagerly and iterate the full inbound protocol.

        Yields InboundEvent for `message` and every `presence:*` frame, sharing
        the same reader/reconnect/backoff/resubscribe path as subscribe()."""
        queue = await self._register(channels)
        return self._drain_raw(channels, queue)

    async def _drain_events(
        self, channels: list[str], queue: asyncio.Queue[InboundEvent],
    ) -> AsyncIterator[EventFrame]:
        try:
            while True:
                evt = await queue.get()
                if evt.kind != "message":
                    continue
                yield EventFrame(
                    channel=evt.channel,
                    event=evt.data.get("event", ""),
                    payload=evt.data.get("payload") or {},
                    sender_id=evt.sender_id,
                )
        finally:
            for ch in channels:
                self._queues.pop(ch, None)

    async def _drain_raw(
        self, channels: list[str], queue: asyncio.Queue[InboundEvent],
    ) -> AsyncIterator[InboundEvent]:
        try:
            while True:
                yield await queue.get()
        finally:
            for ch in channels:
                self._queues.pop(ch, None)
