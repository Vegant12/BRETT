# Phase 8: Apple Health & Nutrition Ingest - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-02
**Phase:** 08-apple-health-nutrition-ingest
**Areas discussed:** Body-mass & workout scope, Freshness granularity, Unexpected metric handling, Nutrition wire format

---

## Body-mass & workout scope

### Non-Hevy Apple Health body weight

| Option | Description | Selected |
|--------|-------------|----------|
| Exclude all Apple Health body-mass | body_measurements stays Hevy+manual only; simplest, matches architecture research | ✓ |
| Ingest non-Hevy Apple Health body-mass | Matches PROJECT.md's literal "not already Hevy-sourced" phrasing; requires a third body_measurements source and precedence-map work | |

**User's choice:** Exclude all Apple Health body-mass (recommended option)
**Notes:** Deliberate narrowing of PROJECT.md's literal phrasing, confirmed explicitly during discussion — not an oversight. Recorded as D-01.

### Apple Health workouts

| Option | Description | Selected |
|--------|-------------|----------|
| Skip storing workouts entirely | No new table; simplest reading of HEALTH-08 | ✓ |
| Build quarantined `health_workouts` coverage table | Stores all workouts, walled off from analytics, for future cross-check value | |

**User's choice:** Skip storing workouts entirely (recommended option)
**Notes:** Design for the coverage table stays documented in ARCHITECTURE.md if picked up in a future phase. Recorded as D-02.

---

## Freshness granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Two separate resources: 'activity' and 'nutrition' | Independent `last_synced_at` per data kind; catches partial failures | ✓ |
| One combined 'apple_health' resource | Simpler single freshness value, but blends partial failures | |

**User's choice:** Two separate resources (recommended option)
**Notes:** Directly implements Pitfall 7's fix; satisfies HEALTH-11 and NUTR-05 independently. Recorded as D-03.

---

## Unexpected metric handling

| Option | Description | Selected |
|--------|-------------|----------|
| Silently drop, keep processing | Matches vendor guidance against "ingest everything"; avoids losing the whole window over one unexpected metric | ✓ |
| Drop but log a visible warning event | Same behavior plus a structured log line for discoverability | |
| Reject the whole request | Strictest; risks losing an entire delivery window given HAE's no-retry semantics | |

**User's choice:** Silently drop it, keep processing the rest (recommended option)
**Notes:** The visible-warning-log behavior (second option) was folded into the decision as a follow-up implementation detail — the user chose the drop-and-continue behavior; whether it also logs is left to planning as Claude's discretion. Recorded as D-04.

---

## Nutrition wire format

| Option | Description | Selected |
|--------|-------------|----------|
| Leave it as a research flag | gsd-phase-researcher investigates HAE field names/units for calories + six macros before planning | ✓ |
| User has a payload/detail to share now | User would type field names/example payload directly | |

**User's choice:** Leave it as a research flag (recommended option)
**Notes:** Existing v2.0 research (SUMMARY/ARCHITECTURE/FEATURES/PITFALLS/STACK) predates the same-day decision to fold nutrition into Phase 8 — nutrition wire shape was never verified the way activity metrics were. Recorded as D-05, an explicit gap for gsd-phase-researcher rather than a guessed decision.

---

## Claude's Discretion

- Webhook auth header scheme (Bearer + `secrets.compare_digest`, mirroring `StaticTokenVerifier`)
- Exact structured-log field names for the unrecognized-metric warning event
- Rate-limit bucket capacity/refill tuning for the new ingest path (a separate bucket is locked; numbers are not)
- Exact ingest route path, as long as registered above the MCP catch-all mount

## Deferred Ideas

- `health_workouts` coverage cross-check table — deferred, not this phase (design stays on file)
- Apple Health as a third `body_measurements` source — deferred to a future revisit of Phase 11's `_dedupe_by_day` work, if ever wanted
- HAE automation configuration specifics (batch requests, aggregation interval) — belongs in a setup doc, not phase code
