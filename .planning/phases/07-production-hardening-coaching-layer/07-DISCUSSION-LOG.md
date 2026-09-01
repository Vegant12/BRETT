# Phase 7: Production Hardening & Coaching Layer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-01
**Phase:** 07-production-hardening-coaching-layer
**Areas discussed:** Backup, restore & secret rotation; Coaching instructions document
**Areas surfaced but not selected:** Rate limiting; Test coverage gap

---

## Gray Area Selection

| Area | Description | Selected |
|------|-------------|----------|
| Rate limiting | Mechanism/keying/limits for the MCP endpoint | |
| Backup, restore & secret rotation | Neon PITR vs. scripted path; which secrets need rotation | ✓ |
| Coaching instructions document | How closely to follow blueprint §34-36; format/location/verification | ✓ |
| Test coverage gap | Depth of the missing mock-Hevy-to-MCP end-to-end test | |

**User's choice:** Backup/restore/rotation and the coaching document.
**Notes:** Rate limiting and the test-coverage gap remain real work items for this phase (both
appear in ROADMAP success criteria and REQUIREMENTS DEPLOY-03) but were left to research/planning
discretion rather than discussed — see CONTEXT.md "Areas Explicitly Not Discussed."

---

## Backup & Restore

| Option | Description | Selected |
|--------|-------------|----------|
| Neon PITR/branching only | Rely on Neon-native restore-to-branch, documented runbook | ✓ |
| Scripted pg_dump/pg_restore, independent of Neon | Portable backup script, survives full Neon loss | |
| Both | Neon as default + scripted fallback | |

**User's choice:** Neon PITR/branching only.
**Notes:** Matches the project's self-paced, single-user, cost-conscious posture — no new backup
infrastructure to build or maintain.

### Follow-up: Restore verification method

| Option | Description | Selected |
|--------|-------------|----------|
| One-time manual verification | Create a Neon branch, diff row counts/checksums, document as runbook | ✓ |
| Scripted verification (Neon CLI/API) | On-demand script that automates the same check | |

**User's choice:** One-time manual verification, mirroring Phase 2's Auth Verification Matrix
style.

---

## Secret Rotation

**Question:** Which secrets need a documented/tested rotation procedure this phase? (multi-select)

| Option | Description | Selected |
|--------|-------------|----------|
| MCP_AUTH_SECRET | Static bearer token, compared in StaticTokenVerifier | ✓ |
| DATABASE_URL (Neon connection string) | Rotating breaks everything if botched | |
| HEVY_API_KEY | Sync-job only, not in the live connector's request path | |

**User's choice:** MCP_AUTH_SECRET only.

### Follow-up: Rotation proof mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| New secret version + redeploy + verify old-rejected/new-works | Exercises StaticTokenVerifier as-built, no new code | ✓ |
| Dual-secret/grace-period mechanism | New code in auth.py to accept current+previous secret for a window | |

**User's choice:** New version + redeploy + verify. No dual-secret mechanism — a hard cutover is
acceptable since the static path is CLI/rollback-only, not the primary live connector auth.

---

## Coaching Instructions Document

### Q1: Closeness to blueprint outline + tool-name mapping

| Option | Description | Selected |
|--------|-------------|----------|
| Follow blueprint closely + map to tool names | Persona/objectives/framework from §34-36, plus explicit "for X question, call fitness_get_Y" using real Phase 6 tool names | ✓ |
| Follow blueprint structure only, no tool mapping | Same content, let Claude infer tool choice from schemas | |

**User's choice:** Follow closely + explicit tool-name mapping.

### Q2: Document location and loading mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| docs/coaching-instructions.md, pasted into a Claude Project's custom instructions | Persistent Project setup with connector attached | ✓ |
| docs/coaching-instructions.md, pasted per-conversation | No Project dependency, more manual | |
| Something else | Free text | |

**User's choice:** docs/coaching-instructions.md + Claude Project custom instructions.

### Q3: Verification of success criterion #4

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — manual checkpoint in a Claude Project | Ask both example questions + one stale/sparse-data question, record transcript/result | ✓ |
| Just write the document, skip formal verification | No recorded live-conversation check this phase | |

**User's choice:** Manual UAT checkpoint during phase execution, same style as Phase 2's
connector-auth checkpoint.

---

## Claude's Discretion

- Exact runbook doc name/location for backup-restore and secret-rotation verification steps
- Exact wording/structure of the coaching document beyond the blueprint outline and tool mapping
- Where the coaching UAT transcript/result gets recorded (e.g. a `07-COACH-VERIFICATION.md`)
- Rate limiting: mechanism, keying strategy, limit numbers, 429 response shape — not discussed
- Test coverage gap: exact depth/shape of the new end-to-end integration test — not discussed

## Deferred Ideas

- Independent pg_dump/pg_restore backup path (not chosen)
- DATABASE_URL and HEVY_API_KEY rotation procedures (not chosen)
- Dual-secret/grace-period rotation mechanism (not chosen)
- Per-conversation (non-Project) loading of the coaching document (not chosen)
