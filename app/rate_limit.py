import asyncio
import hmac
from ipaddress import IPv6Address, ip_address, ip_network

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from app.config import Settings
from app.models import RequestRate
from app.security import API_PATH, AUTH_PATH


def limit_bucket(path: str, method: str, settings: Settings) -> tuple[str, int] | None:
    if method == "POST":
        if path.startswith(f"{AUTH_PATH}/"):
            return "auth", settings.auth_attempts_per_minute
        if path.startswith(f"{API_PATH}/ai/"):
            return "ai", settings.ai_requests_per_minute
    if method == "GET" and (
        path.startswith(f"{API_PATH}/analytics/")
        or path in {f"{API_PATH}/focus/{name}" for name in ("summary", "daily", "weekly", "monthly", "by-task")}
        or path in {f"{API_PATH}/habits/{name}" for name in ("summary", "today", "weekly", "monthly")}
        or (path.startswith(f"{API_PATH}/habits/") and path.endswith("/stats"))
    ):
        return "analytics", settings.analytics_requests_per_minute
    return None


def fingerprint(peer: str, settings: Settings) -> bytes:
    try:
        address = ip_address(peer)
        if isinstance(address, IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        identity = str(ip_network((address, 64), strict=False)) if address.version == 6 else str(address)
    except ValueError:
        identity = "unknown"
    return hmac.digest(bytes.fromhex(settings.jwt_secret.get_secret_value()),
                       f"rate-limit:{identity}".encode(), "sha256")


async def admit(factory, settings: Settings, peer: str, bucket: str, limit: int) -> bool:
    window = sa.cast(sa.func.floor(sa.extract("epoch", sa.func.statement_timestamp()) / 60), sa.BigInteger)
    query = insert(RequestRate).values(
        window=window, bucket=bucket, fingerprint=fingerprint(peer, settings), hits=1,
    ).on_conflict_do_update(
        index_elements=[RequestRate.window, RequestRate.bucket, RequestRate.fingerprint],
        set_={"hits": RequestRate.hits + 1}, where=RequestRate.hits < limit,
    ).returning(RequestRate.hits)
    async with asyncio.timeout(settings.readiness_timeout_seconds):
        async with factory.begin() as session:
            return await session.scalar(query) is not None
