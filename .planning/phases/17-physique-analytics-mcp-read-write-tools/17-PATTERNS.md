# Phase 17: Physique Analytics & MCP Read/Write Tools - Pattern Map

**Mapped:** 2026-09-11
**Files analyzed:** 6 (2 new, 4 modified) + 2 read-only reference dependencies
**Analogs found:** 6 / 6

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/app/mcp/tools/physique.py` (NEW — write tool `fitness_log_physique_observation`) | controller (MCP tool) | request-response, write | `backend/app/mcp/tools/program_switch.py` | exact |
| `backend/app/mcp/tools/physique.py` (NEW — read tool `fitness_get_latest_physique_observation`) | controller (MCP tool) | request-response, read | `backend/app/mcp/tools/programs.py` (`fitness_get_training_program`) | exact |
| `backend/app/mcp/tools/_common.py` (MODIFY — docstring only) | utility (shared MCP helpers) | request-response | itself (in-place docstring edit) | n/a — no analog needed |
| `backend/app/analytics/physique.py` (NEW — `get_physique_diff` + volume cross-reference) | service (analytics composition) | transform / batch | `backend/app/analytics/recomposition.py` (composition-only pattern) + `backend/app/analytics/comparison.py` (two-snapshot diff pattern) | role-match (composite of two analogs) |
| `backend/app/db/repositories/physique.py` (MODIFY — `get_latest_observation` supersede filter) | model/repository | CRUD (read) | itself, guided by `backend/app/db/repositories/programs.py::get_active_period`-style predicate-only-change | exact (self-modification) |
| `backend/tests/test_mcp_isolation.py` (MODIFY — widen `_WRITE_ALLOWLIST`) | test | static/structural | itself (existing assertions, values change) | exact |
| `backend/tests/test_mcp_tool_schemas.py` (MODIFY — per-tool `EXPECTED_WRITE_ANNOTATIONS`) | test | static/structural | itself (existing assertions, restructured) | exact |
| `docs/coaching-instructions.md` (MODIFY — new bullet + table rows) | config/docs | n/a | itself (existing sections) | exact |

## Pattern Assignments

### `backend/app/mcp/tools/physique.py` — write tool: `fitness_log_physique_observation`

**Analog:** `backend/app/mcp/tools/program_switch.py` (the ONLY existing write-tool precedent)

**Module docstring contract to copy** (`program_switch.py` lines 1-24): every write module in this
codebase opens by naming (a) which write-guard tests target it, (b) that it is one of exactly N
entries in `_WRITE_ALLOWLIST`, (c) that it must NOT import `read_only_session` unless it also has
a genuine read path (this module DOES have one — the read tool lives in the same file per D-07 —
so unlike `program_switch.py`, `physique.py` legitimately imports both `read_only_session` and
`writable_session`), and (d) the no-raw-SQL-write-import rule applies unconditionally:

```python
"""BRETT's second MCP write path (PHYS-06, PHYS-08; MCP-07, MCP-08).

`fitness_log_physique_observation` is the SECOND tool under `app/mcp/` allowed to commit.
`test_mcp_isolation._WRITE_ALLOWLIST` names this module alongside `program_switch.py`, and
asserts that allowlist holds exactly TWO entries -- a third write tool either fails the
write-import ban (no allowlist at all) or fails that length assertion.

Unlike `program_switch.py`, this module ALSO holds a read tool
(`fitness_get_latest_physique_observation`) in the same file -- both `read_only_session` and
`writable_session` are imported here, deliberately.

Per 12-RESEARCH.md Pitfall A (inherited unchanged), this module must still NOT import `insert`,
`update` or `delete` from `sqlalchemy` -- every write statement lives in
`app/db/repositories/physique.py`; this module only calls into it.
"""
```

**Imports pattern** (`program_switch.py` lines 26-40, adapted):
```python
from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from app.db.repositories.physique import RatingEntry, create_observation, get_latest_observation
from app.db.models.physique import PoseState
from app.mcp.context import AppContext
from app.mcp.tools._common import (
    read_only_session,
    resolve_user_id,
    safe_tool,
    writable_session,
)
from app.mcp.tools.schemas import PhysiqueLogResponse, PhysiqueLogStatus, ...
```

**`safe_tool` degraded-factory pattern** — copy verbatim shape from `program_switch.py` lines 54-77
(`_degraded_switch`): a module-level `_degraded_log()` function returning a `PhysiqueLogResponse`
with `data_available=False`, a `PhysiqueLogStatus.UNKNOWN`-equivalent enum member (never a
"not applied" value — same PITFALLS #15 reasoning: an exception after a successful INSERT must
not read as "nothing happened," because Phase 17's write has no confirmation-token replay path to
fall back on the way `program_switch.py` does), and every other field `None`.

**Core write pattern** — copy the transaction-ownership contract from `program_switch.py` lines
80-239:
- `user_id = resolve_user_id(ctx)` first, always server-side.
- `async with writable_session(ctx) as session:` wraps the entire write body.
- The repository call (`create_observation`) does the INSERT but never commits — matches
  `create_observation`'s own docstring ("the CALLER owns the transaction").
- `await session.commit()` is the LAST statement in the success branch, with nothing able to run
  after it (PITFALLS #15, restated in `program_switch.py` lines 171-175 and 235-238).
- Any refusal path (e.g. an invalid `supersedes_observation_id`) returns without committing and
  relies on the session close to roll back — same as `program_switch.py`'s no-op-switch and
  refused-token branches (lines 132-146, 180-195).

**Supersede-write composition (D-07):** `supersedes_observation_id` + `superseded_reason` are
optional `Annotated[..., Field(...)]` parameters on the SAME tool signature, following
`program_switch.py`'s `confirmation_token: Annotated[str | None, Field(...)] = None` pattern
(lines 92-102) for how an optional gated parameter is declared and documented in its `Field`
description. Validate `supersedes_observation_id` through the existing tenant-scoped
`_read_observation` lookup in `app/db/repositories/physique.py` (already `user_id`-scoped) rather
than adding a new query path — this is what D-07's discretion note asks for.

**Response shape (new, in `mcp/tools/schemas.py`):** follow `ProgramSwitchStatus` /
`ProgramSwitchResponse`'s three-state-enum-plus-flat-response shape (`mcp/tools/schemas.py` lines
241-287) rather than a boolean success flag — model a `PhysiqueLogStatus` StrEnum (e.g. `LOGGED`,
`REFUSED`, `UNKNOWN`) the same way `ProgramSwitchStatus` separates `NOT_APPLIED` from `UNKNOWN`.

---

### `backend/app/mcp/tools/physique.py` — read tool: `fitness_get_latest_physique_observation`

**Analog:** `backend/app/mcp/tools/programs.py` (`fitness_get_training_program`) — the closest
existing "read the one current record, no arguments" tool.

**Full pattern to copy** (`programs.py` lines 1-67):
```python
def _degraded_program() -> TrainingProgramResponse:
    """... every field None, data_available=False ..."""
    return TrainingProgramResponse(data_available=False, program=None, ...)


