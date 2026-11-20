from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.ai_quota import AIQuota
from app.ai_schemas import (
    CoachRequest, CoachView, InsightsView, PeriodView, PlanRequest, PlanView, ReviewView, StatusView, UsageView,
)
from app.ai_service import AIService, advice, rules
from app.api import Database, current_user
from app.errors import ErrorResponse
from app.models import User
from app.planning_schemas import Input
from app.security import API_PATH

router = APIRouter(prefix=API_PATH, responses={
    code: {"model": ErrorResponse} for code in (401, 403, 413, 422, 429, 500)
})
ai = APIRouter(prefix="/ai", tags=["ai"])
analytics = APIRouter(prefix="/analytics", tags=["productivity"])
Owner = Annotated[User, Depends(current_user)]


async def quota(request: Request, response: Response, db: Database, user: Owner) -> AIQuota:
    response.headers["Cache-Control"] = "no-store"
    return AIQuota(db, user.id, request.app.state.ai_settings, request.app.state.ai_provider)


Quota = Annotated[AIQuota, Depends(quota)]


async def service(db: Database, user: Owner, gate: Quota) -> AIService:
    return AIService(db, user.id, gate)


Service = Annotated[AIService, Depends(service)]


@ai.get("/status", response_model=StatusView)
async def status(gate: Quota):
    return StatusView(external_enabled=gate.provider is not None)


@ai.get("/usage", response_model=UsageView)
async def usage(gate: Quota):
    return await gate.view()


@ai.post("/coach", response_model=CoachView)
async def coach(payload: CoachRequest, assistant: Service):
    return await assistant.coach(payload)


@ai.post("/daily-plan", response_model=PlanView)
async def daily_plan(payload: PlanRequest, assistant: Service):
    return await assistant.plan(payload)


@ai.post("/weekly-review", response_model=ReviewView)
async def weekly_review(assistant: Service, payload: Input | None = None):
    return await assistant.review()


@analytics.get("/weekly", response_model=PeriodView)
async def weekly(assistant: Service):
    report, metrics = await assistant.period(False)
    return {"from_date": report.from_date, "to_date": report.to_date, "timezone": report.timezone,
            "metrics": metrics}


@analytics.get("/monthly", response_model=PeriodView)
async def monthly(assistant: Service):
    report, metrics = await assistant.period(True)
    return {"from_date": report.from_date, "to_date": report.to_date, "timezone": report.timezone,
            "metrics": metrics}


@analytics.get("/insights", response_model=InsightsView)
async def insights(assistant: Service):
    _, metrics = await assistant.period(False)
    return {"weekly_facts": metrics, "suggestions": advice(rules(metrics))}


router.include_router(ai)
router.include_router(analytics)
