# Secret access policy

CASA AL1 evidence for **6.7.1** — secrets management: where secrets live, who
may access them, and how that access is logged.

**No secret value appears in this document.** Secrets are named by their
variable name and described by their purpose only. That is a hard rule for this
file: a compliance document that quotes a credential has created the incident
it was written to prevent.

---

## 1. Inventory — every secret this system holds

### 1.1 Operator secrets (one per deployment)

| Name | Purpose | Stored in |
| --- | --- | --- |
| `JOBTRACKER_SECRET_ENCRYPTION_KEY` | Fernet key for stored user credentials; also signs the OAuth `state` JWT | Vercel environment variables (API project) |
| `JOBTRACKER_SUPABASE_JWT_SECRET` | verifies legacy HS256 Supabase tokens | Vercel environment variables (API project) |
| `JOBTRACKER_GOOGLE_OAUTH_CLIENT_SECRET` | the Google OAuth web client secret | Vercel environment variables (API project) |
| `JOBTRACKER_VERCEL_CRON_SECRET` | authenticates the scheduled sync invocation | Vercel environment variables (API project) |
| `JOBTRACKER_DATABASE_URL_OVERRIDE` | pooled Postgres DSN — **contains the `jobtracker_app` password** | Vercel environment variables (API project) |
| `DIRECT_URL` | direct Postgres DSN for DDL — **contains the `postgres` password** | GitHub Actions secret, `production` environment |

`JOBTRACKER_GOOGLE_OAUTH_CLIENT_ID`, `NEXT_PUBLIC_SUPABASE_URL` and
`NEXT_PUBLIC_SUPABASE_ANON_KEY` are **not** secrets. The anon key is
publishable by design and reaches no data. `anon` holds no grants on nine of
the ten tables in `public`; it retains the default grant on
`gmail_sync_enrollment`, which was created after the 2026-08-03 revocation, and
that grant is inert because every policy on that table is scoped `TO
jobtracker_app` under forced RLS. The exception is set out in full — with the
query that finds it — in
[`ARCHITECTURE-AND-TENANT-ISOLATION.md`](ARCHITECTURE-AND-TENANT-ISOLATION.md)
§4.1, and it is an open item there.

### 1.2 User secrets (one per user, per kind)

| What | Where | Protection |
| --- | --- | --- |
| Gmail OAuth refresh/access token (`kind = "gmail_oauth"`) | `user_credentials` table | Fernet-encrypted; RLS `ENABLE`+`FORCE`; 4 policies |
| iCloud app-specific password (`kind = "icloud_mail"`) | `user_credentials` table | same |

Cryptographic detail is in [`CRYPTOGRAPHY.md`](CRYPTOGRAPHY.md).

---

## 2. The policy

### 2.1 Storage

1. Secrets are held **only** in a managed secret store — Vercel environment
   variables for runtime, GitHub Actions encrypted secrets for CI. No secret is
   committed to the repository, written to a file in the deployment artifact,
   or placed in `vercel.json`.
2. Secret scanning runs at **two** layers, and the stronger one is CI:
   - `.github/workflows/gitleaks.yml` scans **full history** — not just the
     diff — on every pull request, every push to `main`, and weekly on a
     schedule. History is what matters: a credential committed once and deleted
     the next day is still in the pack file and still fetchable by anyone who
     clones.
   - `.githooks/pre-commit` scans the staged diff before the commit exists, so
     a credential caught there never leaves the machine. It is tracked in the
     repository rather than left in `.git/hooks`, and it requires a one-time
     `git config core.hooksPath .githooks` per clone. That arrangement is a
     direct response to a real failure: the hook previously lived untracked in
     `.git/hooks` with `core.hooksPath` pointing at a directory that a project
     rename deleted, git skips a missing hooks path **in silence**, and so no
     local hook fired for weeks while the documentation went on describing it
     as a backstop.
   - If `gitleaks` is not installed, the hook fails loudly rather than passing
     quietly — a missing scanner must never look like a clean scan.
   - Findings triaged as non-secrets are allowlisted **by value, individually,
     with reasons** in `.gitleaks.toml`, never by excluding paths or disabling
     rules. Both shortcuts produce a scanner that cannot catch the real thing.
   - `--no-verify` is forbidden by project policy, and CI fails the pull
     request regardless, so bypassing the hook does not bypass the control.
