from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from app.admin_bootstrap import bootstrap
from app.ai_provider import GeneratedText
from app.models import AIUsage, DailyStatistic, Task, User
from test_auth import credentials, login, register

ROOT = "/api/v1"
ADMIN = ROOT + "/admin"


async def account(client, app, role="user"):
    data = credentials()
    profile = await register(client, data)
    if role != "user":
        async with app.state.sessions.begin() as db:
            await db.execute(update(User).where(User.id == UUID(profile["id"])).values(role=role))
    await login(client, data)
    return profile, data


async def test_every_admin_operation_enforces_its_role(client, app):
    missing = str(uuid4())
    settings = {"feedback_enabled": True, "token_price": None}
    operations = [
        ("GET", "/access", None, 200, 200),
        ("GET", "/overview", None, 200, 200),
        ("GET", "/users", None, 200, 200),
        ("GET", "/users/{user_id}", None, 404, 404),
        ("PATCH", "/users/{user_id}/role", {"role": "admin"}, 403, 404),
        ("PATCH", "/users/{user_id}/status", {"status": "suspended"}, 404, 404),
        ("GET", "/feedback", None, 200, 200),
        ("PATCH", "/feedback/{feedback_id}", {"status": "closed"}, 404, 404),
        ("GET", "/audit", None, 200, 200),
        ("GET", "/settings", None, 200, 200),
        ("PUT", "/settings", settings, 403, 200),
    ]
    assert {(method.lower(), ADMIN + path) for method, path, *_ in operations} == {
        (method, path) for path, methods in app.openapi()["paths"].items()
        if path.startswith(ADMIN + "/") for method in methods
    }
    for role in ("anonymous", "user", "admin", "super_admin"):
        client.cookies.clear()
        if role != "anonymous":
            await account(client, app, role)
        if role == "super_admin":
            settings.update((await client.get(ADMIN + "/settings")).json())
        for method, path, body, as_admin, as_super in operations:
            uri = ADMIN + path.format(user_id=missing, feedback_id=missing)
            response = await client.request(method, uri, json=body)
            expected = as_super if role == "super_admin" else as_admin if role == "admin" else 403
            assert response.status_code == expected, (role, method, path, response.text)


async def test_overview_filters_period_totals_and_anchors_activity_at_end(client, app):
    user, _ = await account(client, app, "super_admin")
    owner = UUID(user["id"])
    first = datetime.now(UTC).date() - timedelta(days=45)
    second = first + timedelta(days=1)
    last = second + timedelta(days=1)
    async with app.state.sessions.begin() as db:
        await db.execute(update(User).where(User.id == owner).values(created_at=datetime.combine(first, time.min, UTC)))
        db.add_all([
            Task(user_id=owner, title="report fixture", completed_at=datetime.combine(second, time.min, UTC)),
            DailyStatistic(user_id=owner, statistic_on=first, discipline_score=20),
            DailyStatistic(user_id=owner, statistic_on=second, discipline_score=80),
            AIUsage(user_id=owner, usage_on=first, request_count=3, provider_calls=1, reported_tokens=30, budgeted_tokens=30),
            AIUsage(user_id=owner, usage_on=second, request_count=5, provider_calls=1, reported_tokens=50, budgeted_tokens=50),
        ])

    async def read(start, end):
        response = await client.get(ADMIN + "/overview", params={"from_date": start, "to_date": end})
        assert response.status_code == 200, response.text
        return response.json()

    early = await read(first, first)
    late = await read(second, second)
    combined = await read(first, second)
    later_end = await read(first, last)
    assert early["new_registrations"] == 1 and late["new_registrations"] == 0
    assert early["completed_tasks"] == 0 and late["completed_tasks"] == 1
    assert combined["average_discipline_score"] == 50 and late["average_discipline_score"] == 80
    assert combined["scored_user_days"] == 2 and late["scored_user_days"] == 1
    assert combined["ai"]["requests"] == 8 and late["ai"]["requests"] == 5
    assert combined["ai"]["reported_tokens"] == 80 and late["ai"]["reported_tokens"] == 50
    assert [item["ai_requests"] for item in combined["days"]] == [3, 5]
    assert late["daily_active_users"] == 1 and later_end["daily_active_users"] == 0
    assert later_end["monthly_active_users"] == 1 and later_end["total_users"] == combined["total_users"]


