import asyncio
from pathlib import Path

from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from app.errors import ErrorResponse, error_response
from app.security import API_PATH

router = APIRouter(prefix=API_PATH)


def expected_heads() -> frozenset[str]:
    root = Path(__file__).resolve().parent.parent
    return frozenset(ScriptDirectory(str(root / "migrations")).get_heads())


@router.get("/health/ready", responses={503: {"model": ErrorResponse}})
async def readiness(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        async with asyncio.timeout(request.app.state.readiness_timeout):
            async with request.app.state.sessions() as db:
                heads = await db.scalars(text("SELECT version_num FROM alembic_version"))
                if set(heads) == request.app.state.alembic_heads:
                    return {"status": "ready"}
    except Exception:
        pass
    return error_response(503, "not_ready", "Service is not ready.")
