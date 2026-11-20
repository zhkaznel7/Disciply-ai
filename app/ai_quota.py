import asyncio
import hashlib
import json
import logging
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app import ai_repository as repo
from app.ai_provider import MAX_CONTEXT_BYTES, SYSTEM, Provider, ProviderResult
from app.ai_schemas import Selection, Source, UsageView
from app.config import Settings
from app.errors import APIError
from app.focus_service import now_utc
from app.observability import event


class AIQuota:
    def __init__(self, db: AsyncSession, owner: UUID, settings: Settings, provider: Provider | None):
        self.db = db
        self.owner = owner
        self.settings = settings
        self.provider = provider

    async def view(self) -> UsageView:
        day = now_utc().date()
        row = await repo.usage(self.db, self.owner, day)
        return UsageView(
            date_utc=day, requests=row.request_count if row else 0,
            provider_calls=row.provider_calls if row else 0,
            reported_tokens=row.reported_tokens if row else 0,
            budgeted_tokens=row.budgeted_tokens if row else 0,
            request_limit=self.settings.ai_daily_requests, token_limit=self.settings.ai_daily_tokens,
        )

    async def reserve_request(self) -> date:
        day = now_utc().date()
        row = await repo.usage(self.db, self.owner, day, lock=True)
        if row.request_count >= self.settings.ai_daily_requests:
            midnight = datetime.combine(day + timedelta(days=1), time.min, UTC)
            remaining = max(1, int((midnight - now_utc()).total_seconds()) + 1)
            raise APIError(429, "ai_quota_exceeded", "Daily recommendation request limit reached.",
                           {"Retry-After": str(remaining)})
        row.request_count += 1
        await self.db.commit()
        return day

    async def select(self, day: date, context: dict, fallback: Selection) -> tuple[Selection, Source]:
        if self.provider is None:
            return fallback, "rules"
        packed = json.dumps(context, separators=(",", ":"), sort_keys=True)
        size = len(packed.encode())
        if size > MAX_CONTEXT_BYTES:
            return fallback, "rules"
        key = hashlib.sha256(json.dumps(
            [SYSTEM, self.settings.ai_provider_url, self.settings.ai_model,
             self.settings.ai_max_output_tokens, packed]
        ).encode()).hexdigest()
        reservation = size + len(SYSTEM.encode()) + 256 + self.settings.ai_max_output_tokens
        row = await repo.usage(self.db, self.owner, day, lock=True)
        if key in row.selections:
            cached = row.selections[key]
            await self.db.commit()
            return (Selection.model_validate(cached), "cache") if cached else (fallback, "rules")
        if row.budgeted_tokens + reservation > self.settings.ai_daily_tokens:
            await self.db.commit()
            return fallback, "rules"

        row.provider_calls += 1
        row.budgeted_tokens += reservation
        row.selections = {**row.selections, key: None}
        await self.db.commit()

        try:
            async with asyncio.timeout(self.settings.ai_timeout_seconds):
                result = await self.provider.select(packed)
        except Exception:
            result = ProviderResult(None)
        selection = result.selection
        tasks = context.get("tasks", [])
        if selection is not None and (
            not set(selection.actions) <= set(context["allowed_actions"])
            or len(set(selection.actions)) != len(selection.actions)
            or len(set(selection.task_refs)) != len(selection.task_refs)
            or not set(selection.task_refs) <= set(range(1, len(tasks) + 1))
            or (selection.task_refs and sum(tasks[ref - 1]["minutes"] for ref in selection.task_refs)
                > context["available_minutes"])
        ):
            selection = None

        if selection is None:
            event("ai_provider_fallback", level=logging.WARNING, reason="unusable_response")

        row = await repo.usage(self.db, self.owner, day, lock=True)
        if result.tokens is not None:
            row.reported_tokens += result.tokens
            row.budgeted_tokens += result.tokens - reservation
        if selection is not None:
            row.selections = {**row.selections, key: selection.model_dump()}
        await self.db.commit()
        return (selection, "provider") if selection is not None else (fallback, "rules")
