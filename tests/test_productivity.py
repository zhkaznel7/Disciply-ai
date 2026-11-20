import asyncio
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app import focus_service, productivity_service
from app.models import Habit, HabitLog, Task, UserSettings
from app.productivity_service import score
from conftest import ORIGIN
from test_auth import credentials, login, register

API = "/api/v1"
REPORT = f"{API}/analytics"
REFLECTION = f"{API}/reflections"


@pytest.fixture
async def account(client):
    data = credentials()
    profile = await register(client, data)
    await login(client, data)
    return client, UUID(profile["id"])


def test_discipline_score_is_bounded_and_explainable():
    assert score((0, 0), (0, 0), 0).value is None
    assert score((1, 1), (0, 0), 0).value == 67
    focus_only = score((0, 0), (0, 0), 30 * 60_000_000)
    assert focus_only.value == 100
    assert not focus_only.tasks.applicable and not focus_only.habits.applicable
    assert focus_only.focus.completion_percentage == 100


async def test_daily_range_use_local_task_habit_and_focus_rules(account, app, monkeypatch):
    client, owner = account
    day = date(2025, 1, 8)
    instant = [datetime(2025, 1, 9, 4, 55, tzinfo=UTC)]
    monkeypatch.setattr(focus_service, "now_utc", lambda: instant[0])
    monkeypatch.setattr(productivity_service, "now_utc", lambda: instant[0])
    async with app.state.sessions.begin() as db:
        await db.execute(update(UserSettings).where(UserSettings.user_id == owner)
                         .values(timezone="America/New_York"))
        db.add_all([
            Task(user_id=owner, title="Done before local midnight", scheduled_on=day,
                 completed_at=datetime(2025, 1, 9, 4, 0, tzinfo=UTC)),
            Task(user_id=owner, title="Done after local midnight", scheduled_on=day,
                 completed_at=datetime(2025, 1, 9, 5, 0, tzinfo=UTC)),
            Task(user_id=owner, title="Unscheduled",
                 completed_at=datetime(2025, 1, 8, 12, 0, tzinfo=UTC)),
        ])
        daily = Habit(user_id=owner, title="Daily", starts_on=day, target_count=2)
        missed = Habit(user_id=owner, title="Missed", starts_on=day)
        weekly = Habit(user_id=owner, title="Quota reached", starts_on=date(2025, 1, 6),
                       frequency="weekly", weekly_target=1)
        weekday = Habit(user_id=owner, title="Monday only", starts_on=day,
                        frequency="weekdays", weekday_mask=1)
        db.add_all([daily, missed, weekly, weekday])
        await db.flush()
        db.add_all([
            HabitLog(user_id=owner, habit_id=daily.id, logged_on=day, count=2),
            HabitLog(user_id=owner, habit_id=weekly.id, logged_on=date(2025, 1, 6)),
        ])

    started = await client.post(f"{API}/focus/sessions", json={})
    assert started.status_code == 201
    instant[0] = datetime(2025, 1, 9, 5, 10, tzinfo=UTC)
    finished = await client.post(f"{API}/focus/sessions/{started.json()['id']}/complete")
    assert finished.status_code == 200
    result = await client.get(f"{REPORT}/daily?date={day}")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["timezone"] == "America/New_York"
    assert data["tasks"] == data["habits"] == {
        "target": 2, "completed": 1, "completion_percentage": 50,
    }
    assert data["focus"]["focus_minutes"] == 5
    assert data["focus"]["completed_focus_sessions"] == 0
    assert data["discipline_score"]["value"] == 44
    report = (await client.get(
        f"{REPORT}/range?from_date=2025-01-08&to_date=2025-01-09"
    )).json()
    assert report["days"][0] == data
    assert report["days"][1]["focus"]["focus_minutes"] == 10
    assert report["days"][1]["focus"]["completed_focus_sessions"] == 1
    assert (await client.get(f"{REPORT}/daily")).json() == report["days"][1]
    empty = (await client.get(f"{REPORT}/daily?date=2025-01-05")).json()
    assert empty["discipline_score"]["value"] is None and empty["tasks"]["target"] == 0


async def test_reflection_upsert_csrf_isolation_and_validation(account, app):
    client, _ = account
    day = "2024-03-01"
    path = f"{REFLECTION}/{day}"
    assert (await client.get(path)).status_code == 404
    first, second = await asyncio.gather(
        client.put(path, json={"notes": "First", "mood": 3}),
        client.put(path, json={"notes": "Second", "mood": 4}),
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    saved = await client.get(path)
    assert saved.json()["notes"] in ("First", "Second")
    assert saved.headers["Cache-Control"] == "no-store"
    report = (await client.get(f"{REPORT}/daily?date={day}")).json()
    assert report["has_evening_reflection"] and report["discipline_score"]["value"] is None
    assert "notes" not in report
    for payload in ({"notes": " "}, {"notes": "Valid", "mood": 6},
                    {"notes": "Valid", "user_id": "invalid"}):
        assert (await client.put(path, json=payload)).status_code == 422
    assert (await client.get(f"{REPORT}/daily?date=9998-01-01")).status_code == 422
    assert (await client.get(f"{REPORT}/range?from_date=2024-01-01&to_date=2024-03-01")).status_code == 422
    rejected = await client.put(path, json={"notes": "Blocked"}, headers={"Origin": "null"})
    assert rejected.status_code == 403
    preflight = await client.options(path, headers={"Access-Control-Request-Method": "PUT"})
    assert preflight.status_code == 200

    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN,
                           headers={"Origin": ORIGIN}) as other:
        assert (await other.get(f"{REPORT}/daily")).status_code == 401
        data = credentials()
        await register(other, data)
        await login(other, data)
        assert (await other.get(path)).status_code == 404
        assert (await other.delete(path)).status_code == 404
        assert not (await other.get(f"{REPORT}/daily?date={day}")).json()["has_evening_reflection"]
        separate = await other.put(path, json={"notes": "Another owner's entry"})
        assert separate.json()["id"] != first.json()["id"]

    assert (await client.delete(path)).status_code == 204
    assert not (await client.get(f"{REPORT}/daily?date={day}")).json()["has_evening_reflection"]
