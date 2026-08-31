# Session cookies — attributes and compensating controls

CASA AL1 evidence for **2.3.1** and **2.3.2** (cookie attributes).

Read against production on **2026-08-15**. This control is **partially met**,
and the part that is not met is architectural rather than an oversight. Both
halves are described.

---

## 1. What the cookies are

Authentication is Supabase Auth. The session cookies are written by
`@supabase/ssr` **0.12.4**, not by application code, from three factories:

| Factory | File | Runs |
| --- | --- | --- |
| `createServerClient` | `apps/web/lib/supabase/server.ts:90` | Route Handlers, Server Components |
| `createServerClient` | `apps/web/lib/supabase/middleware.ts:104` | the proxy, on every matched request |
| `createBrowserClient` | `apps/web/lib/supabase/client.ts:23` | Client Components, via `document.cookie` |

Those three are the complete set; a grep for `createServerClient|createBrowserClient`
across `apps/web` returns exactly them and nothing else outside test stubs.

The application writes two cookies of its own: the recovery marker
(`apps/web/lib/auth/recoverySession.ts:69-72`) and the PKCE verifier deletions
written by `expireSpentPkceVerifierCookies`
(`apps/web/lib/supabase/pkceVerifierCookies.ts:172-178`).

---

## 2. Attributes

### 2.1 What they were, before remediation

The library's `DEFAULT_COOKIE_OPTIONS`
(`node_modules/@supabase/ssr/dist/main/utils/constants.js`) is exactly:

```js
{ path: "/", sameSite: "lax", httpOnly: false, maxAge: 400*24*60*60 }
```

**There is no `secure` key at all.** No `cookieOptions` was being passed, so
session cookies went to the browser with no `Secure` attribute.

Confirmed on the production wire rather than inferred from the constant —
`/callback` with verifier cookies present returns:

```
HTTP/2 307
set-cookie: sb-<ref>-auth-token-code-verifier=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0
```

`Path=/` and nothing else. *Precisely:* that observation is of the **verifier
deletion** written by application code. The session cookie's missing `Secure`
was established by reading the installed library, because obtaining a real
session cookie requires a sign-in and the repository holds no seeded test
account.

### 2.2 What they are now

`cookieOptions: { secure: process.env.NODE_ENV === "production" }` is passed to
all three factories. Both `applyServerStorage` and the browser storage's
`setItem` build their options as `{ ...DEFAULT_COOKIE_OPTIONS, ...cookieOptions }`,
so the attribute reaches every write, including the sign-out deletions. The
`NODE_ENV` gate follows the pattern already established at
`apps/web/lib/auth/recoverySession.ts:71`.

| Attribute | Value | Status |
| --- | --- | --- |
| `Secure` | set in every deployed environment | **remediated** |
| `SameSite` | `Lax` | met |
| `Path` | `/` | met |
| `HttpOnly` | **`false`** | **not met — see §3** |
| `Max-Age` | 400 days | see §4 |

`SameSite=Lax` rather than `Strict` is deliberate: the browser arrives at the
auth callback from Supabase's domain, a cross-site top-level navigation, which
is exactly the case Lax permits and Strict does not. `Strict` would break
sign-in.

`apps/web/tests/unit/cookie-attributes.test.mjs` pins this against the **real
installed library**, and was proven able to fail — reverting any one factory
reddens only that factory's assertions.

---

## 3. `HttpOnly` is `false`, and cannot be `true`

**This is a genuine deviation from the control text, not a remediation, and it
is stated as such.**

`@supabase/ssr`'s browser client stores the session in `document.cookie`. Seven
modules import that client — the login, signup, forgot-password and
set-new-password forms, the Google sign-in button, the session controls in the
shell, and the settings transport. Marking the auth cookie `HttpOnly` would
make it unreadable to the client library and break sign-in outright.

Changing this would require replacing the session transport — a server-side
session with an opaque `HttpOnly` cookie, and every client-side Supabase call
proxied through a route handler. That is a re-architecture of authentication,
not a configuration change.

### 3.1 Compensating controls, each verified on the wire

