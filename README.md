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

Each workspace may also store one durable primary growth goal at
`/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/primary-growth-goal`. Use `POST` to create,
`GET` to retrieve, and `PATCH` to update one or more supplied fields. `objective` is required and
the optional `success_definition` and ISO calendar `target_date` may be explicitly cleared with
`null`. Goal text and dates record supplied intent only; they are not measured evidence, progress,
attainment, attribution, or proof of business performance. Successful mutations add one redacted
audit event containing only the workspace ID and alphabetically sorted supplied field names.

Each workspace may store one autonomy preference at
`/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/autonomy-policy`. Use `POST` to create,
`GET` to retrieve, and `PATCH` to update the required autonomy level or strict boolean pause flag.
New policies are paused by default. These values are stored customer intent only: they do not
grant permission, change approval requirements, start work, or enforce a runtime kill switch.
Successful mutations add one redacted audit event containing only the workspace ID and
alphabetically sorted explicitly supplied policy field names.

Each workspace may store a bounded catalog of customer-supplied competitors at
`/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/competitors`. Use `POST` on the collection,
`GET` on the collection or a nested `/{competitor_id}`, and `PATCH` on a nested competitor.
Names are required; normalized HTTP(S) website URLs and notes are optional and may be cleared.
The catalog is inert stored context only: it performs no crawling, discovery, monitoring,
inference, outreach, backlink activity, connector call, or external action. Successful mutations
add one value-redacted audit containing only the workspace ID and sorted supplied field names.

Read foundational onboarding completeness with
`GET /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/onboarding-status`. The response reports
only whether the workspace has at least one site and stored business-profile, primary-growth-goal,
and autonomy-policy records, plus the canonically ordered missing records. It does not expose the
underlying content and creates no audit event or other side effect.

This status means foundational record completeness only. It is not connector authentication,
monitoring readiness, approval, permission, policy enforcement, execution eligibility, evidence
that Growth OS is operational, or any other operational-readiness claim. Autonomy values are not
read or applied; policy presence is only the presence of a stored onboarding record.

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

For PRODUCT-002, reverting the application code while retaining the additive
`workspace_primary_growth_goals` table is likewise the preferred rollback because it stops new
goal operations without deleting stored intent. The PRODUCT-002 downgrade drops only that table
and permanently deletes its goal records, so it is limited to disposable development databases.
Before any approved downgrade against meaningful shared or production data, obtain explicit
approval, take and verify a backup, and document and test recovery.

For PRODUCT-003, revert the application code while retaining the additive
`workspace_autonomy_policies` table to stop new policy operations without deleting preferences.
Retaining the table cannot trigger actions because this milestone adds no enforcement consumer.
The PRODUCT-003 downgrade drops only that table and permanently deletes its policy rows, so use it
only in a disposable development database. Downgrading meaningful shared or production data
requires explicit approval, a verified backup, and a documented, tested recovery plan.

For PRODUCT-005, revert the application code while retaining the additive
`workspace_competitors` table to stop catalog operations without deleting customer context. The
PRODUCT-005 downgrade drops only that table and permanently deletes every competitor row, so use
it only in a disposable development database. Before any downgrade involving meaningful data,
stop writes, obtain explicit approval, take and verify a backup, and test recovery. Reapply the
migration before restoring rows, then validate tenant/workspace ownership and exact-name
uniqueness.
