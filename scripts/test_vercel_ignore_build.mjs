#!/usr/bin/env node
//
// Tests for vercel-ignore-build.sh — the Vercel "Ignored Build Step" guard that
// decides whether EITHER Vercel project deploys at all.
//
// Run:  node --test scripts/test_vercel_ignore_build.mjs
//
// Why this file exists (issue #235): the script's failure mode is silence. A
// wrong exit code does not fail a build, does not post a status and does not
// turn anything red — it just means a merge produces no deployment while the
// repo goes on looking green. Every other gate here announces itself when it
// breaks; this one's breakage is indistinguishable from "nothing needed to
// deploy".
//
// ---------------------------------------------------------------------------
// THE EXIT CODES ARE INVERTED. Read vercel-ignore-build.sh's own header first.
// ---------------------------------------------------------------------------
//
//     exit 0  ->  SKIP the build (deployment is marked CANCELED)
//     exit >=1 ->  BUILD as normal
//
// So `verdict()` below is not a typo, and a *crash* (127, 128) also reads as
// BUILD. That is the script's deliberate fail-open contract — which is exactly
// why every BUILD expectation in this file must also name the log line it
// expects on stderr. Without that, a syntax error in the script would satisfy
// half these tests. `expect()` makes the reason mandatory, not optional.
//
// ---------------------------------------------------------------------------
// FIXTURES ARE REAL COMMITS FROM THIS REPOSITORY.
// ---------------------------------------------------------------------------
//
// The script reads the commit under test from VERCEL_GIT_COMMIT_SHA rather than
// from HEAD specifically so it can be aimed at history without a deployment;
// its own comments say so. So these are not synthetic diffs — they are the
// commits whose real path lists exercise each arm of the allowlist, including
// the two commits from #174 that merged green and never reached production.
//
// This requires FULL history: `actions/checkout` must run with `fetch-depth: 0`
// (see .github/workflows/vercel-ignore-build.yml). If the fixtures are not
// present the suite FAILS rather than skips — a skipped suite is green, and
// dead-but-green coverage is the defect this file was written to end.
//
// No dependencies: node:test and node:assert ship with Node. Nothing to
// install, nothing to keep in a lockfile, no reason for anyone to make this
// step optional.

import { test, before } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync, existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

const REPO = spawnSync('git', ['rev-parse', '--show-toplevel'], {
  cwd: HERE,
  encoding: 'utf8',
}).stdout.trim();

if (!REPO) {
  console.error('not inside a git checkout; the fixtures are commits, so there is nothing to test');
  process.exit(1);
}

// Overridable so the negative control (scripts/negative_control_ignore_build.mjs)
// can aim this same suite at a deliberately broken copy of the script. The copy
// must live inside the repository: the script does `cd "$(dirname "$0")"` and
// then resolves the repo root from there, so a copy in /tmp would take the
// "no git checkout here; building" arm and every case would pass for the wrong
// reason.
const SCRIPT = process.env.IGNORE_BUILD_SCRIPT
  ? resolve(process.env.IGNORE_BUILD_SCRIPT)
  : join(REPO, 'vercel-ignore-build.sh');

const SKIP = 'SKIP';
const BUILD = 'BUILD';

