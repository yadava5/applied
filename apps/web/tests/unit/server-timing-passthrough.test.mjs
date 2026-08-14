/**
 * The backend's `Server-Timing` must survive the same-origin proxy.
 *
 * WHY THIS GATE EXISTS. #265 put a real instrument on the FastAPI app — `app`,
 * `db_connect;desc="n=N"`, `db_query;desc="n=N"` on every response — and the
 * browser never saw a single one of them, because every route handler under
 * `app/api/**` answers with a `NextResponse.json(...)` built from the parsed
 * body: a new response, new headers, the backend's dropped on the floor
 * (#269). An instrument you can only read by curling the backend directly is
 * not an instrument the product has.
 *
 * WHAT IT ASSERTS, in two registers:
 *
 *   1. `withServerTiming` itself, executed against a REAL `NextResponse` —
 *      copies a present header verbatim, and touches nothing when the backend
 *      sent none or when there was no backend response at all. The real object
 *      matters: whether a `NextResponse.json(...)`'s header guard permits a
 *      later `.set()` is a runtime fact, and asserting it against a hand-rolled
 *      stub would only prove what this file believes.
 *   2. Every read-path handler under `app/api/**` calls it. Source-level and
 *      crude on purpose, like `settings-publish-contract.test.mjs` next door:
 *      executing a route handler needs the Next runtime and a Supabase cookie
 *      jar that these unit tests do not have. A false positive (the call
 *      present but on an unreachable branch) is possible; a false NEGATIVE — a
 *      new GET proxy that rebuilds the body and never copies the header, which
 *      is precisely the defect — is not.
 *
 * The predicate is exercised against a synthetic offender before it is trusted
 * on the real tree, and the scan is checked for actually seeing the known
 * handlers, so neither half can pass vacuously (the checks-that-cannot-fail
 * rule).
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// `next/server.js`, not `next/server`: node resolves the file, the bundler
// resolves the bare specifier. Same module either way.
import { NextResponse } from "next/server.js";

import { withServerTiming } from "../../lib/api/serverTiming.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const API_DIR = join(HERE, "../../app/api");

/** A verbatim header off the backend, `desc` quoting and all (main_cloud.py). */
const BACKEND_HEADER =
  'app;dur=712.4, db_connect;dur=431.9;desc="n=2", db_query;dur=95.1;desc="n=7"';

test("a present Server-Timing reaches the browser, with its phase names unchanged", () => {
  const backend = new Response("{}", { headers: { "Server-Timing": BACKEND_HEADER } });
  const proxied = withServerTiming(backend, NextResponse.json({ id: 1 }, { status: 200 }));

  // Equality, not a substring match: the phases are deliberately NOT prefixed,
  // so `app` read in devtools is the same name (and the same number) as `app`
  // on a direct curl of the backend. A namespacing "improvement" fails here.
  assert.equal(proxied.headers.get("server-timing"), BACKEND_HEADER);
  assert.equal(proxied.status, 200);
});

test("a backend that sent no timing leaves the proxied response untouched", async () => {
  const silent = withServerTiming(
    new Response("{}"),
    NextResponse.json({ id: 1 }, { status: 200 }),
  );
  assert.equal(silent.headers.has("server-timing"), false);

  // The error paths that never reached the backend have no response to copy
  // from. Nothing is synthesized there — a header invented here would be a
  // measurement of nothing wearing the name of a real one.
  const unreached = withServerTiming(
    undefined,
    NextResponse.json({ detail: "bad id" }, { status: 400 }),
  );
  assert.equal(unreached.headers.has("server-timing"), false);
  assert.equal(unreached.status, 400);
  assert.deepEqual(await unreached.json(), { detail: "bad id" });
});

/**
 * The modules that carry the caller's JWT to FastAPI. A route that imports
 * none of them — and names no `BACKEND_API_URL` of its own — is not proxying a
 * backend read, whatever else its GET does.
 */
const BACKEND_TRANSPORTS = [
  "@/lib/api/server",
  "@/lib/applications/server",
  "@/lib/gmail/server",
];

/**
 * The `export async function GET` declaration, up to the next top-level
 * `export`. Scoped rather than file-wide because these files hold several
 * methods: `app/api/account/delete/route.ts` reaches the backend from its
 * POST while its GET is a local capability probe, and `app/api/applications/
 * [id]/route.ts` must be judged on its GET even though PATCH and DELETE sit
 * beside it.
 */
function getHandler(source) {
  const start = source.indexOf("export async function GET");
  if (start === -1) return null;
  const rest = source.slice(start);
  const end = rest.indexOf("\nexport ", 1);
  return end === -1 ? rest : rest.slice(0, end);
}

/** Does this route's GET proxy a backend read back as its own JSON response? */
function proxiesABackendRead(source) {
  const get = getHandler(source);
  if (!get || !get.includes("NextResponse.json(")) return false;
  return (
    BACKEND_TRANSPORTS.some((mod) => source.includes(`from "${mod}"`)) ||
    get.includes("BACKEND_API_URL")
  );
}

