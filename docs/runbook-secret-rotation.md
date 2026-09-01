# Runbook — Rotating MCP_AUTH_SECRET

First executed: 2026-09-01
Scope: `MCP_AUTH_SECRET` only (D-03). `DATABASE_URL` and `HEVY_API_KEY` were considered and
deliberately not given a procedure this phase — `DATABASE_URL` rotation is a Neon-side concern
covered by `docs/runbook-backup-restore.md`'s preconditions, and `HEVY_API_KEY` is minted in the
Hevy web UI and bound by `scripts/deploy-sync-job.sh`, not by the web service.
Owner artifacts: `deploy/cloud-run.env.yaml` (the `MCP_AUTH_MODE` lever),
`scripts/deploy-cloud-run.sh` (the mechanism), `backend/app/mcp/auth.py` (the two verifiers),
guarded by `backend/tests/test_cloud_run_deploy.py::test_auth_mode_is_a_valid_literal`.

**Redaction rule for this file:** no credential value is ever recorded. `MCP_AUTH_SECRET` is
referred to by Secret Manager name and version number only; no token, DSN or header value appears
below. Where a verification row sent a credential, the row records the header as
`Bearer $OLD_TOKEN` / `Bearer $NEW_TOKEN` **(value not recorded)**. The only quantitative fact
recorded about a token is its byte length, which is a property of the generator, not of the value.

---

## Why this is a DEPLOY procedure, not a `gcloud secrets` procedure

Cloud Run resolves `--set-secrets=NAME=secret:latest` into an environment variable **at instance
start**, not per request. Google's own wording: "newly started instances use the current latest
version, but already running instances keep the value they received at startup." Adding a version
therefore has **zero effect** until a new revision serves traffic.

`scripts/deploy-cloud-run.sh:40` is where that binding lives:

```bash
  --set-secrets="DATABASE_URL=brett-database-url:latest,MCP_AUTH_SECRET=brett-mcp-auth-secret:latest" \
```

So the rotation mechanism is `./scripts/deploy-cloud-run.sh`, and a rotation that stops after
`gcloud secrets versions add` has changed nothing about the running service.

## Why the mode has to be flipped

`deploy/cloud-run.env.yaml:50` sets `MCP_AUTH_MODE: "authkit"`, and `build_token_verifier`
(`backend/app/mcp/auth.py:117-141`) returns `AuthKitJWTVerifier` in that mode — `StaticTokenVerifier`
is never constructed. `AuthKitJWTVerifier` validates an RS256 JWT against the WorkOS tenant JWKS,
so a bearer request carrying the NEW secret is rejected with `401` **identically to the old one**,
and for a reason that has nothing to do with the rotation.

That makes D-04's stated verification ("old token → 401, new token → success") not observable in
the steady-state configuration. The only honest way to observe it is a temporary flip to `static`.
That flip is not an improvisation: it is the same lever `deploy/cloud-run.env.yaml:38-41` already
documents as the WorkOS-outage rollback path —

> Rollback is one value plus a redeploy, never a code change: set this back to `static` and re-run
> `./scripts/deploy-cloud-run.sh`.

— exercised here for the first time. A rotation drill therefore doubles as a rollback drill.

## Does rotation break the live connector?

**No, and the reason is worth stating plainly rather than implying risk.** In the steady state
(`MCP_AUTH_MODE=authkit`), Claude authenticates with a WorkOS-issued JWT and `MCP_AUTH_SECRET` is
not in the request path at all. Rotating it is invisible to the connector.

ROADMAP Phase 7 criterion #3 — "a secret can be rotated without breaking the live connector" — is
therefore satisfied trivially by the architecture, not narrowly by careful execution. The only
window of exposure is the deliberate `static` interval this procedure opens and closes, and the
connector is unaffected even then, because Claude keeps presenting a JWT the static verifier will
reject; a coaching session started during the window would fail, which is why the procedure says
not to run one.

## Preconditions

1. `BRETT_GCP_PROJECT` exported (`brett-fitness`), `gcloud` authenticated as an account with
   `roles/secretmanager.secretVersionAdder` and Cloud Run deploy rights.
