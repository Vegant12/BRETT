# Phase 13 — RPT-03 Scheduled-Task Spike Record

**Purpose:** the durable record ROADMAP.md success criterion #4 requires — "the outcome, working
or broken with a documented workaround, is written into docs/coaching-instructions.md rather
than assumed." This file is the raw evidence; plan 13-09 writes the one-line user-facing
consequence into `docs/coaching-instructions.md` from it.

## Spike 1 — capability probe with `fitness_ping` (before report tools existed)

| Field | Value |
|---|---|
| Date run | 2026-09-05 |
| Client | Claude Desktop (D-12) |
| Connector | BRETT live remote MCP connector |
| Tool called | `fitness_ping` |
| Verdict | PASS |
| Subagent-delegation workaround | N/A |

**Scheduled run's actual reply:**

> The database field returned by fitness_ping is: 'connected'. This is a routine health check
> with a normal, healthy result — no issue to flag.

**Reading:** The eight community reports in 13-RESEARCH.md Pitfall 5 do not reproduce against
this connector as of this date. The scheduled session's reply quoted the exact string
`fitness_ping`'s implementation (`backend/app/mcp/tools/ping.py`) returns on a successful DB
round-trip — `database="connected"` — which is strong corroborating evidence the tool schema
actually reached the scheduled session and a real call was made, rather than the model guessing
a plausible-sounding value from memory (a model with no tool schema would have no way to produce
"connected" specifically, since neither the tool name nor its output shape is public or otherwise
guessable). Spike 2 must still confirm the report tools specifically, since ROADMAP success
criterion #4 names them, not `fitness_ping`.

## D-13 preamble draft

D-13: this text is added to `docs/coaching-instructions.md` by plan 13-09 **only if** the live
spike actually reproduced the failure. It is drafted here regardless so plan 13-09 does not have
to invent it under a tight character budget.

Status: NOT ELIGIBLE — the spike passed, do not add this

```text
Scheduled tasks: start the prompt with "Delegate this to a subagent; the subagent has the BRETT
tools, you do not." Scheduled sessions sometimes receive no tool schemas.
```

(148 characters. Sized deliberately: D-09's rewritten document must stay under
`_PASTE_CEILING_CHARS = 9_000`.)

## Spike 2 — report tools

Recorded by plan 13-10, after `fitness_get_weekly_report` and `fitness_get_monthly_report` are
registered. ROADMAP success criterion #4 names the REPORT tools specifically, so Spike 1 alone
does not discharge RPT-03.

Status: **PASS**.

| Field | Value |
|---|---|
| Date run | 2026-09-05 |
| Client | Claude Desktop (D-12) |
| Connector | BRETT live remote MCP connector |
| Tool called | `fitness_get_weekly_report` |
| Deployed revision tested | `brett-00011-n2z` (Cloud Run, `us-central1`, project `brett-fitness`, deployed 2026-09-05) |
| Verdict | PASS |
| Subagent-delegation workaround | N/A — not eligible, the verdict was PASS |
| On-demand result | `ON-DEMAND-OK` — confirmed separately in a normal (non-scheduled) conversation with the connector attached; a real answer came back |

**Scheduled run's actual reply (final, passing attempt):**

> window_start: 2026-08-31, window_end: 2026-09-05, muscles list entries: 19

`2026-08-31` is the Monday of the week containing `2026-09-05`, and `19` matches
`CANONICAL_MUSCLE_GROUP_COUNT` — real, correct values, not a plausible-sounding guess.

**Operational context for an honest record (two prior attempts this session, both discarded from
the formal verdict but retained here since they happened live and are informative):**

1. **First attempt**, against the OLD revision `brett-00010-kln` (2026-09-02, before
   `brett-00011-n2z` was deployed): the model reported `fitness_get_weekly_report` "isn't in the
   BRETT MCP server's tool list" / "NO TOOL SCHEMA". Diagnosed as a **false negative from a stale
   revision** — the tool genuinely did not exist on the live server yet at that point. Not a Spike
   2 data point; background only.
2. **Second attempt**, against the newly-deployed `brett-00011-n2z`, before a pending database
   migration was applied: the tool responded, but with `data_available: false` and every other
   field null/empty. Root cause (confirmed via Cloud Run logs): the production database was one
   Alembic migration behind (`alembic current` == `0005`, code needed `0006` for
   `user_program_history`, the Phase 12 training-programs table) —
   `asyncpg.exceptions.UndefinedTableError: relation "user_program_history" does not exist` inside
   `get_recomposition_status` → `get_periods_overlapping`. This is the **third** occurrence of an
   already-twice-documented failure mode (`scripts/deploy-cloud-run.sh` has no migration step; see
   `.planning/STATE.md`). The user ran `alembic upgrade head` against production themselves
   (confirmed after: `alembic current` == `0006 (head)`). Not a valid RPT-03 finding on its own —
   it reproduced a real migration-lag bug, not a scheduled-task schema-delivery failure — but it
   IS corroborating evidence for Spike 2: the tool call reached the real `compose_report` code
   path and executed real SQL, which means the scheduled session DID receive the tool's schema
   and DID invoke it for real, the same signal Spike 1 read out of `fitness_ping`'s exact
   `"connected"` string.

**Reading:** Spike 2 agrees with Spike 1 — both scheduled-task attempts (once the deployed
revision and the database were both current) received the tool schema and completed a real call,
with no workaround needed. The eight community reports 13-RESEARCH.md catalogued do not reproduce
against this connector on this date, for either the connectivity canary (Spike 1) or the report
tools ROADMAP criterion #4 names specifically (Spike 2). Both intervening failures this session
were infrastructure staleness (a stale deployed revision, a migration-lagging database), not
schema-delivery failures — reinforcing rather than undermining the PASS verdict, since a session
that received no tool schema at all could not have produced either failure mode's specific,
data-shaped symptoms.
