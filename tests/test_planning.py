from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app.models import UserSettings
from conftest import ORIGIN
from test_auth import credentials, login, register

API = "/api/v1"


async def create(client, path, **fields):
    response = await client.post(f"{API}/{path}", json=fields)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def signed_in(client):
    account = credentials()
    profile = await register(client, account)
    await login(client, account)
    return client, profile


async def test_goal_crud_progress_and_pagination(signed_in):
    client, _ = signed_in
    goal = await create(client, "goals", title="  Learn Python  ", target_on="2030-01-10",
                        description="Read the docs", priority=2)
    assert goal["title"] == "Learn Python"
    assert goal["progress"] == 0 and goal["status"] == "active"
    assert "user_id" not in goal
    path = f"{API}/goals/{goal['id']}"
    assert (await client.get(path)).json() == goal

    response = await client.patch(path, json={"progress": 100, "description": None})
    assert response.status_code == 200, response.text
    finished = response.json()
    assert finished["status"] == "completed" and finished["completed_at"]
    assert finished["updated_at"] > goal["updated_at"]
    assert finished["description"] is None
    await create(client, "goals", title="Another goal", status="completed", target_on="2030-01-10")
    params = {"limit": 1, "status": "completed", "target_on": "2030-01-10"}
    first = (await client.get(f"{API}/goals", params=params)).json()
    next_page = (await client.get(f"{API}/goals", params={**params, "offset": 1})).json()
    assert first["has_more"] and not next_page["has_more"]
    assert next_page["items"] == [finished]
    assert (await client.patch(path, json={"status": "active"})).json()["progress"] == 0
    assert (await client.delete(path)).status_code == 204
    assert (await client.get(path)).status_code == 404


async def test_project_crud_and_relationships(signed_in):
    client, _ = signed_in
    goal = await create(client, "goals", title="Goal")
    project = await create(client, "projects", title="Project", goal_id=goal["id"],
                           starts_on="2030-01-01", target_on="2030-01-20")
    project_path = f"{API}/projects/{project['id']}"
    goal_path = f"{API}/goals/{goal['id']}"
    assert (await client.get(project_path)).json() == project
    assert (await client.delete(goal_path)).status_code == 409
    assert (await client.patch(project_path, json={"starts_on": "2030-01-21"})).status_code == 422
    response = await client.patch(project_path, json={"status": "archived", "goal_id": None})
    assert response.status_code == 200
    archived = response.json()
    assert archived["archived_at"] and archived["goal_id"] is None
    assert (await client.get(f"{API}/projects?status=archived")).json()["items"] == [archived]
    task = await create(client, "tasks", title="Linked task", project_id=project["id"])
    assert (await client.get(f"{project_path}/tasks")).json()["items"] == [task]
    assert (await client.delete(project_path)).status_code == 409
    assert (await client.delete(f"{API}/tasks/{task['id']}")).status_code == 204
    assert (await client.delete(project_path)).status_code == 204
    assert (await client.get(f"{project_path}/tasks")).status_code == 404
    assert (await client.delete(goal_path)).status_code == 204


async def test_task_crud_filters_and_completion(signed_in):
    client, _ = signed_in
    goal = await create(client, "goals", title="Inherited goal")
    other = await create(client, "goals", title="Direct goal")
    project = await create(client, "projects", title="Project", goal_id=goal["id"])
    task = await create(client, "tasks", title="Overdue task", priority=3, project_id=project["id"],
                        scheduled_on="2020-01-01", due_at="2020-01-03T00:00:00Z")
    explicit = await create(client, "tasks", title="Override", goal_id=other["id"],
                            project_id=project["id"])
    path = f"{API}/tasks/{task['id']}"
    assert (await client.get(path)).json() == task
    params = {"goal_id": goal["id"], "project_id": project["id"], "priority": 3,
              "scheduled_on": "2020-01-01", "status": "open", "overdue": "true"}
    assert (await client.get(f"{API}/tasks", params=params)).json()["items"] == [task]
    assert (await client.get(f"{API}/tasks", params={"goal_id": other["id"]})).json()["items"] == [explicit]
    assert (await client.get(f"{API}/tasks", params={"goal_id": goal["id"]})).json()["items"] == [task]
    finished = (await client.patch(path, json={"status": "completed"})).json()
    assert finished["completed_at"] and finished["status"] == "completed"
    assert (await client.patch(path, json={"status": "completed"})).json() == finished
    assert (await client.get(f"{API}/tasks?overdue=true")).json()["items"] == []
    assert len((await client.get(f"{API}/tasks?overdue=false")).json()["items"]) == 2
    reopened = (await client.patch(path, json={"status": "open", "title": "Reopened"})).json()
    assert reopened["completed_at"] is None and reopened["title"] == "Reopened"
    assert (await client.delete(path)).status_code == 204
    assert (await client.get(path)).status_code == 404