// ---------------------------------------------------------------------------
// Fixtures. Full SHAs, pinned: an abbreviation can become ambiguous, and a
// fixture that silently resolves to a different commit is a test that silently
// stops testing. `base` is what Vercel would put in VERCEL_GIT_PREVIOUS_SHA.
// `touches` is asserted independently of the script in "fixtures are intact"
// below, so a rewritten history is caught as a fixture failure rather than
// misreported as a script regression.
// ---------------------------------------------------------------------------
const C = {
  // Backend only: README + backend/jobtracker/cloud/gmail_oauth.py + backend tests.
  backendOnly: {
    sha: '70a81acb341911b481c762652f89211e154b2a6d',
    base: 'f18aaf56e2935d40b630742322cd435b38d2de97',
    touches: ['backend/jobtracker/'],
    absent: ['apps/web/'],
    subject: 'fix(gmail): only hold the cursor on the branch that can step it',
  },
  // Web only. This is one of the two commits in #174 that merged green and
  // produced no production deployment. It is here as a fixture *and* as
  // evidence: the guard's answer for it is BUILD, so the guard did not cause
  // that miss.
  webOnly: {
    sha: '60fcec28bcc54eae2248ba885d8e9f06f36bd31d',
    base: '939448512bd7785f555ad34431343fccae2e33db',
    touches: ['apps/web/'],
    absent: ['backend/'],
    subject: 'fix(dashboard): dock the row detail from lg (#171)',
  },
  // The other #174 commit, same reason.
  webOnly174: {
    sha: '12b8aeee511414c48bb75f722572b9ead1280acc',
    base: 'd3765b22b63701c15bf0aba5cceedea409cfc368',
    touches: ['apps/web/'],
    absent: ['backend/'],
    subject: 'feat(dashboard): the pulse band opens into day-level detail (#165)',
  },
  // Both: backend/jobtracker/cloud/*.py and apps/web/components/*.
  both: {
    sha: '43da78f7c978a7b373871aeb1ccb52373c4eeb15',
    base: '8e3c1ff740fdf0170135fa0f3c5e56a999815b0d',
    touches: ['backend/jobtracker/', 'apps/web/'],
    absent: [],
    subject: 'fix(identity): ask before a near-miss employer name opens a row',
  },
  // Neither: README.md, docs/DEPLOYMENT.md, scripts/readme_facts.py.
  neither: {
    sha: '23f56994d87eea5c4e06c027e411d53ea0db23c0',
    base: 'b955238bf9fabeb53c0826f99dffda94cb589eb6',
    // Its grandparent. b955238 (the commit in between) is 9 files under
    // apps/web, so base..head over the WIDE window must build the web app even
    // though the tip commit alone touches nothing. This is the scenario the
    // script's "WHY THE BASE IS NOT JUST HEAD^" section describes, with real
    // commits instead of a hypothetical.
    grandparent: '77796123a316489791c6ecfffe3d46d0dd261135',
    touches: ['docs/'],
    absent: ['apps/web/', 'backend/'],
    subject: 'docs(ci): correct the Frontend CI toolchain (#220)',
  },
  // An empty commit — `chore(deploy): re-run production deploys after the
  // Vercel 24h window`. Zero files changed. Both projects must skip.
  empty: {
    sha: 'c3d55062c4f6f64f930471d83846bdc0604020c7',
    base: 'caf8e00326a6869641fbbb7d0ac73c4f018003d7',
    touches: [],
    absent: ['apps/web/', 'backend/'],
    subject: 'chore(deploy): re-run production deploys',
  },
  // Touches ONLY vercel-ignore-build.sh — the guard itself.
  guardOnly: {
    sha: '2940cee53cebffb637b6420eeddd10da68abbd34',
    base: 'd4f083644c1579689019e0f18b56282759c3f910',
    touches: ['vercel-ignore-build.sh'],
    absent: ['apps/web/', 'backend/'],
    subject: 'fix(ci): build when the ignore step cannot resolve the base',
  },
  // One file: api/index.py, the Vercel Python entrypoint. The `api` entry in
  // the allowlist has no other commit in this repository's history, so without
  // this fixture it could be deleted from the allowlist and nothing would
  // notice — the entrypoint of the whole cloud function would stop deploying.
  apiEntrypointOnly: {
    sha: 'dc1711e0732cf895a2a7e6a23a41379cfa13e318',
    base: '8d8d375eb4b08219a045008465d4c7b61c193d3d',
    touches: ['api/'],
    absent: ['apps/web/', 'backend/'],
    subject: 'feat(vercel): add api/index.py Vercel serverless entrypoint',
  },
  // One file: the ROOT requirements.txt, which is what Vercel pip-installs.
  // backend/requirements.txt is deliberately a different, much heavier file and
  // is NOT an input — which is why this fixture matters: the two are easy to
  // confuse and only one of them can change the deployed function.
  rootRequirementsOnly: {
    sha: 'da4555e428574cc70668078c1fb5c0fc6e214ff3',
    base: '0195f4d2e5257829e7dc7c40fd76750e25c60c57',
    touches: ['requirements.txt'],
    absent: ['apps/web/', 'backend/'],
    subject: 'chore(deps): update sqlalchemy requirement (#125)',
  },
  // One file: .vercelignore — the only entry in BOTH allowlists, and the one
  // with the worst history in the file. It is read from the repository root for
  // every project whatever its Root Directory, and this is literally the commit
  // that undid a blanket `apps` entry after it deleted apps/web before the web
  // build could run and every push failed with NEXT_NO_VERSION.
  vercelignoreOnly: {
    sha: 'fd34a7081cea228cd11193c25d86beeb4664fcb3',
    base: 'd2ac5b01b2035076b1c7c373f4c9989af1e8e352',
    touches: ['.vercelignore'],
    absent: ['apps/web/', 'backend/'],
    subject: 'fix(deploy): stop excluding the web app from its own build',
  },
  // vercel-ignore-build.sh + vercel.json. vercel.json is in the api allowlist
  // and deliberately not in web's.
  guardAndApiConfig: {
    sha: 'e4c72f04701f9d5ca3579af2154f32884b63b8c0',
    base: '23aba9d26b5dd2b67e9bac425e3429e1cd3b3d1d',
    touches: ['vercel.json'],
    absent: ['apps/web/', 'backend/'],
    subject: 'build(vercel): stop creating api preview deployments (#189)',
  },
};

// A 40-hex string that is not an object in any clone of this repository.
const UNKNOWN_SHA = 'dead0000dead0000dead0000dead0000dead0000';

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

