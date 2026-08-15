import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { getCurrentUser } from "@/lib/supabase/auth";

/**
 * The auth boundary, and nothing else.
 *
 * `proxy.ts` already redirects unauthenticated visitors away from every path in
 * `PROTECTED_PREFIXES`. This re-check is defence in depth: if the proxy matcher
 * is ever misconfigured for a new protected route, rendering falls back to a
 * redirect instead of serving the page.
 *
 * WHY IT IS A LAYOUT OF ITS OWN RATHER THAN A LINE IN `(app)/layout.tsx`. The
 * shell above must cover `/import` and `/privacy` too — they render inside it
 * when you are signed in, which is the whole point of the parent layout — and
 * those two are PUBLIC at the same URL. A layout cannot read the pathname, so
 * one layout cannot both wrap every route in this group and redirect only some
 * of them. A route group can: the directory name IS the predicate, it costs no
 * URL segment, and `tests/unit/protected-routes.test.mjs` reads it to derive
 * what `PROTECTED_PREFIXES` must contain.
 *
 * It renders `children` unchanged, so it adds no node to the tree and cannot
 * affect the shell's persistence across navigations.
 *
 * `getCurrentUser()` is request-memoized (see `lib/supabase/auth`), so this
 * costs no second Supabase Auth round-trip beyond the parent layout's.
 */
export default async function ProtectedLayout({ children }: { children: ReactNode }) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  return <>{children}</>;
}