3. `.env` and `.env.local` are git-ignored. They exist only on the owner's
   machine for local development and never carry production values.
4. User secrets are **encrypted before they reach the database** and are never
   written in plaintext to any column, log or response.

### 2.2 Who may access what

The deployment has a single human operator (the owner), who is the only
principal with a Vercel account, a Supabase dashboard login or repository admin
rights. Access is therefore not granted, it is inherent — and this document
says so rather than describing a role matrix that does not exist.

| Principal | May read | Route |
| --- | --- | --- |
| Owner | all operator secrets | Vercel dashboard / CLI, GitHub settings, Supabase dashboard |
| Deployed API function | the operator secrets injected into its environment | `os.environ` at runtime |
| CI (`DB migrate` workflow) | `DIRECT_URL` only | GitHub Actions secret injection |
| Deployed API function | any user's encrypted credential row, at the moment that user's request or the scheduled sync runs | `get_gmail_credentials` / `get_icloud_credentials` |
| Anyone else | nothing | — |

**No third party, contractor or subprocessor has access to any secret.** There
are no other developers on this project.

### 2.3 Rules the code enforces

1. The Fernet key has exactly **one construction site** in the codebase —
   `_require_fernet()` at `backend/jobtracker/credentials/cloud.py:107`. Every
   encrypt and every decrypt of a stored credential goes through it, so no
   `Fernet` is built anywhere else. The *variable* it reads,
   `settings.secret_encryption_key`, has **three** read sites, and the pack
   names all three rather than rounding to one:

   ```
   $ grep -rn 'settings\.secret_encryption_key' backend/jobtracker/ \
       | grep -v __pycache__ | grep -vE ':\s*(#|``)'
   backend/jobtracker/cloud/gmail_oauth.py:566:    return jwt.encode(payload, settings.secret_encryption_key, algorithm="HS256")
   backend/jobtracker/cloud/gmail_oauth.py:594:            settings.secret_encryption_key,
   backend/jobtracker/credentials/cloud.py:116:    key = settings.secret_encryption_key
   ```

   The two extra reads are the OAuth `state` HMAC — sign at `:566`, verify at
   `:594` — which reuses this key for a second purpose. That dual use is
   disclosed in [`CRYPTOGRAPHY.md`](CRYPTOGRAPHY.md) §3.4. What still holds is
   the property the control needs: the whole access surface is three named
   lines in two modules, so "who reads the key" is answerable by citation
   rather than by a grep across the tree, and a fourth reader arrives as a
   diff.

2. Decrypted plaintext is never logged, never returned to an HTTP caller, and
   never leaves the request that decrypted it. Tokens are excluded from all API
   responses.
3. Configuration errors name the **variable**, never the value.
   `CronSyncUserIdsError` (`backend/jobtracker/config.py:34-59`) exists solely
   for this: pydantic re-raises `ValueError` from a validator with
   `input_value=<the raw env var>` appended, so a validator that promised not
   to echo the value was echoing it a line later. Raising a non-`ValueError`
   type is what stops pydantic appending it. That was measured on pydantic
   2.12, not theorised — and the realistic mishap it protects against is
   pasting the cron secret into the wrong box and then finding it in a build
   log.
4. Reconnecting a mailbox re-writes the credential and clears `revoked_at`
   (`cloud.py:157-171` on Postgres, `:192` on the SQLite test path), so a
   revoked grant has exactly one self-service route back and it is a write,
   not a flag flip.

### 2.4 Rotation

- **User credentials** are rotated by the user reconnecting the mailbox, and
  revoked at Google on account deletion.
- **Database passwords** were last rotated 2026-08-14. Rotation requires a
  redeploy, because Vercel injects environment variables at deploy time — a
  rotation without an available redeploy breaks production until one runs.
