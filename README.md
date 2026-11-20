# Disciply AI backend

Disciply AI is an async FastAPI backend for account management, goals, projects, tasks, daily and weekly planning, habit tracking, focus sessions with Pomodoro, daily analytics, and evening reflections.

## Windows 11 with Docker Desktop

Open PowerShell in the repository root. Start Docker Desktop and wait for its engine. On the first run, create the local environment file:

```powershell
function New-HexSecret {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return -join ($bytes | ForEach-Object { $_.ToString('x2') })
}

if (-not (Test-Path .env)) {
    $dbPassword = New-HexSecret
    $jwtSecret = New-HexSecret
    (Get-Content .env.example) |
        ForEach-Object {
            $_ -replace '^POSTGRES_PASSWORD=$', "POSTGRES_PASSWORD=$dbPassword" `
               -replace '^DATABASE_URL=$', "DATABASE_URL=postgresql+asyncpg://disciply:${dbPassword}@db:5432/disciply" `
               -replace '^JWT_SECRET=$', "JWT_SECRET=$jwtSecret"
        } | Set-Content -Encoding ascii .env
}
docker compose build api
docker compose up -d db --wait
docker compose run --rm api alembic upgrade head
docker compose up -d api
Invoke-RestMethod http://localhost:8000/api/v1/health
```

Use [Swagger UI](http://localhost:8000/api/v1/docs) in development. The Compose database persists across normal stops. Changing the password in an existing volume requires changing the PostgreSQL role password as well.

## Run with local Python and PostgreSQL

Install Python 3.12 or later and PostgreSQL. Create a local role and an owned database. Copy `.env.example` to `.env`, set `DATABASE_URL` to the local database using `postgresql+asyncpg`, and set `JWT_SECRET` using `New-HexSecret` above. Percent-encode reserved characters in database credentials.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --no-proxy-headers --no-access-log
```

Create a separate PostgreSQL database with a name ending in `_test`, using a role that can run DDL in that database. Tests apply and check the migration, use randomly generated account IDs and emails, and leave test rows in the dedicated database.

```powershell
$env:TEST_DATABASE_URL = Read-Host 'Dedicated PostgreSQL asyncpg test database URL'
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:TEST_DATABASE_URL
```

For an existing Docker setup, rebuild the API image and run `docker compose run --rm api alembic upgrade head` before restarting the API. The current Alembic revision is `0006`. See the database guide for prior migration preflight requirements.

Use `alembic current` to inspect the deployed revision and `alembic check` to detect model drift. Pass either command to `docker compose run --rm api` when using Docker. Review generated revisions before applying them. The initial downgrade drops Phase 1 tables and their data.

See [Architecture](ARCHITECTURE.md), [Database](DATABASE.md), and [API](API.md).

## Optional AI provider

Local development defaults to deterministic recommendations. To enable external AI, set `AI_ENABLED=true`, `AI_PROVIDER_URL` to the operator-selected HTTPS Chat Completions endpoint, `AI_MODEL` to its model identifier, and `AI_API_KEY` through environment-based secret configuration. The configured endpoint must support JSON response mode and `max_completion_tokens`. There is no automatic provider or model switch. Apply `alembic upgrade head` before starting this release.

`AI_DAILY_REQUESTS` and `AI_DAILY_TOKENS` control per-account UTC-day admission. `AI_TIMEOUT_SECONDS` and `AI_MAX_OUTPUT_TOKENS` bound outbound calls. The token reservation uses request bytes, fixed framing overhead, and the output limit. Providers use different tokenizers and may report usage above the reservation, which can exhaust the remaining budget. Unreported usage retains the reservation. This is an admission control, and billing limits should also be configured with the provider.

## Single-server production deployment

1. Use a protected environment file and set `ENVIRONMENT=production`, `COOKIE_SECURE=true`, a random 32-byte hex JWT secret, a strong PostgreSQL role password, and exact HTTPS browser origins. Use an application-only database role and pass the migration role URL to the Alembic process. See [Database operations](DATABASE.md).
2. Keep `API_BIND_HOST=127.0.0.1` with a host proxy. Set `API_BIND_PORT` if needed and use the same upstream port in the proxy. Compose keeps PostgreSQL on its private network and stores its data in the named volume.
3. Point an operator-controlled hostname at the host and configure a TLS reverse proxy. The [Caddy example](deploy/Caddyfile.example) expects `DISCIPLY_HOST` in the Caddy service environment and a reachable certificate challenge. Allow inbound HTTPS and the certificate challenge through the firewall. The example keeps readiness on loopback and serves HSTS over HTTPS. Set the proxy request-body cap at or below `MAX_BODY_BYTES`.
4. Leave `TRUSTED_PROXY_IPS=[]` for direct access. For a reverse proxy, configure only its actual upstream-side IP as seen by Uvicorn, which may be the Docker bridge gateway. Use a proxy that replaces untrusted forwarded headers and restrict direct access to the upstream. Verify per-client throttling in staging. With forwarding disabled, clients behind one proxy share an IP quota.
5. Build the image, start the database, run Alembic once, then start the API. Wait for `/api/v1/health/ready` on loopback and verify `/api/v1/health` over HTTPS. If readiness returns 503, check PostgreSQL connectivity, role grants, and `alembic current`.

```powershell
docker compose build api
if ($LASTEXITCODE -ne 0) { throw 'API build failed' }
docker compose up -d db --wait
if ($LASTEXITCODE -ne 0) { throw 'Database did not become ready' }
docker compose run --rm api alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Migration failed' }
docker compose up -d api --wait
if ($LASTEXITCODE -ne 0) { throw 'API did not become ready' }
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/ready
```

For separate roles, supply the migration DSN in the host process environment and add `-e MIGRATION_DATABASE_URL` before `api` in the migration command. Clear the host variable after migration. The regular API container blanks the PostgreSQL bootstrap password and migration DSN. Development still uses the existing Compose .env setup.

Before an upgrade, retain the previous tested image and a verified backup. If a migration fails, keep traffic on the prior compatible release, inspect `alembic current`, and resolve the cause before retrying. Roll back application and schema together after verifying compatibility in a disposable database. Revision `0006` rollback removes request-rate counters. Restore backups into a fresh database and verify them before a deliberate cutover.

Rotate the JWT signing secret together across instances. Existing access tokens become invalid. Existing refresh sessions can still mint access tokens unless they are revoked. During an incident, revoke the affected refresh sessions as well. Rotate provider or database credentials through the deployment secret store, restart the affected services, verify access, then retire the old credentials.

GitHub Actions runs syntax checks, redacted secret scanning, PostgreSQL integration tests with Alembic validation, and an image build on pushes and pull requests. Deployment remains a manual step.
