# API v1

All API routes are under `/api/v1`. Browser clients send requests with credentials enabled. Send JSON with `Content-Type: application/json` for registration and login. Each POST must carry an allowed browser Origin. Browsers supply the Origin header automatically. Command-line clients must set it explicitly.

| Method | Path | Success | Behavior |
| --- | --- | --- | --- |
| GET | /api/v1/health | 200 | Process liveness with `{"status":"ok"}`. Startup verifies database connectivity. |
| POST | /api/v1/auth/register | 201 | Creates an account with `email` and `password`, initializes settings, returns the profile. |
| POST | /api/v1/auth/login | 200 | Verifies `email` and `password`, sets both cookies, returns the profile. |
| POST | /api/v1/auth/refresh | 204 | Rotates the refresh credential and replaces both cookies. |
| POST | /api/v1/auth/logout | 204 | Revokes the session when identified and clears both cookies. Safe to repeat. |
| GET | /api/v1/auth/me | 200 | Returns the session owner's profile. |

Profiles contain `id`, `email`, and `created_at`. Registration accepts passwords of 15–128 characters. Email is normalized case-insensitively. Login errors for unknown email and incorrect passwords are identical. Registration returns 409 when the normalized email already exists.

Access cookie path is `/api/v1`. Refresh cookie path is `/api/v1/auth`. Responses keep credentials in cookie headers and use `Cache-Control: no-store` on authentication routes. Refresh has a fixed absolute session lifetime of 30 days by default. Serialize refresh calls across browser tabs and prompt for login after a 401 from the refresh endpoint.

Application errors use `{"error":{"code":"unauthorized","message":"Authentication failed."}}`. Expect 401 for invalid credentials, 403 for a missing or untrusted Origin on POST, 409 for a registration conflict, 413 for an oversized request, 422 for invalid input, and 429 with `Retry-After` for per-IP auth throttling.

Swagger UI is available at [localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs) in development.

## Goals, projects, tasks, and planning

All routes in this section require an authenticated session. Mutations require an allowed Origin. Foreign records and relationship IDs return the same 404 as missing records. A 409 on DELETE means a goal or project still has dependent records. Clear the corresponding relationship with PATCH before retrying.

| Relative path under /api/v1 | Methods | Filters and behavior |
| --- | --- | --- |
| /goals | GET, POST | Filter by `status` and exact `target_on`. |
| /goals/{goal_id} | GET, PATCH, DELETE | Update progress and status through PATCH. |
| /projects | GET, POST | Filter by `status`. |
| /projects/{project_id} | GET, PATCH, DELETE | Use `goal_id` to link or unlink the project. |
| /projects/{project_id}/tasks | GET | Page through tasks assigned to this project. |
| /tasks | GET, POST | Filter by `status`, `priority`, `project_id`, `goal_id`, exact `scheduled_on`, and `overdue`. |
| /tasks/{task_id} | GET, PATCH, DELETE | Set status to `completed` to finish or `open` to reopen. |
| /planner/daily | GET | Accepts `date=YYYY-MM-DD`. Defaults to the account's local today. |
| /planner/weekly | GET | Accepts `start_date=YYYY-MM-DD`, defaults to local today, and normalizes to Monday. |

POST returns 201 and the created resource. GET and PATCH return 200. DELETE returns 204. Collection responses contain `items`, `limit`, `offset`, and `has_more`. Collections default to `limit=50`, accept 1–200, and accept offsets from 0–100000. Lists sort newest first with ID as the tie-breaker. Filters combine with AND. An overdue task is open and has a due timestamp earlier than the current instant.

### Resource fields

Create requests require `title` (1–200 characters) and accept `description` (up to 4000 characters) plus the write fields below. PATCH accepts a subset of the create fields. Explicit null clears a nullable field. Responses include the resource ID, title, description, the fields below, and `created_at` and `updated_at`. Ownership and server-generated timestamps cannot be set in a request.

| Resource | Write fields | Server-generated fields and behavior |
| --- | --- | --- |
| Goal | `target_on`, `priority` (0–3), `progress` (0–100), `status` (`active` or `completed`) | Progress of 100 sets `completed_at`. Reopening via status alone resets progress to 0. Explicit progress and status must agree. Defaults to active with progress 0 and priority 0. |
| Project | `goal_id`, `starts_on`, `target_on`, `status` (`active` or `archived`) | Setting status controls `archived_at`. Target date must be on or after start date when both are set. Defaults to active. |
| Task | `project_id`, `goal_id`, `scheduled_on`, `scheduled_start_at`, `scheduled_end_at`, `due_at`, `priority` (0–3), `status` (`open` or `completed`) | Completion sets `completed_at` once. Reopening clears it. Defaults to open and priority 0. A direct goal takes precedence over the project's goal for goal filtering. |

