"""Client for the realtime service's /announcements API (`_system` callers only).

Both targets are first-class: pass scope=PLATFORM for every tenant, or a tenant
id for one tenant. There is no default."""

from __future__ import annotations

import builtins
from collections.abc import Callable
from datetime import datetime
from typing import Any, Self
from urllib.parse import quote

import httpx

from realtime_client.publisher import _resolve_api_prefix
from realtime_core import Announcement, Severity


class AnnouncementsApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"announcements API {status}: {detail}")
        self.status = status
        self.detail = detail


def _iso(name: str, value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.isoformat()


class AnnouncementsClient:
    def __init__(
        self, base_url: str, *, token_provider: Callable[[], str] | None = None,
        internal_api_key: str | None = None, api_prefix: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if (token_provider is None) == (internal_api_key is None):
            raise ValueError("pass exactly one of token_provider or internal_api_key")
        self._root = f"{base_url.rstrip('/')}{_resolve_api_prefix(api_prefix)}/announcements"
        self._token_provider = token_provider
        self._key = internal_api_key
        self._owns = client is None
        self._client = client or httpx.AsyncClient(timeout=10)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        # An injected client belongs to the caller; only close one we created.
        if self._owns:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        if self._token_provider is not None:
            return {"Authorization": f"Bearer {self._token_provider()}"}
        assert self._key is not None
        return {"X-Internal-Api-Key": self._key}

    async def _send(self, method: str, url: str, **kw: Any) -> Any:
        resp = await self._client.request(method, url, headers=self._headers(), **kw)
        if resp.is_error:
            try:
                detail = str(resp.json().get("detail", resp.text))
            except (ValueError, AttributeError):
                detail = resp.text
            raise AnnouncementsApiError(resp.status_code, detail)
        return resp.json()

    @staticmethod
    def _body(scope: str, severity: Severity | str, title: str, body: str, ends_at: datetime,
              starts_at: datetime | None, event_at: datetime | None, dismissible: bool | None,
              requested_by: str | None) -> dict[str, Any]:
        out: dict[str, Any] = {"scope": scope, "severity": str(severity), "title": title, "body": body,
                               "ends_at": _iso("ends_at", ends_at)}
        for k, v in (("starts_at", _iso("starts_at", starts_at)), ("event_at", _iso("event_at", event_at)),
                     ("dismissible", dismissible), ("requested_by", requested_by)):
            if v is not None:
                out[k] = v
        return out

    async def create(self, *, scope: str, severity: Severity | str, title: str, body: str, ends_at: datetime,
                     starts_at: datetime | None = None, event_at: datetime | None = None,
                     dismissible: bool | None = None, requested_by: str | None = None) -> Announcement:
        payload = self._body(scope, severity, title, body, ends_at, starts_at, event_at, dismissible, requested_by)
        return Announcement.model_validate(await self._send("POST", self._root, json=payload))

    async def update(self, announcement_id: str, *, scope: str, severity: Severity | str, title: str, body: str,
                     ends_at: datetime, starts_at: datetime | None = None, event_at: datetime | None = None,
                     dismissible: bool | None = None, requested_by: str | None = None) -> Announcement:
        payload = self._body(scope, severity, title, body, ends_at, starts_at, event_at, dismissible, requested_by)
        url = f"{self._root}/{quote(announcement_id, safe='')}"
        return Announcement.model_validate(await self._send("PUT", url, json=payload))

    async def clear(self, announcement_id: str, *, scope: str) -> None:
        await self._send("DELETE", f"{self._root}/{quote(announcement_id, safe='')}", params={"scope": scope})

    async def list(self, *, scope: str) -> builtins.list[Announcement]:
        return [Announcement.model_validate(a) for a in await self._send("GET", self._root, params={"scope": scope})]