/**
 * Invoke the guard with a controlled environment.
 *
 * Every VERCEL_* variable inherited from the ambient environment is stripped
 * first. On a Vercel build these are all set, and a test that accidentally read
 * a real one would pass or fail for reasons that have nothing to do with its
 * fixture.
 *
 * GIT_ALLOW_PROTOCOL is pinned to an unusable value so the script's best-effort
 * `git fetch --depth=1 origin <sha>` cannot reach the network. That reproduces
 * one of the exact conditions its header names ("a build container may have no
 * network") and keeps the suite hermetic and fast. It constrains the
 * environment the script runs in; it does not touch what is asserted about it.
 */
function run(project, env = {}) {
  const clean = Object.fromEntries(
    Object.entries(process.env).filter(([k]) => !k.startsWith('VERCEL_')),
  );
  const args = project === undefined ? [SCRIPT] : [SCRIPT, project];
  const result = spawnSync('bash', args, {
    cwd: REPO,
    encoding: 'utf8',
    env: { ...clean, GIT_ALLOW_PROTOCOL: 'none-for-tests', GIT_TERMINAL_PROMPT: '0', ...env },
  });
  if (result.error) throw result.error;
  return {
    code: result.status,
    verdict: result.status === 0 ? SKIP : BUILD,
    stderr: result.stderr ?? '',
  };
}

/**
 * Assert a verdict AND the reason the script gave for it.
 *
 * The reason is not decoration. Because any exit code >= 1 means BUILD, a
 * script that fails to parse exits 2 and "passes" every BUILD assertion in this
 * file. Requiring a log substring is what makes those assertions able to fail
 * for the right reason.
 */
function expect(project, env, wanted, reason) {
  const got = run(project, env);
  const detail = `\n  exit=${got.code} verdict=${got.verdict}\n  stderr: ${got.stderr.trim() || '(empty)'}`;
  assert.equal(got.verdict, wanted, `expected ${wanted}, got ${got.verdict}${detail}`);
  assert.ok(
    got.stderr.includes(reason),
    `expected stderr to contain ${JSON.stringify(reason)}${detail}`,
  );
  return got;
}

/** Env for a production deployment of `fixture`, as Vercel would supply it. */
function prod(fixture, overrides = {}) {
  return {
    VERCEL_ENV: 'production',
    VERCEL_GIT_COMMIT_REF: 'main',
    VERCEL_GIT_COMMIT_SHA: fixture.sha,
    VERCEL_GIT_PREVIOUS_SHA: fixture.base,
    ...overrides,
  };
}

function changedFiles(base, head) {
  const out = spawnSync('git', ['diff', '--name-only', base, head], {
    cwd: REPO,
    encoding: 'utf8',
  });
  assert.equal(out.status, 0, `git diff ${base}..${head} failed: ${out.stderr}`);
  return out.stdout.split('\n').filter(Boolean);
}

// ---------------------------------------------------------------------------
// 0. Preconditions. These must FAIL, never skip.
// ---------------------------------------------------------------------------

before(() => {
  assert.ok(existsSync(SCRIPT), `guard script not found at ${SCRIPT}`);
});

test('the whole fixture set is present in this clone', () => {
  const missing = [];
  for (const [name, f] of Object.entries(C)) {
    for (const sha of [f.sha, f.base, f.grandparent].filter(Boolean)) {
      const ok = spawnSync('git', ['cat-file', '-e', `${sha}^{commit}`], { cwd: REPO });
      if (ok.status !== 0) missing.push(`${name}: ${sha}`);
    }
  }
  assert.deepEqual(
    missing,
    [],
    'fixture commits are missing from this clone. These tests are worthless ' +
      'without them, so this fails rather than skipping. In CI the cause is ' +
      'almost always a shallow checkout: actions/checkout needs fetch-depth: 0.\n  ' +
      missing.join('\n  '),
  );
});

test('fixtures still touch what they claim to touch', () => {
  // Derived from git, not from the guard, so a rebase or a mis-pasted SHA is
  // reported as a broken fixture instead of a script regression.
  for (const [name, f] of Object.entries(C)) {
    const files = changedFiles(f.base, f.sha);
    for (const prefix of f.touches) {
      assert.ok(
        files.some((p) => p.startsWith(prefix)),
        `fixture ${name} (${f.subject}) no longer touches ${prefix}: ${files.join(', ')}`,
      );
    }
    for (const prefix of f.absent) {
      assert.ok(
        !files.some((p) => p.startsWith(prefix)),
        `fixture ${name} (${f.subject}) unexpectedly touches ${prefix}: ${files.join(', ')}`,
      );
    }
  }
  assert.deepEqual(changedFiles(C.empty.base, C.empty.sha), [], 'the empty fixture is not empty');
});

// ---------------------------------------------------------------------------
// 1. The allowlist matrix. One commit, two projects, two independent answers.
// ---------------------------------------------------------------------------

test('backend-only commit: api builds', () => {
  expect('api', prod(C.backendOnly), BUILD, 'api: changes found');
});

test('backend-only commit: web skips', () => {
  expect('web', prod(C.backendOnly), SKIP, 'web: no changes in apps/web .vercelignore');
});

test('web-only commit: web builds', () => {
  expect('web', prod(C.webOnly), BUILD, 'web: changes found');
});

