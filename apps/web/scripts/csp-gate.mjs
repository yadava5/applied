/**
 * CSP wire gate. Reads the SERVED response, never the config.
 *
 *   node scripts/csp-gate.mjs [baseUrl]
 *
 * Point it at a running `next build && next start` (NOT `next dev` — the dev
 * policy carries `'unsafe-eval'` by design, and dev serves an entirely
 * different script graph).
 *
 * WHY THIS EXISTS RATHER THAN A UNIT TEST OF THE POLICY STRING. The failure
 * mode this change can ship is silent and passes every naive check: the header
 * advertises a fresh nonce while the HTML carries a stale one (or none),
 * because the route was served from a build-time prerender or because
 * `proxy.ts` set the request headers after `updateSession` had already built
 * its response. The page still returns 200. Asserting the policy string alone
 * cannot see it. Comparing the header nonce against every nonce in the body
 * can, and that comparison is the whole point of this file.
 *
 * PROVEN ABLE TO FAIL. Before `/system-card` was excluded from the proxy
 * matcher, this gate reported `un-nonced=1` on it against
 * `<script type="module" crossorigin src="/system-card/assets/index-*.js">` —
 * a real break (under `'strict-dynamic'` the `'self'` source is ignored, so
 * that script would not have run). The fix was driven by this output.
 */

const base = process.argv[2] ?? "http://localhost:3000";

/** Routes that must carry the per-request nonce policy. */
const NONCED = [
  "/",
  "/login",
  "/signup",
  "/forgot-password",
  "/reset-password",
  "/demo",
  "/demo/inbox",
  "/demo/scan",
  "/demo/settings",
  "/demo/shell",
  "/privacy",
  "/import",
];

/** Redirect exits — no body to check, but they must still carry a policy. */
const REDIRECTS = ["/dashboard", "/inbox", "/settings", "/callback"];

/**
 * The System Card is a static Vite bundle, deliberately OUTSIDE the nonce
 * scheme (see `proxy.ts`'s matcher). Its policy is classic and stricter:
 * `script-src 'self'` with no inline grant at all. That only stays correct
 * while the bundle ships zero inline scripts, so this asserts the absence
 * rather than assuming it.
 */
const CLASSIC = ["/system-card"];

let failures = 0;
const fail = (route, msg) => {
  failures += 1;
  console.log(`  FAIL ${route}: ${msg}`);
};

/** All CSP headers on the response, so "exactly one" is actually checked. */
function cspHeaders(res) {
  return [...res.headers].filter(([k]) => k.toLowerCase() === "content-security-policy");
}

function checkSingle(route, res) {
  const all = cspHeaders(res);
  if (all.length !== 1) {
    fail(route, `expected exactly 1 Content-Security-Policy header, got ${all.length}`);
    return null;
  }
  return all[0][1];
}

/** Every <script …> open tag, whether inline or `src=`. */
function scriptTags(body) {
  return [...body.matchAll(/<script(\s[^>]*)?>/gi)].map((m) => m[0]);
}

/** Inline <script>…</script> bodies with actual content. */
function inlineScriptBodies(body) {
  return [...body.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)]
    .map((m) => m[1])
    .filter((s) => s.trim().length > 0);
}

async function checkNonced(route) {
  const res = await fetch(base + route, { redirect: "manual" });
  const csp = checkSingle(route, res);
  if (csp === null) return;

  if (/script-src[^;]*'unsafe-inline'/.test(csp)) {
    fail(route, "script-src still grants 'unsafe-inline'");
  }
  if (!/script-src[^;]*'strict-dynamic'/.test(csp)) {
    fail(route, "script-src is missing 'strict-dynamic'");
  }

  const m = csp.match(/'nonce-([A-Za-z0-9+/_-]+={0,2})'/);
  if (!m) {
    fail(route, "no nonce in the served policy");
    return;
  }
  const headerNonce = m[1];

  const body = await res.text();
  const tags = scriptTags(body);
  if (tags.length === 0) {
    fail(route, "no <script> tags in the body at all — did the route render?");
    return;
  }

  // The assertion that matters. A tag without THIS request's nonce is a tag
  // the browser will refuse to execute under 'strict-dynamic'.
  const unNonced = tags.filter((t) => !t.includes(`nonce="${headerNonce}"`));
  console.log(
    `  ${route} -> ${res.status}  nonce=${headerNonce.slice(0, 10)}…  scripts=${tags.length}  un-nonced=${unNonced.length}`,
  );
  if (unNonced.length > 0) {
    fail(route, `${unNonced.length} <script> tag(s) do not carry the served nonce`);
    unNonced.slice(0, 5).forEach((t) => console.log(`      ${t.slice(0, 140)}`));
  }
}

async function checkRedirect(route) {
  const res = await fetch(base + route, { redirect: "manual" });
  const csp = checkSingle(route, res);
  if (csp === null) return;
  if (res.status < 300 || res.status >= 400) {
    fail(route, `expected a redirect while signed out, got ${res.status}`);
    return;
  }
  if (!res.headers.get("location")) {
    fail(route, "redirect carries no Location header");
    return;
  }
  console.log(`  ${route} -> ${res.status} ${res.headers.get("location")}  (policy present)`);
}

async function checkClassic(route) {
  const res = await fetch(base + route, { redirect: "manual" });
  const csp = checkSingle(route, res);
  if (csp === null) return;

  if (!/script-src\s+'self'\s*(;|$)/.test(csp)) {
    fail(route, `expected exactly \`script-src 'self'\`, got: ${csp}`);
  }
  if (/script-src[^;]*'unsafe-inline'/.test(csp)) {
    fail(route, "script-src grants 'unsafe-inline'");
  }
  if (/'strict-dynamic'/.test(csp)) {
    fail(route, "'strict-dynamic' would disable the 'self' this route relies on");
  }

  const body = await res.text();
  const inline = inlineScriptBodies(body);
  if (inline.length > 0) {
    fail(
      route,
      `${inline.length} inline <script> in a bundle whose policy has no inline grant — ` +
        `it would be blocked. Either nonce this route or hash the script.`,
    );
  }
  console.log(`  ${route} -> ${res.status}  classic 'self' policy, inline scripts=${inline.length}`);
}

console.log(`CSP wire gate against ${base}\n`);
console.log("nonced routes:");
for (const r of NONCED) await checkNonced(r);
console.log("\nredirect exits:");
for (const r of REDIRECTS) await checkRedirect(r);
console.log("\nclassic-policy routes:");
for (const r of CLASSIC) await checkClassic(r);

console.log(`\n${failures === 0 ? "PASS" : `FAIL — ${failures} problem(s)`}`);
process.exit(failures === 0 ? 0 : 1);