/** …and rebuild that response without carrying the backend's timing over? */
function dropsServerTiming(source) {
  return proxiesABackendRead(source) && !getHandler(source).includes("withServerTiming(");
}

test("the predicate can fail: a GET that rebuilds the body without the header is flagged", () => {
  const offender = [
    'import { NextResponse } from "next/server";',
    "",
    'import { getReviewQueue } from "@/lib/applications/server";',
    "",
    "export async function GET() {",
    "  const r = await getReviewQueue();",
    "  return NextResponse.json(r.data ?? {}, { status: r.status });",
    "}",
  ].join("\n");
  assert.equal(dropsServerTiming(offender), true);

  const carrier = offender.replace(
    "return NextResponse.json(r.data ?? {}, { status: r.status });",
    "return withServerTiming(r.response, NextResponse.json(r.data ?? {}, { status: r.status }));",
  );
  assert.equal(dropsServerTiming(carrier), false);

  // Two shapes that are NOT read paths, and must not be demanded to carry a
  // header they have nothing to put in. Both are real: `app/api/gmail/
  // authorize` answers with a redirect, and `app/api/account/delete` answers
  // its GET from this deployment's own configuration while its POST is the
  // thing that talks to the backend.
  assert.equal(
    proxiesABackendRead(
      'import { getGmailAuthorizeUrl } from "@/lib/gmail/server";\n' +
        "export async function GET() {\n  return NextResponse.redirect(url);\n}",
    ),
    false,
  );
  assert.equal(
    proxiesABackendRead(
      "export async function GET() {\n" +
        "  return NextResponse.json({ deletionEnabled: deletionEnabled() });\n" +
        "}\n" +
        "\nexport async function POST() {\n" +
        "  const { BACKEND_API_URL } = serverEnv();\n}",
    ),
    false,
  );
});

/**
 * The data export (`app/api/applications/route.ts`) is the one read-path GET
 * that deliberately copies nothing: it fans out into a backend call per page,
 * and a single `Server-Timing` cannot describe N round trips.
 */
const FANS_OUT = "applications/route.ts";

/** Every `route.ts` under `app/api`, as a path relative to that directory. */
function routeFiles(dir, prefix = "") {
  const found = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) found.push(...routeFiles(join(dir, entry.name), rel));
    else if (entry.name === "route.ts") found.push(rel);
  }
  return found;
}

test("every read-path proxy carries the backend's Server-Timing", () => {
  // A renamed transport module would quietly narrow the scan to nothing, so
  // the alias each name resolves to is checked to be a file that exists.
  for (const mod of BACKEND_TRANSPORTS) {
    assert.ok(
      readFileSync(join(HERE, "../..", `${mod.replace("@/", "")}.ts`), "utf8").length > 0,
      `${mod} no longer resolves — the read-path scan below would see less than it thinks`,
    );
  }

  const sources = new Map(
    routeFiles(API_DIR).map((rel) => [rel, readFileSync(join(API_DIR, rel), "utf8")]),
  );
  const readPath = [...sources.keys()].filter((rel) => proxiesABackendRead(sources.get(rel)));

  // The scan must be seeing the handlers this is about — a wrongly-pointed or
  // empty walk would pass with nothing to say (zero-match = failure).
  for (const known of [
    "applications/[id]/route.ts",
    "applications/mail/route.ts",
    "applications/review/route.ts",
    "gmail/inbox/route.ts",
  ]) {
    assert.ok(
      readPath.includes(known),
      `the scan is not seeing ${known} — found: ${readPath.join(", ") || "none"}`,
    );
  }
  // And the exemption must still name a handler the scan reaches, AND that
  // handler must still be the thing the exemption claims it is. A name-match
  // escape hatch that nobody re-checks is how an allowlist rots into a hole:
  // if the export is ever rewritten into a single backend read, the reason for
  // exempting it is gone and the gate should say so rather than keep letting
  // it through.
  assert.ok(
    readPath.includes(FANS_OUT),
    `${FANS_OUT} is exempted but the scan no longer sees it — re-derive the exemption`,
  );
  const fanOutGet = getHandler(sources.get(FANS_OUT));
  assert.ok(
    fanOutGet.includes("buildExportPages(") && fanOutGet.includes("collectMail("),
    `${FANS_OUT} is exempted because its GET fans out into a backend call per page, and it ` +
      `no longer does — either it copies the timing now, or the exemption needs a new reason`,
  );

  const offenders = readPath.filter(
    (rel) => rel !== FANS_OUT && dropsServerTiming(sources.get(rel)),
  );
  assert.deepEqual(
    offenders,
    [],
    `these read-path handlers rebuild the response without withServerTiming(), so the ` +
      `backend's app / db_connect / db_query phases (#265) never reach the browser: ` +
      `${offenders.join(", ")}. The only handler allowed to skip it is ${FANS_OUT}, ` +
      `which fans out into one backend call per page and cannot be described by one header.`,
  );
});