test('web-only commit: api skips', () => {
  expect('api', prod(C.webOnly), SKIP, 'api: no changes in');
});

test('commit touching both: api builds', () => {
  expect('api', prod(C.both), BUILD, 'api: changes found');
});

test('commit touching both: web builds', () => {
  expect('web', prod(C.both), BUILD, 'web: changes found');
});

// Decided deliberately, not by default: a commit that touches only README.md,
// docs/ and scripts/ changes nothing either deployment reads, so both skip.
// This is the case the guard exists for — it is what stopped four production
// web builds in an hour from GitHub Actions bumps and a Python dependency the
// cloud function never installs. The cost of being wrong here is one stale
// docs change not being republished, which is nothing, because neither
// deployment serves docs/.
test('docs / scripts-only commit: api skips', () => {
  expect('api', prod(C.neither), SKIP, 'api: no changes in');
});

test('docs / scripts-only commit: web skips', () => {
  expect('web', prod(C.neither), SKIP, 'web: no changes in');
});

test('an empty commit skips both projects', () => {
  expect('api', prod(C.empty), SKIP, 'api: no changes in');
  expect('web', prod(C.empty), SKIP, 'web: no changes in');
});

// ---------------------------------------------------------------------------
// 2. Edges of the allowlist itself.
// ---------------------------------------------------------------------------

// Pinned deliberately: the guard is not a build input for either project, so a
// commit that changes only the guard deploys nothing. That is correct — neither
// deployment reads this file at runtime, Vercel re-reads it from the commit
// being deployed on the NEXT push, and adding it to both allowlists would mean
// every edit to it costs two deployments. The consequence to know is that a
// change to the guard is not exercised in production until some other commit
// triggers a build.
test('a commit touching only the guard script deploys neither project', () => {
  expect('api', prod(C.guardOnly), SKIP, 'api: no changes in');
  expect('web', prod(C.guardOnly), SKIP, 'web: no changes in');
});

// vercel.json carries the api function config, headers and CSP, so it is an api
// build input. It is deliberately NOT a web input: Vercel reads configuration
// from the Root Directory, and the web project's Root Directory is apps/web.
test('root vercel.json is an api input and not a web input', () => {
  expect('api', prod(C.guardAndApiConfig), BUILD, 'api: changes found');
  expect('web', prod(C.guardAndApiConfig), SKIP, 'web: no changes in');
});

// One test per remaining allowlist entry, so that every entry has something
// holding it in place. Before these existed, `api`, `requirements.txt` and
// `.vercelignore` could each be deleted from the allowlist with the suite still
// green — the negative control found that, which is what it is for.
test('api/index.py alone builds the api and not the web app', () => {
  expect('api', prod(C.apiEntrypointOnly), BUILD, 'api: changes found');
  expect('web', prod(C.apiEntrypointOnly), SKIP, 'web: no changes in');
});

test('the root requirements.txt alone builds the api and not the web app', () => {
  expect('api', prod(C.rootRequirementsOnly), BUILD, 'api: changes found');
  expect('web', prod(C.rootRequirementsOnly), SKIP, 'web: no changes in');
});

// The only entry in both allowlists, and the only fixture here that must build
// both projects off a single file.
test('.vercelignore alone builds BOTH projects', () => {
  expect('api', prod(C.vercelignoreOnly), BUILD, 'api: changes found');
  expect('web', prod(C.vercelignoreOnly), BUILD, 'web: changes found');
});

// ---------------------------------------------------------------------------
// 3. The window. Why the base is VERCEL_GIT_PREVIOUS_SHA and not HEAD^.
// ---------------------------------------------------------------------------

// The narrow answer, stated so the pair below is a contrast and not a claim.
test('over a one-commit window the docs-only tip skips the web build', () => {
  expect('web', prod(C.neither), SKIP, 'web: no changes in');
});

// The same tip commit, measured over the window Vercel actually supplies: the
// last commit this project DEPLOYED. b955238 sits inside it with 9 files under
// apps/web. A HEAD^-only guard skips here and the web change never ships. This
// is the regression the script's header describes; it is real commits, not a
// hypothetical, and it is the case a naive "diff HEAD^ HEAD" rewrite would
// reintroduce silently.
test('over the real deployed-since window the same tip builds the web app', () => {
  // Establish from git, independently of the guard, that the two windows really
  // differ — otherwise this test and the one above could both be measuring the
  // same thing and agreeing for no reason.
  const narrow = changedFiles(C.neither.base, C.neither.sha);
  const wide = changedFiles(C.neither.grandparent, C.neither.sha);
  assert.ok(!narrow.some((p) => p.startsWith('apps/web/')), 'the narrow window should be web-free');
  assert.ok(wide.some((p) => p.startsWith('apps/web/')), 'the wide window should carry web changes');

  expect('web', prod(C.neither, { VERCEL_GIT_PREVIOUS_SHA: C.neither.grandparent }), BUILD,
    'web: changes found');
});

// ---------------------------------------------------------------------------
// 4. Arguments. The guard must never skip a project it does not recognise.
// ---------------------------------------------------------------------------