Date fields use `YYYY-MM-DD`. Task timestamps require an ISO 8601 UTC offset or `Z`. A timed task requires `scheduled_on` to match its start date in the account timezone. An end time requires a start time and must follow it. A date without times creates an untimed task. Clear the date and both times together to unschedule a timed task.

### Planner responses

Daily returns `date`, `timezone`, and `tasks`. Weekly returns `start_date`, `timezone`, and `days` with exactly seven Monday–Sunday entries. Each entry contains a `date` and a `tasks` array. Both responses include `limit`, `offset`, and `has_more`. Weekly pagination applies to all tasks in the week, so days with no matching tasks on the requested page have empty arrays.

Tasks are grouped by the stored local schedule date. Each day orders timed tasks by start instant, then untimed tasks by descending priority. Equal start times use priority, creation time, and ID as tie-breakers. Historical schedule dates remain stable after timezone changes. The planner uses the saved IANA timezone, with UTC as the default.

## Habits and streaks

All habit routes use the same authenticated session and Origin rules as planning. The paths below are relative to `/api/v1/habits`. Lists use the existing `items`, `limit`, `offset`, and `has_more` envelope and limits.

| Path | Methods | Behavior |
| --- | --- | --- |
| / | GET, POST | List habits, optionally filtering by `status=active` or `status=archived`, or create a habit. Use `/api/v1/habits` without a trailing slash. |
| /{habit_id} | GET, PATCH, DELETE | Read, edit, archive or restore through `status`, or permanently delete the habit and its logs. |
| /{habit_id}/logs | GET, POST | List newest local dates first with optional inclusive `from_date` and `to_date`, or add a log. |
| /{habit_id}/logs/{log_id} | PATCH, DELETE | Replace the completion count or remove the log. |
| /{habit_id}/stats | GET | Current and longest streak, streak unit, last completed date, lifetime completion percentage, and week and month progress. |
| /summary | GET | Active habit count, completed habits today, and aggregate today, week, and month rates. |
| /today | GET | Active habit records with today's count, scheduled flag, and completed flag. |
| /weekly, /monthly | GET | Active habit records with progress for the current local week or calendar month. |

Example create body:

```json
{"title":"Read","description":"Pages read","frequency":"weekdays","weekdays":[0,2,4],"target_count":10,"preferred_time":"19:30","starts_on":"2026-01-05"}
```

Use `frequency: "daily"` for every day, `"weekdays"` for distinct days numbered Monday 0 through Sunday 6, or `"weekly"` with `weekly_target` of 1–7 distinct completion days per week. A log is complete when its count meets the daily `target_count`, even for weekly habits. Counts and daily targets accept integers from 1 to 1,000,000 and default to 1. A preferred time is a local wall-clock time. Dates default to the account's local today for habit creation and log creation. For example, POST `{"count":10}` to the habit's logs and PATCH `{"count":12}` to change that log. Responses include the log ID, habit ID, local `date`, `count`, `created_at`, and `updated_at`. Progress responses contain `completed`, `target`, and `completion_percentage` on a 0–100 scale, for example `{"completed":2,"target":3,"completion_percentage":66.67}`. An empty target yields zero percent.

Create returns 201, reads and updates return 200, and deletes return 204. A missing or inaccessible ID returns 404, including a log ID under the wrong habit. Invalid schedules, dates outside the eligible range, and invalid counts return 422. Duplicate-date creation, archived-habit log writes, and schedule changes while logs exist return 409. Archived habits retain readable logs and statistics. Restoring permits writes and includes elapsed dates in streak calculations.

### Calendar and streak rules

