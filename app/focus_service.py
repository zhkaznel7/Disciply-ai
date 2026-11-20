from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import focus_repository as repo
from app.errors import APIError
from app.focus_calendar import microseconds, validate_dates
from app.focus_schemas import DEFAULT_MINUTES, HistoryFilters, SessionView, StartSession
from app.models import FocusInterval, FocusSession
from app.planning_schemas import Page
from app.repositories import user_timezone

Action = Literal["pause", "resume", "complete", "cancel"]
TRANSITIONS = {
    "active": {"pause": "paused", "complete": "completed", "cancel": "cancelled"},
    "paused": {"resume": "active", "complete": "completed", "cancel": "cancelled"},
}


def now_utc() -> datetime:
    return datetime.now(UTC)


def missing():
    return APIError(404, "not_found", "Resource not found.")


class FocusService:
    def __init__(self, db: AsyncSession, owner: UUID):
        self.db = db
        self.owner = owner

    async def start(self, payload: StartSession) -> SessionView:
        if not await repo.lock_owner(self.db, self.owner):
            raise missing()
        if payload.task_id is not None and not await repo.has_task(self.db, self.owner, payload.task_id):
            raise missing()
        now = now_utc()
        session = FocusSession(
            user_id=self.owner, task_id=payload.task_id, status="active",
            session_type=payload.session_type, started_at=now, updated_at=now,
            planned_minutes=payload.planned_minutes or DEFAULT_MINUTES[payload.session_type],
        )
        self.db.add(session)
        try:
            await self.db.flush()
            self.db.add(FocusInterval(session_id=session.id, started_at=now))
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            state = getattr(exc.orig, "sqlstate", None)
            if state == "23505":
                raise APIError(409, "focus_session_in_progress", "An unfinished session already exists.") from None
            if state == "23503":
                raise missing() from None
            raise
        return self._view(session, 0, now)

    async def _get(self, session_id: UUID, *, lock: bool = False):
        session = await repo.get(self.db, self.owner, session_id, lock=lock)
        if session is None:
            raise missing()
        return session

    async def transition(self, session_id: UUID, action: Action) -> SessionView:
        if not await repo.lock_owner(self.db, self.owner):
            raise missing()
        session = await self._get(session_id, lock=True)
        status = TRANSITIONS.get(session.status, {}).get(action)
        if status is None:
            raise APIError(409, "invalid_focus_transition", "This action is invalid for the session state.")

        interval = await repo.latest_interval(self.db, session.id)
        if interval is None or (interval.ended_at is None) != (session.status == "active"):
            raise RuntimeError("Unfinished focus session has inconsistent intervals")
        now = max(now_utc(), interval.ended_at or interval.started_at, session.updated_at)
        if status in ("completed", "cancelled"):
            now = max(now, session.started_at + timedelta(microseconds=1))
            session.ended_at = now
        if session.status == "active":
            interval.ended_at = now
        elif status == "active":
            self.db.add(FocusInterval(session_id=session.id, started_at=now))
        session.status = status
        session.updated_at = now
        await self.db.flush()
        result = (await self._views([session], now))[0]
        await self.db.commit()
        return result

    @staticmethod
    def _view(session: FocusSession, running: int, now: datetime) -> SessionView:
        elapsed = microseconds((session.ended_at or max(now, session.updated_at)) - session.started_at)
        return SessionView(
            id=session.id, task_id=session.task_id, session_type=session.session_type,
            status=session.status, started_at=session.started_at, ended_at=session.ended_at,
            created_at=session.created_at, updated_at=session.updated_at,
            planned_minutes=session.planned_minutes, actual_running_microseconds=running,
            actual_focused_microseconds=running if session.session_type == "focus" else 0,
            total_paused_microseconds=max(0, elapsed - running),
        )

    async def _views(self, sessions: list[FocusSession], now: datetime) -> list[SessionView]:
        durations = await repo.durations(self.db, sessions, now)
        return [self._view(session, durations.get(session.id, 0), now) for session in sessions]

    async def current(self) -> SessionView | None:
        session = await repo.current(self.db, self.owner)
        return (await self._views([session], now_utc()))[0] if session else None

    async def get(self, session_id: UUID) -> SessionView:
        return (await self._views([await self._get(session_id)], now_utc()))[0]

    async def history(self, filters: HistoryFilters) -> Page[SessionView]:
        zone = None
        if filters.from_date is not None or filters.to_date is not None:
            validate_dates(filters.from_date, filters.to_date)
            zone = (await user_timezone(self.db, self.owner)).key
        sessions, more = await repo.history(self.db, self.owner, filters, zone)
        return Page[SessionView](items=await self._views(sessions, now_utc()),
                                 limit=filters.limit, offset=filters.offset, has_more=more)