async def test_planner_timezone_order_and_pagination(signed_in, app):
    client, profile = signed_in
    async with app.state.sessions.begin() as db:
        await db.execute(
            update(UserSettings).where(UserSettings.user_id == UUID(profile["id"]))
            .values(timezone="America/Los_Angeles")
        )
    day = "2030-01-07"
    untimed = await create(client, "tasks", title="Untimed", scheduled_on=day, priority=3)
    later = await create(client, "tasks", title="Evening", scheduled_on=day,
                         scheduled_start_at="2030-01-08T04:00:00Z")
    earlier = await create(client, "tasks", title="Morning", scheduled_on=day,
                           scheduled_start_at="2030-01-07T17:00:00Z",
                           scheduled_end_at="2030-01-07T18:00:00Z")
    response = await client.post(f"{API}/tasks", json={
        "title": "Wrong local date", "scheduled_on": "2030-01-08",
        "scheduled_start_at": "2030-01-08T04:00:00Z",
    })
    assert response.status_code == 422
    assert (await client.patch(f"{API}/tasks/{earlier['id']}",
                               json={"scheduled_on": None})).status_code == 422
    daily = (await client.get(f"{API}/planner/daily?date={day}")).json()
    assert daily["timezone"] == "America/Los_Angeles"
    assert daily["tasks"] == [earlier, later, untimed]
    assert (await client.get(f"{API}/planner/daily?date=2030-01-08")).json()["tasks"] == []
    weekly = (await client.get(f"{API}/planner/weekly?start_date=2030-01-09&limit=2")).json()
    assert weekly["start_date"] == day
    assert [entry["date"] for entry in weekly["days"]] == [f"2030-01-{d:02}" for d in range(7, 14)]
    assert weekly["days"][0]["tasks"] == [earlier, later] and weekly["has_more"]
    assert all(not entry["tasks"] for entry in weekly["days"][1:])
    page = (await client.get(f"{API}/planner/daily?date={day}&limit=2&offset=2")).json()
    assert page["tasks"] == [untimed] and not page["has_more"]


async def test_auth_csrf_owner_isolation_and_invalid_input(signed_in, app):
    client, _ = signed_in
    goal = await create(client, "goals", title="Private goal")
    project = await create(client, "projects", title="Private project", goal_id=goal["id"])
    task = await create(client, "tasks", title="Private task", scheduled_on="2030-01-07")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other:
        for endpoint in ("goals", "projects", "tasks", "planner/daily", "planner/weekly"):
            assert (await other.get(f"{API}/{endpoint}")).status_code == 401
        account = credentials()
        await register(other, account)
        await login(other, account)
        for endpoint, record in (("goals", goal), ("projects", project), ("tasks", task)):
            path = f"{API}/{endpoint}/{record['id']}"
            assert (await other.get(path)).status_code == 404
            assert (await other.patch(path, json={"title": "Forbidden"})).status_code == 404
            assert (await other.delete(path)).status_code == 404
            assert (await other.get(f"{API}/{endpoint}")).json()["items"] == []
        assert (await other.get(f"{API}/projects/{project['id']}/tasks")).status_code == 404
        for endpoint, fields in (
            ("projects", {"goal_id": goal["id"]}),
            ("tasks", {"project_id": project["id"]}),
            ("tasks", {"goal_id": goal["id"]}),
        ):
            assert (await other.post(f"{API}/{endpoint}", json={"title": "Foreign", **fields})).status_code == 404
        own_task = await create(other, "tasks", title="Owned task")
        assert (await other.patch(f"{API}/tasks/{own_task['id']}", json={"goal_id": goal["id"]})).status_code == 404
        assert (await other.get(f"{API}/planner/daily?date=2030-01-07")).json()["tasks"] == []

    path = f"{API}/tasks/{task['id']}"
    assert (await client.patch(path, json={"title": "Blocked"}, headers={"Origin": "null"})).status_code == 403
    request = client.build_request("DELETE", path)
    del request.headers["Origin"]
    assert (await client.send(request)).status_code == 403
    preflight = await client.options(path, headers={"Access-Control-Request-Method": "PATCH"})
    assert preflight.status_code == 200
    assert (await client.get(path)).json() == task

    for endpoint, body in (
        ("goals", {"title": "Goal", "progress": 101}),
        ("goals", {"title": "Goal", "status": "completed", "progress": 1}),
        ("projects", {"title": "Project", "target_on": "2030-13-01"}),
        ("tasks", {"title": "Task", "user_id": str(uuid4())}),
        ("tasks", {"title": "Task", "completed_at": datetime.now(UTC).isoformat()}),
        ("tasks", {"title": "Task", "due_at": "2030-01-07T09:00:00"}),
        ("tasks", {"title": "Task", "due_at": "0001-01-01T00:00:00+01:00"}),
        ("tasks", {"title": "Task", "scheduled_end_at": "2030-01-07T09:00:00Z"}),
    ):
        assert (await client.post(f"{API}/{endpoint}", json=body)).status_code == 422
    for query in ("limit=201", "goal_id=broken", "user_id=123"):
        assert (await client.get(f"{API}/tasks?{query}")).status_code == 422
    assert (await client.patch(path, json={"title": None})).status_code == 422
    assert (await client.patch(path, json={})).status_code == 422
    assert (await client.get(f"{API}/tasks/invalid-id")).status_code == 422
    assert (await client.get(f"{API}/planner/weekly?start_date=9999-12-31")).status_code == 422
