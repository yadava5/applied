# Schema migrations

Applied's cloud schema is owned by Alembic. Until 2026-08-13 nothing applied it:
`vercel.json` builds `api/index.py` as a function with no build step, `init_db()`
returns early on Postgres, and the runtime `ALTER TABLE` helper below it is
SQLite-only. A revision merged to main and sat in the repo while the code that
needed it went live — and because every `select(Email)` in `jobtracker.cloud`
emits an explicit column list, the first read of a missing column was an
`UndefinedColumn` 500 across the whole board.

CI could not catch it. `rls-postgres` and `test_migrations_postgres` both build
their database *by running the migrations*, so the failing state — production's
schema without the new revision — is the one state those gates are structurally
unable to construct.

That is fixed. This document is the contract that keeps it fixed.

## The short version

| you are doing | how it ships |
|---|---|
| new nullable column, new table, new index, new enum label | **one PR** — write the revision, merge, done |
| drop, rename, narrow a type, add `NOT NULL`, add `UNIQUE` | **two merges** — see [Contract steps](#contract-steps) |

## How it works now

1. You add a revision under `backend/alembic/versions/` and update
   `EXPECTED_REVISION` in `backend/jobtracker/database/schema_version.py` in the
   same commit. `tests/test_schema_version.py` fails if you forget, and fails if
   the chain has grown a second head.
2. On the PR, **DB migrate → Preview** renders the exact SQL a merge would run
   against production, into the job summary. No credentials, no connection.
3. On merge to main, **DB migrate → migrate** runs `alembic upgrade head`
   against `DIRECT_URL`, then verifies `alembic_version` equals this commit's
   `EXPECTED_REVISION`. `upgrade head` exiting 0 only proves Alembic did as it
   was told; the second check is what proves the database matches the code that
   is about to serve reads from it.
4. `GET /health/schema` reports `{expected, applied, ok}` at any time.

### Why a GitHub Action and not a Vercel build step

Deploys are rate-limited to a daily cap on this account, so a migration that
fails inside a build burns a slot and ships nothing. And a build step would have
to be gated on `VERCEL_ENV == "production"` — otherwise every preview migrates
the production database — which means the runner would only ever execute in
production. That is the same "gate that cannot fail before it matters" shape
this codebase keeps finding.

## The race

Pushing to main starts the migration workflow **and** a Vercel deploy at the
same time. Nothing orders them, and nothing can: Vercel's git integration owns
its own trigger.

For an **additive** revision this does not matter. Old code ignores a column it
does not select, and new code is exposed only for the seconds until the workflow
lands. Whichever wins, both halves work. The window self-heals — and before the
workflow existed, that same state was permanent.

For anything **destructive** it matters completely, because there is no ordering
in which one PR is safe: the old code is still serving when the column
disappears.

## Contract steps

Splitting is not a workaround for a missing feature. It is the only correct
sequence when you do not control deploy ordering, and it is what every
zero-downtime migration guide describes as expand/contract.

**Dropping a column `applications.legacy_note`:**

1. **PR 1 — stop using it.** Remove every read and write of the column. Merge.
   Production now runs code that does not care whether the column exists.
2. Confirm the deploy is live (`/health` reports the new `commit`).
3. **PR 2 — drop it.** The revision, and `EXPECTED_REVISION`. Merge. The
   workflow applies it against code that already ignores it.

**Renaming** is the same shape with an extra beat: add the new column, backfill,
write to both, switch reads, then drop the old one. Four merges, and each one is
independently safe. A single `ALTER TABLE ... RENAME COLUMN` is not.

**Adding `NOT NULL`** needs the backfill to complete *and* every writer to be
supplying the value before the constraint goes on.

## Writing a revision

```sh
cd backend
pip install -r ../requirements.txt -r requirements-migrate.txt
python -m alembic revision -m "what it does"
```

Then edit the generated file, and:

- **Guard Postgres-only DDL.** SQLite is the desktop and unit-test backend, and
  `alembic upgrade head` must stay green there. Use the
  `op.get_context().dialect.name == "postgresql"` check that `a8d4ec5fba26` and
  `b9e42f7c10ad` already use, and make the SQLite branch a documented no-op
  rather than an error.
- **Enums store the member NAME, not the value.** SQLModel persists
  `ApplicationStatus.ASSESSMENT` as `'ASSESSMENT'`. `ADD VALUE 'assessment'`
  succeeds as DDL and then fails on every write — a green migration followed by a
  500. SQLite renders `sa.Enum` as `VARCHAR`, so no SQLite test can catch it;
  `tests/test_migrations_postgres.py` asserts the labels against
  `[s.name for s in ApplicationStatus]` and is the check that can.
- **A new enum label cannot be USED in the transaction that added it.**
  `env.py` wraps the whole chain in one transaction, so use
  `op.get_context().autocommit_block()` as `b9e42f7c10ad` does.
- **Say what the downgrade loses.** Postgres has no `DROP VALUE`; a downgrade
  that remaps rows is data loss, not a rollback. Write that in the docstring.

## Row-level security is a postcondition of every migration

The runner connects as the migration role, which **is** `BYPASSRLS` — it has to
be. DDL requires ownership, and `b9e42f7c10ad`'s downgrade documents that a
non-`BYPASSRLS` role would silently remap zero rows and report success.

That makes this workflow an unattended process capable of weakening tenant
isolation, and `alembic upgrade head` exits 0 either way. So every run ends with
`scripts/verify_rls.py`, which fails the job unless:

- every base table in `public` except `alembic_version` has RLS **enabled** and
  **forced**, and carries at least one policy;
- the runtime role `jobtracker_app` exists and is **NOBYPASSRLS**.

The invariant is structural, not a count. Asserting "8 tables, 32 policies"
would make adding a ninth table fail until someone bumped a constant — which
teaches people to bump constants — and would happily pass a table with RLS on
and zero policies. As written, a new table shipped without RLS fails the job
rather than leaking, and nothing needs maintaining when the schema grows.

`FORCE` matters separately from `ENABLE`: without it the table's owner bypasses
every policy on it, so a table that is `ENABLE`-only looks protected in
`pg_policies` and is not.

This complements `tests/test_rls_postgres.py` rather than duplicating it. That
suite proves the policies actually isolate tenants — but against a database the
test built. This proves the property holds on the database real rows live in,
immediately after something changed it.

Run it by hand any time:

```sh
DIRECT_URL="postgresql://..." python scripts/verify_rls.py
```

## Verifying against production without touching it

`scripts/schema_fingerprint.sql` emits one text line per schema fact — columns,
constraints, indexes, enums, RLS flags, policies — ordered so two databases can
be compared as text. Run it against production (read-only) and against a scratch
database built by `alembic upgrade head`, and diff.

```sh
docker run -d --name applied-schema --rm \
  -e POSTGRES_PASSWORD=postgres -p 55432:5432 postgres:17

# Supabase's auth objects, which the RLS revisions reference. Without these
# `upgrade head` dies on `schema "auth" does not exist` — the migrations are
# not runnable on a bare Postgres.
docker exec -i applied-schema psql -U postgres -q <<'SQL'
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (id uuid primary key);
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('request.jwt.claims', true)::jsonb ->> 'sub', '')::uuid
$$;
SQL

cd backend && DIRECT_URL="postgresql+psycopg://postgres:postgres@127.0.0.1:55432/postgres" \
  python -m alembic upgrade head
```

Comparing per-category MD5s rather than 200 lines makes a match a single glance
and points at the category to drill into when it is not. On 2026-08-13 this
proved production byte-identical to a from-empty build across all six
categories, which is what made it safe to automate.

## If something goes wrong

**`/health/schema` says `ok: false`.** A revision merged and the workflow did not
apply it — check the DB migrate run, then re-run it (`workflow_dispatch`). The
API is not broken *per se*; reads that name the new column are.

**"Could not acquire the migration advisory lock".** Another run holds it, or one
died holding it. `SELECT * FROM pg_locks WHERE locktype = 'advisory';` — the lock
is released automatically when that session disconnects.

**"Multiple head revisions are present".** Two PRs each branched a revision off
the same parent. Both were green in isolation. Rebase one onto the other so the
chain is linear; `test_schema_version.py` now catches this before merge.

**The database is unreachable.** Supabase's free tier pauses a project after 7
days idle. The workflow reports that case distinctly and applies nothing —
restore from the dashboard and re-run.

**Applying by hand** (only when the workflow cannot run). One transaction, and
put the stamp in it — DDL without moving `alembic_version` leaves the real schema
diverged from its recorded head, and the next genuine run dies re-adding the
column:

```sql
SET LOCAL lock_timeout = '3s';
ALTER TABLE public.emails ADD COLUMN suggested_category public.emailcategory;
UPDATE public.alembic_version SET version_num = 'c2e7f4a91b83';
```

## What is deliberately NOT unified

`init_db()`'s `create_all` plus `_apply_runtime_migrations` is a second schema
authority for the same models, on SQLite. It stays. Existing desktop databases
have no `alembic_version` row and unknown drift, so putting them under Alembic
means writing a reconciliation for states nobody has enumerated — and the macOS
app is out of scope for backend work. The cloud path is what this document
governs.