- **`JOBTRACKER_SECRET_ENCRYPTION_KEY` cannot currently be rotated without
  invalidating every stored credential.** This is the known gap; it is
  described in full, with its remediation, in [`CRYPTOGRAPHY.md`](CRYPTOGRAPHY.md) §3.3.

---

## 3. Logging access to secrets

This control has two limbs, and they have different honest answers.

### 3.1 Access to the *encrypted user credentials* — logged

Every access to a stored user credential is logged. This is tractable because
the access surface is small and closed: reads go through
`get_gmail_credentials` and `get_icloud_credentials`, writes through
`save_gmail_credentials` / `save_icloud_credentials`, and deletions through
`delete_*` and `clear_all_credentials` — all in
`backend/jobtracker/credentials/cloud.py`.

All **seven** of those access functions emit a single fixed-shape record:

```
secret_access user_id=%s kind=%s key_id=%s op=%s outcome=%s
```

| `op` | `outcome` values actually emitted | Level |
| --- | --- | --- |
| `read` | `hit`, `miss` | `logger.info` |
| `read` | `decrypt_failed`, with ` error=InvalidToken` appended | `logger.error` |
| `write` | `written`, `write_failed` | `logger.info` |
| `delete` | `deleted` | `logger.info` |
| `clear` | `deleted`, with `kind=all` — the account-deletion purge | `logger.info` |

Two exactness notes, because a compliance table that overstates its own
vocabulary is the thing an assessor checks first:

- **`logger.info` is the level for every outcome except the two decrypt
  failures**, which are `logger.error` at `cloud.py:357` (Gmail) and `:473`
  (iCloud). That is deliberate — a failed decrypt of a live credential is an
  incident, not a routine outcome — and it is pinned:
  `backend/tests/test_secret_access_logging.py:300` asserts
  `record.levelno == logging.ERROR` on that record.
- **There is no `absent` outcome.** Both delete paths issue the `DELETE` and
  log `deleted` unconditionally (`cloud.py:393-395`, `:501-503`); neither
  checks whether a row existed. The log therefore **cannot** distinguish
  removing a credential from removing nothing. An earlier draft of this table
  listed `absent`; it was never emitted, and it is removed rather than left
  standing. Adding it would cost a `SELECT` before the `DELETE` — the same
  round trip this section declines below for `key_id` — so the honest record
  is the limitation, not a value that does not exist.

`key_id` is `None` on the delete and clear paths, deliberately: those issue a
`DELETE` and never read a row, and adding a `SELECT` purely to populate the
field would buy a database round trip for a log field. Records go to the
application logger and are collected by Vercel's runtime logs.

The record deliberately carries **no plaintext, no ciphertext and no key**.
`backend/tests/test_secret_access_logging.py` enforces that: it drives a real
credential round-trip with a sentinel token value and sweeps every emitted
record — both the formatted message and `record.args` — asserting the sentinel,
both ciphertext renderings and the Fernet key appear in none of them. It also
carries positive controls, so that an absence assertion cannot pass by nothing
having been logged at all: the decrypt is asserted to have genuinely returned
the sentinel, and at least one record from
`jobtracker.credentials.cloud` must be present.

That test is a negative gate and was **proven able to fail** before being
accepted: with the plaintext interpolated as a lazy `%s` argument, it reddens
with `the plaintext reached a log record`, and only that test reddens.

Two related findings from implementing this, recorded because both are the kind
of thing an assessor asks about:

- **`cryptography`'s `InvalidToken` cannot echo the ciphertext.** It is a bare
  `class InvalidToken(Exception): pass` and all twelve `raise` sites in
  `fernet.py` are argument-less, so `str(exc)` is empty. The pre-existing
  `logger.error` on the decrypt-failure path was therefore not leaking. The
  exception interpolation was replaced with a fixed `error=InvalidToken` token
  anyway — hardening against a future release that might attach the offending
  token, not a fix for a live leak.
- **The Gmail credential *miss* was previously `logger.debug`**, which is off in
  production — so the single most common access attempt emitted nothing at all.
  It is now `info`. The iCloud miss had no log line whatsoever. This is a real
  increase in log volume: `/auth/gmail/status` calls `get_gmail_credentials`
  directly, so every status poll now emits one line per user.

