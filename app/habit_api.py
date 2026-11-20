from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api import Database, current_user
from app.errors import ErrorResponse
from app.habit_schemas import (
    DayStatus, HabitCreate, HabitFilters, HabitStats, HabitUpdate, HabitView, LogCreate,
    LogFilters, LogUpdate, LogView, PeriodHabit, Summary,
)
from app.habit_service import HabitService
from app.models import User
from app.planning_schemas import Page, Pagination
from app.security import API_PATH

router = APIRouter(prefix=f"{API_PATH}/habits", tags=["habits"], responses={
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 422, 500)
})


async def habit_service(
    db: Database, user: Annotated[User, Depends(current_user)], response: Response
) -> HabitService:
    response.headers["Cache-Control"] = "no-store"
    return HabitService(db, user.id)


Service = Annotated[HabitService, Depends(habit_service)]
Paging = Annotated[Pagination, Query()]


@router.post("", status_code=201, response_model=HabitView)
async def create_habit(payload: HabitCreate, service: Service):
    return await service.save(payload)


@router.get("", response_model=Page[HabitView])
async def list_habits(filters: Annotated[HabitFilters, Query()], service: Service):
    return await service.list(filters)


@router.get("/summary", response_model=Summary)
async def habit_summary(service: Service):
    return await service.summary()


@router.get("/today", response_model=Page[DayStatus])
async def today(pagination: Paging, service: Service):
    return await service.today(pagination)


@router.get("/weekly", response_model=Page[PeriodHabit])
async def weekly(pagination: Paging, service: Service):
    return await service.period(pagination, "weekly")


@router.get("/monthly", response_model=Page[PeriodHabit])
async def monthly(pagination: Paging, service: Service):
    return await service.period(pagination, "monthly")


@router.get("/{habit_id}", response_model=HabitView)
async def get_habit(habit_id: UUID, service: Service):
    return await service.get(habit_id)


@router.patch("/{habit_id}", response_model=HabitView)
async def update_habit(habit_id: UUID, payload: HabitUpdate, service: Service):
    return await service.save(payload, habit_id)


@router.delete("/{habit_id}", status_code=204)
async def delete_habit(habit_id: UUID, service: Service):
    await service.delete(habit_id)


@router.post("/{habit_id}/logs", status_code=201, response_model=LogView)
async def create_log(habit_id: UUID, payload: LogCreate, service: Service):
    return await service.add_log(habit_id, payload)


@router.get("/{habit_id}/logs", response_model=Page[LogView])
async def list_logs(habit_id: UUID, filters: Annotated[LogFilters, Query()], service: Service):
    return await service.logs(habit_id, filters)


@router.patch("/{habit_id}/logs/{log_id}", response_model=LogView)
async def update_log(habit_id: UUID, log_id: UUID, payload: LogUpdate, service: Service):
    return await service.update_log(habit_id, log_id, payload)


@router.delete("/{habit_id}/logs/{log_id}", status_code=204)
async def delete_log(habit_id: UUID, log_id: UUID, service: Service):
    await service.delete_log(habit_id, log_id)


@router.get("/{habit_id}/stats", response_model=HabitStats)
async def habit_stats(habit_id: UUID, service: Service):
    return await service.stats(habit_id)
