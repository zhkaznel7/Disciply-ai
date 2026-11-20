import logging
from time import monotonic

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings
from app.errors import error_response
from app.security import AUTH_PATH

logger = logging.getLogger(__name__)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class RequestGuards:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings
        self.origins = frozenset(settings.cors_origins)
        self.window = -1
        self.attempts: dict[str, int] = {}

    def allow_auth(self, client: str) -> bool:
        window = int(monotonic() // 60)
        if window != self.window:
            self.window = window
            self.attempts.clear()
        if client not in self.attempts and len(self.attempts) >= 4096:
            return False
        used = self.attempts.get(client, 0)
        if used >= self.settings.auth_attempts_per_minute:
            return False
        self.attempts[client] = used + 1
        return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        headers = Headers(scope=scope)
        path = scope["path"]
        started = False

        async def send_secure(message):
            nonlocal started
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Content-Type-Options"] = "nosniff"
                if path.startswith(f"{AUTH_PATH}/"):
                    response_headers["Cache-Control"] = "no-store"
                started = True
            await send(message)

        async def reject(status, code, message, extra=None):
            await error_response(status, code, message, extra)(scope, receive, send_secure)

        try:
            if scope["method"] not in SAFE_METHODS:
                origins = headers.getlist("origin")
                if len(origins) != 1 or origins[0] not in self.origins:
                    return await reject(403, "origin_denied", "Request origin is not allowed.")
                if path.startswith(f"{AUTH_PATH}/"):
                    client = scope.get("client")
                    if not self.allow_auth(client[0] if client else "unknown"):
                        return await reject(
                            429, "rate_limited", "Too many authentication requests.",
                            {"Retry-After": "60"},
                        )

                buffered = bytearray()
                while True:
                    incoming = await receive()
                    if incoming["type"] == "http.disconnect":
                        return
                    chunk = incoming.get("body", b"")
                    if len(buffered) + len(chunk) > self.settings.max_body_bytes:
                        return await reject(413, "body_too_large", "Request body is too large.")
                    buffered.extend(chunk)
                    if not incoming.get("more_body", False):
                        break

                delivered = False

                async def bounded_receive():
                    nonlocal delivered
                    if delivered:
                        return await receive()
                    delivered = True
                    return {"type": "http.request", "body": bytes(buffered), "more_body": False}

                return await self.app(scope, bounded_receive, send_secure)
            return await self.app(scope, receive, send_secure)
        except Exception as exc:
            logger.error("Request failed (%s)", type(exc).__name__)
            if started:
                raise
            return await reject(500, "internal_error", "An internal error occurred.")
