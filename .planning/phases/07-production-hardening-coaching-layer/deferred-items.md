# Phase 07 — Deferred Items

Out-of-scope discoveries logged during execution. Not fixed in the plan that found them.

## From plan 07-07 (2026-09-01)

### `backend/app/cli.py` logs `hevy_cli_stopped` on the crash path, so "started + stopped, no failed" is not proof of success

`_run_sync` catches `HevyError` and `RuntimeError` and logs `hevy_cli_failed` for each. Any
other exception — observed live: `sqlalchemy.exc.ProgrammingError` from a database whose schema
was behind the code — propagates uncaught. The `finally` block still logs `hevy_cli_stopped`,
so a failed run produces exactly the log signature a successful run produces:
`hevy_cli_started` … `hevy_cli_stopped`, and **no** `hevy_cli_failed`.

Confirmed against execution `brett-sync-hevy-rmrb5`/`brett-sync-hevy-xv7jv`: both logged
started + stopped with no failed line, and both exited 1.

Consequence for verification: plan 07-07's Task 3 step 6 log check is necessary but not
sufficient. The authoritative success signal is the execution's `status.succeededCount`, which
is what `docs/runbook-sync-schedule.md` records as the primary evidence.

Possible fix, deliberately not made here (it is `cli.py`'s file, not this plan's): add a
bare `except Exception` arm that logs `hevy_cli_failed` with `reason=type(exc).__name__` and
re-raises, so the failure signature is honest without changing the exit code or leaking a
message. Belongs with whoever next owns `backend/app/cli.py`.

### Production database schema drift was invisible until a job ran against it

The live Neon database sat at alembic revision `0002` from the Phase 2 deploy while the code
advanced through `0004`. Nothing detected this: `/health` probes `SELECT 1`, which succeeds
against any schema, and the MCP round trip verified in plan 07-06 confirmed the tool set
without exercising data flow. It surfaced only when the sync job tried to read `sync_state`.

Worth a cheap standing check — e.g. `alembic current` against production compared to `head`
as part of a deploy runbook, or a `/health` field reporting the applied revision. Not built
here; noted so it is not rediscovered the same way.
