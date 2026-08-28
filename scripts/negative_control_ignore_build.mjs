#!/usr/bin/env node
//
// Negative control for scripts/test_vercel_ignore_build.mjs.
//
// Run:  node scripts/negative_control_ignore_build.mjs
//
// A test suite written for a script whose entire problem is that nothing checks
// it must itself be checked. This one breaks vercel-ignore-build.sh in each of
// the specific ways it is worth being broken, runs the suite against the broken
// copy, and fails if the suite still passes.
//
// Every mutation below is a defect somebody could plausibly introduce: a
// swapped exit code, a "simplified" fail-open path, a dropped allowlist entry,
// the HEAD^ rewrite the script's header spends thirty lines arguing against.
// A mutation the suite survives is a hole in the suite, and this reports it as
// a failure with the mutation named.
//
// The mutant is written INSIDE the repository, at .ignore-build-mutant.sh. That
// is not arbitrary: the guard does `cd "$(dirname "$0")"` and resolves the repo
// root from there, so a copy in a temp directory would take the "no git
// checkout here; building" arm and every case would pass for the wrong reason —
// which would make this negative control itself a check that cannot fail.

import { spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = spawnSync('git', ['rev-parse', '--show-toplevel'], {
  cwd: HERE,
  encoding: 'utf8',
}).stdout.trim();

const SOURCE = join(REPO, 'vercel-ignore-build.sh');
const MUTANT = join(REPO, '.ignore-build-mutant.sh');
const SUITE = join(REPO, 'scripts', 'test_vercel_ignore_build.mjs');

/**
 * One mutation per entry of a project's allowlist: drop that entry and require
 * the suite to notice. `entries` is the exact text between the parentheses of
 * the `paths=(...)` line, so if the line is reformatted the anchor stops
 * matching and this reports a failure rather than silently mutating nothing.
 *
 * @param {string} project
 * @param {string} entries
 */
function allowlistMutations(project, entries) {
  const list = entries.split(' ');
  return list.map((entry) => ({
    name: `${entry} dropped from the ${project} allowlist`,
    find: `    paths=(${entries})`,
    replace: `    paths=(${list.filter((e) => e !== entry).join(' ')})`,
  }));
}

/**
 * @type {{name: string, find: string, replace: string}[]}
 * `find` must appear EXACTLY ONCE in the source. A mutation that no longer
 * applies is reported as a failure rather than quietly doing nothing — a
 * negative control that silently stops mutating is the same defect it exists
 * to catch.
 */
const MUTATIONS = [
  {
    name: 'exit codes swapped (SKIP=1, BUILD=0) — the inversion this script warns about',
    find: 'readonly SKIP=0\nreadonly BUILD=1',
    replace: 'readonly SKIP=1\nreadonly BUILD=0',
  },
  {
    name: 'the final verdict inverted: no changes now BUILDs, changes now SKIP',
    find:
      '  log "${project}: no changes in ${paths[*]} between ${base_sha} and ${head_sha}; skipping"\n' +
      '  exit "$SKIP"\n' +
      'fi\n' +
      '\n' +
      'log "${project}: changes found in ${paths[*]}; building"\n' +
      'exit "$BUILD"',
    replace:
      '  log "${project}: no changes in ${paths[*]} between ${base_sha} and ${head_sha}; skipping"\n' +
      '  exit "$BUILD"\n' +
      'fi\n' +
      '\n' +
      'log "${project}: changes found in ${paths[*]}; building"\n' +
      'exit "$SKIP"',
  },
  {
    name: 'unknown project silently skips instead of building',
    find: '    log "unknown project \'${project}\'; building"\n    exit "$BUILD"',
    replace: '    log "unknown project \'${project}\'; building"\n    exit "$SKIP"',
  },
  {
    name: 'an unresolvable supplied base narrows to HEAD^ instead of building',
    find:
      '    log "cannot resolve supplied base ${base_sha}; building rather than narrowing to HEAD^"\n' +
      '    exit "$BUILD"',
    replace:
      '    log "cannot resolve supplied base ${base_sha}; building rather than narrowing to HEAD^"\n' +
      '    base_sha="$(git rev-parse --verify -q "${head_sha}^" 2>/dev/null || true)"',
  },
  {
    name: 'the base is rewritten to HEAD^, discarding the deployed-since window',
    find: 'base_sha="${VERCEL_GIT_PREVIOUS_SHA:-}"',
    replace: 'base_sha="$(git rev-parse --verify -q "${head_sha}^" 2>/dev/null || true)"',
  },
  // The allowlist entries are mutated one at a time, generated from the lists
  // themselves rather than hand-listed. "A NEW BUILD INPUT THAT IS NOT ADDED
  // HERE WILL NEVER DEPLOY" is the guard's loudest maintenance warning, and the
  // converse is just as quiet: an entry DELETED from a list stops a real build
  // input from ever deploying again, with no error. Generating these means
  // adding an entry to either list automatically demands a fixture that covers
  // it — the suite cannot go green on an allowlist it does not exercise.
  ...allowlistMutations('api', 'api requirements.txt backend/jobtracker vercel.json .vercelignore'),
  ...allowlistMutations('web', 'apps/web .vercelignore'),
  {
    name: 'the head-not-in-clone guard skips instead of building',
    find: '  log "head ${head_sha} is not in this clone; building"\n  exit "$BUILD"',
    replace: '  log "head ${head_sha} is not in this clone; building"\n  exit "$SKIP"',
  },
  {
    name: 'the Dependabot backstop is removed',
    find: '    log "branch ${VERCEL_GIT_COMMIT_REF} is a Dependabot branch; skipping"\n    exit "$SKIP"',
    replace: '    log "branch ${VERCEL_GIT_COMMIT_REF} is a Dependabot branch; skipping"\n    :',
  },
  {
    name: 'the preview path gains a HEAD^ fallback it must not have',
    find: "if [ -z \"$base_sha\" ] && [ \"${VERCEL_ENV:-}\" = 'production' ]; then",
    replace: 'if [ -z "$base_sha" ]; then',
  },
  {
    // The measured saving: three of the seven web previews of 2026-08-27/28
    // were full Next.js builds of branches whose entire diff is Python. With
    // this arm gone every first preview builds again, and only a SKIP
    // assertion can tell — a BUILD is also what a broken script produces.
    name: "a branch's first preview loses its default-branch window",
    find: "if [ -z \"$base_sha\" ] && [ \"${VERCEL_ENV:-}\" = 'preview' ]; then",
    replace: 'if false; then',
  },
  {
    // A Vercel builder has NO `origin`. Without this fallback the arm can never
    // resolve a base there, and the symptom is an unexplained BUILD — the
    // failure mode the whole file exists to make visible.
    name: 'the default branch can only be fetched from a remote that does not exist',
    find: "if [ -z \"$base_sha\" ] && [ -n \"${VERCEL_GIT_REPO_OWNER:-}\" ] && [ -n \"${VERCEL_GIT_REPO_SLUG:-}\" ]; then",
    replace: 'if false; then',
  },
  {
    // Fail-open doctrine: only a build whose shape we recognise gets measured.
    name: 'the preview window is taken on any non-production environment',
    find: "if [ -z \"$base_sha\" ] && [ \"${VERCEL_ENV:-}\" = 'preview' ]; then",
    replace: "if [ -z \"$base_sha\" ] && [ \"${VERCEL_ENV:-}\" != 'production' ]; then",
  },

  // The two call sites. These mutate a TRACKED file in place rather than a
  // copy, because there is no indirection to point the suite at a different
  // vercel.json — Vercel reads the one at a fixed path and so does the suite.
  // The original content is restored in a `finally`, and the CI job runs
  // `git diff --exit-code` afterwards so a failed restore cannot pass silently.
  {
    name: 'the guard is renamed out from under vercel.json',
    file: 'vercel.json',
    find: '"ignoreCommand": "bash vercel-ignore-build.sh api"',
    replace: '"ignoreCommand": "bash scripts/vercel-ignore-build.sh api"',
  },
  {
    name: "apps/web/vercel.json passes the wrong project name",
    file: 'apps/web/vercel.json',
    find: '"ignoreCommand": "bash ../../vercel-ignore-build.sh web"',
    replace: '"ignoreCommand": "bash ../../vercel-ignore-build.sh apps/web"',
  },
  // The key the guard's own header calls load-bearing. Dropping it means the
  // api project stops creating PRODUCTION deployments — no record, no status,
  // nothing to notice. This is the #174 signature, and until now nothing
  // checked it at all.
  {
    name: 'the load-bearing "main": true is simplified away from vercel.json',
    file: 'vercel.json',
    find: '      "**": false,\n      "main": true\n',
    replace: '      "**": false\n',
  },
  {
    name: 'the web project stops filtering Dependabot',
    file: 'apps/web/vercel.json',
    find: '      "dependabot/**": false,\n      "dependabot/*": false\n',
    replace: '      "dependabot/**": false\n',
  },
];

/**
 * Run the suite once. `--test-reporter=tap` is pinned so the summary line is
 * parseable regardless of Node version and of whether stdout is a TTY: node
 * --test picks `spec` or `tap` on its own otherwise, and the two differ.
 */
function runSuite(env = {}) {
  return spawnSync(process.execPath, ['--test', '--test-reporter=tap', SUITE], {
    cwd: REPO,
    encoding: 'utf8',
    env: { ...process.env, ...env },
  });
}

// EVERY TRACKED TARGET MUST BE CLEAN BEFORE WE TOUCH IT.
//
// The mutations below that name a `file` rewrite a TRACKED config in place and
// restore it from a copy taken one line earlier. That is safe alone and unsafe
// beside anything else: two copies of this script running at once each take the
// OTHER's mutation as the original, and whichever finishes last writes a
// mutated vercel.json back to the working tree and calls it restored. Running
// the unit suite concurrently is the milder version of the same race — it reads
// a config that is mid-mutation and fails for a reason that has nothing to do
// with the change under test. Both happened while #563 was being written.
//
// Refusing on a dirty target also refuses to overwrite an edit someone made on
// purpose, which is the more likely way to lose work here.
const dirty = [...new Set(MUTATIONS.map((m) => m.file).filter(Boolean))].filter(
  (file) => spawnSync('git', ['diff', '--quiet', '--', file], { cwd: REPO }).status !== 0,
);
if (dirty.length > 0) {
  console.error(
    'These tracked files have uncommitted changes and are mutation targets:\n  ' +
      dirty.join('\n  ') +
      '\n\nThis script rewrites them in place and restores them from a copy, so ' +
      'running it now would restore the wrong content. Commit or stash them ' +
      'first — and if another copy of this script is already running, wait for it.',
  );
  process.exit(1);
}

const results = [];

for (const m of MUTATIONS) {
  // A mutation with no `file` targets the guard, which is mutated as a COPY.
  // One naming a file mutates that tracked file IN PLACE and restores it.
  const target = m.file ? join(REPO, m.file) : SOURCE;
  const original = readFileSync(target, 'utf8');

  const hits = original.split(m.find).length - 1;
  if (hits !== 1) {
    results.push({
      name: m.name,
      ok: false,
      why:
        `anchor matched ${hits} times in ${m.file ?? 'vercel-ignore-build.sh'}, ` +
        'expected exactly 1. If you changed an allowlist or a vercel.json, add ' +
        'a case covering it to scripts/test_vercel_ignore_build.mjs and update ' +
        'the anchor here',
    });
    continue;
  }

  const mutated = original.replace(m.find, m.replace);
  let run;
  try {
    if (m.file) {
      writeFileSync(target, mutated);
      run = runSuite();
    } else {
      writeFileSync(MUTANT, mutated);
      run = runSuite({ IGNORE_BUILD_SCRIPT: MUTANT });
    }
  } finally {
    // Unconditional. An in-place mutation that escaped this block would leave a
    // tracked config file broken, which is a worse defect than the one this
    // script exists to catch.
    if (m.file) writeFileSync(target, original);
    else rmSync(MUTANT, { force: true });
  }

  // Require the failure COUNT, not merely a non-zero exit: a mutant that made
  // the suite crash would also exit non-zero, and that is not the same as the
  // suite detecting it.
  const failed = /^(?:ℹ|#)\s*fail (\d+)\s*$/m.exec(run.stdout ?? '');
  const count = failed ? Number(failed[1]) : null;
  const detected = run.status !== 0 && count !== null && count > 0;
  results.push({
    name: m.name,
    ok: detected,
    why: detected
      ? `${count} test${count === 1 ? '' : 's'} red`
      : `SUITE STILL GREEN (exit ${run.status})`,
  });
}

rmSync(MUTANT, { force: true });

let survivors = 0;
console.log('Negative control: each mutation must turn the suite red.\n');
for (const r of results) {
  if (!r.ok) survivors += 1;
  console.log(`  ${r.ok ? 'caught  ' : 'SURVIVED'}  ${r.name}  (${r.why})`);
}
console.log();

if (survivors > 0) {
  console.error(
    `${survivors} of ${results.length} mutations survived. The suite does not ` +
      'detect them, so it does not cover what it claims to cover. Add the ' +
      'missing case rather than removing the mutation.',
  );
  process.exit(1);
}

// DEPLOY.md quotes this count in prose, and a number nothing recomputes goes
// stale: it said "ten ways" while this file held nineteen, for long enough that
// nobody could say when it stopped being true. The file that owns the number is
// the only one that can keep it honest, so it asserts it here rather than
// leaving the prose to be re-read by hand. Failing on a mismatch is the point —
// a stale figure in the deployment runbook is exactly the kind of claim this
// repository keeps having to correct after the fact.
const runbook = readFileSync(new URL('../DEPLOY.md', import.meta.url), 'utf8');
const quoted = runbook.match(/breaks the guard (\d+) ways/);
if (quoted === null) {
  console.error(
    'DEPLOY.md no longer states how many ways this file breaks the guard. ' +
      'Restore the sentence or delete this check — a claim nobody can find is ' +
      'not a claim this file can keep true.',
  );
  process.exit(1);
}
if (Number(quoted[1]) !== results.length) {
  console.error(
    `DEPLOY.md says this file breaks the guard ${quoted[1]} ways; it breaks it ` +
      `${results.length}. Update the sentence in the same commit as the ` +
      'mutation.',
  );
  process.exit(1);
}

console.log(`All ${results.length} mutations detected. The suite can fail.`);
