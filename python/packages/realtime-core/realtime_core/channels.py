# python/packages/realtime-core/realtime_core/channels.py
"""Channel-name grammar for the realtime service.

Mirrors the realtime server's channel-type rules. Channel type is determined by
prefix: `private-` -> PRIVATE, `presence-` -> PRESENCE (dash, NOT colon —
a `presence:` colon form is a PUBLIC channel and presence will not track it),
everything else -> PUBLIC."""
from __future__ import annotations

from enum import StrEnum
from fnmatch import fnmatch


class ChannelType(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    PRESENCE = "presence"


def channel_type(name: str) -> ChannelType:
    if name.startswith("private-"):
        return ChannelType.PRIVATE
    if name.startswith("presence-"):
        return ChannelType.PRESENCE
    return ChannelType.PUBLIC


def is_presence(name: str) -> bool:
    return channel_type(name) is ChannelType.PRESENCE


def matches(channel: str, pattern: str) -> bool:
    return fnmatch(channel, pattern)