- Local dates use the account's saved IANA timezone, defaulting to UTC. Stored log dates remain stable across timezone changes. Logs must be on or after the habit start, on a scheduled date, and on or before local today.
- Daily streaks count consecutive completed dates. Selected-weekday streaks count consecutive completed scheduled dates and skip other weekdays. An unfinished scheduled date today keeps a streak alive. If that date remains incomplete tomorrow, the gap breaks it.
- Weekly streaks count consecutive Monday–Sunday weeks meeting the weekly target. The first week caps the target at the number of days available after habit start. An unfinished current week keeps the previous streak alive until the week ends.
- Daily and selected-weekday rates divide completed dates by scheduled dates through today. Weekly-habit rates sum completed days capped at each week’s quota. In monthly progress, week segments are clipped to the calendar month and to the habit start. An ongoing week includes its quota even while some of its days are still ahead. Future weeks are excluded.
- Today's rate counts habits due today. A weekly habit is due while its quota was still unmet before today. `completed_habits_today` counts all active habits that met their daily count today, including extra completions after a weekly quota was met. Aggregate rates weight each completion opportunity equally.
- Frequency, weekdays, weekly target, target count, and start date can change only while a habit has no logs. An archived habit's statistics use its archive date as the cutoff. A restored habit uses local today.

## Focus sessions and Pomodoro

All paths below are relative to `/api/v1/focus`. Requests require an authenticated session, and POST requests require an allowed Origin.

| Path | Methods | Behavior |
| --- | --- | --- |
| /sessions | POST, GET | Start a session or page through history, most recent start first. Optional filters include `status`, `session_type`, `from_date`, and `to_date`. Dates filter the local start date and are inclusive. |
| /sessions/current | GET | Return the active or paused session, or JSON `null`. |
| /sessions/{session_id} | GET | Return the specified session. |
| /sessions/{session_id}/{action} | POST | Use `pause`, `resume`, `complete`, or `cancel`. |
| /summary | GET | Today's, this week's, and this month's focus metrics, plus the Pomodoro recommendation. |
| /daily, /weekly, /monthly | GET | Period totals plus daily rows, including empty days. Accept optional `date=YYYY-MM-DD`, defaulting to local today. Weeks start Monday. |
| /by-task | GET | Completed focus time grouped by task. Accepts inclusive `from_date` and `to_date`, up to 366 days. Defaults to the month-to-date, or the start of the supplied end date's month. Uses the standard pagination envelope and sorts by focus time descending. |

Start with a JSON body such as `{"session_type":"focus","planned_minutes":25}`. The types `focus`, `short_break`, and `long_break` default to 25, 5, and 15 minutes. Override the duration per start with an integer from 1 through 1440. An optional `task_id` must belong to the account. Deleting the task leaves the session intact and makes its task ID null. Sessions never change task status or start another timer.

Start returns 201. Other successful operations return 200. Session responses include `id`, `task_id`, `session_type`, `status`, `planned_minutes`, `started_at`, `ended_at`, `created_at`, and `updated_at`. Server-calculated fields are `actual_running_microseconds`, `actual_focused_microseconds` (zero for breaks), and `total_paused_microseconds`. A timer can complete before or after its planned duration. The server records elapsed time from UTC timestamps and excludes pauses from running time.

Active sessions can be paused, completed, or cancelled. Paused sessions can be resumed, completed, or cancelled. Completed and cancelled sessions are terminal. A second unfinished session or an invalid transition returns 409. Foreign and missing session or task IDs both return 404. Invalid inputs return 422.

The recommendation requests a long break after four completed focus sessions since the last completed long break. Before that threshold, it recommends a short break after a completed focus session and focus after a completed break or with no history. Completing a long break resets the count. Cancelled sessions do not advance the cycle.

Analytics include completed sessions only. Cancelled sessions retain their elapsed time in history and contribute zero to analytics. Focus and break totals sum running intervals separately, splitting intervals at local date boundaries using the account's IANA timezone. Session counts and average full focus duration are attributed to the local completion date. The average covers completed focus sessions only. Period responses include exact integer microseconds and minutes rounded to six decimals. A null task group includes unlinked sessions and sessions whose tasks were deleted. Analytics are read-only.

## Daily productivity and evening reflections

All endpoints require an authenticated session. Analytics return the account's IANA timezone and use local calendar dates. PUT and DELETE require an allowed Origin.

| Method and path | Behavior |
| --- | --- |
| GET /api/v1/analytics/daily | Optional `date=YYYY-MM-DD`. Defaults to local today. |
| GET /api/v1/analytics/range | Requires inclusive `from_date` and `to_date`. Returns up to 31 daily rows in date order. |
| GET /api/v1/reflections/{day} | Returns the owner's entry or 404. |
| PUT /api/v1/reflections/{day} | Creates or replaces the entry for the local date. Returns 200 with the same entry ID on replacement. |
| DELETE /api/v1/reflections/{day} | Deletes the entry and returns 204. A missing entry returns 404. |