2. The live `MCP_AUTH_MODE` is `authkit`. Confirm it — do not assume it. If it already reads
   `static`, a previous rotation or rollback did not finish, and that must be understood and
   fixed before rotating; rotating on top of it would erase the evidence.
3. `roles/secretmanager.secretAccessor` is bound on the **secret** `brett-mcp-auth-secret` for
   `brett-run@`, not per version. If it were bound per version, the flip deploy would produce a
   revision that cannot start (07-RESEARCH.md Assumptions Log A1).
4. The fast suite is green.
5. No coaching session is in progress. The `static` window is a real, if brief, weakening of
   production auth.

## Procedure

### Step 0 — confirm the live mode and record the current revision

```bash
export BRETT_GCP_PROJECT=brett-fitness
gcloud run services describe brett --project="$BRETT_GCP_PROJECT" --region=us-central1 \
  --format='json(spec.template.spec.containers[0].env)'
gcloud run services describe brett --project="$BRETT_GCP_PROJECT" --region=us-central1 \
  --format='value(status.latestReadyRevisionName)'
```

`MCP_AUTH_MODE` must read `authkit`. Record the revision name — it is the "before" half of the
proof that a new revision actually served traffic.

### Step 1 — confirm the IAM binding is at the secret level

```bash
gcloud secrets get-iam-policy brett-mcp-auth-secret --project="$BRETT_GCP_PROJECT" \
  --format='value(bindings.role,bindings.members)'
```

Expect `roles/secretmanager.secretAccessor` for
`serviceAccount:brett-run@brett-fitness.iam.gserviceaccount.com`.

### Step 2 — record the current version list

```bash
gcloud secrets versions list brett-mcp-auth-secret --project="$BRETT_GCP_PROJECT" \
  --format='table(name,state,createTime)'
```

The highest `enabled` version number here is `PREV_VERSION`, the one disabled at the end. Write it
down now; do not re-derive it later, when a new version exists to be confused with it.

> **gcloud output gotcha.** On SDK 578.0.0 the `state` column renders **lowercase** (`enabled`),
> not `ENABLED`. A verification one-liner written as `... | grep -c ENABLED` returns `0` on a
> perfectly healthy secret. Use `grep -ci enabled`.

### Step 3 — mint and add a new version

```bash
python3 -c 'import secrets,sys; sys.stdout.write(secrets.token_urlsafe(48))' \
  | gcloud secrets versions add brett-mcp-auth-secret \
      --project="$BRETT_GCP_PROJECT" --data-file=-
```

Three details, each of which has a failure mode:

- `secrets.token_urlsafe(48)` matches the generator Phase 2 used. It yields a 64-character value.
- `sys.stdout.write` (or `printf '%s'`) rather than `print` — a trailing newline becomes part of
  the secret, and `secrets.compare_digest` would then reject the token a human copies correctly.
  Confirm with `gcloud secrets versions access N --secret=brett-mcp-auth-secret | wc -c` → `64`.
- `--data-file=-`, **never** `--data="..."`, which lands the credential in the process table and
  the shell history.

The value is never echoed, never written to a file, and never recorded here. When a later step
needs it, re-read it from Secret Manager rather than carrying it.

### Step 4 — flip to `static`, then run the fast suite BEFORE deploying

Edit `deploy/cloud-run.env.yaml`: `MCP_AUTH_MODE: "authkit"` → `MCP_AUTH_MODE: "static"`. Change
nothing else; the surrounding comment block already documents this flip as the sanctioned rollback
path and is part of why it is safe.

```bash
uv run pytest backend/tests -x -q -m "not integration"
```

`test_auth_mode_is_a_valid_literal` is the reason this ordering matters. A typo like `"static "` or
`"workos"` does not fail the deploy — it kills the process at boot, on Cloud Run, remotely, with a
pydantic `ValidationError` nobody is watching for. Ten seconds of local test run replaces that.

### Step 5 — deploy

```bash
./scripts/deploy-cloud-run.sh
gcloud run services describe brett --project="$BRETT_GCP_PROJECT" --region=us-central1 \
  --format='value(status.latestReadyRevisionName)'
```

`:latest` resolves on this deploy; that is the whole mechanism. The revision name must differ from
the one recorded in step 0 and must be serving 100% of traffic.

