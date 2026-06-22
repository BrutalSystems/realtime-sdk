# Releasing

## Contract changes

The canonical fixtures in `contract/` are owned by the private service repo:
`scripts/export_contract.py` generates them and a golden test
pins them. To pull a contract change into the SDK:

1. In the service repo, update protocol/channels code, run
   `python scripts/export_contract.py`, commit the new `contract/*.json`.
2. In this repo: `cd python && make pull-contract`, then `make check`.
3. If anything turns red, the SDK encoders must be updated to match — that is
   the guardrail working. A breaking change is a coordinated major bump.

## Python (PyPI)

Versions are tagged `python-vX.Y.Z`. Bump the `version` in BOTH
`packages/realtime-core/pyproject.toml` and
`packages/realtime-client/pyproject.toml` (and the `==` pin between them), then
build and publish each package with your standard PyPI tooling.

## Changelog

### 0.3.0

Additive — two opt-in behaviors for a long-running daemon consumer that
dispatches command delivery. No breaking changes; existing defaults unchanged.

- `RealtimeSubscriber(..., max_reconnect_attempts=10)` — configurable reconnect.
  `None` reconnects indefinitely (a daemon never goes permanently offline);
  default 10 preserves prior behavior. Backoff and resubscribe-on-reconnect are
  unchanged.
- `RealtimePublisher.publish_now(channel, data, *, scope=None)` — strict,
  raising publish for delivery that must not be silently dropped. It ensures the
  connection (lazy connect / reconnect with a freshly minted token), sends the
  frame, and propagates any failure to the caller (no queue, no drop). Works
  without `start()`. Use a given instance for EITHER the best-effort queue
  (`start()` + `publish`/`publish_event`) OR `publish_now`, not both — they
  share the socket.
- `brutalsystems-realtime-core` bumped to 0.3.0 in lockstep (the pin stays
  matched); the changes are client-side.

### 0.2.0

Additive — surfaces the realtime service's full inbound protocol. No breaking
changes to `subscribe()` / `EventFrame`.

- `EventFrame` gains a `sender_id: str = ""` field, populated from the message
  frame's `sender_id`.
- New `realtime_core.InboundEvent(kind, channel, sender_id, data)` and
  `parse_frame()`, which parse `message` and every `presence:*` frame (the raw
  inner `data` dict is preserved verbatim); control/transport frames return
  `None`.
- New `RealtimeSubscriber.subscribe_raw(channels)` yields `InboundEvent` for the
  full inbound protocol, sharing the same reconnect/backoff/resubscribe path as
  `subscribe()`. `InboundEvent` is re-exported from `realtime_client`.

### 0.1.0

Initial release: WS subscriber + publisher, generic JWT minter, wire-contract
core.
