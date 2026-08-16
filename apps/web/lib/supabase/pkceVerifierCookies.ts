import type { NextRequest, NextResponse } from "next/server";

/**
 * Expire the PKCE code-verifier cookies a server-side exchange spends but
 * cannot clear (#321).
 *
 * WHAT THE LIBRARY LEAVES BEHIND, MEASURED
 * ----------------------------------------
 * A flow start in the browser (`signInWithOAuth`, `signUp`,
 * `resetPasswordForEmail`) writes THREE cookies, all with
 * `Max-Age=34560000` — 400 days, `DEFAULT_COOKIE_OPTIONS.maxAge` in
 * `@supabase/ssr/dist/main/utils/constants.js`:
 *
 *     sb-<ref>-auth-token-code-verifier                  the fixed "legacy" key
 *     sb-<ref>-auth-token-flow-<flowId>-code-verifier    this flow's slot
 *     sb-<ref>-auth-token-flows-code-verifier            the index of flow ids
 *
 * The exchange runs HERE, on the server, and auth-js resolves the flow id from
 * `window.location` — which a Route Handler does not have. So `flowId` is
 * `null`, `removePKCEVerifier` (auth-js `lib/helpers.js`) takes its
 * no-flow-id branch and asks for the legacy key alone. Driven against a fake
 * auth server with the installed packages, that leaves:
 *
 *   SUCCESS  legacy deleted (Max-Age=0). Slot and index SURVIVE.
 *   FAILURE  nothing deleted AT ALL — all three survive, the legacy key
 *            included. `@supabase/ssr`'s server adapter buffers the legacy
 *            removal and only flushes it from `createServerClient`'s
 *            `onAuthStateChange` on SIGNED_IN / PASSWORD_RECOVERY / …; a
 *            failed exchange emits only INITIAL_SESSION, which is not on that
 *            list, so `applyServerStorage` never runs.
 *
 * The failure branch is why this is applied on EVERY exit after the client is
 * created rather than only after a successful exchange. It is also the half
 * #321 got wrong: the issue lists the legacy key as "cleared", which is true
 * of the success branch only.
 *
 * WHAT IT COSTS, AND WHAT IT DOES NOT
 * -----------------------------------
 * Not unbounded, contrary to #321. auth-js's ring (`storePKCEVerifier`, with
 * `PKCE_MAX_CONCURRENT_FLOWS = 5`) evicts the oldest slot on every flow start,
 * so the residue settles at five slots plus the index — measured at 1,437
 * bytes of Cookie header on every request to the origin, in a fixture whose
 * project ref is short. A browser-side `signOut()` clears them
 * (`_removeSession` → `removeAllPKCEVerifiers`); nothing else does.
 *
 * And it does not break the next sign-in: the next flow start overwrites the
 * legacy key, so a retry after a failed exchange succeeds. This is hygiene —
 * a spent single-use secret left resident for 400 days — not a functional
 * defect.
 *
 * WHAT THIS DELIBERATELY DOES NOT FIX. Two tabs mid-sign-in: tab B completes,
 * then tab A fails with `AuthPKCECodeVerifierMissingError`. The cause is the
 * legacy key mirroring only the MOST RECENT flow, so tab A's exchange reads
 * tab B's spent verifier — tab A's own slot is sitting in the browser, unused,
 * because the server has no flow id to address it with. That wants
 * `sb_flow_id` plumbed through the redirect, which is a change to the sign-in
 * path; it is not this. Verified that this sweep leaves that sequence exactly
 * as it was.
 */

/**
 * `<storageKey>-flow-<flowId>-code-verifier`. The bound on the id mirrors
 * auth-js's `PKCE_FLOW_ID_PATTERN`, and the pattern is `@supabase/ssr`'s own
 * `PKCE_VERIFIER_SLOT_KEY` (`dist/main/cookies.js`) — kept identical so a
 * version bump has one place to compare against. It must not match the index
 * (`-flows-`, no `-` after `flow`) or the legacy key.
 */
const SLOT_COOKIE = /^(.+)-flow-[A-Za-z0-9_-]{8,64}-code-verifier$/;

/** `<storageKey>-flows-code-verifier`, auth-js's index of pending flow ids. */
const INDEX_SUFFIX = "-flows-code-verifier";

/** The fixed key every flow start also writes, and the only one the exchange reads. */
const VERIFIER_SUFFIX = "-code-verifier";

const isSlot = (name: string) => SLOT_COOKIE.test(name);
const isIndex = (name: string) => name.endsWith(INDEX_SUFFIX);
const isLegacy = (name: string) =>
  name.endsWith(VERIFIER_SUFFIX) && !isSlot(name) && !isIndex(name);

