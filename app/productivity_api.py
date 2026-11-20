from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api import Database, current_user
from app.errors import ErrorResponse
from app.models import User
from app.planning_schemas import LocalDate
from app.productivity_schemas import (
    DateQuery, ProductivityDay, ProductivityRange, RangeQuery, ReflectionView, ReflectionWrite,
)
from app.productivity_service import ProductivityService, ReflectionService
from app.security import API_PATH

router = APIRouter(prefix=API_PATH, tags=["productivity"], responses={
    code: {"model": ErrorResponse} for code in (401, 403, 404, 413, 422, 500)
})
Owner = Annotated[User, Depends(current_user)]


async def productivity_service(db: Database, user: Owner, response: Response) -> ProductivityService:
    response.headers["Cache-Control"] = "no-store"
    return ProductivityService(db, user.id)


async def reflection_service(db: Database, user: Owner, response: Response) -> ReflectionService:
    response.headers["Cache-Control"] = "no-store"
    return ReflectionService(db, user.id)


Productivity = Annotated[ProductivityService, Depends(productivity_service)]
Reflections = Annotated[ReflectionService, Depends(reflection_service)]


@router.get("/analytics/daily", response_model=ProductivityDay)
async def daily(filters: Annotated[DateQuery, Query()], service: Productivity):
    return await service.daily(filters.date)


@router.get("/analytics/range", response_model=ProductivityRange)
async def date_range(filters: Annotated[RangeQuery, Query()], service: Productivity):
    return await service.range(filters.from_date, filters.to_date)


@router.get("/reflections/{day}", response_model=ReflectionView)
async def get_reflection(day: LocalDate, service: Reflections):
    return await service.get(day)


@router.put("/reflections/{day}", response_model=ReflectionView)
async def put_reflection(day: LocalDate, payload: ReflectionWrite, service: Reflections):
    return await service.save(day, payload)


@router.delete("/reflections/{day}", status_code=204)
async def delete_reflection(day: LocalDate, service: Reflections):
    await service.delete(day)
