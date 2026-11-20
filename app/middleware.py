import logging

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings
from app.errors import error_response
from app.observability import event
from app.rate_limit import admit, limit_bucket
from app.security import AUTH_PATH

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class RequestGuards:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings
        self.origins = frozenset(settings.cors_origins)

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
            protected = limit_bucket(path, scope["method"], self.settings)
            if scope["method"] not in SAFE_METHODS:
                origins = headers.getlist("origin")
                if len(origins) != 1 or origins[0] not in self.origins:
                    return await reject(403, "origin_denied", "Request origin is not allowed.")
            if protected:
                bucket, limit = protected
                client = scope.get("client")
                try:
                    allowed = await admit(
                        scope["app"].state.sessions, self.settings,
                        client[0] if client else "unknown", bucket, limit,
                    )
                except Exception as exc:
                    event("rate_limit_unavailable", level=logging.WARNING, error_type=type(exc).__name__)
                    return await reject(503, "temporarily_unavailable", "Service is temporarily unavailable.",
                                        {"Retry-After": "5"})
                if not allowed:
                    return await reject(429, "rate_limited", "Too many requests.", {"Retry-After": "60"})

            if scope["method"] not in SAFE_METHODS:
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
            event("request_failed", level=logging.ERROR, error_type=type(exc).__name__)
            if started:
                return
            return await reject(500, "internal_error", "An internal error occurred.")