**If the revision never becomes ready,** the most likely cause is the step 1 assumption: grant
`roles/secretmanager.secretAccessor` on the secret to `brett-run@` and redeploy before continuing.

### Step 6 — verify against the live endpoint

`BASE` comes from `status.url`, not from memory. The MCP envelope's `params._meta` is **mandatory**:
omit it and the server answers `-32602` *inside a 200*, which would make the auth assertion
meaningless.

```bash
BASE="$(gcloud run services describe brett --project="$BRETT_GCP_PROJECT" \
          --region=us-central1 --format='value(status.url)')"
MCP_BODY='{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'
MCP_HDRS=(-H 'Accept: application/json, text/event-stream'
          -H 'Content-Type: application/json'
          -H 'MCP-Protocol-Version: 2026-07-28'
          -H 'Mcp-Method: tools/list' -H 'Mcp-Name: tools/list')

OLD_TOKEN="$(gcloud secrets versions access PREV_VERSION --secret=brett-mcp-auth-secret --project="$BRETT_GCP_PROJECT")"
NEW_TOKEN="$(gcloud secrets versions access latest        --secret=brett-mcp-auth-secret --project="$BRETT_GCP_PROJECT")"
```

| Row | Request | Expected |
|---|---|---|
| A | `POST $BASE/mcp` + `Authorization: Bearer $OLD_TOKEN` | `401` |
| B | `POST $BASE/mcp` + `Authorization: Bearer $NEW_TOKEN` | `200`, listing 13 tools |
| C | `POST $BASE/mcp`, no `Authorization` | `401` + `WWW-Authenticate` containing `resource_metadata=` |
| D | `GET $BASE/health` | `200` |

Count and name the tools rather than eyeballing the blob. The response is `text/event-stream`, so
extract the JSON payload first:

```bash
curl -sS -X POST "$BASE/mcp" "${MCP_HDRS[@]}" \
  -H "Authorization: Bearer $NEW_TOKEN" --data "$MCP_BODY" \
| sed -n 's/^data: //p' \
| python3 -c 'import json,sys; d=json.load(sys.stdin); n=[t["name"] for t in d["result"]["tools"]]; print(len(n)); print("\n".join(sorted(n)))'
```

**Two STOP conditions.** They exist because both failures produce a result that *looks* like a
successful rotation from one angle only:

- **Row A returns `200`** → STOP. The old version is still resolving as `:latest`, or the revision
  did not actually restart. Nothing has been rotated.
- **Row B returns `401`** → STOP. The new token carries a trailing newline, or the deploy did not
  pick up the new version. Do not disable the old version; you would lock yourself out.

### Step 7 — flip back to `authkit`, and verify it

**Mandatory and verified, not a trailing note.** `static` is a weaker configuration than `authkit`
— a single long-lived bearer versus OAuth 2.1 with a short-lived JWT — and leaving production there
is the failure mode this step exists to prevent.

1. Edit `deploy/cloud-run.env.yaml`: `MCP_AUTH_MODE: "static"` → `MCP_AUTH_MODE: "authkit"`.
2. `uv run pytest backend/tests -x -q -m "not integration"` — green before deploying.
3. `./scripts/deploy-cloud-run.sh`
4. Read the mode back **from the live service, not from the file**:
   ```bash
   gcloud run services describe brett --project="$BRETT_GCP_PROJECT" --region=us-central1 \
     --format='json(spec.template.spec.containers[0].env)'
   ```
   The `MCP_AUTH_MODE` entry must read `authkit`.
5. Re-run rows B and C. Row B must now return `401` (the static token is out of the request path
   again) and row C must still return `401` with `resource_metadata=`.
6. `git diff --quiet deploy/cloud-run.env.yaml` must exit 0 — the file ends byte-identical to how
   it started.

The procedure is not complete until step 4 reports `authkit` **and** step 6 exits 0. Those are two
independent checks on purpose: the file can be right while the service is stale, and the service
can be right while an uncommitted edit waits to surprise the next deploy.

### Step 8 — disable, never destroy, the previous version

Only after step 7 is green:

