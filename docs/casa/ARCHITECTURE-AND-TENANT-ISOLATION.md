# Architecture, data flow and tenant isolation

CASA AL1 evidence for **3.1.1** (application architecture documented),
**3.1.2** (data flow documented) and **3.1.3** (trust boundaries and tenant
isolation).

Every number in this document was read against the **production** Supabase
database on **2026-08-15**, not against the migrations, and every query used is
reproduced inline so an assessor can re-run it. Where a figure is a snapshot of
live data rather than an invariant, it is labelled as such with its `N`.

---

## 1. What the system is

Applied reads a user's Gmail mailbox, recognises which messages are job
applications, and files them onto a board. There is one deployed system and
three pieces:

| Piece | Where it runs | Source |
| --- | --- | --- |
| Next.js 16 web app — the only user interface | Vercel | `apps/web/` |
| FastAPI serverless function — the whole API | Vercel | `api/index.py` → `backend/jobtracker/` |
| Supabase — Postgres for data, Auth for identity | Supabase (AWS) | — |

There is no desktop process, no WebSocket, no message queue and no SQLite in
the deployed path. The macOS client was de-scoped on 2026-08-12 and deleted;
`docs/ARCHITECTURE.md` carries that note at its head.

Communication is HTTPS throughout. Production negotiated **TLS 1.3** with
`AEAD-CHACHA20-POLY1305-SHA256` when probed on 2026-08-15.

---

## 2. Data flow

### 2.1 The Gmail read path — the one that touches restricted data

```
Google                Vercel (FastAPI)                    Supabase Postgres
  │                          │                                    │
  │  gmail.readonly          │                                    │
  │  format="full"           │                                    │
  ├─────────────────────────►│                                    │
  │  headers + snippet       │  classify(subject, body, sender)    │
  │  + MESSAGE BODY          │  ── in memory, request-scoped ──    │
  │                          │                                    │
  │                          │  persist: subject, sender, date,   │
  │                          │  Gmail's snippet, the verdict      │
  │                          ├───────────────────────────────────►│
  │                          │                                    │
  │                     body falls out of scope                   │
  │                     when the request ends                     │
```

The message body is fetched, read for classification, and never written
anywhere. That is a structural property of the code, not a promise:

- `CloudGmailMessage` — the object every persist path receives — has **no body
  field**. Bodies travel beside it in a separate `dict[message_id, str]` on
  `MessagePage`, are passed to `classifier.classify(...)` as its `body`
  argument, and fall out of scope at the end of the request.
  (`backend/jobtracker/cloud/gmail_client.py:36-53`)
- `backend/tests/test_body_is_never_persisted.py` drives a real scan whose
  message bodies carry a sentinel string, then asserts the sentinel reaches no
  column of any table in the schema, no log record, and no response of any
  endpoint the scan touches — `GET /gmail/inbox` included.

### 2.2 What is retained — read this before reading the schema

**The message *body* is never stored. Gmail's own ~200-character *snippet*
is.** The distinction matters and an assessor will meet it in the schema
before meeting it here, so it is stated plainly:

| Column | What it holds | Live count, 2026-08-15 |
| --- | --- | --- |
| `emails.body_text` | nothing, ever | **0 of 54** rows non-NULL |
| `emails.body_html` | nothing, ever | **0 of 54** rows non-NULL |
| `emails.body_snippet` | Gmail's own `snippet` field, verbatim | 51 of 54 populated (2 empty string, 1 NULL) |
| `training_data.body_text` | a copy of `emails.body_snippet` | 7 of 11 populated (4 empty string, 0 NULL) |

```sql
SELECT count(*) FILTER (WHERE body_text IS NOT NULL)  AS body_text_populated,
       count(*) FILTER (WHERE body_html IS NOT NULL)  AS body_html_populated,
       count(*) FILTER (WHERE body_snippet IS NOT NULL AND body_snippet <> '') AS snippet_populated,
       max(length(body_snippet))                      AS max_snippet_len,
       count(*)                                       AS total
FROM emails;
--  0 | 0 | 51 | 201 | 54
```

