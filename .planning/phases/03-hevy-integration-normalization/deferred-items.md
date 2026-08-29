# Phase 3 — Deferred Items

Out-of-scope discoveries logged during execution. Per the executor scope boundary, these are
**not** fixed by the plan that found them: they pre-date the change and live in files the task
only incidentally touched.

| Found in | Item | Why deferred |
|----------|------|--------------|
| 03-01 Task 3 | `mypy backend/tests/conftest.py` reports 6 errors, all pre-existing: `The return type of an async generator function should be "AsyncGenerator" or one of its supertypes [misc]` and `Unused "type: ignore" comment [unused-ignore]` on the `engine` / `session` / `client` fixtures. | Verified pre-existing by stashing the 03-01 conftest edit and re-running mypy: the identical 6 errors appear at the pre-change line numbers (191/195 instead of 224/228), i.e. they are only shifted by this plan's +33 lines, not caused by them. The repo's type gate is `mypy backend/app` (plan `<verification>` step 3), which exits 0. Fixing the fixture annotations means changing `-> AsyncEngine` to `-> AsyncGenerator[AsyncEngine, None]` and dropping the now-redundant `# type: ignore[misc]` on three fixtures — a self-contained cleanup, but it touches shared fixtures every Phase 3 plan depends on, so it should not land mid-wave. |