```bash
gcloud secrets versions disable PREV_VERSION --secret=brett-mcp-auth-secret \
  --project="$BRETT_GCP_PROJECT"
gcloud secrets versions list brett-mcp-auth-secret --project="$BRETT_GCP_PROJECT" \
  --format='table(name,state)'
unset OLD_TOKEN NEW_TOKEN
```

**Disable, never destroy.** `disable` is reversible for the retention period; `destroy` is not, and
a destroyed version removes the only rollback if the new one turns out to be wrong.

---

## Verification record — 2026-09-01

Service `brett`, project `brett-fitness`, region `us-central1`.
`BASE = https://brett-cglno6k2xq-uc.a.run.app` (read from `status.url`; both this host and the
deterministic `brett-792870654598.us-central1.run.app` are in `MCP_ALLOWED_HOSTS`).

| Row | Check | Expected | Observed | Pass/Fail |
|---|---|---|---|---|
| 1 | pre-flight: live `MCP_AUTH_MODE` | `authkit` | `authkit` on revision `brett-00007-xz7`, 100% traffic | **PASS** |
| 2 | pre-flight: secret-level `secretAccessor` for `brett-run@` | bound | `roles/secretmanager.secretAccessor` → `serviceAccount:brett-run@brett-fitness.iam.gserviceaccount.com`, one binding, `version: 1`, no version-scoped condition | **PASS** |
| 3 | new version added, enabled | version 2 | version `2` `enabled` at `2026-09-01T12:17:26`; version `1` still `enabled`; `access 2 \| wc -c` → `64`, i.e. no trailing newline | **PASS** |
| 4 | fast suite green after the flip edit | 0 failures | `401 passed, 286 deselected in 1.64s`, exit 0 | **PASS** |
| 5 | static-mode deploy: new revision ready, 100% traffic | revision ≠ `brett-00007-xz7` | `brett-00008-rlg` deployed, `latestRevision: true`, `percent: 100`; live env re-read shows `MCP_AUTH_MODE = static` | **PASS** |
| 6 | old token to `/mcp` (`Bearer $OLD_TOKEN`, value not recorded) | `401` | *(pending — Task 2)* | *(pending)* |
| 7 | new token to `/mcp` (`Bearer $NEW_TOKEN`, value not recorded) | `200`, 13 tools | *(pending — Task 2)* | *(pending)* |
| 8 | no `Authorization` header | `401` + `resource_metadata=` | *(pending — Task 2)* | *(pending)* |
| 9 | `GET /health` during the window | `200` | *(pending — Task 2)* | *(pending)* |
| 10 | flip-back deploy: live mode reads `authkit` | `authkit` | *(pending — Task 2)* | *(pending)* |
| 11 | `git diff deploy/cloud-run.env.yaml` | empty | *(pending — Task 2)* | *(pending)* |
| 12 | new token to `/mcp` after flip-back | `401` | *(pending — Task 2)* | *(pending)* |
| 13 | previous version state | `disabled`, none destroyed | *(pending — Task 2)* | *(pending)* |
| 14 | Claude connector round-trip (human-verified) | `fitness_ping` and `fitness_get_weekly_volume` both succeed | *(pending — Task 3 checkpoint)* | *(pending)* |

Row 14 is a human-verified checkpoint, not a claim inferred from code.

## Known limitations

- **Hard cutover, by design (D-04).** There is no dual-secret grace window: the moment a new
  revision starts, the old token is dead. Acceptable because the static path is CLI/rollback-only,
  not the primary connector auth, and the only holder of the old token is the operator running this
  procedure.
- **The static window is a real, if brief, weakening of production auth.** Run this procedure when
  no coaching session is in progress.
- **Nothing alerts on a service left in `static` mode.** Rows 10 and 11 are the only guard, which
  is why they are mandatory rather than advisory. There is no monitor, no dashboard and no test
  that would catch it after the fact — `test_auth_mode_is_a_valid_literal` checks that the value is
  *legal*, not that it is `authkit`.
- **The `:latest` binding means a rotation cannot be staged.** Because
  `scripts/deploy-cloud-run.sh` binds `brett-mcp-auth-secret:latest` rather than a pinned version,
  adding a version arms the change for the *next* deploy, whoever makes it and for whatever reason.
  Do not add a version and walk away.
