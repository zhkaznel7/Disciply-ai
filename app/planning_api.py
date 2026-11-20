from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api import Database, current_user
from app.errors import ErrorResponse
from app.models import Goal, Project, Task, User
from app.planning_schemas import (
    DailyPlan, GoalCreate, GoalFilters, GoalUpdate, GoalView, LocalDate, Page, Pagination,
    ProjectCreate, ProjectFilters, ProjectUpdate, ProjectView, TaskCreate, TaskFilters,
    TaskUpdate, TaskView, WeeklyPlan,
)
from app.planning_service import PlanningService
from app.security import API_PATH

router = APIRouter(prefix=API_PATH, responses={
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 422, 500)
})
goals = APIRouter(prefix="/goals", tags=["goals"])
projects = APIRouter(prefix="/projects", tags=["projects"])
tasks = APIRouter(prefix="/tasks", tags=["tasks"])
planner = APIRouter(prefix="/planner", tags=["planner"])


async def planning_service(
    db: Database, user: Annotated[User, Depends(current_user)], response: Response
) -> PlanningService:
    response.headers["Cache-Control"] = "no-store"
    return PlanningService(db, user.id)


Service = Annotated[PlanningService, Depends(planning_service)]


@goals.post("", status_code=201, response_model=GoalView)
async def create_goal(payload: GoalCreate, service: Service):
    return await service.save_goal(payload)


@goals.get("", response_model=Page[GoalView])
async def list_goals(filters: Annotated[GoalFilters, Query()], service: Service):
    return await service.goals(filters)


@goals.get("/{goal_id}", response_model=GoalView)
async def get_goal(goal_id: UUID, service: Service):
    return await service.get(Goal, goal_id)


@goals.patch("/{goal_id}", response_model=GoalView)
async def update_goal(goal_id: UUID, payload: GoalUpdate, service: Service):
    return await service.save_goal(payload, goal_id)


@goals.delete("/{goal_id}", status_code=204)
async def delete_goal(goal_id: UUID, service: Service):
    await service.delete(Goal, goal_id)


@projects.post("", status_code=201, response_model=ProjectView)
async def create_project(payload: ProjectCreate, service: Service):
    return await service.save_project(payload)


@projects.get("", response_model=Page[ProjectView])
async def list_projects(filters: Annotated[ProjectFilters, Query()], service: Service):
    return await service.projects(filters)


@projects.get("/{project_id}", response_model=ProjectView)
async def get_project(project_id: UUID, service: Service):
    return await service.get(Project, project_id)


@projects.patch("/{project_id}", response_model=ProjectView)
async def update_project(project_id: UUID, payload: ProjectUpdate, service: Service):
    return await service.save_project(payload, project_id)


@projects.delete("/{project_id}", status_code=204)
async def delete_project(project_id: UUID, service: Service):
    await service.delete(Project, project_id)


@projects.get("/{project_id}/tasks", response_model=Page[TaskView])
async def project_tasks(project_id: UUID, pagination: Annotated[Pagination, Query()], service: Service):
    return await service.tasks(TaskFilters(project_id=project_id, **pagination.model_dump()))


@tasks.post("", status_code=201, response_model=TaskView)
async def create_task(payload: TaskCreate, service: Service):
    return await service.save_task(payload)


@tasks.get("", response_model=Page[TaskView])
async def list_tasks(filters: Annotated[TaskFilters, Query()], service: Service):
    return await service.tasks(filters)


@tasks.get("/{task_id}", response_model=TaskView)
async def get_task(task_id: UUID, service: Service):
    return await service.get(Task, task_id)


@tasks.patch("/{task_id}", response_model=TaskView)
async def update_task(task_id: UUID, payload: TaskUpdate, service: Service):
    return await service.save_task(payload, task_id)


@tasks.delete("/{task_id}", status_code=204)
async def delete_task(task_id: UUID, service: Service):
    await service.delete(Task, task_id)


class DailyQuery(Pagination):
    date: LocalDate | None = None


class WeeklyQuery(Pagination):
    start_date: LocalDate | None = None


@planner.get("/daily", response_model=DailyPlan)
async def daily(filters: Annotated[DailyQuery, Query()], service: Service):
    return await service.daily(filters.date, filters)


@planner.get("/weekly", response_model=WeeklyPlan)
async def weekly(filters: Annotated[WeeklyQuery, Query()], service: Service):
    return await service.weekly(filters.start_date, filters)


for module_router in (goals, projects, tasks, planner):
    router.include_router(module_router)
