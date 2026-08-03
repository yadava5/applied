-- Applied hardening, 2026-08-03. Run in the Supabase SQL editor.
--
-- Both changes are safe today and both close a trap that opens the moment
-- Applied moves to a non-bypassing application role -- the same hardening
-- Cadence completed on this date.
--
-- 1. anon/authenticated hold table grants on all nine public tables. Nothing in
--    the repository uses supabase-js, createClient() or an anon key (checked
--    across all 550 tracked files); every query goes through the FastAPI
--    backend's own connection. The grants are unreachable surface. Forced RLS
--    makes them harmless today -- and that is one DISABLE ROW LEVEL SECURITY
--    away from not being true.
--
-- 2. alembic_version has RLS ENABLED with ZERO policies and no FORCE. A table
--    with RLS on and no policy denies everything to any non-bypassing role.
--    Harmless while the app connects as BYPASSRLS; destructive the moment it
--    does not. Alembic would read the version table, get ZERO ROWS, conclude
--    the database is unmigrated, and replay every migration from the beginning
--    against populated data. Silent when reading, destructive when writing.
--    The table holds one version string and no tenant data, so RLS buys
--    nothing there; the grants are what protect it.

BEGIN;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;

ALTER TABLE public.alembic_version DISABLE ROW LEVEL SECURITY;

COMMIT;

-- Verify. Expect: nine rows, anon_or_auth_granted = 0 everywhere;
-- alembic_version rls_enabled = false; the eight tenant tables still
-- rls_enabled = true, forced = true, policies = 4.
SELECT c.relname,
       c.relrowsecurity  AS rls_enabled,
       c.relforcerowsecurity AS forced,
       (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies,
       (c.relacl::text LIKE '%anon%' OR c.relacl::text LIKE '%authenticated%')
         AS anon_or_auth_granted
FROM pg_class c
WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
ORDER BY c.relname;