**`training_data.body_text` is a badly named column, and the name is the whole
risk of misreading this system.** It does not hold a body. It holds the same
snippet, copied from `emails.body_snippet` by `_add_training_example`
(`backend/jobtracker/cloud/applications.py:2219`, the copy itself at `:2238`).
Two independent facts establish it:

1. The longest value in that column across all 11 rows is **201 characters** —
   Gmail's snippet budget. No message body is 201 characters.
2. `backend/tests/test_body_is_never_persisted.py:714` asserts
   `row.body_text == REJECTION_SNIPPET` by **equality**, not by sentinel
   absence. The test's own comment explains why: a sentinel search alone passes
   for a body prefix that stops short of the sentinel, so equality is what
   catches "a future improvement that feeds the corpus the full text the
   message was classified on". That assertion reddens on a full body even when
   no sentinel is in play.

Two disclosures an assessor should have without asking:

- **`training_data` has no foreign key to `emails`.** `training_data.email_id`
  is a bare indexed integer, documented as such at
  `backend/jobtracker/cloud/applications.py:2196`. One of the 7 populated rows
  today points at an `emails` row that no longer exists — its snippet copy
  (199 characters) outlived its source. This is deliberate: a `training_data`
  row is a *human's correction*, retained as the record of a decision rather
  than as a derivative of the message. It is **not** exempt from deletion; see
  §4.3.
- **Retention is for the life of the account.** There is no time-based
  expiry of `emails` or `training_data` rows. They are removed when the user
  deletes their account, or when the user deletes the parent application.

### 2.3 The credential path

Gmail OAuth tokens and iCloud app-specific passwords are the only secrets
belonging to a user that the system stores. They live Fernet-encrypted in
`user_credentials`, one row per `(user_id, kind)`. The full cryptographic
description — algorithm, key management, and the fact that key **rotation is
not implemented** — is in [`CRYPTOGRAPHY.md`](CRYPTOGRAPHY.md).

---

## 3. Trust boundaries

| # | Boundary | Crossed by | Control |
| --- | --- | --- | --- |
| 1 | Browser → Next.js | HTTPS | Supabase session cookie; `proxy.ts` → `updateSession` gates protected paths |
| 2 | Next.js → FastAPI | HTTPS, `Authorization: Bearer <JWT>` | Signature verified per request, ES256 against the project JWKS. Two exceptions with their own mechanisms — see §4.3 |
| 3 | FastAPI → Postgres | TLS, pooled | Connects as `jobtracker_app`, which is **`NOBYPASSRLS`**; per-transaction identity GUC |
| 4 | FastAPI → Google | HTTPS | `gmail.readonly` only; token decrypted per request, never logged |

The browser never holds `BACKEND_API_URL` or a service-role key. The Supabase
anon key it does hold is publishable by design and reaches no data: `anon`
holds no grants on nine of the ten tables, and on the tenth the grant is inert
because every policy there is scoped to the `jobtracker_app` role. See §4.1 for
that exception in full.

**How the revocation was applied, stated precisely, because it bears on
reproducibility.** It is *not* a migration. The `REVOKE` statements were run by
hand against production on 2026-08-03 and are recorded in
`docs/harden-2026-08-03.sql`; no Alembic revision performs them, and
`backend/alembic/versions/` contains no `revoke_anon_grants_*` file. Alembic
does run on merge to `main` (`.github/workflows/db-migrate.yml`), so a database
rebuilt from the migration chain alone would carry the default `anon` grants
that production no longer has. Porting the revoke into a migration is the fix
and is **open**.

---

## 4. Tenant isolation

Applied is single-tenant-per-user: there are no organisations, no shared
records and no sharing feature. "Tenant" therefore means "user", and isolation
is enforced at three independent layers.

### 4.1 Layer 1 — row-level security in Postgres

Read live on 2026-08-15:

```sql
SELECT c.relname                        AS table_name,
       c.relrowsecurity                 AS rls_enabled,
       c.relforcerowsecurity            AS rls_forced,
       (SELECT count(*) FROM pg_policies p
         WHERE p.schemaname = 'public' AND p.tablename = c.relname) AS policy_count
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY c.relname;
```