@safe_tool(degraded=_degraded_program)
async def fitness_get_training_program(ctx: Context[AppContext]) -> TrainingProgramResponse:
    """..."""
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        periods = await get_recent_periods(session, user_id=user_id, limit=2)
        current = periods[0] if periods else None
        # Response built INSIDE the session block -- read_only_session's unconditional
        # rollback() on exit expires every ORM instance it loaded.
        response = TrainingProgramResponse(data_available=True, ...)
    return response
```

Apply directly: `fitness_get_latest_physique_observation` takes no arguments (mirrors
`fitness_get_training_program`'s "what's current is always about now" reasoning), calls
`get_latest_observation(session, user_id=user_id)` inside `read_only_session`, and — critically —
constructs the Pydantic response INSIDE the `async with` block, not after, for the identical
`DetachedInstanceError` reason `programs.py` lines 51-56 document (this matters even more here
because `PhysiqueObservationRecord` is a frozen dataclass assembled by
`_read_observation`/`get_latest_observation` themselves, so the dataclass-to-Pydantic mapping must
happen before the session closes).

**Supersede-aware read (D-08's target for `get_latest_observation`):** the read tool calls the
repository function as-is; the supersede-awareness change belongs entirely in
`db/repositories/physique.py` (see below), not duplicated in the tool.

---

### `backend/app/mcp/tools/_common.py` (docstring update only)

**Analog:** itself — no external analog; this is a two-sentence prose edit.

**Exact text to change** (`_common.py` line 24-25, module docstring's "reusable assets" bullet):
```
**The one writable session** (GOAL-03, PITFALLS #14). ``writable_session`` is
``read_only_session``'s sibling, not its replacement; exactly one tool module opens it.
```
becomes (per `_common.py`'s own docstring already anticipating this, and matching how
`programs.py` lines 5-8 phrase the same fact about `_WRITE_ALLOWLIST`):
```
**The one writable session** (GOAL-03, PITFALLS #14). ``writable_session`` is
``read_only_session``'s sibling, not its replacement; `program_switch.py` and `physique.py` are
the only two tool modules that open it.
```
Also update `writable_session`'s own docstring at line 189-190 ("Used by exactly one module...")
the same way. No functional/code change to this file — `writable_session`, `safe_tool`,
`resolve_user_id`, `local_today` are consumed as-is, verbatim, by the new module.

---

### `backend/app/analytics/physique.py` (NEW) — `get_physique_diff` + volume cross-reference

**Analogs:**
- `backend/app/analytics/recomposition.py` for the composition-only style, the required-disclaimer
  field, and the "read one repository/analytics result, don't re-derive it" discipline.
- `backend/app/analytics/comparison.py` for the two-snapshot-diff shape (though comparison.py
  diffs two DATE PERIODS of aggregated numbers; physique's diff is two discrete OBSERVATIONS of
  discrete rating levels — closer in spirit, not in mechanics).
- `backend/app/analytics/volume.py::get_muscle_group_volume` as the read-only dependency the
  cross-reference function joins against (no new volume query needed).

**Module docstring pattern to copy** (`recomposition.py` lines 1-43 style — lead with the
counter-intuitive rules, cite requirement IDs, name the ONE place a locked constant may be
compared against):
```python
"""Physique diff and volume cross-reference (PHYS-09, PHYS-10). Composition only -- no SQL of
its own beyond calling get_muscle_group_volume and get_latest_observation-shaped inputs.

**RECOMP_LOOKBACK_WEEKS is reused, not reinvented** (D-02). The 12-week window this module's
cross-reference uses is `app.analytics.recomposition.RECOMP_LOOKBACK_WEEKS` -- importing it,
never a second literal `12`, so "am I recomping" and "which muscles are undertrained" describe
the same block of training.

**PHYSIQUE_DIFF_MIN_LEVEL_DELTA gates what counts as a reportable change** (from
`app.db.models.physique`, carried forward from the Phase 15 spike -- copy verbatim, do not
paraphrase or re-derive).

... [D-01 through D-04 volume cross-reference rules, restated from 17-CONTEXT.md decisions] ...
"""
```

**Constants to import, never re-literal:**
```python
from app.analytics.recomposition import RECOMP_LOOKBACK_WEEKS
from app.db.models.physique import (
    PHYSIQUE_DIFF_MIN_LEVEL_DELTA,
    PHYSIQUE_MIN_ELAPSED_DAYS,
    PhysiqueRatingLevel,
)
```

**Diff function shape** — model `get_physique_diff` as a pure/async composition function taking
two already-fetched `PhysiqueObservationRecord`s (or one record plus a repository call) and
returning a frozen Pydantic/dataclass result with one row per `CanonicalMuscleGroup` (all 19,
matching D-07's "always 19 rows" invariant from `db/repositories/physique.py`'s own docstring) —
follow `MuscleGroupVolumeResult`'s "gap-free spine, sorted by `muscle_group.value`" convention
(`volume.py` lines 241-274) rather than only reporting groups that changed.

**Volume cross-reference function** — signature and composition to copy from
`recomposition.py::get_recomposition_status` (lines 577-663): take `session` positionally,
`user_id` keyword-only with no default, call `get_muscle_group_volume` once (reused, never
re-queried — same argument `recomposition.py` line 623-628 makes about `get_exercise_trends`),
derive the bottom-quartile-by-`weighted_sets` set from its `MuscleGroupRollup`-shaped output, cross
it with the latest observation's ratings filtered to `{Minimal, Emerging}` (D-01, D-03: exclude
`Not Assessable` from the underdeveloped side only), and return the flagged-list-only shape (D-04)
— a `list[CanonicalMuscleGroup]` or a small named tuple list, NOT a full 19-row table, matching
`_common.py`'s `MAX_REPORT_PR_HIGHLIGHTS`-style "narrow, purpose-built response" precedent (D-04's
own cited rationale).

**Disclaimer field, if this result ever reaches a caller directly (Phase 18):** reuse the
`INTERPRETATION_DISCLAIMER`-as-required-field pattern from `recomposition.py` lines 108-111 and
938-944 — "Decision support ... not a medical or diagnostic claim" is the register to match if
PHYS-11's "subjective model output, not measurement" framing needs a similar constant.

**Isolation-guard constraints this new module MUST satisfy** (`test_analytics_isolation.py`,
applies automatically via `rglob` — no test file changes needed, but the code must comply):
- No `import app.mcp` or `import app.integrations` (lines 32-33).
- No raw `text(...)` SQL (line 44).
- No `session.commit/flush/add/add_all` and no `insert/update/delete` import (lines 48-51) — this
  module is read/compose only, same as every other `app/analytics/` module.
- `Decimal`, never `float`, anywhere (line 60) — `weighted_sets` is already `Decimal` from
  `volume.py`; do not coerce it.
- No `ExerciseMuscle`/`ExerciseMuscleOverride` class reference (line 37) — irrelevant here since
  this module never queries exercise-muscle tables directly, only composes `get_muscle_group_volume`.

---

### `backend/app/db/repositories/physique.py` — `get_latest_observation` supersede filter

**Analog:** itself. This is a targeted predicate change to an existing function, not a new
pattern. The function's own docstring (lines 256-269) names exactly what changes:

```python
async def get_latest_observation(
    session: AsyncSession, *, user_id: uuid.UUID
) -> PhysiqueObservationRecord | None:
    """... PHYS-08 SCOPE NOTE: this does NOT filter `superseded_at IS NULL` ... When Phase 17
    adds supersede-aware reads, this predicate is the thing it changes.
    """
    observation_id = (
        await session.execute(
            select(PhysiqueObservation.id)
            .where(
                PhysiqueObservation.user_id == user_id,
                PhysiqueObservation.superseded_at.is_(None),  # <-- the added predicate
            )
            .order_by(
                PhysiqueObservation.observed_on.desc(),
                PhysiqueObservation.created_at.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    ...
```

Update the function's own docstring to remove the "SCOPE NOTE" paragraph and state the new
behavior plainly (matching how `create_observation`'s docstring states its own invariant plainly
rather than as a forward-reference). The `_validate_rating_coverage`/`create_observation`
functions need NO changes — the supersede WRITE (setting `superseded_at`,
`superseded_by_id`, `superseded_reason` on the OLDER row when a new observation supersedes it) is
new logic inside `create_observation` or a small helper it calls, added per D-07: when
`supersedes_observation_id` is provided by the MCP write tool, this repository module is where the
UPDATE statement touching the older row's three supersede columns belongs (this module is the
"ONE writer of `physique_observations`" per its own docstring line 3) — likely a small
`_mark_superseded(session, *, observation_id, user_id, superseded_by_id, reason)` helper called
from `create_observation` after the new row is flushed, still inside the same transaction, still
uncommitted (caller commits).

---

### `backend/tests/test_mcp_isolation.py` — widen `_WRITE_ALLOWLIST`

**Analog:** itself — mechanical value/assertion updates, no new pattern.

**Exact changes** (four assertions, per REQUIREMENTS.md's own count, matching CONTEXT.md's
canonical-refs section):

1. Line 79: `_WRITE_ALLOWLIST = frozenset({"program_switch.py"})` →
   `_WRITE_ALLOWLIST = frozenset({"program_switch.py", "physique.py"})`
2. Line 166: `assert len(_WRITE_ALLOWLIST) == 1` → `assert len(_WRITE_ALLOWLIST) == 2`, and update
   the assertion message (lines 166-171) from "exactly ONE module" to "exactly TWO modules" —
   copy the surrounding rationale prose style, just widen the number and add "a THIRD entry" in
   place of "a second entry".
3. `test_the_write_allowlist_holds_exactly_one_module` (lines 174-185): rename to
   `test_the_write_allowlist_holds_exactly_two_modules` (or similar), update both assertions to
   `frozenset({"program_switch.py", "physique.py"})` and `len == 2`.
4. `test_only_one_module_opens_a_writable_session` (lines 187-197): rename similarly, update
   `assert opens_writable == {"program_switch.py"}` → `{"program_switch.py", "physique.py"}`.

Also bump `test_the_walk_actually_finds_files`'s comment/count (lines 130-135) if the new module
pushes the module count past its current floor — check the literal `>= 15` still holds; it likely
does since one new file (`physique.py`) only adds one module, but re-verify the walk's floor
against the actual post-Phase-17 module count.

Also bump `test_every_tool_module_guards_its_public_tools`'s literal `== 19` (lines 296-309, in
`test_mcp_tool_schemas.py`-adjacent file — actually this literal lives in
`test_mcp_isolation.py` line 305) to `== 21` (two new tools: `fitness_log_physique_observation`,
`fitness_get_latest_physique_observation`), following the exact precedent comment style already
in that docstring ("Raised from 17 to 19 in Plan 13-09...").

---

### `backend/tests/test_mcp_tool_schemas.py` — per-tool `EXPECTED_WRITE_ANNOTATIONS`

**Analog:** itself — the existing uniform `WRITE_TOOLS`/`read_only_false` assertions
(`test_annotations_are_an_exact_partition`, lines 142-208) are what gets restructured into a
mapping.

**Current pattern being replaced** (lines 184-202): a single loop asserting every tool in
`read_only_false` (== `WRITE_TOOLS`) carries `destructiveHint=True, idempotentHint=False`
uniformly. MCP-08 needs this to become per-tool because
`fitness_log_physique_observation` is non-destructive (`destructiveHint=False`, since PHYS-06
frames it as an append, never a delete/overwrite of workout-shaped data) while
`fitness_switch_training_program` stays `destructiveHint=True`.

**New structure to add**, modeled directly on the existing `EXPECTED_CAPS` dict pattern (lines
62-77 — "written out as literals on purpose, so the test asserts the CONTRACT, not that a constant
equals itself"):
```python
EXPECTED_WRITE_ANNOTATIONS: dict[str, dict[str, bool]] = {
    "fitness_switch_training_program": {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
    "fitness_log_physique_observation": {
        "readOnlyHint": False,
        "destructiveHint": False,  # PHYS-06: append-only, never destructive
        "idempotentHint": False,
        "openWorldHint": False,
    },
}
```
Update `WRITE_TOOLS` (line 135) to
`frozenset({"fitness_switch_training_program", "fitness_log_physique_observation"})` and its
length assertion (line 157) to `== 2`. Update `EXPECTED_TOOLS` (lines 37-60) to add both new tool
names. Replace `test_the_write_tool_publishes_explicit_write_annotations`'s single-tool assertion
(lines 210-236) with a loop over `EXPECTED_WRITE_ANNOTATIONS.items()`, same
`tool.model_dump(by_alias=True)["annotations"]` extraction, same `_WRITE_ANNOTATION_KEYS` subset
comparison per tool.

Note `fitness_get_latest_physique_observation` is a READ tool and belongs in
`EXPECTED_TOOLS - WRITE_TOOLS`, annotated `READ_ONLY` exactly like every other read tool in
`server.py`'s `_TOOLS` loop — it does NOT enter `EXPECTED_WRITE_ANNOTATIONS`.

Also add both new tool names to `test_ping_is_still_registered_first_class`-adjacent
`test_tool_registry_is_exactly_the_twenty` — rename/recount as needed (21 tools total).

---

### `docs/coaching-instructions.md`

**Analog:** itself — the existing "Which tool answers which question" table and "Things the
schemas do not tell you" bullet list (both read above).

**Table rows to add** (D-05's discretion: place near `fitness_get_recomposition_status` and the
report tools, which already synthesize across sources) — copy the exact table row grammar from
line 69 (`fitness_get_recomposition_status`) and line 71
(`fitness_switch_training_program`, for the two-call write-tool row format):
```
| "Log what I see in my physique photos" | `fitness_log_physique_observation` | **19 muscle-group ratings**, `pose_state`, `photo_angles_present` |
| "What was my last physique observation?" | `fitness_get_latest_physique_observation` | *(none)* |
```
(Exact parameter list depends on the planner's final tool signature — match the table's existing
convention of bolding only the truly required parameters, `*(none)*` for zero-argument tools per
line 65/67/68/69/70/74's precedent.)

**New bullet under "Things the schemas do not tell you"** (D-05: same register as the existing
bullets at lines 78-94 — bolded lead phrase, one gotcha per bullet, declarative):
```
- **A physique rating is derived from the photo, not from the prior observation.** Treat the
  previous rating as a sanity check, never as a target to converge toward — if the photo shows
  clear new development, rate it higher even if the last observation said otherwise. [carries the
  Phase 15 D-08 anti-ratchet instruction; exact wording is the planner's/executor's discretion per
  D-05's own note]
```

**Do NOT add** a second restatement of PHYS-11's "subjective, not measurement" framing (D-06) —
the required `disclaimer`-style field (if `analytics/physique.py` ships one, per the
`RecompositionResult.disclaimer` pattern) already carries that at the response level; no doc echo.

**Verify against `test_coaching_doc.py`** (`_TOOL_TOKEN` regex, lines 20-30): every
`fitness_[a-z_]+` token added to the doc must be one of the two real new tool names exactly, and
both new tool names must appear in the doc or `test_coaching_doc.py`'s "nothing is missing"
direction will fail once that test's own tool-name set is updated to expect them.

## Shared Patterns

### Write-tool module contract (MCP-07/MCP-08)
**Source:** `backend/app/mcp/tools/program_switch.py` (whole file, esp. lines 1-24, 54-77, 111,
174, 238-239)
**Apply to:** `backend/app/mcp/tools/physique.py`'s write tool
- Docstring names the write-guard tests targeting the module by name and states the current
  `_WRITE_ALLOWLIST` size.
- `safe_tool(degraded=<factory>)` decorator on every public `fitness_*` coroutine — no exceptions,
  including this being the write path (`test_every_tool_module_guards_its_public_tools` in
  `test_mcp_isolation.py` scans ALL tool modules, not just read ones).
- `writable_session(ctx)` opens the transaction; `session.commit()` is the LAST statement in every
  success branch; every refusal path returns without committing and relies on session-close
  rollback.
- Degraded factory returns an `UNKNOWN`-style status, never a "not applied" status, on exception.

### Read-tool, no-argument module contract
**Source:** `backend/app/mcp/tools/programs.py` (whole file)
**Apply to:** `backend/app/mcp/tools/physique.py`'s read tool
- `read_only_session(ctx)` opens the transaction.
- Response object constructed INSIDE the `async with` block (ORM/dataclass attributes are read
  before the session's rollback-on-exit detaches them).
- `safe_tool(degraded=<factory>)` with an all-`None`-fields, `data_available=False` payload.

### `_McpModel` / `_AnalyticsModel` base config
**Source:** `backend/app/mcp/tools/schemas.py` lines 67-82; `backend/app/analytics/schemas.py`
lines 42-56 (mirrors it exactly)
**Apply to:** any new Pydantic response/result models in both `mcp/tools/schemas.py` and
`analytics/schemas.py`
```python
model_config = ConfigDict(hide_input_in_errors=True, extra="forbid", frozen=True)
```

### `Decimal`, never `float`
**Source:** `test_analytics_isolation.py` line 60, `test_mcp_isolation.py` line 56 — enforced by
static regex over both `app/analytics/` and `app/mcp/`
**Apply to:** `analytics/physique.py` and `mcp/tools/physique.py` — any percentile/quartile math
for the volume cross-reference must stay `Decimal`, matching `weighted_sets: Decimal` already on
`MuscleGroupVolume`.

### Constant reuse over re-literal
**Source:** `recomposition.py`'s `RECOMP_LOOKBACK_WEEKS` (line 104), `db/models/physique.py`'s
`PHYSIQUE_DIFF_MIN_LEVEL_DELTA`/`PHYSIQUE_MIN_ELAPSED_DAYS`/`PHYSIQUE_RATING_LEVELS` (lines 48-70)
**Apply to:** `analytics/physique.py` — import these constants; never re-declare the number `12`
or the level ordinals locally.

### "All N rows, gap-free spine, sorted by `.value`" response shape
**Source:** `volume.py::get_muscle_group_volume` (lines 241-274), `MuscleGroupVolumeResponse`
docstring (`mcp/tools/schemas.py` lines 419-426)
**Apply to:** `get_physique_diff`'s per-muscle-group output — all 19 `CanonicalMuscleGroup` rows,
never a subset, matching D-07's invariant from `db/repositories/physique.py`.

## No Analog Found

None. Every file in scope has at least a role-match analog in the existing codebase; the write-
tool and read-tool patterns are both exact matches (`program_switch.py`, `programs.py`), and the
analytics composition function is a straightforward blend of two existing analogs
(`recomposition.py`'s composition style + `volume.py`'s dependency).

## Metadata

**Analog search scope:** `backend/app/mcp/tools/`, `backend/app/analytics/`,
`backend/app/db/repositories/`, `backend/app/db/models/`, `backend/tests/`, `docs/`
**Files scanned:** `program_switch.py`, `programs.py`, `_common.py`, `schemas.py` (mcp),
`server.py`, `volume.py`, `recomposition.py`, `comparison.py`, `schemas.py` (analytics),
`physique.py` (db model), `physique.py` (repository), `muscles.py`, `test_mcp_isolation.py`,
`test_mcp_tool_schemas.py`, `test_analytics_isolation.py`, `test_coaching_doc.py`,
`coaching-instructions.md`
**Pattern extraction date:** 2026-09-11
