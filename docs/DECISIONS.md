# Decisions

## D-001 — SaaS from day one
The product is multi-tenant and usage-aware from the beginning.

## D-002 — Simplicity for naive users
The UI uses business language and minimizes required configuration. Advanced controls are optional.

## D-003 — Zero copy/paste development workflow
GitHub/project files are the shared source of truth between product reasoning and Codex implementation.

## D-004 — Codex does not work directly on main
Codex works on task branches, runs checks, and produces draft PRs.

## D-005 — Production deployment is gated
No autonomous production deployment in the initial development workflow.

## D-006 — FastAPI preferred for core intelligence/control
Python/FastAPI is preferred unless later evidence favors a different choice.

## D-007 — n8n is integration glue
n8n may accelerate integrations but is not the source of truth or core reasoning engine.

## D-008 — PostgreSQL is operational memory
Persistent operational memory resides in PostgreSQL. pgvector supports semantic retrieval.

## D-009 — Obsidian is optional human-readable knowledge
Obsidian/Markdown is not the authoritative operational database.

## D-010 — Toolbox principle
MagicAI, Dograh, Antigravity, MiroFish, and external GitHub projects are optional tools to evaluate, not required dependencies.

## D-011 — Evidence over claims
Reports and autonomous decisions preserve source/provenance. The LLM explains data; it does not invent metrics.

## D-012 — High-risk actions require approval
Auth, billing, tenant boundaries, destructive database operations, secrets, large spend, high-volume outreach, and production infrastructure changes are gated.

## D-013 — Doing nothing is a valid action
Agents are not required to make changes when monitoring finds no justified intervention.
