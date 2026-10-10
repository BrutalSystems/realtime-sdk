"""Client for the realtime service's /announcements API (`_system` callers only).

Both targets are first-class: pass scope=PLATFORM for every tenant, or a tenant
id for one tenant. There is no default."""

from __future__ import annotations

import builtins
import json
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
                raw = resp.json().get("detail", resp.text)
                detail = raw if isinstance(raw, str) else json.dumps(raw)
            except (ValueError, AttributeError):
                detail = resp.text
            raise AnnouncementsApiError(resp.status_code, detail)
        try:
            return resp.json()
        except ValueError:
            snippet = " ".join(resp.text.split())[:120]
            raise AnnouncementsApiError(
                resp.status_code,
                f"realtime returned {resp.status_code} but the body isn't JSON — check base_url: {snippet}",
            ) from None

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
        """Create an announcement.

        create is not idempotent: if a create times out it may still have been
        stored; list before retrying."""
        payload = self._body(scope, severity, title, body, ends_at, starts_at, event_at, dismissible, requested_by)
        return Announcement.model_validate(await self._send("POST", self._root, json=payload))

    async def update(self, announcement_id: str, *, scope: str, severity: Severity | str, title: str, body: str,
                     ends_at: datetime, starts_at: datetime | None = None, event_at: datetime | None = None,
                     dismissible: bool | None = None, requested_by: str | None = None) -> Announcement:
        """Replace an announcement (PUT; this is not a patch).

        update replaces the announcement - pass every field you want to keep;
        only starts_at is preserved when omitted. Omitted event_at and
        requested_by become null, and an omitted dismissible returns to the
        severity default."""
        payload = self._body(scope, severity, title, body, ends_at, starts_at, event_at, dismissible, requested_by)
        url = f"{self._root}/{quote(announcement_id, safe='')}"
        return Announcement.model_validate(await self._send("PUT", url, json=payload))

    async def clear(self, announcement_id: str, *, scope: str) -> None:
        await self._send("DELETE", f"{self._root}/{quote(announcement_id, safe='')}", params={"scope": scope})

    async def list(self, *, scope: str) -> builtins.list[Announcement]:
        return [Announcement.model_validate(a) for a in await self._send("GET", self._root, params={"scope": scope})]
