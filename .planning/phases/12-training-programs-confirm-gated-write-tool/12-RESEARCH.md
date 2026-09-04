# Phase 12: Training Programs & Confirm-Gated Write Tool - Research

**Researched:** 2026-09-04
**Domain:** MCP write-tool security pattern (server-issued single-use token), effective-dated
history modelling, per-program threshold parametrization in an existing table-driven classifier
**Confidence:** HIGH — every claim below is grounded in this repo's own source (read directly,
including the installed `mcp==2.0.0` package source), this repo's own `PITFALLS.md` research
(already HIGH-confidence per its own header), or a verified web source for the one PostgreSQL
mechanism (`postgresql_where` partial index) not yet used anywhere in this codebase.

## Summary

This phase has almost no external-library research surface — `mcp`, SQLAlchemy, Pydantic and
PostgreSQL are all already pinned, installed, and used elsewhere in this exact way in this repo.
The research value here is entirely in **how the existing patterns compose**: PITFALLS.md #13–#16
already prescribe the shape (server-issued token, narrowed guards, three-state result,
effective-dated history); this document verifies each prescription against the actual installed
SDK source and the actual repo conventions, and resolves the six open design questions the phase
context flagged.

The two decisions with the highest blast radius if gotten wrong: (1) the confirmation token **must
be DB-backed, not in-memory** — `deploy-cloud-run.sh` sets `MIN_INSTANCES=0`
(`PITFALLS.md` #5), so the service scales to zero on idle and a 5-minute TTL can easily span a
cold start that loses any in-process dict; and (2) the write tool's session helper, SQL writes, and
guard-test allowlisting must all be scoped to **exactly one new module**, verified against the
installed `mcp.server.MCPServer.add_tool` signature and the current `test_mcp_isolation.py` /
`test_mcp_tool_schemas.py` assertions this phase must extend without weakening.

**Primary recommendation:** One new MCP tool module (`app/mcp/tools/programs.py`), one new
DB-repository module (`app/db/repositories/programs.py`), two new tables
(`user_program_history`, `program_switch_tokens`), one new `_common.writable_session` sibling to
`read_only_session`, and per-program threshold/matrix tables added directly to
`recomposition.py` following its existing data-table style — no new abstraction layer anywhere.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Program history storage (append-only periods) | Database / Storage | API/Backend (repository) | New table, single source of truth; MCP never queries it directly |
| Active-program resolution ("as of date X") | API/Backend (`app/db/repositories/programs.py`) | Database | Small, testable SQL predicate; reused by both recomposition classification and the MCP read side |
| Per-program threshold/label matrices | API/Backend (`app/analytics/recomposition.py`) | — | Pure, synchronous, table-driven — same tier as today's single-program version |
| Confirmation-token issuance/consumption | API/Backend (`app/db/repositories/programs.py`) | Database (atomic `UPDATE...RETURNING`) | Must be transactionally atomic with the switch; cannot live in-process (Cloud Run `MIN_INSTANCES=0`) |
| Write-tool registration & annotations | API/Backend (`app/mcp/server.py`) | — | Must sit outside `_TOOLS`/`READ_ONLY` loop per PITFALLS #14 |
| Guard/isolation tests | API/Backend (`backend/tests/test_mcp_isolation.py`, `test_mcp_tool_schemas.py`) | — | Static, source-level; no runtime tier |

## User Constraints (from CONTEXT.md)

<user_constraints>

### Locked Decisions

- **D-01–D-03:** Per-program weight-rate thresholds are fixed: Lean Bulk unchanged
  (stable ±0.10%/wk, on-target gain 0.10–0.25%/wk, too-fast gain >0.25%/wk, too-fast loss
  < -1.00%/wk). Cut: stable ±0.10%/wk, on-target loss -0.50% to -1.00%/wk, slow loss -0.10% to
  -0.50%/wk, too-fast loss faster than -1.00%/wk, too-fast gain faster than +0.25%/wk. Recomp:
  stable/on-target ±0.25%/wk, too-fast gain faster than +0.50%/wk, too-fast loss faster than
  -0.50%/wk.
- **D-04/D-05:** Each program gets its own fully explicit bucket-ladder + status matrix (three
  separate tables), NOT a shared "goal-relative" abstraction. Bulk's ladder is asymmetric
  (fine-grained gain side); Cut's mirrors this on the loss side; Recomp's is symmetric.
- **D-06:** Full ~24-cell status assignment per program is Claude's discretion, following Bulk's
  table as precedent, EXCEPT: a stable-or-on-target weight combined with a POSITIVE progression
  signal must generally read `likely_recomp_progressing` across all three tables where the shape
  allows it. No eighth `RecompositionStatus` enum member.
- **D-07:** Append-only, effective-dated history (`program_periods`/`user_program_history` —
  naming left to planning), NOT a mutable `users.active_program` column, per PITFALLS #16.
- **D-08:** Seed the initial history row as Lean Bulk, `started_on` = earliest date BRETT has real
  training data for this user (from synced Hevy history at migration/seed time), not today.
- **D-09:** The switch tool always starts the new period on local today
  (`_common.local_today`); it never accepts a backdated `started_on`.
- **D-10:** A 12-week lookback that straddles a program switch classifies against the CURRENT
  (active) program's thresholds for the whole window, but surfaces a field naming the switch date
  and prior program. Never refuse to classify / return `insufficient_data` for a straddle.
- **D-11:** Confirmation token TTL is 5 minutes.
- **D-12:** `required_scopes` stays `None`. No WorkOS AuthKit scope reconfiguration this phase.
  Leave the in-code "Revisit when the first write tool ships" note in place.
- All other write-tool mechanics follow PITFALLS.md #13–#16 exactly: server-issued single-use
  token bound to exact target state, `confirmation_token: str` not `confirm: bool`, atomic
  consume-in-same-transaction, three-state `applied`/`not_applied`/`unknown` result, narrow
  single-module write allowlist in `test_mcp_isolation.py`, own `ToolAnnotations` registered
  outside the `_TOOLS`/`READ_ONLY` loop.

### Claude's Discretion

- Exact naming of the new history table/columns, the write-tool module's filename/location
  (`app/services/programs.py` OR `app/db/repositories/` per PITFALLS #14 — NOT `app/analytics/`),
  and the exact field name(s) added to `RecompositionResult` for the active program and the
  straddle caveat (D-10) — follow `schemas.py`'s existing conventions.
- The full ~24-cell status matrix per program (D-06) beyond the one preserved rule.
- Whether the three-state result and degraded-payload wording need program-specific phrasing, or
  can be fully generic.

### Deferred Ideas (OUT OF SCOPE)

- Backdating a program switch's start date — declined (D-09). Every switch starts today.
- A required-scope gate on the write tool — declined (D-12), `required_scopes=None` stays.
- Full per-cell status assignment for all three programs beyond the one preserved rule — left to
  planning.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GOAL-01 | Active training program stored as data, not a hardcoded constant | Schema design (`user_program_history`), migration pattern, seed-from-live-data approach below |
| GOAL-02 | Recomposition thresholds/recommendations adapt to the active program | Per-program constant/matrix parametrization pattern for `recomposition.py`, preserving `zip(..., strict=True)` |
| GOAL-03 | Confirm-gated MCP write tool, two-call token design, `confirm: bool` rejected as insufficient | Token schema, atomic issue/consume design, tool signature, verified against installed `mcp==2.0.0` source |
| GOAL-04 | All other tools stay read-only; guard suite extended for exactly one exception | Exact edits needed to `test_mcp_isolation.py` and `test_mcp_tool_schemas.py`, identified below |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

- MCP tools read-only in v1 **except** this phase's one confirm-gated write tool — the exception
  this phase exists to carve out, narrowly.
- Never expose API keys, DB credentials, or internal tokens through MCP responses or logs — the
  confirmation token is server-issued and echoed by the model, not a secret in the `MCP_AUTH_SECRET`
  sense, but `_common.safe_tool`'s exception-interpolation ban still applies to the write tool.
- HTTPS everywhere; secrets only via environment/secret storage — unaffected by this phase.
- Data integrity: writes must be idempotent and must never corrupt existing data on partial
  failure — directly the three-state `applied`/`not_applied`/`unknown` requirement (PITFALLS #15).
- Deployment: Google Cloud Run, `MIN_INSTANCES=0` (verified in `scripts/deploy-cloud-run.sh` per
  PITFALLS #5) — this is why the confirmation token cannot be in-process memory.

## Standard Stack

No new dependencies. Every library this phase needs is already pinned and installed:

| Library | Version (verified installed) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `mcp` | 2.0.0 (verified via `.venv/lib/python3.13/site-packages/mcp`) | `MCPServer.add_tool`, `ToolAnnotations`, `Context[AppContext]` | Already the project's pinned SDK; `add_tool` signature verified live (below) |
| SQLAlchemy | 2.0.x (already in tree) | New tables, atomic `UPDATE...RETURNING`, partial unique index | Existing convention throughout `app/db/` |
| Pydantic | 2.x (already in tree) | New response models, `TrainingProgram` StrEnum | Existing convention in `app/analytics/schemas.py` / `app/mcp/tools/schemas.py` |
| `secrets` (stdlib) | — | `secrets.token_urlsafe(16)` for the confirmation token | PITFALLS #13's exact recommendation; stdlib, no new dependency |
| Alembic | already in tree | New migration(s) for the two new tables | Existing convention (`backend/migrations/versions/000N_*.py`) |

**Version verification:** No `npm view`/`pip index` needed — every package is already installed in
this repo's `.venv` and pinned in `pyproject.toml`/`uv.lock`. Confirmed by direct inspection
(`python3 -c "import mcp; ..."` and `inspect.signature`) rather than by trusting training data.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| DB-backed confirmation token | In-process dict/cache | **Rejected.** `MIN_INSTANCES=0` (verified in `deploy-cloud-run.sh`) means the instance can scale to zero between the warn call and the confirm call within the 5-minute TTL, silently invalidating every token. Also breaks under any future horizontal scaling. |
| Plaintext token stored in DB | SHA-256 hash of the token stored, compared by hash | Hashing is defense-in-depth (token compromise via DB read discloses nothing usable) but not required by CONTEXT.md's decisions or PITFALLS #13's literal recipe (which stores the token value itself). Left as a Claude's-discretion hardening — plaintext storage is acceptable given every call to this endpoint is already bearer/JWT-authenticated before the tool body ever runs. |
| One `user_program_history` table with a boolean `is_active` | A mutable `users.active_program` column | **Explicitly rejected by PITFALLS #16 / D-07.** A mutable column retroactively reclassifies every past verdict inside the 12-week lookback. |
| `ctx.elicit()` as the confirmation gate | Server-issued token (this design) | **Rejected, verified against installed source.** `Context.elicit`'s own docstring (read directly from `.venv`) states: "If the client is an agent, it might decide how to handle the elicitation — either by asking the user or automatically generating a response." Not a guaranteed human gate, and `stateless_http=True` makes `client_capabilities` frequently `None` anyway. |

## Architecture Patterns

### System Architecture Diagram

```
Claude (model)
  │
  │  1st call: fitness_switch_training_program(program="cut")
  ▼
┌─────────────────────────────────────────────────────────────┐
│ app/mcp/tools/programs.py  (NEW — outside _TOOLS loop)       │
│   @safe_tool(degraded=_degraded_switch)                      │
│   async def fitness_switch_training_program(                 │
│       program: TrainingProgram,                               │
│       confirmation_token: str | None = None,                  │
│   ) -> ProgramSwitchResponse                                  │
└───────────────┬─────────────────────────────────────────────┘
                │ no/invalid token → WARN branch
                ▼
┌─────────────────────────────────────────────────────────────┐
│ app/db/repositories/programs.py  (NEW)                        │
│   get_active_period(session, user_id)      -- read current    │
│   issue_switch_token(session, ..., ttl=5min) -- INSERT token   │
└───────────────┬─────────────────────────────────────────────┘
                │ writable_session (NEW _common sibling)
                ▼
        PostgreSQL: program_switch_tokens (INSERT), commit
                │
                ▼
   Response: warning text + confirmation_token + expires_at
                │
   Claude relays the warning to the user, gets confirmation,
   ▼
  2nd call: fitness_switch_training_program(program="cut",
            confirmation_token="<echoed exact token>")
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│ programs.py CONFIRM branch                                    │
│  1. atomic UPDATE program_switch_tokens                       │
│     SET consumed_at = now()                                   │
│     WHERE token = :token AND to_program = :program             │
│       AND consumed_at IS NULL AND expires_at > now()           │
│     RETURNING from_period_id                                   │
│  2. verify from_period_id is still the OPEN period              │
│  3. UPDATE user_program_history SET ended_on = today            │
│     WHERE id = from_period_id AND ended_on IS NULL              │
│  4. INSERT new row (program, started_on=today, ended_on=NULL)   │
│  5. build response object (pure, in memory)                     │
│  6. session.commit()   <-- LAST statement, nothing after it     │
└───────────────┬─────────────────────────────────────────────┘
                ▼
        Response: status="applied", previous/new program, dates
```

Read side (GOAL-02, D-10), unchanged tiers, just a new input:

```
fitness_get_recomposition_status
        │
        ▼
get_recomposition_status(session, user_id)          [app/analytics/recomposition.py]
        │
        ├─→ get_active_period(session, user_id)                       [NEW read]
        ├─→ get_periods_overlapping(session, user_id, window_start,   [NEW read,
        │        anchor)                                               straddle check]
        ├─→ get_body_weight_trend(...)                    [unchanged]
        ├─→ get_exercise_trends(...)                       [unchanged]
        │
        ▼
classify_recomposition(rate, signal, program=active.program)  [now program-parametrized]
        │
        ▼
RecompositionResult(status=..., active_program=..., program_switch_caveat=...)
```

### Recommended Project Structure

```
backend/app/
├── analytics/
│   └── recomposition.py        # per-program constants + 3 matrices added here (D-04/D-05)
├── db/
│   ├── models/
│   │   └── program.py          # NEW: ProgramPeriod, ProgramSwitchToken ORM models
│   └── repositories/
│       └── programs.py         # NEW: get_active_period, get_periods_overlapping,
│                                #      issue_switch_token, consume_token_and_switch
├── mcp/
│   ├── server.py                # write tool registered OUTSIDE the _TOOLS loop
│   └── tools/
│       ├── _common.py           # + writable_session (sibling to read_only_session)
│       ├── programs.py          # NEW: the one write tool, fitness_switch_training_program
│       └── schemas.py           # + TrainingProgram-adjacent response models
└── migrations/versions/
    └── 0006_user_program_history.py   # two tables: user_program_history, program_switch_tokens
```

### Pattern 1: Effective-dated history with a partial unique index

**What:** One append-only table, `ended_on IS NULL` marks the currently-open period, and a
**partial unique index** enforces "at most one open period per user" at the database level
instead of in application code.

**When to use:** Any "current state with history" modelling where a naive mutable-column design
would retroactively rewrite past derived answers (PITFALLS #16's exact failure mode).

**Example (verified pattern — `postgresql_where` confirmed via SQLAlchemy/Alembic docs and
community usage; not yet used elsewhere in this repo, so treat the specific migration syntax as
MEDIUM confidence pending a first real `alembic upgrade` run against Postgres 18):**

```python
# Source: SQLAlchemy Core Index(postgresql_where=...) — verified via web search against
# sqlalchemy/alembic project docs and issue trackers (multiple independent sources agree
# on the op.create_index(..., unique=True, postgresql_where=sa.text(...)) shape).
op.create_index(
    "uq_user_program_history_one_open_period",
    "user_program_history",
    ["user_id"],
    unique=True,
    postgresql_where=sa.text("ended_on IS NULL"),
)
```

Query "the active program as of date X" (used for both the read path and D-10's straddle
detection):

```python
# app/db/repositories/programs.py
async def get_active_period(session: AsyncSession, *, user_id: uuid.UUID) -> ProgramPeriod | None:
    """The currently open period -- ended_on IS NULL. At most one row by the partial index."""
    return await session.scalar(
        select(ProgramPeriod).where(
            ProgramPeriod.user_id == user_id, ProgramPeriod.ended_on.is_(None)
        )
    )


async def get_periods_overlapping(
    session: AsyncSession, *, user_id: uuid.UUID, window_start: dt.date, window_end: dt.date
) -> Sequence[ProgramPeriod]:
    """Every period touching [window_start, window_end], ascending by started_on.

    More than one row means the window straddles a switch (D-10). Ascending order lets the
    caller report "N weeks of X, M weeks of Y" without a second query.
    """
    stmt = (
        select(ProgramPeriod)
        .where(
            ProgramPeriod.user_id == user_id,
            ProgramPeriod.started_on <= window_end,
            or_(ProgramPeriod.ended_on.is_(None), ProgramPeriod.ended_on >= window_start),
        )
        .order_by(ProgramPeriod.started_on)
    )
    return (await session.scalars(stmt)).all()
```

### Pattern 2: Atomic single-use token consumption

**What:** `UPDATE ... WHERE consumed_at IS NULL AND expires_at > now() RETURNING ...` in one
round trip — the row either updates and returns (first, valid, un-expired use) or the `UPDATE`
matches zero rows (already consumed, expired, or wrong token/program), with no read-then-write
race window.

**When to use:** Exactly this: a single-use, time-limited authorization token consumed inside the
same transaction as the state change it authorizes (PITFALLS #13's "consume atomically").

**Example:**

```python
# app/db/repositories/programs.py
async def consume_switch_token(
    session: AsyncSession, *, token: str, program: TrainingProgram
) -> uuid.UUID | None:
    """Atomically spend the token. Returns the authorized from_period_id, or None if the
    token is missing, already consumed, expired, or bound to a different target program.

    The `to_program = :program` predicate is IN the WHERE clause, not checked after the
    fact: a mismatched program argument leaves the token untouched (available for a
    corrected retry within its TTL) rather than silently burning a valid token on a typo.
    """
    stmt = (
        update(ProgramSwitchToken)
        .where(
            ProgramSwitchToken.token == token,
            ProgramSwitchToken.to_program == program.value,
            ProgramSwitchToken.consumed_at.is_(None),
            ProgramSwitchToken.expires_at > func.now(),
        )
        .values(consumed_at=func.now())
        .returning(ProgramSwitchToken.from_period_id)
    )
    return await session.scalar(stmt)
```

### Pattern 3: Per-program threshold/matrix tables (extends `recomposition.py`'s own style)

**What:** Keep the existing `_WeightBucket` / `_MATRIX_ROWS` / `_LABEL_MATRIX` / `zip(...,
strict=True)` shape, but key everything by `TrainingProgram` at the outermost level — three full
copies of the constant block and the matrix, not a parametrized bucket function.

**When to use:** Exactly D-04's instruction: "write three tables," not a shared abstraction.

**Example — sketch, not the full ~24-cell assignment (D-06 leaves that to planning):**

```python
# app/analytics/recomposition.py — extends the existing module, does not replace it

_THRESHOLDS: Mapping[TrainingProgram, "_ProgramThresholds"] = MappingProxyType({
    TrainingProgram.LEAN_BULK: _ProgramThresholds(
        too_fast_gain=Decimal("0.25"), too_fast_loss=Decimal("-1.00"),
        stable_band=Decimal("0.10"), on_target_loss_far=None, on_target_loss_near=None,
    ),
    TrainingProgram.CUT: _ProgramThresholds(
        too_fast_gain=Decimal("0.25"), too_fast_loss=Decimal("-1.00"),
        stable_band=Decimal("0.10"),
        on_target_loss_far=Decimal("-1.00"), on_target_loss_near=Decimal("-0.50"),
    ),
    TrainingProgram.RECOMP: _ProgramThresholds(
        too_fast_gain=Decimal("0.50"), too_fast_loss=Decimal("-0.50"),
        stable_band=Decimal("0.25"), on_target_loss_far=None, on_target_loss_near=None,
    ),
})

# Each program still gets its OWN _MATRIX_ROWS / _LABEL_MATRIX built the same
# zip(..., strict=True) way the single-program version does today -- three separate
# MappingProxyType tables, not one shared dict keyed by an extra tuple element. This keeps
# a missing branch a load-time ImportError PER PROGRAM, exactly as D-04 asks.
```

`get_recomposition_status` changes from reading five module constants to reading
`_THRESHOLDS[active_program]` and `_LABEL_MATRIX_BY_PROGRAM[active_program]`, resolved once at the
top of the function from the period returned by `get_active_period`. `zip(..., strict=True)` is
unaffected — it still zips one program's four-signal row against `_SIGNAL_ORDER`, just three times
at import time instead of once.

### Pattern 4: Write tool registered outside the shared loop

**Verified live against the installed `mcp==2.0.0` package** (`inspect.signature(MCPServer.add_tool)`):

```python
(self, fn, name=None, title=None, description=None,
 annotations: ToolAnnotations | None = None, icons=None, meta=None,
 structured_output: bool | None = None) -> None
```

```python
# app/mcp/server.py — added AFTER the `for _fn, _description in _TOOLS:` loop, never inside it
from app.mcp.tools.programs import fitness_switch_training_program

WRITE_TOOL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,  # explicit: spec default is True; this tool touches only this DB
)

mcp.add_tool(
    fitness_switch_training_program,
    name="fitness_switch_training_program",
    description="Switch the active training program (Lean Bulk/Cut/Recomp). Two-call "
    "confirmation: the first call returns a one-time token; only a second call echoing "
    "that exact token performs the switch.",
    annotations=WRITE_TOOL,
)
```

`ToolAnnotations.model_fields` confirmed live: `title`, `read_only_hint` (alias `readOnlyHint`),
`destructive_hint` (`destructiveHint`), `idempotent_hint` (`idempotentHint`), `open_world_hint`
(`openWorldHint`) — matches `server.py`'s existing `READ_ONLY` object shape exactly, so the new
`WRITE_TOOL` object is a drop-in sibling, not a new pattern.

### Pattern 5: `writable_session` — `read_only_session`'s sibling, not its replacement

```python
# app/mcp/tools/_common.py — NEW function, read_only_session is NOT modified
@asynccontextmanager
async def writable_session(ctx: Context[AppContext]) -> AsyncIterator[AsyncSession]:
    """The one session in app/mcp/ that PostgreSQL will let write.

    Used by exactly one tool module (fitness_switch_training_program). Unlike
    read_only_session, this does NOT set postgresql_readonly and does NOT roll back
    unconditionally in `finally` -- the caller must commit explicitly, and commit is the
    LAST statement the tool body executes (PITFALLS #15), so a post-commit exception has
    nothing left to do but propagate into safe_tool's `unknown` path.
    """
    sessionmaker = ctx.request_context.lifespan_context.sessionmaker
    async with sessionmaker() as session:
        yield session
```

### Pattern 6: Three-state result, `safe_tool`-compatible

```python
# app/mcp/tools/schemas.py — new StrEnum + response model, following data_available convention
class ProgramSwitchStatus(StrEnum):
    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    UNKNOWN = "unknown"


class ProgramSwitchResponse(_McpModel):
    data_available: bool
    status: ProgramSwitchStatus
    reason: str | None          # populated for NOT_APPLIED / UNKNOWN; None for APPLIED
    requested_program: TrainingProgram
    previous_program: TrainingProgram | None
    previous_period_started_on: dt.date | None
    switched_on: dt.date | None
    confirmation_token: str | None    # populated ONLY on the warn-branch response
    expires_at: dt.datetime | None    # populated ONLY on the warn-branch response
```

```python
# app/mcp/tools/programs.py
def _degraded_switch() -> ProgramSwitchResponse:
    """safe_tool's exception path. UNKNOWN, never NOT_APPLIED -- an exception here means we
    do not know whether the commit that may have already happened landed (PITFALLS #15).
    The degraded text instructs the model to READ the current program back, not retry.
    """
    return ProgramSwitchResponse(
        data_available=False, status=ProgramSwitchStatus.UNKNOWN,
        reason="Could not confirm whether the switch applied. Call the program-status read "
        "tool to check the current active program before retrying.",
        requested_program=..., previous_program=None, previous_period_started_on=None,
        switched_on=None, confirmation_token=None, expires_at=None,
    )
```

### Anti-Patterns to Avoid

- **Weakening `read_only_session` or its guard test to accommodate the write tool.** Add a
  sibling; never touch the original (PITFALLS #14, explicit).
- **Putting `insert`/`update`/`delete` SQLAlchemy imports inside `app/mcp/`.** Keep every actual
  write statement construction inside `app/db/repositories/programs.py`. This keeps the
  `_WRITE_IMPORT` regex allowlist in `test_mcp_isolation.py` needing **zero** new entries — only
  `_SESSION_WRITE` (the `session.commit()` call) needs the one-module allowlist.
  Verified: `_WRITE_IMPORT` matches `from sqlalchemy import ... insert|update|delete`, which the
  MCP module never needs to write if the repository owns all statement construction.
- **A generic toward-goal/away-from-goal abstraction shared by all three programs.** D-04
  explicitly rejects this in favor of three explicit tables.
- **Checking `program == confirmation_token`'s bound target only after consuming the token.**
  Bind the `to_program` predicate into the atomic `UPDATE ... WHERE` itself (Pattern 2) so a
  mismatched argument cannot burn a token it didn't actually authorize.
- **Building `ctx.elicit()` into the control path.** Acceptable as an *additional* UX nicety on
  clients that support it; verified via the installed SDK source that it is not a guaranteed
  human gate and degrades to `None` capabilities under `stateless_http=True`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| "Only one open period per user" invariant | An application-level check-then-insert | PostgreSQL partial unique index (`ended_on IS NULL`) | Race-free by construction; the database enforces it even if two requests interleave |
| Single-use token semantics | A Python-side "is this token already used" set/cache | Atomic `UPDATE ... WHERE consumed_at IS NULL ... RETURNING` | The in-process alternative is exactly the pitfall this research flags for `MIN_INSTANCES=0` — it does not survive a scale-to-zero event |
| Human-in-the-loop confirmation | `ctx.elicit()` alone | Server-issued token echoed by the model | Verified from the SDK's own docstring: an agent client "might decide how to handle the elicitation ... automatically generating a response" — not a gate |
| Exception-safe write reporting | A bespoke try/except per branch in the tool | `safe_tool` (already exists), with a three-state `degraded()` factory | `safe_tool` already closes the DSN-leak hole (MCP-06); reuse it, do not reinvent exception handling for one tool |

**Key insight:** Every mechanism this phase needs already exists in the codebase in a slightly
narrower form (`read_only_session`, `safe_tool`, the repository never-commits convention, the
data-table classifier style). The design work is almost entirely "add a sibling, narrow a guard,"
not "invent a new pattern."

## Common Pitfalls

*(This phase's four defining pitfalls are documented in full in `.planning/research/PITFALLS.md`
#13–#16, which CONTEXT.md already designates canonical reading. They are not restated here in
full; below are the two implementation traps found during this research pass that PITFALLS.md
does not already spell out at the SQL/test-mechanics level.)*

### Pitfall A: `test_mcp_never_writes`'s `_WRITE_IMPORT` regex bans the write module too, unless statements stay in the repository

**What goes wrong:** If the confirmation-token `UPDATE...RETURNING` or the period-close/open
`INSERT`/`UPDATE` statements are constructed directly inside `app/mcp/tools/programs.py` (rather
than inside `app/db/repositories/programs.py`), the existing `_WRITE_IMPORT` regex
(`from sqlalchemy import ... insert|update|delete`) matches the new module too, and the "exactly
one entry" allowlist this phase must add would need to cover TWO regexes' worth of exceptions
instead of one, muddying the "one write module" invariant GOAL-04/success-criterion-#5 wants
provably true.

**Why it happens:** SQLAlchemy's `update()`/`insert()` are the natural thing to reach for when
building the atomic token-consumption statement, and it is easy to write it inline in the tool for
speed.

**How to avoid:** Keep `app/mcp/tools/programs.py` free of any `insert`/`update`/`delete` import.
It calls `app.db.repositories.programs.consume_switch_token(...)`,
`app.db.repositories.programs.switch_program(...)`, etc., and only calls `session.commit()`
itself. Only `_SESSION_WRITE` then needs the one-module allowlist entry.

**Warning signs:** `test_mcp_never_writes` failing on `_WRITE_IMPORT` (not just `_SESSION_WRITE`)
for the new module.

### Pitfall B: `test_every_tool_module_guards_its_public_tools`'s hardcoded count of 13

**What goes wrong:** `test_mcp_isolation.py:249` asserts `len(found) == 13` as a deliberate
literal (its own comment explains why: "the loop above proves every tool it FINDS is decorated,
which says nothing if the walk found none of them"). Adding `fitness_switch_training_program`
without raising this literal to 14 makes the test walk find 14 `@safe_tool`-decorated functions
but still assert 13 — it will fail loudly, which is correct, but a planner who does not know this
literal exists might spend time debugging the wrong thing.

**How to avoid:** This IS a deliberate tripwire, not a bug — the test's own docstring says to
raise it "all three" places when a tool is added: here, `server.py`'s registration, and
`EXPECTED_TOOLS` in `test_mcp_tool_schemas.py`. Plan a task that touches all three in the same
commit.

**Warning signs:** N/A — this is meant to fail until fixed; the risk is only wasted debugging time
if the planner doesn't know it's expected.

## Code Examples

### Migration shape for the two new tables

```python
# backend/migrations/versions/0006_user_program_history.py — sketch; hand-review as convention
# dictates (see 0005's own header: "Generated by alembic revision --autogenerate and
# hand-reviewed" -- autogenerate does NOT detect postgresql_where partial indexes reliably,
# per multiple sqlalchemy/alembic issue-tracker reports, so this table's index must be
# hand-written regardless of what autogenerate proposes).

def upgrade() -> None:
    op.create_table(
        "user_program_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("program", sa.String(length=16), nullable=False),  # 'lean_bulk'|'cut'|'recomp'
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("ended_on", sa.Date(), nullable=True),  # NULL == currently open
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_user_program_history_one_open_period", "user_program_history",
        ["user_id"], unique=True, postgresql_where=sa.text("ended_on IS NULL"),
    )
    # D-08: seed from LIVE data, not a hardcoded literal -- a migration that hardcodes
    # "2025-06-01" would be correct only on the one database it was written against.
    op.execute(sa.text("""
        INSERT INTO user_program_history (id, user_id, program, started_on, ended_on)
        SELECT gen_random_uuid(), u.id, 'lean_bulk',
               (MIN(w.start_time) AT TIME ZONE u.timezone)::date, NULL
        FROM users u JOIN workouts w ON w.user_id = u.id
        GROUP BY u.id, u.timezone
    """))

    op.create_table(
        "program_switch_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("from_period_id", sa.UUID(), nullable=False),
        sa.Column("to_program", sa.String(length=16), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_period_id"], ["user_program_history.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
```

**Note on the seed migration's edge case (flagged, not resolved here):** `MIN(w.start_time)`
returns no row for a user with zero synced workouts. This repo's real production database already
has 218+ synced Hevy workouts (per PITFALLS.md's own figures), so this is not a blocking risk for
the actual deploy target — but a fresh/test database that runs migrations before any Hevy sync has
happened would get zero seed rows, silently. Flagged in Open Questions below for the planner to
decide: fail the migration loudly, or leave it to be caught by `get_active_period` returning `None`
(which the recomposition path must already handle as "no program data yet," similar to today's
`insufficient_data` path).

### Guard-test edits required (exact locations)

```python
# backend/tests/test_mcp_isolation.py
# 1. _SESSION_WRITE check needs a one-module allowlist:
_WRITE_ALLOWLIST = frozenset({"programs.py"})   # exactly one entry, by name -- PITFALLS #14

def test_mcp_never_writes() -> None:
    for path in _mcp_modules():
        if path.name in _WRITE_ALLOWLIST:
            continue
        ...  # existing assertions unchanged for every other module
    # NEW: a second assertion that the allowlist itself has exactly one entry, so a second
    # write tool ever being added is also a red test.
    assert len(_WRITE_ALLOWLIST) == 1

# 2. The literal tool count rises from 13 to 14 (see Pitfall B above).
# 3. _NOT_TOOL_MODULES stays as-is -- programs.py DOES hold a registered tool, so it is not exempt.
```

```python
# backend/tests/test_mcp_tool_schemas.py
# 1. EXPECTED_TOOLS gains "fitness_switch_training_program"
# 2. test_tool_registry_is_exactly_the_fourteen -> rename to fifteen, update the docstring
# 3. test_every_tool_is_annotated_read_only MUST become an exact-partition assertion
#    (PITFALLS #14's explicit instruction): 14 tools with readOnlyHint=True, exactly 1 with
#    readOnlyHint=False/destructiveHint=True. The current version of this test asserts EVERY
#    tool is read-only -- that must change to assert the partition, not merely skip the one
#    exception, or it stops proving anything about the OTHER fourteen.
```

## State of the Art

No external ecosystem drift applies here — this is entirely internal-repo pattern extension. The
one relevant "current vs. historical" note: `mcp==2.0.0`'s `Context.elicit()` (v2's replacement for
v1's various interactive-input primitives) still is not a security control, confirmed by reading
the currently-installed source rather than assuming the newer SDK fixed this — it has not, by
design (the docstring explicitly allows an agent client to auto-generate a response).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Storing the confirmation token in plaintext (not hashed) is acceptable given the tool is already behind bearer/JWT auth | Alternatives Considered | Low — worst case is a future hardening pass adds hashing; no functional break. Flagged as Claude's discretion in CONTEXT.md already. |
| A2 | `TrainingProgram` StrEnum belongs in `app/analytics/schemas.py` (precedent: `BodyMeasurementMetric` lives there despite mapping to DB columns) rather than `app/db/models/` | Pattern 3, Recommended Project Structure | Low — a naming/location choice CONTEXT.md explicitly leaves to planning; easy to relocate before implementation, costly only if implemented then moved |
| A3 | A fresh/fixtureless database (zero synced workouts) at migration time would leave `user_program_history` with zero seed rows, and this is acceptable because production already has real Hevy history | Code Examples note | Medium if wrong for a future dev/test environment that runs migrations before seeding Hevy data — `get_active_period` would need to handle `None` gracefully, which it should anyway, but this hasn't been exercised against an empty-workouts database |

## Open Questions (RESOLVED)

1. **RESOLVED — Should the migration's seed `INSERT...SELECT` fail loudly or silently produce
   zero rows for a user with no synced Hevy history yet?**
   - What we know: production already has extensive real Hevy history, so this will not surface
     there. Test/dev databases that run migrations before any Hevy sync would seed nothing.
   - What's unclear: whether `test_migrations_round_trip` (mentioned in `0005`'s downgrade
     comment) or any other test runs this migration against an empty `workouts` table.
   - Recommendation: planner should check whether the migration test suite runs migrations
     against a schema with zero workout rows, and if so, either seed a guaranteed-safe fallback
     (e.g., skip the INSERT if no workouts exist, leaving `get_active_period` to return `None`
     until the first Hevy sync happens — which the recomposition path must already tolerate) or
     assert the test seeds at least one workout first.
   - **Resolution:** `12-01-PLAN.md` Task 2 seeds via `LEFT JOIN` + `COALESCE` fallback to
     `users.created_at` when no workouts exist, so the seed row is never silently dropped. Verified
     by `12-01-PLAN.md` Task 3's test docstring, which cites this question directly.

2. **RESOLVED — Does the confirm call need to repeat the `program` argument, or can the tool infer
   it purely from the token?**
   - What we know: PITFALLS #13's literal recipe says the switch call "takes
     `confirmation_token: str`" and separately says the token must be "bound to the target" with a
     mismatch check on a second call that "asks for" a different program — implying `program` IS
     still an argument on the confirm call.
   - What's unclear: whether making `program` optional-but-cross-checked-if-present vs.
     always-required is the better model-ergonomics choice; both satisfy the security property.
   - Recommendation: keep `program` required on every call (this document's design) — it is the
     simpler schema (one required parameter, always present) and gives the model a natural,
     self-documenting call shape on both turns.
   - **Resolution:** `12-04-PLAN.md` Task 2 implements exactly this — `program` is required on
     both the warn and confirm calls, per the recommendation above.

## Environment Availability

Skipped — this phase adds no new external dependency, service, or CLI tool. Everything needed
(`mcp`, SQLAlchemy, PostgreSQL, Alembic) is already installed and verified live in this repo's
`.venv` during this research session.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (verified in `pyproject.toml`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest -m "not integration"` |
| Full suite command | `uv run pytest` (spins up `testcontainers.community.postgres.PostgresContainer("postgres:18-alpine")` per `conftest.py`) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GOAL-01 | Program stored as data, seeded correctly | integration | `uv run pytest backend/tests/test_db_program_history.py -x` | ❌ Wave 0 |
| GOAL-02 | Recomposition classifies against active program's own thresholds; straddle reported | unit + integration | `uv run pytest backend/tests/test_analytics_recomposition.py -x` (existing file, extend) | ✅ existing, extend |
| GOAL-03 | Single call cannot switch; token binds to target, single-use, TTL-expires | integration | `uv run pytest backend/tests/test_mcp_program_switch.py -x` | ❌ Wave 0 |
| GOAL-04 | Every other tool still read-only; exactly one write-module allowlist entry | unit (static) | `uv run pytest backend/tests/test_mcp_isolation.py backend/tests/test_mcp_tool_schemas.py -x` | ✅ existing, extend |

### Sampling Rate

- **Per task commit:** `uv run pytest -m "not integration"` (the static guard tests in
  `test_mcp_isolation.py` and the schema tests in `test_mcp_tool_schemas.py` that don't need a
  container run here; the token-atomicity and PostgreSQL read-only-transaction tests do not).
- **Per wave merge:** `uv run pytest` (full suite, container-backed — required for anything that
  touches the partial unique index, the atomic `UPDATE...RETURNING`, or `read_only`/`writable`
  transaction behavior, none of which SQLite-equivalent or mocked tests could validate).
- **Phase gate:** Full suite green before `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] `backend/tests/test_db_program_history.py` — covers GOAL-01: seed migration produces the
      correct row, partial unique index rejects a second open period, `get_active_period` and
      `get_periods_overlapping` return correct results across a switch.
- [ ] `backend/tests/test_mcp_program_switch.py` — covers GOAL-03: single-call switch attempt is
      rejected (no state change), token round-trip succeeds, wrong-program token is rejected
      without being consumed, expired token is rejected, replayed (already-consumed) token is
      rejected, concurrent-consume race resolves to exactly one winner.
- [ ] Extend `backend/tests/test_mcp_isolation.py` — the one-module write allowlist and its
      "exactly one entry" self-check (GOAL-04).
- [ ] Extend `backend/tests/test_mcp_tool_schemas.py` — `EXPECTED_TOOLS` gains the new name; the
      read-only-annotation test becomes an exact-partition assertion (GOAL-04).
- [ ] Extend `backend/tests/test_analytics_recomposition.py` (or confirm its existing name) —
      per-program threshold classification for all three programs' full matrices, plus the
      straddle-caveat field (GOAL-02).

Framework install: none — pytest, pytest-asyncio, and testcontainers are already present and
already exercised by the existing MCP test suites this phase extends.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (unchanged) | `AuthKitJWTVerifier` / `StaticTokenVerifier` — every call to the write tool is already authenticated exactly like every read tool; this phase adds no new auth mechanism |
| V3 Session Management | no | `stateless_http=True`; the confirmation token is an authorization artifact, not a session |
| V4 Access Control | yes | `resolve_user_id` resolves the tenant server-side (unchanged); the token additionally binds to a specific `from_period_id` + `to_program`, so even an authenticated caller cannot apply a token to a different target than the one it was issued for |
| V5 Input Validation | yes | `TrainingProgram` as a closed `StrEnum` (SDK-validated at the schema layer, same as `BodyMeasurementMetric`'s existing precedent, D-09-style); `confirmation_token` is an opaque bound string, never interpolated into SQL |
| V6 Cryptography | yes (minimal) | `secrets.token_urlsafe(16)` — CSPRNG-backed, stdlib, matches PITFALLS #13's explicit recommendation; no hand-rolled randomness |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Model sets a boolean `confirm=true` on the first call | Elevation of Privilege | Server-issued opaque token as the ONLY confirmation credential; `confirm: bool` never exists in the schema (GOAL-03, verified via installed SDK that no protocol-level rule prevents a model from front-loading arguments) |
| Token replay against a different target program | Elevation of Privilege / Tampering | `to_program` bound into the token row and checked in the same atomic `UPDATE...WHERE` that consumes it |
| Token replay after consumption (double-apply) | Tampering / Repudiation | `consumed_at IS NULL` in the atomic `UPDATE...WHERE`; second attempt matches zero rows |
| Stale token found in a scrolled-back conversation | Elevation of Privilege | `expires_at > now()` in the same atomic predicate; D-11's 5-minute TTL |
| Exception mid-write leaks DSN/internal detail to the model | Information Disclosure | `safe_tool` (already exists, MCP-06) wraps the write tool exactly as it wraps every read tool; verified the exception-interpolation ban (`_EXC_IN_RETURN` regex) applies unchanged to the new module |
| A future second write tool silently added without the same guards | Elevation of Privilege | `test_mcp_never_writes`'s allowlist asserts exactly one entry (Pitfall A above); `test_every_tool_is_annotated_read_only` becomes an exact-partition test, not a "some tools are read-only" test |

## Sources

### Primary (HIGH confidence)
- `.venv/lib/python3.13/site-packages/mcp/` (installed `mcp==2.0.0`) — `MCPServer.add_tool` signature, `ToolAnnotations.model_fields`, `Context.elicit` docstring — read directly via `inspect`
- `backend/app/analytics/recomposition.py` — full read, existing constants/matrix/classify function
- `backend/app/analytics/schemas.py` — full read, `RecompositionResult`/`RecompositionStatus`/model conventions
- `backend/app/mcp/server.py` — full read, `_TOOLS` loop, `READ_ONLY`, `required_scopes=None` rationale
- `backend/app/mcp/tools/_common.py` — full read, `read_only_session`, `safe_tool`, `local_today`
- `backend/app/mcp/tools/body.py`, `backend/app/mcp/tools/schemas.py` — tool/response-model conventions
- `backend/app/mcp/auth.py` — `AccessToken.scopes`, `AuthKitJWTVerifier` — confirms D-12 needs no change
- `backend/app/db/models/user.py`, `backend/app/db/models/body.py`, `backend/app/db/models/sync_state.py` — column/table conventions
- `backend/app/db/repositories/sync_state.py`, `backend/app/db/repositories/workouts.py` — repository never-commits convention, upsert pattern, the one already-precedented `app/db -> app/analytics` import arrow
- `backend/tests/test_mcp_isolation.py`, `backend/tests/test_mcp_tool_schemas.py`, `backend/tests/test_mcp_readonly.py` — full read, exact guard mechanics this phase must extend
- `backend/migrations/versions/0002_seed_default_user.py`, `0005_health_daily_metrics.py` — migration/seed conventions
- `scripts/deploy-cloud-run.sh` (via `.planning/research/PITFALLS.md` #5's direct quote) — confirmed `MIN_INSTANCES=0`
- `.planning/research/PITFALLS.md` #13–#16 — full text read, canonical per CONTEXT.md

### Secondary (MEDIUM confidence)
- SQLAlchemy/Alembic `postgresql_where` partial-index syntax — web search cross-referencing multiple independent sqlalchemy/alembic GitHub issues and a third-party walkthrough, all agreeing on the `Index(postgresql_where=...)` / `op.create_index(..., unique=True, postgresql_where=sa.text(...))` shape; not yet exercised in THIS repo, so flagged MEDIUM until a real migration runs against Postgres 18

### Tertiary (LOW confidence)
- None used as authoritative — every claim above traces to installed source, this repo's own committed code, or a cross-verified web search.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; every claim verified against the installed package or this repo's own source
- Architecture: HIGH — every pattern is either already implemented elsewhere in this repo (read directly) or is PITFALLS.md's own prescription (already HIGH-confidence research)
- Pitfalls: HIGH for #13–#16 (canonical, already verified in PITFALLS.md); HIGH for the two new pitfalls found here (both are direct readings of the current guard-test source)

**Research date:** 2026-09-04
**Valid until:** 30 days (stable internal-repo patterns; no fast-moving external dependency in this phase) — re-verify sooner only if `mcp` is upgraded past 2.0.0 before this phase executes
