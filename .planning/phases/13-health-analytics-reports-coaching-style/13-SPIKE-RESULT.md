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

Recorded by plan 13-09, after `fitness_get_weekly_report` and `fitness_get_monthly_report` are
registered. ROADMAP success criterion #4 names the REPORT tools specifically, so Spike 1 alone
does not discharge RPT-03.

Status: pending.
