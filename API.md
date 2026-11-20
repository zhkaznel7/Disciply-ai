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