Report dates and reflection dates cannot be in the future. A reflection body can be `{"notes":"Focused well after lunch","mood":4}`. Notes must contain 1–4000 characters after trimming. Mood is optional and, when supplied, must be an integer from 1 to 5. PUT with an omitted or null mood clears it. Analytics expose only `has_evening_reflection`, and reflection responses use `Cache-Control: no-store`.

Daily rows contain `tasks` and `habits` with `target` (the scheduled count), `completed`, and `completion_percentage`. Only tasks scheduled for the date count. A task earns credit if its current completion timestamp is on or before that local date. Habits use the same due rules as Phase 3, including the Monday-based weekly quota. A currently archived habit contributes only on dates before its local archive date. The `focus` object uses the existing focus report format. Completed sessions contribute running time to each local date they overlap, and completed focus session counts are attributed to their local end date.

### Discipline Score v1

The score is the normalized weighted mean of applicable components, rounded to the nearest integer with ties rounded up. Tasks and habits have weight 40 each and use the exact completion ratios. A category with zero scheduled items is omitted. Focus has weight 20 and divides actual focus time by 25 minutes, capped at 100 percent. Focus participates whenever the day has scheduled work or actual focus time. A day with neither returns a null score, including days with only a reflection or break. For example, half the tasks, half the habits, and 5 minutes of focus yield 44. The breakdown exposes the version, each base weight, applicability, component percentages, and the focus target. Reflections and mood have no score weight.

Reports use current source records. Rescheduling or reopening a task, correcting a log, or restoring a habit can change a past report. Archive and restore intervals are unavailable in the current habit schema.

## Productivity coach and smart planning

These routes require an authenticated session. POST requests require an allowed Origin.

| Method and path | Behavior |
| --- | --- |
| GET /api/v1/ai/status | Reports whether the provider is configured and whether rule-based mode is available. |
| GET /api/v1/ai/usage | Returns this user's UTC-day request count, provider attempts, reported tokens, and charged or reserved token budget. |
| POST /api/v1/ai/coach | Accepts `{}` or `{"include_reflection_mood":true}`. Returns measured weekly facts, current score, goal progress, and separately labeled suggestions. |
| POST /api/v1/ai/daily-plan | Accepts `{}` or `{"available_minutes":90}`. Returns ranked tasks, an estimated workload, overload flag, and suggested focus blocks. |
| POST /api/v1/ai/weekly-review | Returns week-to-date measurements, matched weekdays from the previous week, supported achievements, and suggestions for next week. |
| GET /api/v1/analytics/weekly | Returns local Monday-to-today productivity metrics. |
| GET /api/v1/analytics/monthly | Returns local month-to-date productivity metrics. |
| GET /api/v1/analytics/insights | Returns rule-based insights without using provider quota. |

Suggestions include an action code and short vetted text, for example `{"code":"focus_block","text":"Try one distraction-free focus block and take a short break afterward."}`. Source is `rules`, `provider`, or `cache`. Measurements always come from application records. Reviews use null comparisons when the required measurements are absent. The current day may be partial, and historical reports still reflect edits to source records.

Planning ranks overdue tasks first, then tasks due today, tasks scheduled today, and remaining incomplete tasks. Within each group it considers priority, deadline, and schedule. The response displays up to 20 candidates, flags truncation through the candidate count and overload flag, and estimates workload for the displayed tasks. A timed slot today supplies an estimate from the existing schedule. Other tasks use a 15- or 25-minute estimate based on recent focus activity. Suggested focus blocks preserve an existing upcoming start when available and otherwise have a null start. They do not reserve calendar time or alter records.

A request limit breach returns 429. Provider failures, invalid selections, unavailable token budget, or concurrent identical outbound requests fall back to rules. UTC counters reset at midnight. Requests served from cache or rules count toward the request limit.

## Production health and limits

`GET /api/v1/health` is liveness. `GET /api/v1/health/ready` returns 200 only when PostgreSQL is reachable and its Alembic heads match the running image. A non-ready response returns a generic 503. Both are unauthenticated. Keep readiness behind the proxy or on an internal network.

The server adds a generated `X-Request-ID` to responses, including errors. Auth POSTs, expensive analytics GETs, and AI POSTs have independent per-peer minute limits. The defaults are 20, 60, and 20. AI also applies its daily per-account quota. Expect 429 with `Retry-After` when admission is exhausted and a temporary 503 if the shared rate store is unavailable. Cookie-authenticated writes still require a single exact allowed Origin. API documentation is available in development.
