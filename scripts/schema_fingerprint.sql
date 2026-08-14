-- Canonical, order-stable fingerprint of the `public` schema.
-- Emits one text line per schema fact so two databases can be diffed as text.
-- Runs identically through psql, psycopg, or the Supabase MCP.

WITH cols AS (
  SELECT format('column  %s.%s  type=%s  null=%s  default=%s',
                c.table_name, c.column_name, c.udt_name, c.is_nullable,
                coalesce(c.column_default, '-')) AS line
  FROM information_schema.columns c
  JOIN information_schema.tables t
    ON t.table_schema = c.table_schema AND t.table_name = c.table_name
  WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
),
idx AS (
  SELECT format('index   %s', indexdef) AS line
  FROM pg_indexes WHERE schemaname = 'public'
),
cons AS (
  SELECT format('constr  %s.%s  %s  %s',
                rel.relname, con.conname, con.contype,
                pg_get_constraintdef(con.oid)) AS line
  FROM pg_constraint con
  JOIN pg_class rel ON rel.oid = con.conrelid
  JOIN pg_namespace ns ON ns.oid = rel.relnamespace
  WHERE ns.nspname = 'public'
),
enums AS (
  SELECT format('enum    %s  = %s', t.typname,
                array_agg(e.enumlabel ORDER BY e.enumsortorder)::text) AS line
  FROM pg_type t
  JOIN pg_enum e ON e.enumtypid = t.oid
  JOIN pg_namespace ns ON ns.oid = t.typnamespace
  WHERE ns.nspname = 'public'
  GROUP BY t.typname
),
rls AS (
  SELECT format('rls     %s  enabled=%s  forced=%s',
                c.relname, c.relrowsecurity, c.relforcerowsecurity) AS line
  FROM pg_class c
  JOIN pg_namespace ns ON ns.oid = c.relnamespace
  WHERE ns.nspname = 'public' AND c.relkind = 'r'
),
pol AS (
  SELECT format('policy  %s.%s  cmd=%s  permissive=%s  using=%s  check=%s',
                p.tablename, p.policyname, p.cmd, p.permissive,
                coalesce(p.qual, '-'), coalesce(p.with_check, '-')) AS line
  FROM pg_policies p WHERE p.schemaname = 'public'
)
SELECT line FROM (
  SELECT line FROM cols  UNION ALL
  SELECT line FROM idx   UNION ALL
  SELECT line FROM cons  UNION ALL
  SELECT line FROM enums UNION ALL
  SELECT line FROM rls   UNION ALL
  SELECT line FROM pol
) all_lines
ORDER BY line;
