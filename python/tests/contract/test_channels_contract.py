# python/tests/contract/test_channels_contract.py
from __future__ import annotations

from realtime_core import ChannelType, channel_type, is_presence, matches


def test_channel_type_matches_fixture(channels_fixture):
    for case in channels_fixture["cases"]:
        assert channel_type(case["name"]).value == case["type"], case["name"]


def test_presence_requires_dash_not_colon():
    # The documented past production bug: presence is `presence-`, not `presence:`.
    assert is_presence("presence-room1") is True
    assert is_presence("presence:room1") is False
    assert channel_type("presence:room1") is ChannelType.PUBLIC


def test_matches_supports_wildcards():
    assert matches("worker.alpha.commands", "worker.*.commands")
    assert not matches("notify.events", "worker.*")