| Table | RLS enabled | RLS forced | Policies |
| --- | --- | --- | --- |
| `applications` | ✔ | ✔ | 4 |
| `contacts` | ✔ | ✔ | 4 |
| `email_embeddings` | ✔ | ✔ | 4 |
| `emails` | ✔ | ✔ | 4 |
| `gmail_sync_enrollment` | ✔ | ✔ | 3 |
| `interviews` | ✔ | ✔ | 4 |
| `sync_state` | ✔ | ✔ | 4 |
| `training_data` | ✔ | ✔ | 4 |
| `user_credentials` | ✔ | ✔ | 4 |
| `alembic_version` | ✘ | ✘ | 0 |

**35 policies across 9 of the 10 tables in `public`.**

The one table without RLS is **`alembic_version`**, and that is deliberate, not
an oversight. It holds a single migration revision string and no user data. It
previously had RLS *enabled with zero policies*, which denies everything to a
non-bypassing role — meaning Alembic would have read zero rows, concluded the
database was unmigrated, and attempted to replay every migration against a
populated database. That failure is silent at the read and destructive at the
write. It was corrected on 2026-08-03; the reasoning is recorded in
`docs/RLS-AUDIT-2026-08-03.md`.

`gmail_sync_enrollment` carries 3 policies rather than 4 because it has no
UPDATE path — enrollment is written or deleted, never edited.

**34 of the 35 policies are the same shape**, keyed to the authenticated user:

```sql
SELECT tablename, cmd, qual FROM pg_policies
WHERE schemaname = 'public' AND tablename = 'emails';
--  emails | SELECT | (user_id = ( SELECT auth.uid() AS uid))
--  emails | UPDATE | (user_id = ( SELECT auth.uid() AS uid))
--  emails | DELETE | (user_id = ( SELECT auth.uid() AS uid))
--  emails | INSERT | (WITH CHECK, same predicate)
```

**Role scoping is narrower than the predicate, and this document states which
is doing the work.** Only the **3** `gmail_sync_enrollment` policies carry a
`TO` clause (`TO jobtracker_app`, created that way at
`backend/alembic/versions/e2b6f0a4d517_gmail_sync_enrollment.py:177,183,187`).
The other **32** are created with no `TO` — which in Postgres means `TO PUBLIC`
— by `a8d4ec5fba26_enable_rls_policies_postgres_only.py:110-136` and
`c4_user_credentials_rls.py:34-45`; `c6_rls_initplan_hoist.py` rewrites their
predicates only and never their roles. The `roles` column in the §4.1 dumps
below shows this directly: the `emails` dump carries none, the
`gmail_sync_enrollment` dump carries `{jobtracker_app}`.

Nothing about tenant isolation rests on the missing clause. For those 32
policies, a connection arriving as some other role *does* match the policy and
is then filtered by `user_id = (SELECT auth.uid())` — which returns no rows
unless that connection has bound the row owner's identity. The control is the
predicate, plus the two properties below, not the role list.

`FORCE` is what makes this real rather than nominal: without it, policies do
not apply to the table owner, and the owner is what an application typically
connects as. Together with `jobtracker_app` being `NOBYPASSRLS` (§4.2) and the
per-transaction identity GUC, that is what an assessor should test.

Adding `ALTER POLICY … TO jobtracker_app` across the other 32 would make the
role gate uniform and is worth doing as defence in depth. It has **not** been
done; recorded here as an open item rather than described as if it had.

#### The one policy that is not user-scoped — disclosed

`gmail_sync_enrollment_enumerate` (SELECT) has `qual = true`. Any request
running as `jobtracker_app` can read every row of that table.

```sql
SELECT policyname, cmd, roles::text, qual FROM pg_policies
WHERE schemaname='public' AND tablename='gmail_sync_enrollment';
--  gmail_sync_enrollment_enumerate    | SELECT | {jobtracker_app} | true
--  gmail_sync_enrollment_owner_insert | INSERT | {jobtracker_app} | (WITH CHECK user_id = auth.uid())
--  gmail_sync_enrollment_owner_delete | DELETE | {jobtracker_app} | (user_id = auth.uid())
```