**Scope of the logging, stated exactly.** It covers the deployed application —
`backend/jobtracker/credentials/cloud.py`, which is what `api/index.py` imports.
A **vendored copy** of the same module exists at
`ml/demo/space/jobtracker/credentials/cloud.py`, swept into a public Gradio
classifier demonstration Space by a `copytree`, and it does **not** carry the
access logging. That Space demonstrates the classifier; it is not the
deployment and is not the path any real credential travels. The copy is named
here so that "every access is logged" is read as every access *in the
deployment*, which is what the control is about, and so that the drift is
recorded rather than discovered. **Open item** — the vendored tree should be
re-synced or the module dropped from it.

### 3.2 Access to the *Fernet key itself* — not logged, and why

**This limb is not closed by logging, and no log will be fabricated to suggest
otherwise.**

The key is a Vercel environment variable. The runtime reads it with an
in-process `os.environ` lookup, which is not an event any system can observe —
there is no syscall boundary, no network call and no broker to instrument. A
"log line" emitted next to that read would record only that the application
started, would be written by the same process that holds the key, and would be
evidence of nothing. Writing one would be theatre.

Adopting a secret broker that *does* log every fetch (HashiCorp Vault, AWS
Secrets Manager, Doppler) would close this limb properly. It is not proportionate
for a single-operator deployment with six operator secrets, and it is a paid
dependency this project has decided against.

**The compensating controls, each verifiable:**

1. **One construction site, three reads, all named.** `_require_fernet()`
   (`backend/jobtracker/credentials/cloud.py:107`) is the only place a `Fernet`
   is built, so every credential encrypt and decrypt passes through one
   function. The key *variable* is read at three lines in two modules —
   `credentials/cloud.py:116` and, for the OAuth `state` HMAC,
   `cloud/gmail_oauth.py:566` and `:594` (§2.3 rule 1). A reviewer can confirm
   the whole access surface by reading two functions rather than one, and any
   new reader appears as a diff. The surface is small and enumerable; it is not
   singular, and this document does not claim it is.
2. **The key never leaves the process.** It is not logged, not returned, not
   written to disk, and not included in error messages — §2.3 rule 3 covers
   the mechanism that keeps it out of error output.
3. **Operator access to the value is recorded in Vercel's Activity Log — a
   vendor event feed, not an audit log.** A human reading the secret out of the
   Vercel dashboard or CLI is the threat this control is actually about; a
   compromised runtime would not honestly log its own read anyway.

   **Vercel Audit Logs are an Enterprise feature and this account does not have
   them.** Vercel's documentation scopes audit logs to customers on enterprise
   plans; the plan comparison lists Audit Logs as "Not available" for both Hobby
   and Pro; and the owner's own dashboard, read 2026-08-15, says "Audit Logs are
   available on the Enterprise Plan" beside an upgrade button, and "SIEM
   Integration — Audit log streaming isn't available on your plan." This account
   is on Pro. Audit Logs are therefore **not** a control this deployment holds,
   and are not claimed as one. An earlier draft of this document named them as
   the intended compensating control; that claim was wrong and has been removed
   rather than softened.

   What this account does have is Vercel's **Activity Log** — a different
   product, available on Pro — and it records reads of environment variables.
   That was established by positive control rather than read off a
   documentation page: running `vercel env ls production` produced, within
   seconds, an event of type `env-variable-read:cli:env:ls` reading *"You used
   vc env ls to view all Production environment variables in Project
   jobtracker-web (via Vercel CLI)"*. Observed **2026-08-16T02:31:55Z** via
   `vercel activity ls --all --since 30d --format json`.

   The distinction between what was observed and what is merely documented is
   load-bearing here, so it is drawn explicitly:

   | Event | State |
   | --- | --- |
   | `env-variable-read:cli:env:ls` — listing production environment variables from the CLI | **Observed** — the event above |
   | `env-variable-read` for a plaintext *value* read, and its other per-source variants | **Documented by Vercel; not observed here.** The dashboard reveal-value path was not exercised during this evidence pass |
   | `env-variable-add` / `-edit` / `-delete` for modification | **Documented by Vercel; not observed here** — no operator secret was modified during this evidence pass |

   **Read row 1 precisely.** The command that produced it, `vercel env ls`,
   lists variable *names* and their environments; it does not reveal values. So
   what was observed is that the `env-variable-read` family fires, and that this
   account's plan receives those events — not that a plaintext value read was
   witnessed. Vercel documents the family as covering the reading of an
   encrypted variable's plaintext value, and the variant that does so was not
   exercised. The honest reading of the whole table is: **the mechanism is real
   and reaches this account; the specific value-revealing event is documented
   rather than demonstrated.**

   Four qualifiers must travel with any citation of this feed:

   - **No documented retention period.** Vercel publishes none for the Activity
     Log and no number is asserted here. The 90 days the dashboard offers is an
     *export range*, not a retention guarantee.
   - **No CSV export and no SIEM streaming at this tier.** The feed can be read;
     it cannot be shipped anywhere that would survive the account.
   - **Owner-readable only** — by the same single principal who holds the
     secrets. Nobody else can read it and nobody is alerted by it.
   - **Vendor-held.** It is Vercel's record of actions taken on Vercel,
     retained by Vercel. It is not an independent tamper-evident archive, and
     it is offered as a vendor event feed rather than as an audit log.
