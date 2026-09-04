---
phase: 11
slug: body-measurement-history
status: verified
threats_open: 0
asvs_level: 2
created: 2026-09-04
---

# Phase 11 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

**Plans covered:** 11-01, 11-02, 11-03
**Result:** 18/18 threats closed (14 mitigate, 3 accept, 1 transfer)

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Claude (model) → MCP tool argument | The `metric` selector is model-supplied text, bounded to a closed 16-value enum | Metric name only — no user data |
| Analytics function → PostgreSQL | Every query in this package is tenant-scoped; an unscoped read is a cross-tenant disclosure a single-user test suite cannot observe | `user_id`, resolved column values |
| MCP tool → analytics/database | Crossed inside `read_only_session`, a Postgres `READ ONLY` transaction, with `user_id` resolved server-side | Tenant-scoped measurement rows |
| MCP tool → Claude's context window | Every returned byte enters the model's context; an unbudgeted response is a resource issue, an unguarded exception is a credential-disclosure one | `BodyMeasurementTrendResult` JSON |

---

## Threat Register

| Threat ID | Plan | Category | Component | Disposition | Mitigation | Status |
|-----------|------|----------|-----------|-------------|------------|--------|
| T-11-01 | 11-01 | Tampering | `BodyMeasurementMetric` StrEnum → `getattr` resolution | mitigate | 16 hardcoded literal enum members; `backend/app/analytics/schemas.py:568-602`; `test_the_enum_is_exactly_the_non_weight_numeric_columns` (`test_analytics_body_measurements.py:48`) asserts bidirectional set equality with ORM `Numeric` columns | closed |
| T-11-02 | 11-01 | Information Disclosure | `earliest_metric_measurement_at` | mitigate | `user_id` keyword-only, no default, leads `WHERE`; `backend/app/analytics/metadata.py:288-316`; `test_earliest_metric_measurement_at_is_column_scoped_and_tenant_scoped` (`test_analytics_metadata.py:833`) seeds a second tenant with an earlier date | closed |
| T-11-03 | 11-01 | Information Disclosure | `BodyMeasurementTrendResult` field set | mitigate | `_AnalyticsModel` sets `extra="forbid"`/`frozen=True`; `backend/app/analytics/schemas.py:40,605-639`; no `source`/`external_id`/`id`/`user_id` field present | closed |
| T-11-04 | 11-01 | Tampering | `MEASURED_DAY_FLOORS` mapping | mitigate | Stays `MappingProxyType`; `backend/app/analytics/metadata.py:127`; `test_analytics_metadata.py:608,635-636` pins the exact dict and asserts mutation raises `TypeError` | closed |
| T-11-01 | 11-02 | Tampering | `getattr(BodyMeasurement, metric.value)` in `body_measurements.py` | mitigate | `metric` typed `BodyMeasurementMetric`; `backend/app/analytics/body_measurements.py:160`; SQLAlchemy binds as a compiled column reference, never string-formatted into SQL | closed |
| T-11-02 | 11-02 | Information Disclosure | `_metric_readings` / `earliest_metric_measurement_at` queries | mitigate | Tenant predicate leads every `WHERE`; `backend/app/analytics/body_measurements.py:128-138`; `test_another_tenants_readings_never_enter_the_window` (`test_analytics_body_measurements.py:441`) | closed |
| T-11-03 | 11-02 | Tampering | write path from the analytics layer | mitigate | Module imports only `select`, no `commit`/`flush`/`add`; enforced by `test_analytics_isolation.py`'s static `rglob` walk | closed |
| T-11-04 | 11-02 | Information Disclosure | `MetricReading.source` | mitigate | Carried only for `fold_by_day` determinism, no field on `BodyMeasurementTrendResult`; `body_measurements.py:67-73`; `extra="forbid"` prevents accidental addition | closed |
| T-11-05 | 11-02 | Denial of Service | unbounded result set | mitigate | `WINDOW_DAYS = 90` is a module constant, not a caller parameter; `body_measurements.py:57` | closed |
| T-11-07 | 11-03 | Tampering | `metric` argument on `fitness_get_body_measurement_trend` | mitigate | `Annotated[BodyMeasurementMetric, Field(...)]` derives a 16-value enum `inputSchema`; `backend/app/mcp/tools/body.py:122-133`; `test_body_measurement_trend_rejects_an_unknown_metric` (`test_mcp_tools.py:992`) | closed |
| T-11-08 | 11-03 | Information Disclosure | exception text (asyncpg DSN, credentials) reaching Claude | mitigate | `@safe_tool(degraded=_degraded_measurement_trend)`; `body.py:114-121`; `test_mcp_isolation.py:249` (count raised to 13) and `test_mcp_tools.py:108` (`MINIMAL_TOOL_ARGUMENTS`, real dead-database call) | closed |
| T-11-09 | 11-03 | Information Disclosure | cross-tenant read through the new tool | mitigate | `resolve_user_id(ctx)` resolves tenant server-side; `body.py:145`; `user_id` is not a tool argument, absent from `inputSchema` | closed |
| T-11-10 | 11-03 | Elevation of Privilege | a new write path entering the MCP surface | mitigate | `read_only_session(ctx)` (Postgres `READ ONLY` transaction, `_common.py:123-154`); `body.py:146`; registered via shared `_TOOLS` loop with `READ_ONLY` annotations (`server.py:206,222`); `test_mcp_readonly.py` drives an actual write attempt | closed |
| T-11-11 | 11-03 | Denial of Service | unbounded response entering Claude's context | mitigate | Measured `2_048`-byte budget (1,351 measured), `test_mcp_tool_budget.py:74`; fixed-shape response, 90-day window is a module constant | closed |
| T-11-12 | 11-03 | Spoofing | unauthenticated access to `fitness_get_body_measurement_trend` | transfer | Existing bearer-token verifier on the `/mcp` mount (`backend/app/mcp/auth.py`); no new route, no new auth surface; `test_mcp_auth.py` (`test_rejects_unauthenticated`, `test_rejects_bad_token`, `test_accepts_valid_bearer`, `test_401_leaks_nothing`) continues to cover it unchanged | closed |
| T-11-05 | 11-01 | Repudiation | read path, no audit trail | accept | No write path, no state change added by this phase; v1 keeps MCP read-only end to end | closed |
| T-11-06 | 11-02 | Repudiation | read path, no audit trail | accept | No write, no state change, no credential use in `get_body_measurement_trend` | closed |
| T-11-13 | 11-03 | Repudiation | no audit trail for tool reads | accept | Read-only, no state change, no credential use; consistent with the disposition already accepted for the 13 pre-existing tools | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