async def test_admin_authorization_and_safe_user_search(client, app):
    assert (await client.get(ADMIN + "/access")).status_code == 403
    ordinary, _ = await account(client, app)
    for path in ("access", "overview", "users", "feedback", "audit", "settings"):
        assert (await client.get(f"{ADMIN}/{path}")).status_code == 403
    assert (await client.patch(f"{ADMIN}/users/{ordinary['id']}/role", json={"role": "super_admin"})).status_code == 403
    await account(client, app, "admin")
    query = {"search": ordinary["email"], "role": "user", "status": "active", "limit": 1}
    listed = await client.get(ADMIN + "/users", params=query)
    assert listed.status_code == 200
    row = listed.json()["items"][0]
    assert row["id"] == ordinary["id"]
    assert set(row) == {"id", "email", "role", "created_at", "suspended_at"}
    assert (await client.get(f"{ADMIN}/users/{ordinary['id']}")).json() == row
    assert (await client.get(ADMIN + "/users", params={"search": "%_"})).json()["items"] == []
    assert (await client.get(ADMIN + "/users", params={"limit": 201})).status_code == 422
    assert (await client.get(ADMIN + "/users?role=operator")).status_code == 422
    assert (await client.get(ADMIN + "/users?offset=-1")).status_code == 422
    assert (await client.get(ADMIN + "/users?search=%00")).status_code == 422


async def test_role_restrictions_suspension_revokes_sessions_and_audits(client, app):
    member, member_credentials = await account(client, app)
    member_cookies = dict(client.cookies)
    administrator, admin_credentials = await account(client, app, "admin")
    super_admin, super_admin_credentials = await account(client, app, "super_admin")
    await login(client, admin_credentials)
    actor = f"{ADMIN}/users/{administrator['id']}"
    staff = f"{ADMIN}/users/{super_admin['id']}"
    target = f"{ADMIN}/users/{member['id']}"
    assert (await client.patch(actor + "/status", json={"status": "suspended"})).status_code == 403
    assert (await client.patch(staff + "/status", json={"status": "suspended"})).status_code == 403
    assert (await client.patch(target + "/role", json={"role": "admin"})).status_code == 403
    request = client.build_request("PATCH", target + "/status", json={"status": "suspended"})
    del request.headers["origin"]
    assert (await client.send(request)).status_code == 403
    assert (await client.patch(target + "/status", json={"status": "suspended"})).status_code == 200

    admin_cookies = dict(client.cookies)
    client.cookies.clear()
    client.cookies.update(member_cookies)
    assert (await client.get(ROOT + "/auth/me")).status_code == 401
    assert (await client.post(ROOT + "/auth/refresh")).status_code == 401
    assert (await client.post(ROOT + "/auth/login", json=member_credentials)).status_code == 401

    client.cookies.clear()
    client.cookies.update(admin_cookies)
    assert (await client.patch(target + "/status", json={"status": "active"})).status_code == 200
    client.cookies.clear()
    await login(client, member_credentials)
    client.cookies.clear()
    await login(client, super_admin_credentials)
    assert (await client.get(ADMIN + "/access")).json()["role"] == "super_admin"
    assert (await client.patch(staff + "/role", json={"role": "user"})).status_code == 403
    assert (await client.patch(target + "/role", json={"role": "admin", "admin": True})).status_code == 422
    promoted = await client.patch(target + "/role", json={"role": "admin"})
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "admin"
    audit = (await client.get(ADMIN + "/audit", params={"actor_id": administrator["id"], "limit": 1})).json()
    assert audit["has_more"]
    assert audit["items"][0]["action"] == "account_reactivated"
    assert audit["items"][0]["actor_id"] == administrator["id"]
    assert audit["items"][0]["target_id"] == member["id"]