All five were read off a real response rather than off the config — but not all
from the same place, and the difference matters. The bottom four were read from
the **production** response on 2026-08-15. The `Content-Security-Policy` row is
the policy this change ships and has **not** been observed in production yet; it
was read from a local `next build && next start` by `apps/web/scripts/csp-gate.mjs`.
See §3.1.1 and the provenance note at the foot of this document.

| Control | Value | What it does here |
| --- | --- | --- |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' 'nonce-<per-request>' 'strict-dynamic'; style-src 'self' 'unsafe-inline'; …; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` | a script with no matching nonce does not execute — see §3.1.1 |
| `X-Frame-Options` | `DENY` | no framing, so no clickjacking route to the session |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` | the cookie cannot travel in clear even on a downgrade attempt |
| `X-Content-Type-Options` | `nosniff` | no MIME-confusion script execution |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | no cookie-adjacent leakage via `Referer` |

### 3.1.1 The CSP was rebuilt around a per-request nonce

**This section previously recorded `script-src 'self' 'unsafe-inline'` as an
open item, and said plainly that the CSP therefore did not provide strong XSS
protection. That is no longer the state of the code.** `'unsafe-inline'` has
been removed from `script-src`.

`apps/web/proxy.ts` mints a fresh nonce per request (`crypto.randomUUID`) and
sets the policy on both the request and the response. Next reads the nonce off
the request header during render and stamps it onto the framework bootstrap,
every chunk `<script src>` and the streaming RSC payload scripts; the root
layout passes it by hand to the two pre-paint scripts it authors itself. The
policy is built in `apps/web/lib/security/csp.ts`.

`'strict-dynamic'` accompanies the nonce, which means a conforming browser
**ignores the `'self'` source entirely** — every script must either carry the
request's nonce or be loaded by a script that already did. An injected
`<script>` cannot guess a 128-bit per-request value, and an injected inline
event handler does not execute at all.

**Why a nonce and not hashes.** Hashes would have preserved static rendering.
They cannot work here: the App Router emits its RSC payload as an inline
`self.__next_f.push([1, …])` script — 61 KB on the landing page — whose content
*is* the rendered page. It changes with any content change and is emitted as
multiple differing chunks on a streamed route, so there is no stable hash set
to pin. This was read off a real production build, not assumed.

**What it cost, stated so the trade is auditable.** A nonce requires dynamic
rendering, because Next injects it at render time from a request header and a
build-time prerender has no request. Six routes were `○ Static` and are now
`ƒ Dynamic`: `/`, `/login`, `/signup`, `/forgot-password`, `/demo/inbox` and
`/_not-found`. `/` lost `Cache-Control: s-maxage=31536000`. Measured locally on
`next build && next start`: a single request to `/` moved 4.1 ms → 8.3 ms, and
at concurrency 10 p50 moved 12.4 ms → 59.4 ms with p95 25.2 ms → 98.6 ms. That
was judged acceptable against a beta sized at roughly 100 users.

**A half-measure was considered and rejected.** Noncing only the signed-in
routes, leaving the marketing and auth pages static, would not have worked: the
session cookie is `Path=/` and readable from `document.cookie` on any
same-origin path, so script execution on the static landing page reaches the
session exactly as well as on `/dashboard`. The weakest route sets the ceiling.

**One route is deliberately outside the scheme.** `/system-card` is a
self-contained Vite bundle served from `public/system-card/`, not an app route,
so no nonce can be injected into its HTML. It is excluded from the proxy
matcher and carries its own classic policy, `script-src 'self'`, with no inline
grant at all — stricter than the app's fallback. This is verified rather than
assumed: `apps/web/scripts/csp-gate.mjs` asserts that bundle ships zero inline
scripts, and would fail if one were ever added.

**`style-src` still carries `'unsafe-inline'`, and that part is a genuine
residual.** It is a structural limit, not a deferral: the landing page renders
198 inline `style="--d:…ms"` attributes (animation stagger delays) plus a
`<style>` block from `next/font`, and CSP nonces apply to `<style>` *elements*
only — no mechanism exists that lets a nonce cover a style *attribute*. The
risk profile differs from scripts: inline styles buy defacement and, with a
crafted selector, limited data inference. They do not buy script execution,
which is the path to the session cookie. **Open item, lower severity.**

**Verified on the wire, not in the config.** `apps/web/scripts/csp-gate.mjs`
runs against a live `next build && next start` and, per route, asserts exactly
one CSP header, extracts the nonce from it, and requires **every** `<script>`
tag in the body to carry that same nonce. A header nonce that differs from the
body's is the signature of a route still being served from a prerender — the
failure mode where the page renders fine and nothing is protected. The gate was
proven able to fail: it caught the `/system-card` break described above before
that route was excluded.

### 3.2 What the exposure actually is

If an attacker achieves script execution on this origin, they can read the
session cookie. They could also, with `httpOnly: true`, simply issue
authenticated requests from the victim's browser — so `HttpOnly` raises the
cost of session theft and narrows exfiltration, but it is not the difference
between compromise and safety. The honest summary: **XSS on this origin is a
full account compromise, and `HttpOnly` would not change that conclusion,
though it would make token exfiltration harder.**

---

## 4. Cookie lifetime is not session lifetime

These are distinct and an assessor will conflate them if the document does not
separate them.

| | Value | Set by |
| --- | --- | --- |
| **Cookie** `Max-Age` | 400 days | `@supabase/ssr` default (browser cap) |
| **Access token (JWT)** expiry | short-lived, minutes to an hour | Supabase project setting |
| **Refresh token** | rotated on use | Supabase Auth |

The 400-day figure is the *cookie jar's* lifetime, not an authorisation
lifetime. The credential inside it expires on the JWT schedule and is rotated
on refresh — `auth.sessions.refreshed_at` in production shows rotation
occurring on a session established four days earlier. A stale cookie past its
token's expiry authenticates nothing; the backend verifies the signature and
expiry on **every** request (`backend/jobtracker/auth/supabase_jwt.py`).

`Max-Age` was deliberately **not** shortened. Doing so would force periodic
re-login without improving the authorisation window, which is governed by the
token, and the control does not require it.

---

## 5. Residual risk, stated plainly

1. **`HttpOnly` is `false` and will remain so** without an authentication
   re-architecture. 2.3.x is partially met.
2. **`script-src 'unsafe-inline'` is gone** (§3.1.1) — the compensating control
   for (1) is now a real one rather than a nominal one. Two things must not be
   over-read from that. `style-src` still allows `'unsafe-inline'`, which is
   structural and cannot be nonced (style attributes are outside the mechanism);
   and §3.2's conclusion is **unchanged** — a nonce raises the bar against
   achieving script execution, but if an attacker clears that bar the session is
   still readable, because the cookie is not `HttpOnly`. **Partially open.**
3. **No signed-in browser pass verifies the `Secure` change end to end.** The
   `playwright (production build)` job runs under `NODE_ENV=production` — so the
   gate was active — and passed, which shows the production build serves and
   passes its non-auth specs with `Secure` on. It does **not** establish a
   session across requests, because the repository has no seeded test account
   and the auth-gated specs skip. Sign-in, refresh rotation and sign-out on a
   real project remain unverified by CI. **Open item — a seeded test account
   would close this and several other gaps.**
4. **The post-fix wire attribute has not been observed.** Preview deployments
   are SSO-gated, so the `/callback` probe that produced the pre-fix evidence
   cannot reach the app on a preview. A post-merge production probe would
   settle it.

---

*Prepared 2026-08-15.*

*Provenance of the header values above, because it is not uniform. The
`X-Frame-Options`, `Strict-Transport-Security`, `X-Content-Type-Options` and
`Referrer-Policy` rows in §3.1 were read from the live production response. The
`Content-Security-Policy` row was **not** — it states the policy this change
ships, read off a local `next build && next start` via
`apps/web/scripts/csp-gate.mjs`. It reaches production when this merges; a
post-merge probe of `https://getapplied.vercel.app/` should confirm it before
this pack is filed.*