**Note:** Threat IDs T-11-01 through T-11-06 are reused across Plan 11-01 and Plan 11-02 for distinct components (each plan numbers its own register locally) — disambiguated above by the `Plan` column.

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-11-01 | T-11-05 (11-01) | No write path, no state change added by this phase; v1 keeps MCP read-only end to end; a read audit log carries no threat this milestone's design cares about. Revisit if the MCP surface adds a write tool (tracked as Phase 12 in ROADMAP) | gsd-security-auditor | 2026-09-04 |
| AR-11-02 | T-11-06 (11-02) | No write, no state change, no credential use in `get_body_measurement_trend`. Same revisit condition as AR-11-01 | gsd-security-auditor | 2026-09-04 |
| AR-11-03 | T-11-13 (11-03) | Read-only, no state change, no credential use; consistent with the disposition already accepted for the 13 pre-existing tools. Revisit only if a future phase's write tool changes the calculus | gsd-security-auditor | 2026-09-04 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-09-04 | 18 | 18 | 0 | gsd-security-auditor |

### Unregistered Flags

None. No `## Threat Flags` section was present in any of the 11-01, 11-02, or 11-03 SUMMARY.md files — the executor found no attack surface outside what the phase's threat model already registered.

### Non-regression note

All three plan summaries independently confirm `git diff --stat backend/app/analytics/bodyweight.py` is empty and `fitness_get_body_weight_trend` / `BodyWeightTrendResponse` are byte-for-byte unchanged except for one documentation paragraph in `body.py`'s module docstring — BODY-01's existing threat mitigations (from an earlier phase, not re-audited here) are structurally unregressed by this phase's changes.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-09-04

---

*Note: this is the first `/gsd-secure-phase` run in this repository — no prior phases (1-10) have a recorded SECURITY.md yet. Only Phase 11's threat model was audited here; earlier phases have not been retroactively audited.*
