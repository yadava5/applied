/**
 * Read the ambient-mail preference out of Supabase user metadata.
 *
 * Shared by the Settings page (seeds the Appearance toggle) and the `(app)`
 * layout (decides whether the rail mounts its field) so both agree on the
 * shape and on the default. The default is ON — the field is what keeps the
 * rail's middle run from reading as an unfinished column, so a never-set key
 * means presence; only an explicit `false` turns it off, and malformed
 * metadata cannot. (The notifications default is the opposite, deliberately:
 * an alert placement is an interruption to opt into, a background is not.)
 */
export function readAmbientPref(meta: Record<string, unknown>): boolean {
  return meta.ambient !== false;
}
