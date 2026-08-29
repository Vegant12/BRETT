# Phase 3 — Deferred Items

Out-of-scope discoveries logged during execution. Per the executor scope boundary, these are
**not** fixed by the plan that found them: they pre-date the change and live in files the task
only incidentally touched.

| Found in | Item | Why deferred |
|----------|------|--------------|
| 03-01 Task 3 | `mypy backend/tests/conftest.py` reports 6 errors, all pre-existing: `The return type of an async generator function should be "AsyncGenerator" or one of its supertypes [misc]` and `Unused "type: ignore" comment [unused-ignore]` on the `engine` / `session` / `client` fixtures. | Verified pre-existing by stashing the 03-01 conftest edit and re-running mypy: the identical 6 errors appear at the pre-change line numbers (191/195 instead of 224/228), i.e. they are only shifted by this plan's +33 lines, not caused by them. The repo's type gate is `mypy backend/app` (plan `<verification>` step 3), which exits 0. Fixing the fixture annotations means changing `-> AsyncEngine` to `-> AsyncGenerator[AsyncEngine, None]` and dropping the now-redundant `# type: ignore[misc]` on three fixtures — a self-contained cleanup, but it touches shared fixtures every Phase 3 plan depends on, so it should not land mid-wave. |
| 03-10 Task 2 | An unreachable database makes `python -m app.cli` exit 1 with a raw Python traceback rather than a one-line message. Verified by hand against a closed port: the traceback names only host and port (`ConnectionRefusedError: [Errno 61] Connect call failed ('127.0.0.1', 1)`) and does **not** contain the DSN password, so this is a UX gap and not a FOUND-05 leak. | Out of scope for 03-10: the plan specifies exactly two handled failures (`HevyError` and `build_hevy_client`'s missing-key `RuntimeError`) and says nothing about database reachability. Catching `SQLAlchemyError`/`OSError` around the run and printing a curated line is a small, self-contained addition, but it changes the CLI's failure contract and belongs with Phase 7's scheduling work, where an operator-facing exit-code taxonomy actually matters. |

