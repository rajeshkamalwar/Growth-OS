# Growth OS

Backend foundation for the Autonomous Growth OS. The repository provides a FastAPI
control plane, PostgreSQL persistence and migrations, tenant-safe foundation resources,
health checks, tests, and CI. Product integrations, billing, agents, autonomous actions,
and the frontend remain intentionally out of scope.

## Requirements

- Python 3.12
- Docker with Docker Compose (for local PostgreSQL)

## Local development

```bash
cp .env.example .env
docker compose up -d db
make install
make migrate
make dev
```

The API is available at `http://127.0.0.1:8000`. Use `GET /health` for process
liveness and `GET /ready` for database-backed readiness. Interactive API documentation
is available at `http://127.0.0.1:8000/docs`.

Foundation endpoints are under `/api/v1`. Tenant-owned routes require the provider-neutral
`X-Tenant-ID` request header to match the tenant ID in the path. This header is an explicit
tenant context boundary, not an authentication mechanism; a future authentication provider
must derive and authorize that context before requests reach these services.

Collection endpoints accept `limit` (1–100, default 50) and `offset` (default 0), and return
`items` plus pagination metadata. Errors use a stable `error.code` and `error.message` shape
without database exception text.

Run the complete local verification suite with:

```bash
make check
```

Stop PostgreSQL with `docker compose down`. The named database volume is retained; use
`docker compose down --volumes` only when intentionally discarding local development data.

## Migrations and rollback

Apply all migrations with `make migrate`. During local foundation development, the latest
migration can be reversed with `.venv/bin/alembic downgrade -1`. Downgrading the initial
migration drops its tables and data, so any use against a shared or production database
requires an approved backup and recovery plan first.
