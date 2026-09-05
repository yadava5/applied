#!/usr/bin/env node
//
// Negative control for scripts/csp-gate.mjs.
//
// Run:  node scripts/negative_control_csp_gate.mjs
//
// Until #802 the gate read `script-src` and nothing else, so eight of the nine
// directives on /system-card were asserted by no check in the repository —
// `frame-ancestors 'none'` (clickjacking) and `form-action 'self'` (off-origin
// form posts) among them. The gate now compares the whole policy, and this is
// the proof that comparison can fail, kept as a step rather than as a sentence
// in a pull request nobody re-reads. #742's item 2 shipped that description
// instead of an executing control; this is the executing one.
//
// It serves a controllable policy from a stub and runs the REAL gate against
// it, so what is under test is the shipped file and not a re-implementation.
//
// NOT `spawnSync`: the stub server lives in this process, so a synchronous
// spawn blocks the event loop that has to answer the gate's own fetches, and
// every case deadlocks. Measured the hard way.
//
// The two PASS cases are as load-bearing as the failures. A gate that reds when
// somebody re-wraps a header or upper-cases a directive name is a gate that
// gets switched off, and CSP3 says directive names are case-insensitive.

import { createServer } from "node:http";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const run = promisify(execFile);
const HERE = dirname(fileURLToPath(import.meta.url));
const GATE = join(HERE, "csp-gate.mjs");

/** The policy /system-card is supposed to serve, as one header value. */
const GOOD = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const CASES = [
  ["the served policy is the expected one", GOOD, "PASS"],
  ["connect-src widened to *", GOOD.replace("connect-src 'self'", "connect-src *"), "FAIL"],
  ["frame-ancestors deleted (clickjacking control)", GOOD.replace("; frame-ancestors 'none'", ""), "FAIL"],
  ["form-action widened to *", GOOD.replace("form-action 'self'", "form-action *"), "FAIL"],
  ["script-src granted 'unsafe-inline'", GOOD.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'"), "FAIL"],
  ["default-src deleted", GOOD.replace("default-src 'self'; ", ""), "FAIL"],
  ["an unreviewed directive appended", `${GOOD}; report-uri https://example.invalid/r`, "FAIL"],
  ["re-wrapped: extra spaces and a trailing semicolon", `${GOOD.replace(/; /g, ";   ")};`, "PASS"],
  ["directive names upper-cased (CSP3 says names are case-insensitive)",
    GOOD.replace(/(^|; )([a-z-]+) /g, (_m, sep, name) => sep + name.toUpperCase() + " "), "PASS"],
];

let bad = 0;

for (const [label, policy, expected] of CASES) {
  const server = createServer((req, res) => {
    const headers = { "Content-Type": "text/html" };
    // Only /system-card carries this policy. The gate's nonced and redirect
    // routes are expected to fail against a stub; their lines are ignored
    // below, which is why this control reads per-route output and not the
    // gate's exit code.
    if (req.url.startsWith("/system-card")) headers["Content-Security-Policy"] = policy;
    res.writeHead(200, headers);
    res.end("<html><body>system card</body></html>");
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();

  let stdout = "";
  try {
    ({ stdout } = await run(process.execPath, [GATE, `http://127.0.0.1:${port}`]));
  } catch (err) {
    stdout = err.stdout ?? "";   // the gate exits 1 whenever it reports a problem
  }
  await new Promise((resolve) => server.close(resolve));

  const lines = stdout.split("\n").filter((l) => l.includes("/system-card"));
  if (lines.length === 0) {
    console.log(`  BAD  ${label}\n       the gate said nothing about /system-card — it never ran the check`);
    bad += 1;
    continue;
  }
  const got = lines.some((l) => l.trim().startsWith("FAIL")) ? "FAIL" : "PASS";
  if (got === expected) {
    console.log(`  ok   ${label}  (${got})`);
  } else {
    bad += 1;
    console.log(`  BAD  ${label}\n       expected the gate to ${expected}, it ${got}`);
  }
}

console.log(
  bad === 0
    ? `\nPASS — csp-gate answered all ${CASES.length} cases correctly.`
    : `\nFAIL — ${bad} case(s) the gate got wrong.`,
);
process.exit(bad === 0 ? 0 : 1);
