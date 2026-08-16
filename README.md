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

Each workspace may store one durable business profile at
`/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/business-profile`. Use `POST` to create,
`GET` to retrieve, and `PATCH` for partial updates. Company name is required at creation; the
remaining bounded narrative fields may be supplied incrementally. Profile text is supplied
operational context rather than measured evidence. Successful create and update operations add
redacted audit events containing only the workspace ID and changed field names.

Run the complete local verification suite with:

```bash
make check
```

Stop PostgreSQL with `docker compose down`. The named database volume is retained; use
`docker compose down --volumes` only when intentionally discarding local development data.

## Migrations and rollback

Apply all migrations with `make migrate`. During local foundation development, the latest
migration can be reversed with `.venv/bin/alembic downgrade -1`. Reverting the application code
while retaining the additive profile table is the preferred rollback because it preserves
business-profile data. Downgrading PRODUCT-001 drops `workspace_business_profiles` and all profile
records; run that downgrade only in a disposable development database. Any downgrade against
meaningful shared or production data requires explicit approval, a verified backup, and a tested
recovery plan first.
