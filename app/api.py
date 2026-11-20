from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.errors import ErrorResponse
from app.models import User
from app.schemas import Credentials, Health, Profile, Registration
from app.security import ACCESS_COOKIE, API_PATH, AUTH_PATH, REFRESH_COOKIE
from app.services import AuthService, SessionTokens

router = APIRouter(prefix=API_PATH)
auth = APIRouter(prefix="/auth", tags=["authentication"])
Database = Annotated[AsyncSession, Depends(get_db)]


def get_auth(request: Request) -> AuthService:
    return request.app.state.auth


Auth = Annotated[AuthService, Depends(get_auth)]
errors = {status: {"model": ErrorResponse} for status in (401, 403, 409, 413, 422, 429, 500)}


def set_session(response: Response, auth: AuthService, tokens: SessionTokens) -> None:
    remaining = max(0, int((tokens.expires_at - datetime.now(UTC)).total_seconds()))
    options = {"httponly": True, "secure": auth.settings.cookie_secure, "samesite": "lax"}
    response.set_cookie(
        ACCESS_COOKIE, tokens.access, path=API_PATH,
        max_age=min(remaining, auth.settings.access_seconds), **options,
    )
    response.set_cookie(
        REFRESH_COOKIE, tokens.refresh, path=AUTH_PATH, max_age=remaining, **options,
    )


@router.get("/health", response_model=Health)
async def health():
    return Health(status="ok")


@auth.post("/register", status_code=201, response_model=Profile,
           responses={code: errors[code] for code in (403, 409, 413, 422, 429, 500)})
async def register(credentials: Registration, db: Database, service: Auth):
    return await service.register(db, credentials)


@auth.post("/login", response_model=Profile,
           responses={code: errors[code] for code in (401, 403, 413, 422, 429, 500)})
async def login(credentials: Credentials, response: Response, db: Database, service: Auth):
    user, tokens = await service.login(db, credentials)
    set_session(response, service, tokens)
    return user


@auth.post("/refresh", status_code=204,
           responses={code: errors[code] for code in (401, 403, 413, 429, 500)})
async def refresh(request: Request, db: Database, service: Auth):
    tokens = await service.rotate(db, request.cookies.get(REFRESH_COOKIE))
    response = Response(status_code=204)
    set_session(response, service, tokens)
    return response


@auth.post("/logout", status_code=204,
           responses={code: errors[code] for code in (403, 413, 429, 500)})
async def logout(request: Request, db: Database, service: Auth):
    await service.logout(db, request.cookies.get(REFRESH_COOKIE), request.cookies.get(ACCESS_COOKIE))
    response = Response(status_code=204)
    options = {"httponly": True, "secure": service.settings.cookie_secure, "samesite": "lax"}
    response.delete_cookie(ACCESS_COOKIE, path=API_PATH, **options)
    response.delete_cookie(REFRESH_COOKIE, path=AUTH_PATH, **options)
    return response


async def current_user(request: Request, db: Database, service: Auth) -> User:
    return await service.current_user(db, request.cookies.get(ACCESS_COOKIE))


@auth.get("/me", response_model=Profile,
          responses={code: errors[code] for code in (401, 500)})
async def me(user: Annotated[User, Depends(current_user)]):
    return user


router.include_router(auth)
