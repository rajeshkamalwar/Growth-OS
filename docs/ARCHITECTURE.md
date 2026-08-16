# Architecture

## Architectural Principle
Use the minimum set of tools required. MagicAI, Obsidian, Dograh, Antigravity, MiroFish, and third-party GitHub projects are toolbox options, not mandatory dependencies.

## Core Layers

### SaaS / User Layer
Customer dashboard, workspaces, onboarding, plans/usage/billing, approvals, reports, and simple business-language UX. A pre-existing SaaS shell such as MagicAI may be reused if inspection shows it saves time without constraining the product.

### Core Backend / Control Plane
Preferred: FastAPI / Python.

Responsibilities: tenant/workspace isolation, goals, policies, risk scoring, approval rules, action ledger, budget limits, evidence records, connector health, agent routing, and API surface.

### Agent Intelligence
Growth Director, SEO Agent, GEO Agent, SMM Agent, Content Agent, Authority/Backlink Agent, CRO Agent, Analytics Agent, Reporting Agent, and Quality/Safety Agent.

OpenAI Agents SDK is a preferred implementation option, not a requirement for every operation.

### Durable Execution
Preferred: Temporal or equivalent durable workflow system for long-running jobs, retries, approval waits, scheduled execution, idempotent external actions, and failure recovery.

### Integration Layer
n8n may be used for commodity integrations and workflow glue. Core intelligence and canonical business state must not live exclusively in n8n.

### Data Layer
- PostgreSQL: operational source of truth
- pgvector: semantic retrieval
- Object storage: media/crawl/report artifacts
- Redis: caching/ephemeral coordination where useful

### Knowledge Layer
Human-readable strategy/brand/SOP knowledge may use Git Markdown or Obsidian-compatible Markdown. Operational memory remains in the platform database.

### Monitoring / Data Sources
Google Search Console, GA4, website crawler, SERP provider, backlink provider, social APIs, CMS/site adapters, conversion/revenue sources, and AI/GEO visibility checks.

## Continuous Loop
Observe -> Detect -> Reason -> Simulate when justified -> Risk Check -> Execute -> Verify -> Measure -> Learn -> Report

## Control Plane Requirements
Every executable action should answer: which tenant/workspace, what goal, supporting evidence, risk, estimated cost, approval requirement, idempotency state, rollback capability, and success measurement.

## Safety
No agent gets unrestricted production access. High-risk actions remain approval-gated. Every external action should have an audit record.
