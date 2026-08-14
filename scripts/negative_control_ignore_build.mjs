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
];

const source = readFileSync(SOURCE, 'utf8');
const results = [];

for (const m of MUTATIONS) {
  const hits = source.split(m.find).length - 1;
  if (hits !== 1) {
    results.push({
      name: m.name,
      ok: false,
      why:
        `anchor matched ${hits} times, expected exactly 1. If you changed an ` +
        'allowlist, add a fixture covering the new entry to ' +
        'scripts/test_vercel_ignore_build.mjs and update the entry list here',
    });
    continue;
  }

  writeFileSync(MUTANT, source.replace(m.find, m.replace));
  // --test-reporter=tap is pinned so the summary line is parseable regardless of
  // Node version and of whether stdout is a TTY: node --test picks `spec` or
  // `tap` on its own otherwise, and the two print different summaries.
  const run = spawnSync(process.execPath, ['--test', '--test-reporter=tap', SUITE], {
    cwd: REPO,
    encoding: 'utf8',
    env: { ...process.env, IGNORE_BUILD_SCRIPT: MUTANT },
  });
  rmSync(MUTANT, { force: true });

  // node --test's summary line is `ℹ fail N` in the default (spec) reporter and
  // `# fail N` under TAP. Match both, and require the count rather than
  // trusting the exit code alone: a mutant that made the SUITE crash would also
  // exit non-zero, and that is not the same as the suite detecting it.
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

console.log(`All ${results.length} mutations detected. The suite can fail.`);