/**
 * Delete on `response` every verifier cookie this request can prove is spent.
 *
 * Spent means, precisely:
 *
 *   1. the legacy key — the exchange that just ran read it and nothing else,
 *      so whatever the outcome its value has been submitted; and
 *   2. any flow slot holding the SAME raw cookie value as the legacy key,
 *      which is the slot the legacy key was mirroring, i.e. the flow that was
 *      just spent. Byte equality is enough: `storePKCEVerifier` writes the one
 *      verifier string to both keys through the same client, so both cookies
 *      carry the identical `base64-…` payload.
 *
 * A slot with a DIFFERENT value belongs to another flow — a second tab still
 * mid-sign-in — and is left alone. That is the case #321 says a naive prefix
 * sweep breaks, and value equality is what makes this not a prefix sweep.
 *
 * The index goes only when no slot survives it: an index naming a live slot is
 * that flow's entry in the eviction ring and must stay. Rewriting the index to
 * drop one id would mean re-encoding `base64-` + base64url(JSON) in app code,
 * duplicating library internals to save a stale id whose only cost is a slot
 * read returning null.
 *
 * Chunked verifier cookies are not handled: `createChunks` splits at 3,180
 * bytes and a verifier is ~130, so `<key>.0` cannot exist for these keys. If a
 * future version chunks them, the `.N` siblings would need matching too.
 *
 * Writes go on the RESPONSE, not the `next/headers` store, for the reason
 * `reset-password/callback` already gives for its marker cookie: that handler
 * builds its response before the exchange, and a mutation of the
 * request-scoped store is not guaranteed to reach an already-constructed one.
 *
 * A no-op when the browser sent no verifier cookies, so a route can call it on
 * every exit without first asking whether an exchange happened.
 */
export function expireSpentPkceVerifierCookies<T extends NextResponse>(
  request: NextRequest,
  response: T,
): T {
  const present = request.cookies.getAll();

  const legacyNames = present.filter((c) => isLegacy(c.name));
  if (legacyNames.length === 0) return response;

  const spentValues = new Set(legacyNames.map((c) => c.value));
  const slots = present.filter((c) => isSlot(c.name));
  const spentSlots = slots.filter((c) => spentValues.has(c.value));

  const doomed = [...legacyNames, ...spentSlots].map((c) => c.name);

  // Only once nothing references it: every slot present is one we are deleting.
  if (spentSlots.length === slots.length) {
    doomed.push(...present.filter((c) => isIndex(c.name)).map((c) => c.name));
  }

  for (const name of doomed) {
    // `expires` in the past AND `maxAge: 0`, at the path the library wrote
    // them at (`DEFAULT_COOKIE_OPTIONS.path`) — a deletion at the wrong path
    // shadows the cookie instead of dropping it.
    //
    // THE `expires` IS NOT BELT AND BRACES; `maxAge` ALONE DOES NOT SURVIVE.
    // Observed on a production build, on the SUCCESS branch only: the
    // response went out as `sb-…-code-verifier=; Path=/` with no `Max-Age` at
    // all, so the cookie was emptied but not dropped. When the request-scoped
    // `cookies()` store has mutations — which is exactly what a successful
    // exchange produces, and what a failed one does not — Next merges it into
    // the response by round-tripping the `Set-Cookie` header through
    // `parseSetCookie`, whose `compact()` strips every falsy field
    // (`next/dist/compiled/@edge-runtime/cookies`). `maxAge: 0` is falsy, so
    // the one attribute that made this a deletion was dropped on the one
    // branch that writes a session. `new Date(0)` is an object, so it lives.
    //
    // The asymmetry is the tell, and the same run showed it: the library's own
    // deletion of the fixed key came out intact as `Max-Age=0; SameSite=lax`,
    // because it is written into the `cookies()` store and applied TO the
    // response, while these are written ON the response and are therefore what
    // gets parsed and re-serialized. Same branch, same request, opposite
    // outcomes — which is why the library needs no `expires` here and we do.
    //
    // `secure` and `sameSite` are here so this deletion carries the same
    // attributes the cookie was WRITTEN with — `DEFAULT_COOKIE_OPTIONS`'
    // `sameSite: "lax"`, plus the `secure` the clients now add (see
    // `lib/supabase/server.ts` for the gate and why it follows `NODE_ENV`).
    // Not because they affect which cookie is overwritten — identity is
    // (name, domain, path), and `path` above is what carries that. Because a
    // deletion is a `Set-Cookie` like any other: it is graded by the same
    // rules as the write it undoes, and a cookie that was only ever sent over
    // TLS should be cleared by a write that is too. Under
    // `next dev` the `secure: false` is falsy and `compact()` strips it — the
    // same mechanism the paragraph above is about — which is correct there:
    // the cookie it is deleting was written without `Secure` too.
    response.cookies.set(name, "", {
      expires: new Date(0),
      maxAge: 0,
      path: "/",
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
    });
  }

  return response;
}