test('an unknown project name builds', () => {
  expect('jobtracker-mobile', prod(C.neither), BUILD, "unknown project 'jobtracker-mobile'");
});

test('no project argument at all builds', () => {
  expect(undefined, prod(C.neither), BUILD, "unknown project ''");
});

test('an empty project argument builds', () => {
  expect('', prod(C.neither), BUILD, "unknown project ''");
});

// KNOWN ORDERING, pinned so a change to it is a decision rather than an
// accident: the Dependabot check runs BEFORE the project `case`, so an
// unrecognised project on a Dependabot branch skips instead of building. It is
// the one place the guard's fail-open rule does not hold.
//
// Left as-is rather than "fixed": reaching this branch at all means Vercel
// created a deployment for a Dependabot ref that `git.deploymentEnabled` was
// supposed to prevent, and the only projects that exist are api and web. The
// cost of the ordering is a skipped Dependabot deployment, which is what the
// branch is for. If a third project is ever added, move the `case "$project"`
// arm above the Dependabot check and change this test with it.
test('unknown project on a Dependabot branch skips — the one non-fail-open path', () => {
  expect(
    'jobtracker-mobile',
    prod(C.neither, { VERCEL_GIT_COMMIT_REF: 'dependabot/npm_and_yarn/apps/web/next-16.1.2' }),
    SKIP,
    'is a Dependabot branch; skipping',
  );
});

// ---------------------------------------------------------------------------
// 5. Dependabot.
// ---------------------------------------------------------------------------

// A real three-segment Dependabot ref. `dependabot/*` in a minimatch pattern
// does not match this — `*` does not cross `/` — which is why one of the two
// keys this backstop replaced never worked. The prefix match here is on the
// whole ref and is not glob-based, so it does.
test('a Dependabot branch skips even when the commit touches the project', () => {
  const ref = 'dependabot/npm_and_yarn/apps/web/eslint-config-next-16.1.2';
  expect('web', prod(C.webOnly, { VERCEL_ENV: 'preview', VERCEL_GIT_COMMIT_REF: ref }), SKIP,
    `branch ${ref} is a Dependabot branch; skipping`);
  expect('api', prod(C.backendOnly, { VERCEL_ENV: 'preview', VERCEL_GIT_COMMIT_REF: ref }), SKIP,
    'is a Dependabot branch; skipping');
});

test('a branch merely containing "dependabot" is not a Dependabot branch', () => {
  // The match is a prefix on the whole ref, so this must be measured normally.
  expect('web', prod(C.webOnly, { VERCEL_GIT_COMMIT_REF: 'fix/dependabot-noise' }), BUILD,
    'web: changes found');
});

// ---------------------------------------------------------------------------
// 6. Fail-open. Every uncertain path must BUILD.
// ---------------------------------------------------------------------------

test('a head commit outside the clone builds', () => {
  expect('web', prod(C.webOnly, { VERCEL_GIT_COMMIT_SHA: UNKNOWN_SHA }), BUILD,
    `head ${UNKNOWN_SHA} is not in this clone; building`);
});

// The regression that motivated this arm: deployment dpl_2oExy742yPoteHNp4PHxbKXHJ6za
// narrowed an unresolvable wide base to HEAD^ and answered a question nobody
// asked, with a confident SKIP. A supplied-but-unreadable base means the window
// is known to be wider than one commit and unmeasurable, so it builds.
//
// The fixture is the DOCS-ONLY commit, chosen so the two behaviours disagree.
// Narrowing it to HEAD^ answers SKIP, because its tip touches nothing — which
// is precisely the confident wrong answer the real deployment gave. Aiming this
// test at a commit that builds either way would let a narrowing regression pass
// unnoticed; the negative control caught exactly that and this is the fix.
test('a supplied base that cannot be resolved builds rather than narrowing to HEAD^', () => {
  const got = expect('web', prod(C.neither, { VERCEL_GIT_PREVIOUS_SHA: UNKNOWN_SHA }), BUILD,
    `cannot resolve supplied base ${UNKNOWN_SHA}`);
  assert.ok(
    !got.stderr.includes('no changes in'),
    `an unreadable wide window must not be answered from the narrow one:\n${got.stderr}`,
  );
  // The fetch must be ATTEMPTED, not skipped: widening the clone by one commit
  // is what makes the correct window readable in a real --depth=10 checkout.
  assert.ok(
    got.stderr.includes('is outside the shallow clone; fetching it'),
    `the one-commit widening fetch should be attempted first:\n${got.stderr}`,
  );
});

test('no base supplied on a production deploy falls back to HEAD^', () => {
  const env = prod(C.webOnly);
  delete env.VERCEL_GIT_PREVIOUS_SHA;
  const got = expect('web', env, BUILD, 'web: changes found');
  assert.ok(
    got.stderr.includes('no previous deployment supplied; falling back to HEAD^'),
    `expected the documented production fallback:\n${got.stderr}`,
  );
  // And the fallback must still answer per-project rather than blanket-building.
  const api = { ...env };
  expect('api', api, SKIP, 'api: no changes in');
});

