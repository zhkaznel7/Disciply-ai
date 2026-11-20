from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app import ai_repository as repo
from app.ai_quota import AIQuota
from app.ai_schemas import (
    Action, Advice, CoachRequest, CoachView, FocusBlock, Metrics, PlanRequest, PlanTask, PlanView,
    ReviewView, Selection,
)
from app.focus_calendar import day_windows
from app.focus_service import now_utc
from app.habit_schedule import progress
from app.productivity_schemas import ProductivityDay
from app.productivity_service import ProductivityService
from app.repositories import user_timezone

TIPS: dict[Action, str] = {
    "small_step": "Pick one priority task and define the smallest next step.",
    "habit_cue": "Attach a scheduled habit to a routine you already do.",
    "focus_block": "Try one distraction-free focus block and take a short break afterward.",
    "goal_step": "Choose one action that moves an active goal forward.",
    "reduce_load": "Move optional work to your backlog and keep the nearest deadlines visible.",
    "protect_time": "Protect an existing time slot before adding more work.",
    "keep_routine": "Keep the routine that is working and review one small improvement.",
    "review_energy": "Notice when you felt most able to focus and try planning around that time.",
}


def summarize(days: list[ProductivityDay]) -> Metrics:
    scores = [day.discipline_score.value for day in days if day.discipline_score.value is not None]
    return Metrics(
        tasks=progress(sum(day.tasks.completed for day in days), sum(day.tasks.target for day in days)),
        habits=progress(sum(day.habits.completed for day in days), sum(day.habits.target for day in days)),
        focus_minutes=round(sum(day.focus.focus_microseconds for day in days) / 60_000_000, 6),
        average_discipline_score=round(sum(scores) / len(scores), 2) if scores else None,
        scored_days=len(scores), observed_days=len(days),
    )


def rules(facts: Metrics, goals: int = 0) -> list[Action]:
    result: list[Action] = []
    if facts.tasks.target and facts.tasks.completed < facts.tasks.target:
        result.append("small_step")
    if facts.habits.target and facts.habits.completed < facts.habits.target:
        result.append("habit_cue")
    if facts.focus_minutes < 25:
        result.append("focus_block")
    if goals:
        result.append("goal_step")
    return result or ["keep_routine"]


def advice(actions: list[Action]) -> list[Advice]:
    return [Advice(code=action, text=TIPS[action]) for action in actions]


