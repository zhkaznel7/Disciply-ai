import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app import focus_analytics, focus_service
from app.models import UserSettings
from conftest import ORIGIN
from test_auth import credentials, login, register

API = "/api/v1"
FOCUS = f"{API}/focus"
SESSIONS = f"{FOCUS}/sessions"
MINUTE = 60_000_000


@pytest.fixture
async def account(client):
    data = credentials()
    profile = await register(client, data)
    await login(client, data)
    return client, profile


@pytest.fixture
def clock(monkeypatch):
    value = [datetime(2025, 11, 2, 3, 30, tzinfo=UTC)]
    for module in (focus_service, focus_analytics):
        monkeypatch.setattr(module, "now_utc", lambda: value[0])
    return value


async def start(client, **payload):
    response = await client.post(SESSIONS, json=payload)
    assert response.status_code == 201, response.text
    return f"{SESSIONS}/{response.json()['id']}", response.json()


async def action(client, path, name):
    response = await client.post(f"{path}/{name}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_lifecycle_duration_and_invalid_transitions(account, clock):
    client, _ = account
    assert (await client.get(f"{SESSIONS}/current")).json() is None
    path, session = await start(client, planned_minutes=12)
    assert session["status"] == "active" and session["planned_minutes"] == 12
    assert session["actual_focused_microseconds"] == 0
    assert (await client.post(f"{path}/resume")).status_code == 409

    clock[0] += timedelta(minutes=2, microseconds=13)
    paused = await action(client, path, "pause")
    assert paused["actual_focused_microseconds"] == 2 * MINUTE + 13
    assert (await client.post(SESSIONS, json={})).status_code == 409
    clock[0] += timedelta(minutes=3)
    current = (await client.get(f"{SESSIONS}/current")).json()
    assert current["status"] == "paused" and current["total_paused_microseconds"] == 3 * MINUTE
    await action(client, path, "resume")
    clock[0] += timedelta(minutes=2)
    finished = await action(client, path, "complete")
    assert finished["status"] == "completed"
    assert finished["actual_focused_microseconds"] == 4 * MINUTE + 13
    assert finished["total_paused_microseconds"] == 3 * MINUTE
    for name in ("complete", "resume", "pause", "cancel"):
        assert (await client.post(f"{path}/{name}")).status_code == 409

    other, _ = await start(client)
    clock[0] += timedelta(minutes=1)
    await action(client, other, "pause")
    clock[0] += timedelta(minutes=1)
    cancelled = await action(client, other, "cancel")
    assert cancelled["status"] == "cancelled" and cancelled["actual_focused_microseconds"] == MINUTE
    assert (await client.post(f"{other}/pause")).status_code == 409
    assert (await client.get(path)).json() == finished
    history = (await client.get(SESSIONS, params={"status": "completed", "limit": 1})).json()
    assert history["items"] == [finished]
    assert (await client.get(f"{FOCUS}/summary")).json()["today"]["focus_microseconds"] == 4 * MINUTE + 13


async def test_concurrent_starts_and_completions(account):
    client, _ = account
    starts = await asyncio.gather(client.post(SESSIONS, json={}), client.post(SESSIONS, json={}))
    assert sorted(response.status_code for response in starts) == [201, 409]
    session = next(response.json() for response in starts if response.status_code == 201)
    path = f"{SESSIONS}/{session['id']}"
    completions = await asyncio.gather(
        client.post(f"{path}/complete"), client.post(f"{path}/complete")
    )
    assert sorted(response.status_code for response in completions) == [200, 409]
    assert (await client.get(f"{SESSIONS}/current")).json() is None


async def test_pomodoro_recommendation_and_break_time(account, clock):
    client, _ = account
    summary = f"{FOCUS}/summary"
    assert (await client.get(summary)).json()["pomodoro"]["next_session_type"] == "focus"
    for expected in range(1, 5):
        path, session = await start(client)
        assert session["planned_minutes"] == 25
        clock[0] += timedelta(minutes=1)
        await action(client, path, "complete")
        cycle = (await client.get(summary)).json()["pomodoro"]
        assert cycle["completed_focus_since_long_break"] == expected
        assert cycle["next_session_type"] == ("short_break" if expected < 4 else "long_break")
        if expected == 1:
            path, session = await start(client, session_type="short_break")
            assert session["planned_minutes"] == 5
            clock[0] += timedelta(minutes=2)
            result = await action(client, path, "complete")
            assert result["actual_focused_microseconds"] == 0
            assert result["actual_running_microseconds"] == 2 * MINUTE
    path, session = await start(client, session_type="long_break")
    assert session["planned_minutes"] == 15
    clock[0] += timedelta(minutes=3)
    await action(client, path, "complete")
    result = (await client.get(summary)).json()
    assert result["pomodoro"]["completed_focus_since_long_break"] == 0
    assert result["pomodoro"]["next_session_type"] == "focus"
    assert result["today"]["focus_minutes"] == 4
    assert result["today"]["break_minutes"] == 5


async def test_local_midnight_dst_and_task_deletion(account, app, clock):
    client, profile = account
    async with app.state.sessions.begin() as db:
        await db.execute(update(UserSettings).where(UserSettings.user_id == UUID(profile["id"]))
                         .values(timezone="America/New_York"))
    task = (await client.post(f"{API}/tasks", json={"title": "Owned"})).json()
    path, _ = await start(client, task_id=task["id"])
    clock[0] += timedelta(minutes=45)
    await action(client, path, "pause")
    clock[0] += timedelta(minutes=75)
    await action(client, path, "resume")
    clock[0] += timedelta(hours=2)
    await action(client, path, "complete")

    nov1 = (await client.get(f"{FOCUS}/daily?date=2025-11-01")).json()
    nov2 = (await client.get(f"{FOCUS}/daily?date=2025-11-02")).json()
    assert nov1["timezone"] == "America/New_York"
    assert (nov1["focus_minutes"], nov2["focus_minutes"]) == (30, 135)
    assert (nov1["completed_focus_sessions"], nov2["completed_focus_sessions"]) == (0, 1)
    assert nov2["average_completed_focus_minutes"] == 165
    weekly = (await client.get(f"{FOCUS}/weekly?date=2025-11-02")).json()
    monthly = (await client.get(f"{FOCUS}/monthly?date=2025-11-02")).json()
    assert len(weekly["days"]) == 7 and len(monthly["days"]) == 30
    assert weekly["focus_minutes"] == monthly["focus_minutes"] == 165
    history = (await client.get(f"{SESSIONS}?from_date=2025-11-01&to_date=2025-11-01")).json()
    assert len(history["items"]) == 1
    tasks = (await client.get(f"{FOCUS}/by-task")).json()["items"]
    assert tasks == [{"task_id": task["id"], "focus_minutes": 165, "focus_microseconds": 165 * MINUTE}]
    assert (await client.get(f"{API}/tasks/{task['id']}")).json()["status"] == "open"
    assert (await client.delete(f"{API}/tasks/{task['id']}")).status_code == 204
    assert (await client.get(path)).json()["task_id"] is None
    assert (await client.get(f"{FOCUS}/by-task")).json()["items"][0]["task_id"] is None


async def test_auth_csrf_input_and_owner_isolation(account, app):
    client, _ = account
    task = (await client.post(f"{API}/tasks", json={"title": "Private"})).json()
    path, _ = await start(client, task_id=task["id"])
    request = client.build_request("POST", f"{path}/pause")
    del request.headers["Origin"]
    assert (await client.send(request)).status_code == 403
    for body in ({"planned_minutes": 0}, {"planned_minutes": 1441}, {"elapsed_seconds": 42},
                 {"user_id": "bad"}, {"session_type": "invalid"}):
        assert (await client.post(SESSIONS, json=body)).status_code == 422
    assert (await client.get(f"{FOCUS}/daily?date=2025-02-30")).status_code == 422
    assert (await client.get(f"{FOCUS}/by-task?from_date=2020-01-01&to_date=2025-01-01")).status_code == 422

    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN,
                           headers={"Origin": ORIGIN}) as other:
        assert (await other.get(f"{FOCUS}/summary")).status_code == 401
        data = credentials()
        await register(other, data)
        await login(other, data)
        assert (await other.get(path)).status_code == 404
        assert (await other.post(f"{path}/complete")).status_code == 404
        assert (await other.post(SESSIONS, json={"task_id": task["id"]})).status_code == 404
        assert (await other.get(SESSIONS)).json()["items"] == []
        assert (await other.get(f"{FOCUS}/summary")).json()["today"]["focus_minutes"] == 0
