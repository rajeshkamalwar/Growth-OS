# Current Task

## Task ID

PRODUCT-008 ([GitHub issue #64](https://github.com/rajeshkamalwar/Growth-OS/issues/64))

## Authorization and Mandatory Human Gate

Add the explicitly invoked, asynchronous, fail-closed single-page public HTTP(S) HTML acquisition
primitive specified in [`plans/PRODUCT-008.md`](../plans/PRODUCT-008.md). Issue #64 remains the
authoritative runtime contract and must be preserved exactly. The user explicitly approved
development of this material security boundary on 2026-08-17, including tests, the exact
dependency change, and a reviewed draft PR.

PRODUCT-008 is **high risk** because it defines outbound-network and SSRF policy. The implementation
must not be auto-merged. After all deterministic gates and a fresh security-focused read-only
review pass report zero blocking findings, leave the exact reviewed draft PR open for separate
human merge approval. Do not merge or deploy it.

This current-task update authorizes implementation only after this planning PR merges and the
orchestrator re-inspects the resulting `main`. This planning task does not queue implementation,
apply `codex-ready`, merge either PR, deploy, call any URL, or cause an external/customer-facing
effect. The orchestrator alone owns queueing. If implementation requires any contract or security
policy change, stop and update/review the plan instead of broadening or weakening issue #64.

## Exact Runtime Slice

- Add production dependency `aiohttp>=3.12,<4`; add no other HTTP, DNS, URL, DOM, crawling,
  browser, retry, or scheduling dependency.
- Add `src/growth_os/acquisition/__init__.py`,
  `src/growth_os/acquisition/html.py`, and focused tests at
  `tests/acquisition/test_html.py`.
- Export only `HtmlFetchErrorCode`, `HtmlFetchError`, `FetchedHtml`, and `fetch_html` from
  `growth_os.acquisition`.
- Keep the primitive completely unintegrated: no API, startup, service, repository, model,
  connector, execution, job, worker, scheduler, CLI, persistence, audit, or production path.

## Security Contract Summary

Use one URL representation for validation and `aiohttp`; admit only absolute HTTP(S), DNS names or
IP literals, default ports, and no userinfo, while removing fragments and preserving path/query.
Before every hop, require an entirely global IPv4/IPv6 answer set, reject mixed/unsupported answers,
and pin exactly the validated set in a per-hop resolver without losing the original TLS hostname.

Perform one GET per hop with the exact issue #64 headers, TLS defaults, disabled environment proxy,
cookies, auth, referrer, automatic redirects, DNS cache, retries, and caller overrides. Enforce the
5-second connect, 10-second socket-read, and 30-second whole-chain deadlines; at most five redirect
responses; 200-only final success; HTML/XHTML media types only; a 2,000,000-byte decompressed limit;
declared charset or UTF-8; replacement decoding; deterministic redacted errors; and cancellation
propagation. Close every per-hop session/connector on every path.

## Verification and Delivery

Use controlled fakes and monkeypatched resolution only; tests, validation, review, and examples
must never contact a real website. Prove the full normalization, SSRF/DNS-rebinding, resolver
pinning, TLS hostname, redirect, request configuration, timeout, status, content, byte-limit,
charset, error-redaction, cleanup, cancellation, and non-integration contracts enumerated in issue
#64 and the plan.

Run focused tests, full pytest, Ruff lint/format, strict mypy, pip-audit, `make check`, offline
Alembic upgrade/downgrade SQL rendering, dependency and changed-path inspection, and
`git diff --check` without bypassing failures. Obtain a fresh independent security-focused
read-only review with zero blocking findings. Deliver on a dedicated branch through a draft PR;
leave it unmerged for the mandatory human implementation-merge decision.

## Boundaries and Rollback

The approval does not authorize production traffic, autonomous/scheduled crawling, robots-policy
decisions, tenant integration, deployment, or any external/customer-facing action. A later reviewed
integration must separately define ownership/scope, permissions/robots behavior, tenant/audit
linkage, rate limits, concurrency, scheduling, persistence, and idempotency.

Implementation rollback is reverting its commit and reinstalling the prior dependency set. No
schema, durable data, production resource, credential, or external state needs recovery because the
primitive remains unintegrated and uninvoked. Planning rollback restores PRODUCT-007 as current and
removes the unimplemented PRODUCT-008 plan.
