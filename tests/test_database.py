from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import DailyStatistic, FocusSession, Goal, Habit, HabitLog, Project, Task, User


async def test_constraints_and_ownership(app):
    async with app.state.sessions() as db:
        async with db.begin():
            first = User(email=f"{uuid4()}@example.com", password_hash="unused fixture")
            second = User(email=f"{uuid4()}@example.com", password_hash="unused fixture")
            db.add_all([first, second])
            await db.flush()
            project = Project(title="Project", user_id=first.id)
            habit = Habit(title="Habit", user_id=first.id)
            goal = Goal(title="Goal", user_id=first.id)
            db.add_all([project, habit, goal])
            await db.flush()
            day = date(2026, 1, 1)
            db.add_all([
                HabitLog(user_id=first.id, habit_id=habit.id, logged_on=day),
                DailyStatistic(user_id=first.id, statistic_on=day),
            ])

        first_id, project_id = first.id, project.id
        now = datetime.now(UTC)
        invalid_records = [
            Task(user_id=second.id, project_id=project.id, title="Cross-owner task"),
            Task(user_id=second.id, goal_id=goal.id, title="Cross-owner goal"),
            Task(user_id=first.id, title="No scheduled date", scheduled_start_at=now),
            Task(user_id=first.id, title="End precedes start", scheduled_on=day,
                 scheduled_start_at=now, scheduled_end_at=now - timedelta(seconds=1)),
            Project(user_id=first.id, title="Invalid dates",
                    starts_on=day, target_on=day - timedelta(days=1)),
            Goal(user_id=first.id, title="Invalid progress", progress=101),
            Goal(user_id=first.id, title="Missing completion timestamp", progress=100),
            HabitLog(user_id=second.id, habit_id=habit.id, logged_on=day),
            HabitLog(user_id=first.id, habit_id=habit.id, logged_on=day),
            DailyStatistic(user_id=first.id, statistic_on=day),
            DailyStatistic(user_id=second.id, statistic_on=day, discipline_score=101),
            FocusSession(user_id=first.id, started_at=now, ended_at=now - timedelta(seconds=1)),
        ]
        for record in invalid_records:
            with pytest.raises(IntegrityError):
                async with db.begin():
                    db.add(record)
                    await db.flush()

        async with db.begin():
            db.add(Task(user_id=first_id, project_id=project_id, title="Owned task"))
