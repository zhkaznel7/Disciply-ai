import json
import logging
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import MutableHeaders

logger = logging.getLogger("uvicorn.error.disciply")
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def event(name: str, *, level: int = logging.INFO, **fields) -> None:
    logger.log(level, json.dumps({"event": name, "request_id": request_id.get(), **fields}))


class RequestTelemetry:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        token = request_id.set(uuid4().hex)
        start = perf_counter()
        status = None

        async def respond(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id.get()
            await send(message)

        try:
            await self.app(scope, receive, respond)
        finally:
            method = scope["method"]
            event("http_request", status=status,
                  method=method if method in {"GET", "HEAD", "OPTIONS", "POST", "PATCH", "PUT", "DELETE"} else "OTHER",
                  route=getattr(scope.get("route"), "path", None),
                  duration_ms=round((perf_counter() - start) * 1000, 2))
            request_id.reset(token)
