.PHONY: sync check test lint typecheck pull-contract

sync:
	uv sync

lint:
	uv run ruff check .

typecheck:
	uv run pyright packages/

test:
	uv run pytest

check: lint typecheck test

# Path to your local checkout of the private realtime service repo that owns
# the canonical contract fixtures. Defaults to a sibling checkout named
# `realtime`; override if yours lives elsewhere:
#   make pull-contract REALTIME_SERVICE_REPO=/path/to/service-repo
REALTIME_SERVICE_REPO ?= ../../realtime

# Re-vendor the canonical contract fixtures from the service repo (copy, never move).
pull-contract:
	cp $(REALTIME_SERVICE_REPO)/contract/frames.json ../contract/frames.json
	cp $(REALTIME_SERVICE_REPO)/contract/channels.json ../contract/channels.json