// A preview with no supplied base is measured against the DEFAULT BRANCH TIP.
//
// This test used to assert the opposite — `no usable base commit; building` —
// because a branch's first preview built unconditionally. That was not a
// contract worth defending: three of the seven web previews of 2026-08-27/28
// were full Next.js builds of branches whose entire diff is Python. The script
// header records the measurement. A test that asserts the old answer would now
// defend the waste, so it asserts the new one.
//
// `HEAD^` must STILL not appear on a preview. That half of the old contract is
// intact and is the half that had a real reason: a branch's first push can
// carry many commits and the newest one is not the window.
test('no base supplied on a preview is measured against the default branch tip', () => {
  const env = prod(C.neither, { VERCEL_ENV: 'preview' });
  delete env.VERCEL_GIT_PREVIOUS_SHA;
  const got = expect('web', env, BUILD, 'measuring against main tip');
  assert.ok(
    !got.stderr.includes('falling back to HEAD^'),
    `previews must not narrow to HEAD^:\n${got.stderr}`,
  );
});

// The arm is entered on VERCEL_ENV=preview and on nothing else. "Not
// production" is a wider door than this deserves: an unset or unrecognised
// VERCEL_ENV means the build's shape is not one we recognise, and the script's
// fail-open doctrine says build. Without this test the condition can be widened
// back to `!= 'production'` and every assertion in this file stays green.
test('an unrecognised VERCEL_ENV does not take the preview path', () => {
  const env = prod(C.neither, { VERCEL_ENV: 'development' });
  delete env.VERCEL_GIT_PREVIOUS_SHA;
  const got = expect('web', env, BUILD, 'no usable base commit; building');
  assert.ok(
    !got.stderr.includes('measuring against'),
    `only a preview may be measured against the default branch:\n${got.stderr}`,
  );
});

test('no base and no VERCEL_ENV builds', () => {
  const env = prod(C.neither);
  delete env.VERCEL_GIT_PREVIOUS_SHA;
  delete env.VERCEL_ENV;
  expect('web', env, BUILD, 'no usable base commit; building');
});

// ---------------------------------------------------------------------------
// 6b. A preview's first build, measured. THE SKIP IS THE POINT.
// ---------------------------------------------------------------------------
//
// Everything in section 6 above asserts a BUILD, and a BUILD is what this
// script does when anything at all goes wrong — a syntax error exits 2 and
// reads as BUILD. So none of it can distinguish "the default-branch window was
// computed and it contained web changes" from "the new code never ran". The
// only assertion that can is a SKIP, and a SKIP needs a branch whose diff
// against the default branch is empty for one project and not the other.
//
// The repository's own history cannot supply that fixture. The window is the
// default branch's TIP, which moves; any commit pinned here as "no web changes
// since main" stops being one the next time a web commit lands on main. So
// these cases build their own three-commit repository instead. It is synthetic
// on purpose: the script reads nothing but the path names in a diff, and a
// repository that exists only to hold those path names cannot decay.
//
// The script is COPIED IN rather than invoked from this checkout, for the same
// reason the negative control copies it: `cd "$(dirname "$0")"` means the
// script finds its repository from its own location, so a script left outside
// would take the "no git checkout here; building" arm and every case below
// would pass without measuring anything.

/** A throwaway repository whose only content is path names. */
function scratchRepo({ withOriginMain }) {
  const dir = mkdtempSync(join(tmpdir(), 'ignore-build-'));
  const git = (...args) => {
    const r = spawnSync('git', ['-c', 'core.hooksPath=', '-c', 'user.name=t',
      '-c', 'user.email=t@example.invalid', '-C', dir, ...args], { encoding: 'utf8' });
    assert.equal(r.status, 0, `git ${args.join(' ')} failed: ${r.stderr}`);
    return r.stdout.trim();
  };
  const write = (rel, body) => {
    mkdirSync(join(dir, dirname(rel)), { recursive: true });
    writeFileSync(join(dir, rel), body);
  };

  git('init', '--quiet', '--initial-branch=main');
  for (const f of ['apps/web/x.ts', 'backend/jobtracker/y.py', 'docs/z.md', '.vercelignore']) {
    write(f, 'base\n');
  }
  git('add', '-A');
  git('commit', '--quiet', '-m', 'base');
  const base = git('rev-parse', 'HEAD');

  // The default branch as a build container sees it: a remote-tracking ref.
  // Omitting it is the unreachable-default-branch case, which must fail open.
  if (withOriginMain) git('update-ref', 'refs/remotes/origin/main', base);

  // Three branches off it, each touching exactly one project's inputs.
  const branch = (name, file) => {
    git('checkout', '--quiet', '-b', name, base);
    write(file, 'changed\n');
    git('add', '-A');
    git('commit', '--quiet', '-m', name);
    return git('rev-parse', 'HEAD');
  };
  const heads = {
    backendOnly: branch('t/backend', 'backend/jobtracker/y.py'),
    webOnly: branch('t/web', 'apps/web/x.ts'),
    neither: branch('t/docs', 'docs/z.md'),
  };

  // Two commits in one push, the oldest of which carries the web change. This
  // is the scenario `HEAD^` gets wrong, and the reason the window is not it.
  git('checkout', '--quiet', '-b', 't/two', base);
  write('apps/web/x.ts', 'changed first\n');
  git('add', '-A');
  git('commit', '--quiet', '-m', 'web change');
  write('docs/z.md', 'changed second\n');
  git('add', '-A');
  git('commit', '--quiet', '-m', 'docs change on top');
  heads.twoCommits = git('rev-parse', 'HEAD');

  writeFileSync(join(dir, 'vercel-ignore-build.sh'), readFileSync(SCRIPT));
  return { dir, base, heads };
}

