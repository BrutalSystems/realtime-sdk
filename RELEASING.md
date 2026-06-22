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
