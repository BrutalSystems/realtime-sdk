import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from realtime_client import AnnouncementsApiError, AnnouncementsClient
from realtime_core import PLATFORM, Announcement, Severity

ENDS = datetime(2026, 10, 9, 19, 30, tzinfo=UTC)


def _ann(**over) -> dict:
    a = {
        "id": "01ABC", "revision": 1, "scope": "platform", "severity": "warning", "title": "T", "body": "B",
        "starts_at": "2026-10-09T19:00:00Z", "ends_at": "2026-10-09T19:30:00Z", "event_at": None,
        "dismissible": True, "created_at": "2026-10-09T19:00:00Z", "updated_at": "2026-10-09T19:00:00Z",
        "created_by": "brokenhip-be", "requested_by": None,
    }
    a.update(over)
    return a


def make(handler, **kw) -> AnnouncementsClient:
    kw.setdefault("token_provider", lambda: "tok")
    return AnnouncementsClient("http://rt", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)


@pytest.fixture(autouse=True)
def _no_prefix_env(monkeypatch):
    monkeypatch.delenv("RT_API_PREFIX", raising=False)


async def test_create_platform_posts_body_with_bearer():
    seen: dict = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(method=r.method, url=str(r.url), auth=r.headers.get("authorization"), body=json.loads(r.content))
        return httpx.Response(201, json=_ann())

    async with make(handler) as c:
        a = await c.create(scope=PLATFORM, severity=Severity.WARNING, title="T", body="B", ends_at=ENDS)
    assert isinstance(a, Announcement) and a.id == "01ABC"
    assert seen["method"] == "POST" and seen["url"] == "http://rt/api/v1/announcements"
    assert seen["auth"] == "Bearer tok"
    assert seen["body"] == {"scope": "_platform", "severity": "warning", "title": "T", "body": "B",
                            "ends_at": "2026-10-09T19:30:00+00:00"}


async def test_create_tenant_with_optionals():
    seen: dict = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(r.content)
        return httpx.Response(201, json=_ann(scope="tenant"))

    async with make(handler) as c:
        await c.create(scope="t1", severity=Severity.CRITICAL, title="T", body="B", ends_at=ENDS,
                       event_at=ENDS - timedelta(minutes=25), dismissible=False, requested_by="mike")
    assert seen["body"]["scope"] == "t1"
    assert seen["body"]["dismissible"] is False
    assert seen["body"]["requested_by"] == "mike"
    assert seen["body"]["event_at"] == "2026-10-09T19:05:00+00:00"


async def test_internal_key_header():
    seen: dict = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(key=r.headers.get("x-internal-api-key"), auth=r.headers.get("authorization"))
        return httpx.Response(200, json=[])

    async with make(handler, token_provider=None, internal_api_key="k") as c:
        assert await c.list(scope=PLATFORM) == []
    assert seen == {"key": "k", "auth": None}


async def test_update_list_clear_urls():
    calls: list[tuple[str, str]] = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append((r.method, str(r.url)))
        if r.method == "DELETE":
            return httpx.Response(200, json={"id": "01ABC", "scope": "tenant", "status": "cleared"})
        if r.method == "GET":
            return httpx.Response(200, json=[_ann(scope="tenant")])
        return httpx.Response(200, json=_ann(revision=2))

    async with make(handler) as c:
        assert (await c.update("01ABC", scope="t1", severity=Severity.INFO, title="T", body="B", ends_at=ENDS)).revision == 2
        assert len(await c.list(scope="t1")) == 1
        await c.clear("01ABC", scope="t1")
    assert calls == [
        ("PUT", "http://rt/api/v1/announcements/01ABC"),
        ("GET", "http://rt/api/v1/announcements?scope=t1"),
        ("DELETE", "http://rt/api/v1/announcements/01ABC?scope=t1"),
    ]


async def test_id_is_url_escaped():
    seen: dict = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["path"] = r.url.raw_path.decode()
        return httpx.Response(200, json={"id": "a/b", "scope": "tenant", "status": "cleared"})

    async with make(handler) as c:
        await c.clear("a/b c", scope="t1")
    assert seen["path"].startswith("/api/v1/announcements/a%2Fb%20c?")


async def test_error_carries_status_and_detail():
    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "Too many active announcements for this scope"})

    async with make(handler) as c:
        with pytest.raises(AnnouncementsApiError) as ei:
            await c.create(scope="t1", severity=Severity.INFO, title="T", body="B", ends_at=ENDS)
    assert ei.value.status == 409
    assert "Too many" in ei.value.detail


async def test_non_string_detail_is_json_encoded():
    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": [{"loc": ["body", "x"], "msg": "m"}]})

    async with make(handler) as c:
        with pytest.raises(AnnouncementsApiError) as ei:
            await c.create(scope="t1", severity=Severity.INFO, title="T", body="B", ends_at=ENDS)
    assert ei.value.status == 422
    assert json.loads(ei.value.detail)[0]["msg"] == "m"


async def test_naive_datetime_rejected_client_side():
    def handler(r: httpx.Request) -> httpx.Response:  # pragma: no cover — must not be called
        raise AssertionError("request sent")

    async with make(handler) as c:
        with pytest.raises(ValueError, match="timezone"):
            await c.create(scope="t1", severity=Severity.INFO, title="T", body="B", ends_at=datetime(2026, 10, 9, 19, 30))


def test_requires_exactly_one_auth():
    with pytest.raises(ValueError):
        AnnouncementsClient("http://rt")
    with pytest.raises(ValueError):
        AnnouncementsClient("http://rt", token_provider=lambda: "t", internal_api_key="k")


def test_unknown_fields_ignored():
    assert Announcement.model_validate(_ann(new_field="x")).id == "01ABC"


async def test_prefix_from_env(monkeypatch):
    monkeypatch.setenv("RT_API_PREFIX", "/api/rt/v1")
    seen: dict = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["url"] = str(r.url)
        return httpx.Response(200, json=[])

    async with make(handler) as c:
        await c.list(scope=PLATFORM)
    assert seen["url"] == "http://rt/api/rt/v1/announcements?scope=_platform"


async def test_injected_client_stays_open():
    injected = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    async with AnnouncementsClient("http://rt", token_provider=lambda: "t", client=injected) as c:
        await c.list(scope=PLATFORM)
    assert not injected.is_closed
    await injected.aclose()
