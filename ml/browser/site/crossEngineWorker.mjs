/* Classify a JSON array of cases on stdin with THIS directory's engine.
 *
 * The browser port's opposite number to `apps/web/tests/unit/helpers/
 * crossEngineWorker.mjs`, and it exists for the same reason: the differential's
 * reference engine is an in-process Python import, so every port needs a
 * spawned process. It lives beside `app.js` rather than under `apps/web`
 * because it resolves `./app.js` and `./rules.json` relative to itself and
 * needs no `node_modules` at all.
 *
 * ONE LINE OF NDJSON PER CASE on stdout. A non-zero exit is fatal to the
 * caller by design: a worker that cannot classify must not report a verdict,
 * because `other`/0.5 is also what the Python engine answers for anything that
 * does not score, and the two would read as agreement.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const { useRules, rulesClassify } = await import(join(HERE, 'app.js'));

useRules(JSON.parse(readFileSync(join(HERE, 'rules.json'), 'utf8')));

const cases = JSON.parse(readFileSync(0, 'utf8'));
for (const c of cases) {
  const { category, confidence } = rulesClassify(c.subject, c.body, c.sender);
  process.stdout.write(`${JSON.stringify({ id: c.id, category, confidence })}\n`);
}
