# Architecture

The backend is a modular monolith. `app/main.py` creates the FastAPI application and manages the SQLAlchemy async engine. `app/config.py` validates environment settings. `app/middleware.py` enforces request limits and browser Origin checks. `app/api.py` owns HTTP routes and cookies, `app/schemas.py` defines public payloads, `app/services.py` owns authentication transactions, `app/repositories.py` handles queries, and `app/models.py` defines database constraints. `migrations/` holds explicit Alembic revisions. `tests/` exercises real PostgreSQL through HTTPX and SQLAlchemy.

Future tasks, goals, projects, habits, focus sessions, and analytics should get domain routers under `/api/v1`, with services and owner-scoped queries. Reuse the authenticated-user dependency and take ownership from the verified session. Pass the resulting user ID explicitly to repository methods. Cross-table owner constraints provide a second check in PostgreSQL.

## Authentication and deployment

Passwords use Argon2id with two concurrent hash or verification jobs per process. Unknown emails verify against a dummy hash. Access JWTs carry the user and session IDs and expire after 10 minutes by default. Protected requests verify the JWT and check the PostgreSQL session, so revoke operations invalidate both cookie credentials. Refresh tokens use 256 bits of randomness. Each rotation consumes the old digest under a session row lock. Presenting a consumed credential revokes the entire session before the server returns 401. Concurrent refreshes and retries after a lost rotation response can require a new login.

Cookie-authenticated writes require a single exact trusted Origin. Cookies are HttpOnly, host-only, and SameSite=Lax. Production requires HTTPS origins and Secure cookies, and the application disables interactive API documentation. Deploy the browser application on the same site as the API, or serve both behind one origin. CORS must list each authorized browser origin exactly.

Terminate TLS at a trusted proxy, restrict upstream access to the proxy, and enable HSTS there. Keep Uvicorn proxy headers disabled for direct access. Behind a proxy, enable them only with a specific `--forwarded-allow-ips` allowlist and configure the proxy to replace client-supplied forwarded headers. The app's per-IP auth quota resets each minute and applies per process. Use an ingress rate limit across replicas and account for shared IPs and IPv6 traffic. Set proxy body limits, request timeouts, and connection limits. Strip cookies, authorization headers, and request bodies from proxy logs.

Inject production secrets, use separate migration and least-privilege application roles, and configure PostgreSQL TLS with certificate verification for remote connections. Apply migrations once before starting new application instances. Back up PostgreSQL and schedule deletion of expired refresh sessions in bounded batches. Rotated credentials stay until the associated session expires so replay detection can cover the full session lifetime.

The access-cookie and JWT integration follows the [FastAPI cookie documentation](https://fastapi.tiangolo.com/advanced/response-cookies/) and [PyJWT validation guidance](https://pyjwt.readthedocs.io/en/stable/api.html).
