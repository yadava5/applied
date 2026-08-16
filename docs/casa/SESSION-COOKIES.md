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
(`apps/web/lib/supabase/pkceVerifierCookies.ts:159`).

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

Read from the production response headers on 2026-08-15:

| Control | Value | What it does here |
| --- | --- | --- |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' 'unsafe-inline'; …; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` | constrains script origins — but see the caveat below |
| `X-Frame-Options` | `DENY` | no framing, so no clickjacking route to the session |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` | the cookie cannot travel in clear even on a downgrade attempt |
| `X-Content-Type-Options` | `nosniff` | no MIME-confusion script execution |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | no cookie-adjacent leakage via `Referer` |

**The caveat, and it is a real weakening.** The CSP carries
`script-src 'self' 'unsafe-inline'`. `'unsafe-inline'` permits inline
`<script>` and inline event handlers, which is precisely the injection class a
CSP is normally deployed to stop. So the CSP does **not** provide strong XSS
protection, and the compensating-control argument for `httpOnly: false` is
correspondingly weaker than the presence of a CSP header alone suggests. An
assessor reading only the header list would over-credit it; this document
should not let that happen.

Moving to a nonce- or hash-based `script-src` and dropping `'unsafe-inline'`
would materially strengthen this control. It has not been done. **Open item.**

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
2. **The CSP allows `'unsafe-inline'` scripts** (§3.1), which weakens the main
   compensating control for (1). **Open item.**
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

*Prepared 2026-08-15. Header values were read from the live production
response.*
