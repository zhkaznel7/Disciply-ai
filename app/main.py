import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware

from app.api import router
from app.config import Settings
from app.db import make_engine
from app.errors import APIError, error_response
from app.focus_api import router as focus_router
from app.habit_api import router as habit_router
from app.middleware import RequestGuards
from app.planning_api import router as planning_router
from app.security import API_PATH, Passwords
from app.services import AuthService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    development = settings.environment == "development"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings)
        try:
            try:
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
            except Exception:
                raise RuntimeError("Database connection failed during startup") from None
            app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
            passwords = Passwords()
            dummy_hash = await passwords.hash(secrets.token_urlsafe(32))
            app.state.auth = AuthService(settings, passwords, dummy_hash)
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="Disciply AI", version="1.0.0", lifespan=lifespan,
        docs_url=f"{API_PATH}/docs" if development else None,
        openapi_url=f"{API_PATH}/openapi.json" if development else None,
        redoc_url=None, swagger_ui_oauth2_redirect_url=None,
        redirect_slashes=False,
    )
    app.include_router(router)
    app.include_router(planning_router)
    app.include_router(habit_router)
    app.include_router(focus_router)

    @app.exception_handler(APIError)
    async def handle_api_error(request: Request, exc: APIError):
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError):
        return error_response(422, "invalid_input", "Request validation failed.")

    @app.exception_handler(HTTPException)
    async def handle_http(request: Request, exc: HTTPException):
        code, message = {
            400: ("bad_request", "Invalid request."),
            404: ("not_found", "Resource not found."),
            405: ("method_not_allowed", "Method not allowed."),
        }.get(exc.status_code, ("request_failed", "Request failed."))
        return error_response(exc.status_code, code, message, exc.headers)

    app.add_middleware(RequestGuards, settings=settings)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type"],
    )
    return app
