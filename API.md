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
