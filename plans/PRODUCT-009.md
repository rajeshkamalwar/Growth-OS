# PRODUCT-009: RFC 9309 Offline Robots Permission Evaluator

## Status and Authority

**Proposed — approval required; not authorized for implementation.**

This plan records the proposed runtime contract from
[GitHub issue #68](https://github.com/rajeshkamalwar/Growth-OS/issues/68) exactly, without
authorizing it. PRODUCT-008 is merged, and PRODUCT-009 is the next dependency awaiting explicit
security approval.

Do not apply `codex-ready` or implement issue #68 until the user explicitly approves the robots
permission policy after this planning proposal is merged. Neither planning issue #69 nor its merge
authorizes applying `codex-ready` to issue #68, runtime implementation, implementation merge,
deployment, retrieval, or crawling.

## Objective

Add a deterministic, offline Robots Exclusion Protocol evaluator for the fixed crawler product
token `GrowthOSBot`. It consumes caller-supplied UTF-8 robots.txt bytes and a caller-supplied target
path/query, then returns a value-backed allow/disallow decision with the exact matched rule where
applicable.

This is a prerequisite to any crawler integration. It performs no HTTP/DNS/file access,
scheduling, persistence, caching, logging, audit, or active enforcement and is not imported by any
runtime path.

## Risk and Approval Boundary

Risk is **high** because these semantics will eventually determine whether autonomous network
access is permitted. Approval authorizes implementation and a reviewed draft PR only. It does not
authorize merging the implementation, fetching robots.txt, integrating with PRODUCT-008,
crawling, deployment, production traffic, or treating robots.txt as an access-control mechanism.

## Public Contract

Create `src/growth_os/robots/policy.py` and package exports:

```python
class RobotsPolicyErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    TOO_LARGE = "too_large"
    INVALID_ENCODING = "invalid_encoding"


class RobotsPolicyError(ValueError):
    code: RobotsPolicyErrorCode


class RobotsDecisionReason(StrEnum):
    ROBOTS_URI = "robots_uri"
    MATCHED_ALLOW = "matched_allow"
    MATCHED_DISALLOW = "matched_disallow"
    NO_MATCHING_GROUP = "no_matching_group"
    NO_MATCHING_RULE = "no_matching_rule"


@dataclass(frozen=True, slots=True)
class RobotsDecision:
    allowed: bool
    reason: RobotsDecisionReason
    matched_user_agent: str | None
    matched_rule: str | None


def evaluate_robots(*, robots_txt: bytes, target_path: str) -> RobotsDecision: ...
```

The dataclass is immutable/equality-comparable with exactly those fields and order. The product
token is fixed internally to `GrowthOSBot`, case-insensitively matched, and is not
caller-configurable. Errors expose only a stable code/message and never content, paths, rules, or
parser details.

## Input Limits and Normalization

- Accept `bytes` for `robots_txt` and `str` for `target_path` only; no coercion.
- Accept exactly 512,000 bytes (RFC 9309's 500 KiB minimum processing limit) and reject the first
  byte beyond with `TOO_LARGE` before decoding/parsing.
- Decode strict UTF-8. Invalid UTF-8 raises `INVALID_ENCODING`; no partial decision is returned
  because the caller must fail closed.
- `target_path` contains only path plus optional query, must start with `/`, contain no scheme,
  authority, fragment, ASCII control, lone surrogate, or malformed percent triplet, and must not
  be empty. Invalid input raises `INVALID_INPUT`.
- Normalize rule paths and target paths for RFC 9309 comparison: encode non-ASCII as UTF-8 percent
  octets; decode percent-encoded ASCII unreserved octets; preserve/uppercase percent encoding for
  reserved and non-ASCII octets; preserve path/query separators; compare case-sensitively by
  normalized octets.
- Do not normalize dot segments, collapse slashes, decode reserved separators, infer a host, or
  contact anything.

## RFC 9309 Parsing Contract

Follow RFC 9309 sections 2.2 through 2.2.4:

- support CR, LF, and CRLF; trim only ASCII space/tab around field names and values;
- `#` begins a comment; percent-encoded `%23` is data;
- field names and user-agent matching are ASCII case-insensitive;
- valid product tokens contain only ASCII letters, `_`, and `-`, or exactly `*`;
- a group begins with one or more valid `user-agent` lines and continues through its
  allow/disallow rules; a user-agent after rules starts a new group; blank and unknown/other
  records do not terminate a group or affect rules;
- ignore invalid/unparseable lines, invalid product tokens, allow/disallow lines outside a group,
  empty allow/disallow patterns, and rule patterns that do not begin `/`; continue using every
  parseable rule. In particular, follow the normative `path-pattern` grammar and ignore the
  leading-wildcard `*.gif$` example in RFC 9309 Figure 7, whose conflict with that grammar is
  recorded by RFC erratum 7995; use `/*.gif$` to exercise wildcard/end-anchor behavior and add no
  compatibility extension;
- merge the rules of every group that exactly matches `GrowthOSBot` case-insensitively; use all `*`
  groups only when no exact group exists; if neither exists, allow with `NO_MATCHING_GROUP`;
- other records including Sitemap, Host, Crawl-delay, Request-rate, and misspellings never
  grant/deny access and never terminate a group.

Do not implement substring, prefix, HTTP User-Agent-string, or caller-selected product-token
matching.

## Rule Matching and Decision Contract

- `/robots.txt` is implicitly allowed before rule matching, with `ROBOTS_URI`, null matched fields.
  This applies to the exact path `/robots.txt` with any query, not descendants or case variants.
- Rules match from the first target-path octet. Support `*` for zero or more octets and a final
  unescaped `$` as end anchor. Percent-encoded `%2A` and `%24` are literals, not operators.
- Choose the matching rule with the greatest normalized non-wildcard pattern length in octets. If
  equally specific allow/disallow rules both match, allow wins. Exact duplicates do not change the
  decision.
- A winning allow returns `MATCHED_ALLOW`; a winning disallow returns `MATCHED_DISALLOW`.
  `matched_user_agent` is `GrowthOSBot` for exact groups or `*` for wildcard fallback.
  `matched_rule` is the normalized rule pattern exactly used for matching, including `*`/terminal
  `$` where present.
- If a matching group has no matching rule, allow with `NO_MATCHING_RULE`, the selected matched
  user-agent, and null matched rule.
- No matching group allows by default as stated above. Never produce a recommendation, severity,
  confidence, crawl delay, request rate, sitemap, or inferred permission beyond this one path
  decision.

## Architecture and Non-Action Boundary

- Python standard library only; add no dependency.
- Keep independent of aiohttp, acquisition, evidence, FastAPI, database/SQLAlchemy/Alembic, tenant
  context, services, repositories, connectors, execution, jobs, and workers.
- Do not import from or modify PRODUCT-008. Do not add a URL fetcher, response-status policy, cache,
  scheduler, rate limiter, persistence, route, CLI, audit event, active integration, or production
  behavior.
- Do not log robots content, target paths, rules, or decisions.
- A future separately approved integration must define retrieval status semantics
  (2xx/4xx/5xx/network), initial-authority context, redirects, caching/expiry, tenant/site
  ownership, audit linkage, rate/concurrency controls, idempotency, and fail-closed operational
  behavior.

## Acceptance Tests

Use RFC 9309 examples that conform to the normative grammar, explicitly test the Figure 7
`*.gif$` conflict as ignored and `/*.gif$` as matched, and add focused tests proving:

1. exact public types/fields/exports/immutability, fixed product token, strict types, stable
   redacted errors, 512,000/512,001 byte boundaries, strict UTF-8, and invalid target inputs;
2. CR/LF/CRLF, comments, ASCII whitespace/case, multi-agent groups, exact group merging, wildcard
   fallback/merging, exact-not-substring product matching, empty groups, invalid
   lines/tokens/rules, rules outside groups, and non-interference from unknown/other records;
3. prefix, wildcard, terminal anchor, literal percent-encoded `*`/`$`, empty wildcard matches, case
   sensitivity, path-plus-query, Unicode/percent normalization, reserved/unreserved behavior,
   slash/dot preservation, and malformed escapes;
4. longest normalized-octet specificity, allow tie, duplicates, no group/no rule, exact
   `/robots.txt` implicit allow semantics, and exact provenance fields;
5. adversarial inputs remain bounded/deterministic and cause no network, DNS, HTTP, filesystem,
   database, connector, audit, execution, logging, or active-path call;
6. no dependency, migration, route, persistence, acquisition modification, or runtime integration.

Run focused tests, existing acquisition/evidence tests, full pytest, Ruff lint/format, strict mypy,
pip-audit, `make check`, offline Alembic upgrade/downgrade rendering, and `git diff --check`.
Obtain a fresh separate protocol/security-focused read-only reviewer pass with zero blocking
findings.

## Delivery and Rollback

After explicit approval, deliver implementation on a dedicated branch through a draft PR and stop
for a separate human merge decision because this is a material security policy. Do not deploy.
Rollback is reverting the implementation commit; no dependency, schema, durable data, production
resource, or external state requires recovery.

Planning issue #69 changes exactly `docs/CURRENT-TASK.md` and this new plan. Validate documentation
format, links, commands, paths, final changed-file scope, and `git diff --check`; obtain a fresh
separate protocol/security-focused read-only review with zero blocking findings; then deliver the
planning change on a dedicated branch through a draft PR. Planning rollback restores PRODUCT-008
as the recorded current task and removes this proposal; no runtime, dependency, schema, data,
production, or external recovery is needed.

## Auto-Merge Assessment

The authoritative proposed implementation assessment is:

```json
{
  "risk": "high",
  "roadmap_authorized": true,
  "reversible": true,
  "production_deployment": false,
  "external_customer_side_effect": false,
  "stop_categories": ["material_security_tradeoffs"]
}
```

The planning issue #69 assessment is:

```json
{
  "risk": "low",
  "roadmap_authorized": true,
  "reversible": true,
  "production_deployment": false,
  "external_customer_side_effect": false,
  "stop_categories": []
}
```

The planning assessment authorizes only the reversible documentation change. It does not
authorize any PRODUCT-009 runtime or external action.
