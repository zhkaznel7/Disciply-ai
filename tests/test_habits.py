import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app import habit_service
from app.models import UserSettings
from conftest import ORIGIN
from test_auth import credentials, login, register

PATH = "/api/v1/habits"


@pytest.fixture
async def account(client):
    data = credentials()
    profile = await register(client, data)
    await login(client, data)
    return client, profile


async def new_habit(client, **values):
    response = await client.post(PATH, json={"title": "Read", **values})
    assert response.status_code == 201, response.text
    return f"{PATH}/{response.json()['id']}", response.json()


async def test_habit_crud_log_counts_archive_and_restore(account):
    client, _ = account
    path, habit = await new_habit(client, target_count=3, preferred_time="07:30")
    assert habit["preferred_time"] == "07:30:00" and habit["frequency"] == "daily"
    assert (await client.get(path)).json() == habit

    response = await client.post(f"{path}/logs", json={"count": 2})
    assert response.status_code == 201, response.text
    log = response.json()
    log_path = f"{path}/logs/{log['id']}"
    assert (await client.get(f"{path}/stats")).json()["current_streak"] == 0
    assert (await client.post(f"{path}/logs", json={"count": 3})).status_code == 409
    assert (await client.patch(path, json={"target_count": 4})).status_code == 409
    updated = await client.patch(log_path, json={"count": 3})
    assert updated.status_code == 200 and updated.json()["count"] == 3
    stats = (await client.get(f"{path}/stats")).json()
    assert (stats["current_streak"], stats["longest_streak"], stats["last_completed_date"]) == (1, 1, log["date"])

    response = await client.get(f"{path}/logs", params={"from_date": log["date"], "to_date": log["date"]})
    assert response.json()["items"] == [updated.json()]
    assert (await client.get(f"{path}/logs?from_date=2030-02-02&to_date=2030-02-01")).status_code == 422

    archived = await client.patch(path, json={"status": "archived", "description": "Paused"})
    assert archived.status_code == 200 and archived.json()["archived_at"]
    assert (await client.get(f"{PATH}?status=archived")).json()["items"] == [archived.json()]
    assert (await client.delete(log_path)).status_code == 409
    assert (await client.get(f"{PATH}/summary")).json()["total_active_habits"] == 0
    restored = await client.patch(path, json={"status": "active"})
    assert restored.status_code == 200 and restored.json()["archived_at"] is None
    assert (await client.delete(log_path)).status_code == 204
    assert (await client.patch(path, json={"target_count": 4})).status_code == 200
    assert (await client.post(f"{path}/logs", json={"count": 4})).status_code == 201
    assert (await client.delete(path)).status_code == 204
    assert (await client.get(f"{path}/logs")).status_code == 404


async def test_concurrent_logs_and_analytics(account):
    client, _ = account
    path, habit = await new_habit(client, frequency="weekly", weekly_target=2, starts_on="2020-01-01")
    replies = await asyncio.gather(
        client.post(f"{path}/logs", json={}), client.post(f"{path}/logs", json={})
    )
    assert sorted(reply.status_code for reply in replies) == [201, 409]
    log = next(reply.json() for reply in replies if reply.status_code == 201)
    assert (await client.get(f"{path}/logs?limit=1")).json()["items"] == [log]
    today = (await client.get(f"{PATH}/today?limit=1")).json()["items"]
    assert today == [{"habit": habit, "count": 1, "scheduled": True, "completed": True}]
    summary = (await client.get(f"{PATH}/summary")).json()
    assert summary["today"] == {"completed": 1, "target": 1, "completion_percentage": 100.0}
    assert summary["completed_habits_today"] == 1
    for period in ("weekly", "monthly"):
        response = await client.get(f"{PATH}/{period}")
        assert response.status_code == 200
        assert response.json()["items"] == [{"habit": habit, "progress": summary[period]}]


async def test_timezone_leap_day_and_future_validation(account, app, monkeypatch):
    client, profile = account

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2024, 3, 1, 0, 30, tzinfo=UTC)
            return instant.astimezone(tz)

    monkeypatch.setattr(habit_service, "datetime", FrozenDateTime)
    async with app.state.sessions.begin() as db:
        await db.execute(update(UserSettings).where(UserSettings.user_id == UUID(profile["id"]))
                         .values(timezone="America/Los_Angeles"))
    path, habit = await new_habit(client, frequency="weekdays", weekdays=[3])
    assert habit["starts_on"] == "2024-02-29"
    initial = (await client.get(f"{path}/stats")).json()
    assert initial["timezone"] == "America/Los_Angeles"
    assert initial["last_completed_date"] is None and initial["completion_percentage"] == 0
    assert (await client.post(f"{path}/logs", json={"date": "2024-03-01"})).status_code == 422
    assert (await client.post(f"{path}/logs", json={"date": "2024-02-22"})).status_code == 422
    assert (await client.post(f"{path}/logs", json={})).json()["date"] == "2024-02-29"
    stats = (await client.get(f"{path}/stats")).json()
    assert stats["date"] == "2024-02-29" and stats["monthly"]["completion_percentage"] == 100


async def test_validation_csrf_and_isolation(account, app):
    client, _ = account
    for payload in (
        {"frequency": "weekly"}, {"frequency": "weekly", "weekly_target": 8},
        {"frequency": "weekdays", "weekdays": []}, {"frequency": "weekdays", "weekdays": [1, 1]},
        {"frequency": "daily", "weekdays": [0]}, {"weekly_target": 2},
        {"preferred_time": "08:15Z"}, {"target_count": 0},
    ):
        assert (await client.post(PATH, json={"title": "Invalid", **payload})).status_code == 422
    path, _ = await new_habit(client)
    other_path, _ = await new_habit(client, title="Same owner's different habit")
    log = (await client.post(f"{path}/logs", json={})).json()
    log_path = f"{path}/logs/{log['id']}"
    assert (await client.patch(f"{other_path}/logs/{log['id']}", json={"count": 2})).status_code == 404
    for payload in ({"count": 0}, {"count": 1_000_001}, {"date": "9999-12-31"}, {"user_id": "bad"}):
        assert (await client.post(f"{path}/logs", json=payload)).status_code == 422
    request = client.build_request("PATCH", log_path, json={"count": 2})
    del request.headers["Origin"]
    assert (await client.send(request)).status_code == 403

    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN,
                           headers={"Origin": ORIGIN}) as outsider:
        assert (await outsider.get(f"{PATH}/today")).status_code == 401
        data = credentials()
        await register(outsider, data)
        await login(outsider, data)
        assert (await outsider.get(PATH)).json()["items"] == []
        assert (await outsider.get(f"{PATH}/summary")).json()["total_active_habits"] == 0
        for inaccessible in (path, f"{path}/stats", f"{path}/logs"):
            assert (await outsider.get(inaccessible)).status_code == 404
        assert (await outsider.post(f"{path}/logs", json={})).status_code == 404
        assert (await outsider.patch(log_path, json={"count": 2})).status_code == 404
        assert (await outsider.delete(log_path)).status_code == 404
