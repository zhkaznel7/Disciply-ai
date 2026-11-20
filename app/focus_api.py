from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api import Database, current_user
from app.errors import ErrorResponse
from app.focus_analytics import FocusAnalytics
from app.focus_schemas import (
    FocusSummary, HistoryFilters, PeriodMetrics, SessionView, StartSession, TaskFilters, TaskMetrics,
)
from app.focus_service import FocusService
from app.models import User
from app.planning_schemas import LocalDate, Page
from app.security import API_PATH

router = APIRouter(prefix=f"{API_PATH}/focus", tags=["focus"], responses={
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 422, 500)
})
Owner = Annotated[User, Depends(current_user)]


async def no_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


async def session_service(db: Database, user: Owner) -> FocusService:
    return FocusService(db, user.id)


async def analytics_service(db: Database, user: Owner) -> FocusAnalytics:
    return FocusAnalytics(db, user.id)


router.dependencies.append(Depends(no_cache))
Sessions = Annotated[FocusService, Depends(session_service)]
Analytics = Annotated[FocusAnalytics, Depends(analytics_service)]


@router.post("/sessions", status_code=201, response_model=SessionView)
async def start_session(payload: StartSession, service: Sessions):
    return await service.start(payload)


@router.get("/sessions", response_model=Page[SessionView])
async def session_history(filters: Annotated[HistoryFilters, Query()], service: Sessions):
    return await service.history(filters)


@router.get("/sessions/current", response_model=SessionView | None)
async def current_session(service: Sessions):
    return await service.current()


@router.get("/sessions/{session_id}", response_model=SessionView)
async def get_session(session_id: UUID, service: Sessions):
    return await service.get(session_id)


@router.post("/sessions/{session_id}/pause", response_model=SessionView)
async def pause_session(session_id: UUID, service: Sessions):
    return await service.transition(session_id, "pause")


@router.post("/sessions/{session_id}/resume", response_model=SessionView)
async def resume_session(session_id: UUID, service: Sessions):
    return await service.transition(session_id, "resume")


@router.post("/sessions/{session_id}/complete", response_model=SessionView)
async def complete_session(session_id: UUID, service: Sessions):
    return await service.transition(session_id, "complete")


@router.post("/sessions/{session_id}/cancel", response_model=SessionView)
async def cancel_session(session_id: UUID, service: Sessions):
    return await service.transition(session_id, "cancel")


@router.get("/summary", response_model=FocusSummary)
async def summary(service: Analytics):
    return await service.summary()


@router.get("/daily", response_model=PeriodMetrics)
async def daily(service: Analytics, date: Annotated[LocalDate | None, Query()] = None):
    return await service.period("daily", date)


@router.get("/weekly", response_model=PeriodMetrics)
async def weekly(service: Analytics, date: Annotated[LocalDate | None, Query()] = None):
    return await service.period("weekly", date)


@router.get("/monthly", response_model=PeriodMetrics)
async def monthly(service: Analytics, date: Annotated[LocalDate | None, Query()] = None):
    return await service.period("monthly", date)


@router.get("/by-task", response_model=Page[TaskMetrics])
async def by_task(filters: Annotated[TaskFilters, Query()], service: Analytics):
    return await service.by_task(filters)