class AIService:
    def __init__(self, db: AsyncSession, owner: UUID, quota: AIQuota):
        self.db = db
        self.owner = owner
        self.quota = quota
        self.reports = ProductivityService(db, owner)

    async def local_calendar(self):
        zone = await user_timezone(self.db, self.owner)
        return zone, now_utc().astimezone(zone).date()

    async def period(self, monthly: bool):
        _, today = await self.local_calendar()
        start = today.replace(day=1) if monthly else today - timedelta(days=today.weekday())
        report = await self.reports.range(start, today)
        return report, summarize(report.days)

    async def coach(self, payload: CoachRequest) -> CoachView:
        usage_day = await self.quota.reserve_request()
        report, facts = await self.period(False)
        goals, average = await repo.goals(self.db, self.owner)
        actions = rules(facts, goals)
        context = {"feature": "coach", "weekly": facts.model_dump(),
                   "score_today": report.days[-1].discipline_score.value,
                   "active_goals": goals, "average_goal_progress": average}
        if payload.include_reflection_mood:
            mood = await repo.reflection_mood(self.db, self.owner, report.from_date, report.to_date)
            if mood["entries"]:
                context["reflection_mood"] = mood
                actions.append("review_energy")
        context["allowed_actions"] = actions
        selection, source = await self.quota.select(
            usage_day, context, Selection(actions=actions[:4], task_refs=[]),
        )
        return CoachView(
            date=report.to_date, source=source, weekly_facts=facts,
            discipline_score_today=report.days[-1].discipline_score.value,
            active_goals=goals, average_goal_progress=average,
            suggestions=advice(selection.actions),
        )

    async def plan(self, request: PlanRequest) -> PlanView:
        usage_day = await self.quota.reserve_request()
        zone, today = await self.local_calendar()
        now = now_utc()
        _, _, tomorrow = day_windows(today, today, zone)[-1]
        tasks, count = await repo.candidate_tasks(self.db, self.owner, today, now, tomorrow)
        recent = summarize((await self.reports.range(today - timedelta(days=6), today)).days)
        block = 15 if recent.focus_minutes < 25 else 25
        views = []
        context_tasks = []
        for index, task in enumerate(tasks, 1):
            scheduled_duration = task.scheduled_on == today and task.scheduled_start_at and task.scheduled_end_at
            length = (
                max(1, (task.scheduled_end_at - task.scheduled_start_at
                        + timedelta(minutes=1, microseconds=-1)) // timedelta(minutes=1))
                if scheduled_duration else block
            )
            reason = ("overdue" if task.due_at and task.due_at <= now else
                      "due_today" if task.due_at and task.due_at < tomorrow else
                      "scheduled_today" if task.scheduled_on == today else "priority")
            views.append(PlanTask(id=task.id, title=task.title, priority=task.priority, minutes=length,
                                  estimated=not bool(scheduled_duration), reason=reason))
            context_tasks.append({"ref": index, "priority": task.priority, "reason": reason, "minutes": length})
        workload = sum(task.minutes for task in views)
        overload = workload > request.available_minutes or count > len(views)
        actions: list[Action] = ["reduce_load", "protect_time"] if overload else ["protect_time", "focus_block"]
        if not tasks:
            actions = ["keep_routine"]
        fallback_refs = []
        remaining = request.available_minutes
        for index, task in enumerate(views, 1):
            if task.minutes <= remaining and len(fallback_refs) < 5:
                fallback_refs.append(index)
                remaining -= task.minutes
        context = {
            "feature": "plan", "tasks": context_tasks, "available_minutes": request.available_minutes,
            "recent_focus_minutes": recent.focus_minutes, "overload": overload, "allowed_actions": actions,
        }
        selection, source = await self.quota.select(
            usage_day, context, Selection(actions=actions, task_refs=fallback_refs),
        )
        return PlanView(
            date=today, source=source, available_minutes=request.available_minutes,
            estimated_workload_minutes=workload, candidate_count=count, overload=overload, tasks=views,
            focus_block_minutes=block,
            focus_blocks=[
                FocusBlock(
                    task_id=views[ref - 1].id, minutes=min(block, views[ref - 1].minutes),
                    scheduled_start_at=tasks[ref - 1].scheduled_start_at
                    if tasks[ref - 1].scheduled_on == today and tasks[ref - 1].scheduled_start_at
                    and tasks[ref - 1].scheduled_start_at >= now else None,
                )
                for ref in selection.task_refs
            ],
            suggestions=advice(selection.actions),
        )

    async def review(self) -> ReviewView:
        usage_day = await self.quota.reserve_request()
        _, today = await self.local_calendar()
        monday = today - timedelta(days=today.weekday())
        report = await self.reports.range(monday - timedelta(days=7), today)
        current = summarize(report.days[7:])
        previous = summarize(report.days[:today.weekday() + 1])
        actions = rules(current)
        context = {"feature": "review", "current": current.model_dump(),
                   "previous": previous.model_dump(), "allowed_actions": actions}
        selection, source = await self.quota.select(
            usage_day, context, Selection(actions=actions, task_refs=[]),
        )
        achievements = [
            key for key, value in (
                ("tasks_completed", current.tasks.completed), ("habits_completed", current.habits.completed),
                ("focus_recorded", current.focus_minutes),
            ) if value
        ]
        a, b = current.average_discipline_score, previous.average_discipline_score
        return ReviewView(
            from_date=monday, to_date=today, source=source, current=current, previous=previous,
            focus_minutes_change=round(current.focus_minutes - previous.focus_minutes, 6)
            if current.scored_days and previous.scored_days else None,
            task_completion_change=round(current.tasks.completion_percentage - previous.tasks.completion_percentage, 2)
            if current.tasks.target and previous.tasks.target else None,
            habit_completion_change=round(current.habits.completion_percentage - previous.habits.completion_percentage, 2)
            if current.habits.target and previous.habits.target else None,
            discipline_score_change=round(a - b, 2) if a is not None and b is not None else None,
            achievements=achievements, areas_for_improvement=advice(actions),
            priorities=advice(selection.actions),
        )