This is deliberate and the reasoning is recorded at
`backend/jobtracker/cloud/gmail_oauth.py:865-889`. Two features need a
deployment-wide answer rather than a per-user one: the scheduled sync must
enumerate candidate users (`backend/jobtracker/cloud/cron.py:370`), and the
Gmail connection cap must count total enrolled mailboxes against Google's
limit (`gmail_oauth.py:925`). Neither can be answered from a user-scoped read —
a cap that always counts 1 admits everybody forever.

The design response was to put the *membership fact* in its own table, holding
`user_id` and timestamps and **no secret whatsoever**, so that the global read
never has to touch `user_credentials`. The alternative — widening a policy on
the token table, or wrapping it in `SECURITY DEFINER` — would have put a new
path in front of the refresh tokens for the sake of a number that is not
secret.

**What this concedes, stated plainly:** a signed-in user's request runs with a
role that is permitted to read every enrolled `user_id`. No endpoint exposes
that list — the two callers take a `COUNT` and a self-membership probe — but
the isolation here is enforced by application code rather than by the database,
which is not true of the other nine tables. The data at risk is the set of user
UUIDs and their enrollment timestamps.

#### `anon` retains a grant on one table

```sql
SELECT c.relname, (c.relacl::text LIKE '%anon=%') AS anon_has_grant
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r';
```

Nine of ten tables return `false`. **`gmail_sync_enrollment` returns `true`** —
it carries `anon=arwdDxtm` and `authenticated=arwdDxtm`.

The blanket revocation of `anon` grants on 2026-08-03
(`docs/RLS-AUDIT-2026-08-03.md`) covered the tables that existed then;
`gmail_sync_enrollment` was added afterwards and reintroduced the default
grant. It is **not exploitable today**: every policy on that table is scoped to
the role `jobtracker_app`, RLS is forced, and `anon` therefore matches no
policy and reads nothing. It is unnecessary surface and an inconsistency with
the other nine tables, and it should be revoked. Recorded here as an open item
rather than left for an assessor to find.

### 4.2 Layer 2 — the connecting role cannot bypass RLS

```sql
SELECT rolname, rolbypassrls, rolsuper FROM pg_roles
WHERE rolname IN ('jobtracker_app', 'postgres');
--  jobtracker_app | false | false
--  postgres       | true  | false
```

Production connects as **`jobtracker_app`**, which is `NOBYPASSRLS` and not a
superuser. The `postgres` role can bypass RLS and is used only for DDL, by a
human, on a different port (5432 direct, versus 6543 pooled for the app).

Identity is bound per transaction, not per connection, which is what makes this
safe under Supabase's shared PgBouncer in transaction-pooling mode:

- The verified JWT `sub` is carried in a `ContextVar` and applied as
  `set_config('request.jwt.claims', …, is_local => true)` in a `begin` event
  handler, so it is scoped to the current transaction and discarded at
  COMMIT/ROLLBACK. A physical connection handed to the next tenant by PgBouncer
  cannot carry a stale identity.
  (`backend/jobtracker/database/connection.py:60-90`, `:157-181`)
- `search_path` is pinned to `public` on every transaction in the same call.
  This is not decoration: the shared pooler previously suffered a co-tenant
  `search_path` poisoning incident on a sibling project.
- When no user is bound — health and unauthenticated paths — `request.jwt.claims`
  stays unset, so RLS **fails closed** and reads zero rows rather than reading
  everything.

`backend/tests/test_rls_postgres.py` exercises this against a **real Postgres**,
not SQLite — SQLite has no row-level security, so a test that ran there would
prove nothing. It runs in CI against a Postgres service container
(`.github/workflows/backend-ci.yml:175-177`), and the workflow explicitly guards
against the skip-is-green failure mode: if `JOBTRACKER_TEST_PG_ADMIN_URL` were
unset the tests would skip silently and the job would still pass, so the
workflow parses the JUnit XML and fails the step when the suite reports zero
tests or any skip (`:224-243`).