async def test_admin_overview_ai_counts_feedback_and_settings(client, app):
    supervisor, supervisor_credentials = await account(client, app, "super_admin")
    today = datetime.now(UTC).date().isoformat()
    dates = {"from_date": today, "to_date": today}
    endpoint = ADMIN + "/overview"
    initial = await client.get(endpoint, params=dates)
    assert initial.status_code == 200, initial.text
    baseline = initial.json()
    member, _ = await account(client, app)
    item = (await client.post(ROOT + "/feedback", json={"subject": "Тема", "message": "Сообщение"})).json()
    task = (await client.post(ROOT + "/tasks", json={"title": "private", "scheduled_on": today})).json()
    assert (await client.patch(ROOT + "/tasks/" + task["id"], json={"status": "completed"})).status_code == 200
    report = (await client.get(ROOT + "/analytics/daily", params={"date": today})).json()
    async with app.state.sessions() as db:
        measured = await db.scalar(select(DailyStatistic).where(DailyStatistic.user_id == UUID(member["id"])))
        assert measured.discipline_score == report["discipline_score"]["value"]
    class Provider:
        async def reply(self, context):
            return GeneratedText(None, tokens=1000, failure="quota")

    app.state.ai_provider = Provider()
    app.state.ai_settings = app.state.ai_settings.model_copy(update={"ai_daily_requests": 1})
    assert (await client.post(ROOT + "/ai/coach", json={"message": "Привет"})).status_code == 200
    assert (await client.post(ROOT + "/ai/coach", json={"message": "Ещё вопрос"})).status_code == 429
    await login(client, supervisor_credentials)
    assert (await client.put(ADMIN + "/settings", json={"token_price": -1, "feedback_enabled": False})).status_code == 422
    assert (await client.put(ADMIN + "/settings", json={"token_price": 2, "feedback_enabled": False, "api_key": "invalid"})).status_code == 422
    assert (await client.put(ADMIN + "/settings", json={"token_price": 2, "feedback_enabled": False})).status_code == 200
    assert (await client.post(ROOT + "/feedback", json={"subject": "Тема", "message": "Сообщение"})).status_code == 403
    assert (await client.patch(f"{ADMIN}/feedback/{item['id']}", json={"status": "closed"})).status_code == 200
    closed = (await client.get(ADMIN + "/feedback", params={"status": "closed"})).json()["items"]
    assert item["id"] in {entry["id"] for entry in closed}

    result = (await client.get(endpoint, params=dates)).json()
    assert result["database_ready"]
    assert result["total_users"] == baseline["total_users"] + 1
    assert result["new_registrations"] == baseline["new_registrations"] + 1
    assert result["completed_tasks"] == baseline["completed_tasks"] + 1
    assert result["daily_active_users"] == baseline["daily_active_users"] + 1
    assert result["monthly_active_users"] >= result["daily_active_users"]
    assert result["scored_user_days"] == baseline["scored_user_days"] + 1
    assert result["average_discipline_score"] is not None
    assert result["ai"]["requests"] == baseline["ai"]["requests"] + 1
    assert result["ai"]["provider_failures"] == baseline["ai"]["provider_failures"] + 1
    assert result["ai"]["quota_rejections"] == baseline["ai"]["quota_rejections"] + 1
    assert result["ai"]["estimated_cost_usd"] == pytest.approx(result["ai"]["reported_tokens"] * 2 / 1_000_000)
    assert len(result["days"]) == 1
    assert (await client.get(endpoint, params={"from_date": "2000-01-01", "to_date": today})).status_code == 422
    assert (await client.get(ADMIN + "/audit", params={"actor_id": supervisor["id"], "action": "settings_updated"})).json()["items"]


async def test_super_admin_bootstrap_is_one_time(client, app):
    person, _ = await account(client, app)
    async with app.state.sessions() as db:
        # Keep the one-time bootstrap test independent of other seeded roles.
        await db.execute(update(User).where(User.role == "super_admin").values(role="admin"))
        await bootstrap(db, UUID(person["id"]))
        await db.flush()
        assert (await db.get(User, UUID(person["id"]))).role == "super_admin"
        with pytest.raises(ValueError, match="already exists"):
            await bootstrap(db, UUID(person["id"]))
        await db.rollback()