4. **GitHub provides no equivalent for `DIRECT_URL`, and none is claimed.**
   GitHub's audit log is an organisation and enterprise feature. This
   repository is owned by a personal account, which belongs to no organisation:
   `GET /users/yadava5/audit-log` returns `404 Not Found` and `GET /user/orgs`
   returns an empty list, both checked 2026-08-16. Separately, even where an
   audit log does exist it records the *management* of Actions secrets rather
   than a workflow's reads of them. So the CI limb of this control has no
   platform log behind it. What constrains it instead is scope: `DIRECT_URL` is
   injected only into the `migrate` job, which is pinned to the `production`
   environment (`.github/workflows/db-migrate.yml:170-172`) and reads the
   secret at one place (`:187`).
5. **Use of the key is logged even though reads of it are not** (§3.1). Every
   *effect* the key has — every credential decrypt — produces a record. That is
   the closer proxy to "was this secret used, and for whom".

### 3.3 Summary for the assessor

| Limb of 6.7.1 | State |
| --- | --- |
| Secrets stored in a managed secret store, not in code | **Met** |
| Documented secret access policy | **Met** — this document |
| Access to secrets is logged | **Partially met.** User credentials: logged by the application (§3.1). The Fernet key: reads are not logged by the application, and operator access to the variable is recorded only in Vercel's Activity Log — a vendor event feed with no retention guarantee and no export at this tier (§3.2) |

---

## 4. Residual risk, stated plainly

- **The Fernet key's use is instrumented; its reading is not.** A compromise of
  the Vercel environment would not be visible in any log this application
  writes. Detection would depend on a human reading Vercel's Activity Log
  (§3.2) — a vendor event feed with no documented retention, no export at this
  tier, no alerting, and nobody currently watching it. **There is no
  independent, tamper-evident archive of secret access anywhere in this
  system**, and no audit-log product is available at this plan tier. Stated
  without softening: this limb is detective in principle only.
- **Single operator, no separation of duties.** One person holds every secret
  and can deploy. There is no second approver on a rotation, and no four-eyes
  control is possible at this size. This is a structural property of a
  one-person project, not an oversight.
- **The key cannot be rotated cleanly** ([`CRYPTOGRAPHY.md`](CRYPTOGRAPHY.md) §3.3),
  which means the correct response to a suspected key compromise today is
  costly enough that it might be delayed. That is the most serious consequence
  of the missing rotation capability and it belongs in this document as well as
  in the cryptography one.

---

*Prepared 2026-08-15; §3.2 corrected 2026-08-16 against the platform's own
records. No secret value is reproduced. Where a secret is
referenced it is named by environment variable only.*
