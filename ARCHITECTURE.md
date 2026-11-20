# Architecture

The backend is a modular monolith. `app/main.py` creates the FastAPI application and manages the SQLAlchemy async engine. `app/config.py` validates environment settings. `app/middleware.py` enforces request limits and browser Origin checks. `app/api.py` owns HTTP routes and cookies, `app/schemas.py` defines public payloads, `app/services.py` owns authentication transactions, `app/repositories.py` handles queries, and `app/models.py` defines database constraints. `migrations/` holds explicit Alembic revisions. `tests/` exercises real PostgreSQL through HTTPX and SQLAlchemy.

Future analytics should follow the domain router, service, and owner-scoped query pattern under `/api/v1`. Reuse the authenticated-user dependency and take ownership from the verified session. Pass the resulting user ID explicitly to repository methods. Cross-table owner constraints provide a second check in PostgreSQL.

## Authentication and deployment

Passwords use Argon2id with two concurrent hash or verification jobs per process. Unknown emails verify against a dummy hash. Access JWTs carry the user and session IDs and expire after 10 minutes by default. Protected requests verify the JWT and check the PostgreSQL session, so revoke operations invalidate both cookie credentials. Refresh tokens use 256 bits of randomness. Each rotation consumes the old digest under a session row lock. Presenting a consumed credential revokes the entire session before the server returns 401. Concurrent refreshes and retries after a lost rotation response can require a new login.

Cookie-authenticated writes require a single exact trusted Origin. Cookies are HttpOnly, host-only, and SameSite=Lax. Production requires HTTPS origins and Secure cookies, and the application disables interactive API documentation. Deploy the browser application on the same site as the API, or serve both behind one origin. CORS must list each authorized browser origin exactly.

Terminate TLS at a trusted proxy, restrict upstream access to the proxy, and enable HSTS there. Keep Uvicorn proxy headers disabled for direct access. Behind a proxy, enable them only with a specific `--forwarded-allow-ips` allowlist and configure the proxy to replace client-supplied forwarded headers. The app's per-IP auth quota resets each minute and applies per process. Use an ingress rate limit across replicas and account for shared IPs and IPv6 traffic. Set proxy body limits, request timeouts, and connection limits. Strip cookies, authorization headers, and request bodies from proxy logs.

Inject production secrets, use separate migration and least-privilege application roles, and configure PostgreSQL TLS with certificate verification for remote connections. Apply migrations once before starting new application instances. Back up PostgreSQL and schedule deletion of expired refresh sessions in bounded batches. Rotated credentials stay until the associated session expires so replay detection can cover the full session lifetime.

The access-cookie and JWT integration follows the [FastAPI cookie documentation](https://fastapi.tiangolo.com/advanced/response-cookies/) and [PyJWT validation guidance](https://pyjwt.readthedocs.io/en/stable/api.html).

## Planning modules

`planning_api.py` uses the existing authenticated-user dependency. `planning_schemas.py` defines write fields and typed responses. `planning_service.py` validates state transitions and relationships, locks records for mutations, and commits each write atomically. `planning_repository.py` scopes every resource query to the authenticated owner. PostgreSQL composite foreign keys enforce same-owner links independently of the API. The weekly planner uses one bounded task query and groups results into seven local dates.

## Habit tracking

The habits router reuses the existing authenticated-user dependency and shared account timezone lookup. The service owns transactions and locks the habit row before changing either the schedule or logs, so concurrent log and schedule changes see a consistent configuration. Log inserts use the PostgreSQL unique key. The schedule module computes streaks from qualified local dates and computes calendar denominators without generating every historical date. Summary and period endpoints load recent counts in one owner-scoped batch query across habits.

## Focus and Pomodoro

The focus router reuses the existing session authentication and timezone lookup. Lifecycle writes serialize per account, then lock the target session for state transitions. The database also enforces a single unfinished session. Running intervals open on start or resume and close on pause, completion, or cancellation. The analytics service queries owner-scoped intervals and splits them into local-date windows with UTC boundaries, including DST folds, gaps, and skipped dates.

## Productivity analytics

The productivity service combines owner-scoped task counts, habit due-day results, focus interval aggregates, and reflection presence for a bounded date range. It reuses Phase 3 schedule evaluation and Phase 4 timezone and focus aggregation. The Discipline Score is a versioned calculation that explains each weighted component. Reports are computed from current records on request. The reflection service uses the existing unique owner/date key for atomic replacement.

## AI provider and privacy

The coach and review reuse Phase 5 metrics. Smart planning ranks an owner-scoped candidate set in PostgreSQL. The optional HTTPS Chat Completions adapter receives bounded numeric productivity summaries, ordinal task references, and allowable action codes. It receives no account credentials, IDs, titles, descriptions, reflection notes, or email addresses. With per-request consent, the coach can send the number and average of this week's reflection mood ratings. A small sample can reveal a rating, and provider retention follows the operator's provider agreement.

Provider output selects from validated action codes and bounded task references. The service renders the selected advice from local templates, validates references against the current candidate set and time budget, and has no privileged tools or write operations on productivity records. Requests have an overall deadline, a streamed body cap, an output-token limit, and zero retries. HTTP redirects and environment proxy settings are disabled. [HTTPX client behavior](https://www.python-httpx.org/api/)

## Production controls

The request guard uses PostgreSQL minute buckets for authentication writes, expensive analytics reads, and AI writes. The admission update is atomic across instances. Buckets store HMAC-derived peer identifiers, using a single IPv4 address or IPv6 /64. Trusted forwarding is disabled by default and can be enabled only for literal proxy IPs. AI also keeps its per-account UTC-day request and token admission limits. A database failure closes admission and produces a generic 503. Fixed windows allow bursts at boundaries, and shared networks share a quota. A production ingress should cap connections and requests before they reach PostgreSQL.

The server emits structured events with a generated correlation ID, route template, status, and elapsed milliseconds. Provider failures emit a fixed fallback reason. Logs exclude request paths with resource IDs, query strings, bodies, headers, credentials, prompts, and exception messages. Request durations are available for aggregation from logs. App and proxy logs have separate retention requirements.

The application image runs as a non-root user. Compose configures a read-only root filesystem, dropped capabilities, bounded log files, restart behavior, and a readiness probe. A single host still has a shared failure domain. Host patching, disk capacity, certificate renewal, and tested off-host backups remain operational responsibilities. [Compose service options](https://docs.docker.com/reference/compose-file/services/)