### 4.3 Layer 3 — explicit `user_id` scoping in the application

The user-facing routers under `backend/jobtracker/cloud/` — `applications.py`
and `account.py` — are mounted with a **router-level** `require_user()`
dependency and additionally filter on `user_id` in their own SQL. This
duplicates what RLS already enforces, deliberately: the repo has previously
found DDL it assumed was applied to be absent in production, and a belt-and-
braces filter is what keeps a purge interrupted half-way from leaving orphans
that RLS then makes permanently unreachable.

**Two routers are authenticated differently, and this document names them
rather than claiming a uniformity that does not hold** (`docs/ARCHITECTURE.md`
states the blanket version; it is imprecise):

- **`gmail_oauth.py`** carries no router-level dependency. Its user-facing
  endpoints take `Depends(current_user)` individually (`:1028`, `:1072`,
  `:1254`, `:1411`, `:1585`, `:2041`). The **OAuth callback** deliberately has
  none — the request arrives from Google's redirect and cannot carry the user's
  JWT, so identity comes from the HS256-signed `state` parameter instead, which
  the handler verifies before binding the RLS identity (`:1242`).
- **`cron.py`** is not user-authenticated at all. It is invoked by Vercel's
  scheduler and authenticates with the shared `JOBTRACKER_VERCEL_CRON_SECRET`
  bearer token (`:265`, `:286`). It then binds each user's identity
  individually for that user's own sync, so the per-user RLS context still
  applies to every query it makes.

Both are legitimate — neither can have a user JWT at the point it is called —
but they are the two places where "every endpoint requires a user token" is not
literally true, and an assessor reading the router table will find them.

Account deletion is the clearest instance. `backend/jobtracker/cloud/account.py`
purges children before parents across all nine user-bearing tables —
`EmailEmbedding, Contact, Interview, Email, Application, TrainingData,
SyncState, UserCredential, GmailSyncEnrollment` — each scoped by `user_id` and
each additionally covered by RLS. `training_data` is in that list, so the
snippet copies described in §2.2 are destroyed with the account even though no
foreign key would have cascaded them.
`backend/tests/test_account_deletion_covers_every_table.py` derives the
required list from every table carrying a `user_id`, so a table added later
cannot be silently forgotten.

The user's Gmail grant is revoked at Google *before* the purge, because
`user_credentials` is the only place the token exists and after the purge there
would be nothing left to revoke.

---

## 5. Residual risk, stated plainly

- **Isolation has never been exercised by a second concurrent real user.**
  Production holds **2** users (`auth.users`, 2026-08-15). The controls above
  are enforced by the database and covered by tests against a real Postgres,
  but the evidence is structural, not the result of observing two tenants under
  load.
- **`training_data.email_id` has no foreign key.** Orphan rows are possible and
  one exists today. They are within-account and are removed by account
  deletion, but referential integrity here is maintained by application code
  rather than by the database.
- **`alembic_version` is unprotected by RLS.** It holds no user data. It is
  listed here so its absence from the table above is a documented decision
  rather than something an assessor discovers.
- **One policy is not user-scoped (§4.1).** `gmail_sync_enrollment` is readable
  in full by the application role. The table holds no secret, but tenant
  isolation for it rests on application code rather than on the database.
- **`anon` still holds a grant on `gmail_sync_enrollment` (§4.1).** Inert
  today because that table's policies are role-scoped, but it is drift from the
  2026-08-03 hardening and should be revoked. **Open item.**
- **The 2026-08-03 `anon` revocation is hand-run SQL, not a migration (§3).**
  Production has it; a database rebuilt from `backend/alembic/versions/` alone
  would not. Porting it into a revision is the fix. **Open item.**
- **32 of the 35 policies carry no role clause (§4.1).** Isolation does not
  depend on one — the `user_id = (SELECT auth.uid())` predicate, `FORCE` and
  `NOBYPASSRLS` are what enforce it — but the uniform role gate the pack would
  prefer to describe does not exist yet. **Open item.**

---

*Prepared 2026-08-15. Figures marked live are snapshots; re-run the queries
inline to refresh them.*
