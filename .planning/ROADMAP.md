# Roadmap: BRETT

## Milestones

- ✅ **v1.0 MVP** — Phases 1-7 (shipped 2026-09-02)
- ✅ **v2.0 Apple Health, Strength Tracking & Coaching Programs** — Phases 8-13 (shipped 2026-09-05)
- 📋 **Next milestone** — not yet defined, run `/gsd-new-milestone`

Full phase detail is archived per milestone:
- `.planning/milestones/v1.0-ROADMAP.md`
- `.planning/milestones/v2.0-ROADMAP.md` (phase artifacts in `.planning/milestones/v2.0-phases/`)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-7) — SHIPPED 2026-09-02</summary>

- [x] Phase 1: Backend Foundation (5/5 plans) — completed 2026-08-23
- [x] Phase 2: Deploy & Connector Auth Spike (8/8 plans) — completed 2026-08-29
- [x] Phase 3: Hevy Integration & Normalization (12/12 plans) — completed 2026-08-30
- [x] Phase 4: Volume & Frequency Analytics (9/9 plans) — completed 2026-08-30
- [x] Phase 5: Progression, Records & Recomposition Analytics (10/10 plans) — completed 2026-08-31
- [x] Phase 6: MCP Tools (11/11 plans) — completed 2026-09-01
- [x] Phase 7: Production Hardening & Coaching Layer (10/10 plans) — completed 2026-09-01

</details>

<details>
<summary>✅ v2.0 Apple Health, Strength Tracking & Coaching Programs (Phases 8-13) — SHIPPED 2026-09-05</summary>

- [x] Phase 8: Apple Health & Nutrition Ingest (8/8 plans) — completed 2026-09-03
- [x] Phase 9: Historical Apple Health Backfill (7/7 plans) — completed 2026-09-03
- [x] Phase 10: Max-Weight Strength Signal (1/1 plan) — completed 2026-09-03
- [x] Phase 11: Body Measurement History (3/3 plans) — completed 2026-09-04
- [x] Phase 12: Training Programs & Confirm-Gated Write Tool (5/5 plans) — completed 2026-09-04
- [x] Phase 13: Health Analytics, Reports & Coaching Style (10/10 plans) — completed 2026-09-05

</details>

### 📋 Next milestone (not yet defined)

No phases planned. Run `/gsd-new-milestone` to scope the next version
(questioning → research → requirements → roadmap).

Carried-forward operational debt that is candidate scope — see PROJECT.md
Requirements → Active for full detail:
- Pre-deploy migration step in `scripts/deploy-cloud-run.sh` (production drifted
  behind deployed code three times during v2.0)
- D-06 production nutrition-coverage re-query (blocked all milestone by the
  sandbox command classifier)
- Verify Hevy's real rate limits (carried unresolved from v1.0)

## Progress

| Phase | Milestone | Plans Complete | Status   | Completed  |
| ----- | --------- | -------------- | -------- | ---------- |
| 1. Backend Foundation | v1.0 | 5/5 | Complete | 2026-08-23 |
| 2. Deploy & Connector Auth Spike | v1.0 | 8/8 | Complete | 2026-08-29 |
| 3. Hevy Integration & Normalization | v1.0 | 12/12 | Complete | 2026-08-30 |
| 4. Volume & Frequency Analytics | v1.0 | 9/9 | Complete | 2026-08-30 |
| 5. Progression, Records & Recomposition Analytics | v1.0 | 10/10 | Complete | 2026-08-31 |
| 6. MCP Tools | v1.0 | 11/11 | Complete | 2026-09-01 |
| 7. Production Hardening & Coaching Layer | v1.0 | 10/10 | Complete | 2026-09-01 |
| 8. Apple Health & Nutrition Ingest | v2.0 | 8/8 | Complete | 2026-09-03 |
| 9. Historical Apple Health Backfill | v2.0 | 7/7 | Complete | 2026-09-03 |
| 10. Max-Weight Strength Signal | v2.0 | 1/1 | Complete | 2026-09-03 |
| 11. Body Measurement History | v2.0 | 3/3 | Complete | 2026-09-04 |
| 12. Training Programs & Confirm-Gated Write Tool | v2.0 | 5/5 | Complete | 2026-09-04 |
| 13. Health Analytics, Reports & Coaching Style | v2.0 | 10/10 | Complete | 2026-09-05 |

**Totals:** 13 phases, 99 plans, 232 tasks across two shipped milestones.

---
*v2.0 shipped 2026-09-05. Next milestone: `/gsd-new-milestone`.*