/** Run the COPY inside `repo.dir`, as a preview with nothing supplied. */
function firstPreview(repo, project, sha, overrides = {}) {
  const clean = Object.fromEntries(
    Object.entries(process.env).filter(([k]) => !k.startsWith('VERCEL_')),
  );
  const r = spawnSync('bash', [join(repo.dir, 'vercel-ignore-build.sh'), project], {
    cwd: repo.dir,
    encoding: 'utf8',
    env: {
      ...clean,
      GIT_ALLOW_PROTOCOL: 'none-for-tests',
      GIT_TERMINAL_PROMPT: '0',
      VERCEL_ENV: 'preview',
      VERCEL_GIT_COMMIT_REF: 't/branch',
      VERCEL_GIT_COMMIT_SHA: sha,
      ...overrides,
    },
  });
  if (r.error) throw r.error;
  return { code: r.status, verdict: r.status === 0 ? SKIP : BUILD, stderr: r.stderr ?? '' };
}

function expectFirst(repo, project, sha, wanted, reason) {
  const got = firstPreview(repo, project, sha);
  const detail = `\n  exit=${got.code} verdict=${got.verdict}\n  stderr: ${got.stderr.trim() || '(empty)'}`;
  assert.equal(got.verdict, wanted, `expected ${wanted}, got ${got.verdict}${detail}`);
  assert.ok(got.stderr.includes(reason),
    `expected stderr to contain ${JSON.stringify(reason)}${detail}`);
  return got;
}

test("a branch's first preview skips the project it cannot change", () => {
  const repo = scratchRepo({ withOriginMain: true });
  try {
    // The measured case: three of the seven web previews of 2026-08-27/28 were
    // this exact shape and each cost a full Next.js build.
    expectFirst(repo, 'web', repo.heads.backendOnly, SKIP, 'web: no changes in');
    // Directional control on the SAME commit: the project it CAN change builds.
    expectFirst(repo, 'api', repo.heads.backendOnly, BUILD, 'api: changes found');

    // And the mirror image, so a guard that simply always skips web is caught.
    expectFirst(repo, 'web', repo.heads.webOnly, BUILD, 'web: changes found');
    expectFirst(repo, 'api', repo.heads.webOnly, SKIP, 'api: no changes in');

    // Neither project's inputs: both skip.
    expectFirst(repo, 'web', repo.heads.neither, SKIP, 'web: no changes in');
    expectFirst(repo, 'api', repo.heads.neither, SKIP, 'api: no changes in');
  } finally {
    rmSync(repo.dir, { recursive: true, force: true });
  }
});

test("a first preview's window is the whole branch, not its newest commit", () => {
  const repo = scratchRepo({ withOriginMain: true });
  try {
    // Two commits pushed at once: apps/web changed in the FIRST, docs in the
    // second. `git diff HEAD^ HEAD` sees only the docs commit and would skip
    // the web build entirely — the failure the script's header calls out. The
    // default-branch window sees both.
    const got = expectFirst(repo, 'web', repo.heads.twoCommits, BUILD, 'web: changes found');
    assert.ok(!got.stderr.includes('HEAD^'),
      `a preview must not narrow to HEAD^:\n${got.stderr}`);
  } finally {
    rmSync(repo.dir, { recursive: true, force: true });
  }
});

