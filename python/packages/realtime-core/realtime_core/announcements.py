"""Announcement wire models — mirror the realtime service's
server/announcements/models.py (pinned by contract/announcements.json)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

PLATFORM = "_platform"
ANNOUNCEMENTS_CHANNEL = "announcements"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AnnouncementEvent(StrEnum):
    STATE = "announcement.state"
    UPSERT = "announcement.upsert"
    CLEAR = "announcement.clear"


class Announcement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    revision: int
    scope: str  # "tenant" | "platform"
    severity: Severity
    title: str
    body: str
    starts_at: datetime
    ends_at: datetime
    event_at: datetime | None = None
    dismissible: bool
    created_at: datetime
    updated_at: datetime
    created_by: str
    requested_by: str | None = None
