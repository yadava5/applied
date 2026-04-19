import { type NextRequest } from "next/server";

import { updateSession } from "@/lib/supabase/middleware";

/**
 * Next.js 16 renamed the `middleware.ts` convention to `proxy.ts`
 * (see https://nextjs.org/docs/app/api-reference/file-conventions/proxy).
 * The function body still fulfils the same role: refresh the Supabase
 * session on every eligible request and gate protected routes behind auth.
 *
 * All auth logic lives in `lib/supabase/middleware.ts#updateSession` so it
 * can be unit-tested without a NextRequest mock.
 */
export async function proxy(request: NextRequest) {
  return await updateSession(request);
}

export const config = {
  matcher: [
    /*
     * Run on every path except:
     * - `_next/static`     (static asset bundles)
     * - `_next/image`      (image optimiser)
     * - favicon + metadata files
     * - any file with an extension (png/jpg/svg/...)
     *
     * This is the same negative matcher the Supabase SSR template uses.
     */
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