test('an unreachable default branch builds rather than guessing', () => {
  // No refs/remotes/origin/main and no network: the fetch cannot answer, so
  // there is no window. Fail open. Without this the arm could resolve an empty
  // base and diff against nothing, which git reports as no difference — a
  // silent SKIP of every first preview.
  const repo = scratchRepo({ withOriginMain: false });
  try {
    const got = expectFirst(repo, 'web', repo.heads.webOnly, BUILD, 'no usable base commit');
    assert.ok(got.stderr.includes('main is unreachable'),
      `the reason must name the unresolved default branch:\n${got.stderr}`);
  } finally {
    rmSync(repo.dir, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// 7. The redeploy blind spot (#235, comment of 2026-08-14).
// ---------------------------------------------------------------------------
//
// `vercel redeploy` of the current production deployment sets
// VERCEL_GIT_PREVIOUS_SHA to the commit being redeployed, so the guard diffs a
// commit against itself, finds nothing, and skips. Observed on deployment
// jobtracker-2g3prxucv while activating SUPABASE_SERVICE_ROLE_KEY: the
// deployment went straight to CANCELED and the variable stayed inert.
//
// Pinned as CORRECT, deliberately. The guard answers exactly one question —
// "did this commit touch anything this project builds from" — and for a
// redeploy of an unchanged commit the honest answer is no. Making it guess
// otherwise would mean skipping nothing ever, which is the whole feature.
//
// The gap is that the question it asks is not the only reason a build is
// needed: Vercel injects environment variables at deploy time, so a new or
// changed variable needs a deployment that this guard has no way to see.
// DEPLOY.md now says so out loud. Do not "fix" this by making a same-SHA diff
// build — fix it at the point of use, with a code commit or a forced deploy.
test('a redeploy of an unchanged commit skips — an env-only change cannot build', () => {
  expect('web', prod(C.webOnly, { VERCEL_GIT_PREVIOUS_SHA: C.webOnly.sha }), SKIP,
    `between ${C.webOnly.sha} and ${C.webOnly.sha}; skipping`);
  expect('api', prod(C.backendOnly, { VERCEL_GIT_PREVIOUS_SHA: C.backendOnly.sha }), SKIP,
    'api: no changes in');
});

// ---------------------------------------------------------------------------
// 8. The wiring. A rename breaks deploys without touching the script.
// ---------------------------------------------------------------------------
//
// Nothing else in the repository would notice: neither vercel.json is imported
// by any build, and a missing ignoreCommand does not fail — Vercel just builds
// everything, which looks like success.

const WIRING = [
  {
    project: 'api',
    config: 'vercel.json',
    // Vercel runs the ignore command from the project's Root Directory.
    rootDirectory: '.',
    expected: 'bash vercel-ignore-build.sh api',
    deploymentEnabled: { '**': false, main: true },
    deploymentEnabledWhy:
      'The api takes no previews: nothing consumes one, and on 2026-08-13 they ' +
      'ate the whole daily allowance and blocked production for eleven hours. ' +
      'The "main": true key is LOAD-BEARING — precedence is not ' +
      'most-specific-wins ("if a branch matches multiple rules and at least one ' +
      'rule is true, a deployment will occur"), so "**": false alone would take ' +
      'production down with it and nothing would report an error.',
  },
  {
    project: 'web',
    config: 'apps/web/vercel.json',
    rootDirectory: 'apps/web',
    expected: 'bash ../../vercel-ignore-build.sh web',
    deploymentEnabled: { 'dependabot/**': false, 'dependabot/*': false },
    deploymentEnabledWhy:
      'The web project deliberately keeps its previews — a human looks at them ' +
      'before merge — so only Dependabot is filtered. Both keys are kept: `*` ' +
      'does not cross `/` in minimatch, so `dependabot/*` matches none of the ' +
      'real three-segment branch names and `dependabot/**` carries it alone.',
  },
];

for (const w of WIRING) {
  test(`${w.config} still delegates to the guard with the right argument`, () => {
    const cfg = JSON.parse(readFileSync(join(REPO, w.config), 'utf8'));
    assert.equal(
      cfg.ignoreCommand,
      w.expected,
      `${w.config} ignoreCommand changed. If that is intentional, the guard's ` +
        'allowlist and this test change with it — a wrong path here means the ' +
        'project deploys every commit, or none, with no error either way.',
    );
  });

  test(`${w.config}'s ignoreCommand resolves to a real file from ${w.rootDirectory}`, () => {
    const [, scriptPath, arg] = w.expected.split(/\s+/);
    const resolved = resolve(REPO, w.rootDirectory, scriptPath);
    assert.ok(existsSync(resolved), `${w.config} points at ${resolved}, which does not exist`);
    assert.equal(resolved, join(REPO, 'vercel-ignore-build.sh'));
    assert.equal(arg, w.project);
  });

  // `git.deploymentEnabled` is the more dangerous of the two keys and nothing
  // checked it. A wrong `ignoreCommand` wastes or skips a build but still
  // leaves a deployment record; a wrong `deploymentEnabled` stops the
  // deployment being CREATED, which leaves no record and no commit status at
  // all — the exact signature of the two commits in #174, and the hardest
  // possible thing to notice.
  test(`${w.config}'s git.deploymentEnabled is unchanged`, () => {
    const cfg = JSON.parse(readFileSync(join(REPO, w.config), 'utf8'));
    assert.deepEqual(cfg.git?.deploymentEnabled, w.deploymentEnabled, w.deploymentEnabledWhy);
  });

  test(`the guard recognises the project argument ${w.config} passes it`, () => {
    // Asserted by behaviour, not by grepping the `case` arms: a typo'd argument
    // takes the unknown-project path, which builds every commit forever and
    // reports nothing.
    const arg = w.expected.split(/\s+/)[2];
    const got = run(arg, prod(C.neither));
    assert.ok(
      !got.stderr.includes('unknown project'),
      `the guard does not recognise '${arg}':\n${got.stderr}`,
    );
  });
}
