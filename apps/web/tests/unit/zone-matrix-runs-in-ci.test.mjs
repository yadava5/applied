/**
 * The zone matrix in `frontend-ci.yml` is itself a claim, so it is read back.
 *
 * `local-today.test.mjs` and `dates.test.mjs` assert that day-bucketing follows
 * the READER's calendar day rather than the UTC day. `local-today.test.mjs` is
 * explicit that `TZ=UTC` is its POSITIVE CONTROL: under UTC both of its instants
 * agree with the UTC day, so the UTC arm "passed before this fix and must pass
 * after it". It proves the test still runs; it cannot prove the conversion
 * happens.
 *
 * For as long as those tests existed, UTC was the ONLY arm anyone ran. GitHub's
 * runners are UTC and no workflow set `TZ` -- `grep -rn TZ .github/workflows/`
 * returned nothing (#835). Measured on the likeliest regression, `localTodayISO`
 * rewritten to the `getUTC*` getters: UTC stayed 3 pass / 0 fail while
 * America/New_York, Asia/Tokyo and Pacific/Auckland each went 0 pass / 3 fail.
 *
 * THREE WAYS THE MATRIX CAN ROT, and this file exists for all three:
 *
 *  1. Someone trims it back to one zone for speed. Caught by the span test.
 *  2. Someone keeps four entries but they all sit at the same offset, which
 *     reads like a matrix and is four copies of the control.
 *  3. Someone MISSPELLS a zone. This is the quiet one: `TZ=America/New_Yrok`
 *     does not error. Node resolves it to `undefined` and reports offset 0 --
 *     the arm silently becomes another UTC run. Measured on the Node in use.
 *
 * The offsets are derived from `Intl` at a fixed instant, never from a table of
 * zone names kept here, because a list of names in this file would be one more
 * unchecked registration of exactly the kind #401 is about.
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/** `apps/web/tests/unit/` -> the repository root. Four segments, fixed. */
const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
const WORKFLOW = join(REPO_ROOT, ".github", "workflows", "frontend-ci.yml");

/**
 * A fixed instant in August, so the answer does not depend on when this runs.
 * DST is deliberately in force for the northern zones here: the matrix has to
 * span both signs of offset on a real day, not only in January.
 */
const INSTANT = Date.UTC(2026, 7, 12, 1, 0, 0);

/** The zones the unit-test step actually loops over, read out of the workflow. */
function zonesInCi() {
  const text = readFileSync(WORKFLOW, "utf8");
  const match = /for tz in ([^;\n]+); do/.exec(text);
  assert.ok(
    match,
    "frontend-ci.yml no longer loops the unit suite over timezones — the zone " +
      "arms of local-today.test.mjs and dates.test.mjs are unreachable again",
  );
  return match[1].trim().split(/\s+/);
}

/**
 * Offset of `zone` from UTC in minutes at `instant`, from `Intl` alone: format
 * the instant in the zone, read the wall-clock parts back as if they were UTC,
 * and subtract. Throws `RangeError` for a name `Intl` does not know, which is
 * what turns a silent typo into a loud one.
 */
function offsetMinutes(zone, instant) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(new Date(instant));
  const at = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  // `hour12: false` can render midnight as "24" in some ICU versions.
  const wall = Date.UTC(
    Number(at.year),
    Number(at.month) - 1,
    Number(at.day),
    Number(at.hour) % 24,
    Number(at.minute),
    Number(at.second),
  );
  return (wall - instant) / 60000;
}

test("every zone named in the workflow is one Intl actually recognises", () => {
  for (const zone of zonesInCi()) {
    assert.doesNotThrow(
      () => offsetMinutes(zone, INSTANT),
      `frontend-ci.yml names the timezone "${zone}", which Intl does not know. ` +
        "Node does not error on an unknown TZ — it resolves to UTC — so this " +
        "arm would run as a second copy of the positive control.",
    );
  }
});

test("the matrix spans both signs of UTC offset, not just several names", () => {
  const offsets = zonesInCi().map((zone) => [zone, offsetMinutes(zone, INSTANT)]);
  const describe = offsets.map(([z, o]) => `${z}=${o}`).join(" ");

  assert.ok(
    offsets.some(([, o]) => o < 0),
    `no zone WEST of UTC in the matrix (${describe}). A reader west of UTC is ` +
      "the case where the UTC day runs ahead of the reader's day.",
  );
  assert.ok(
    offsets.some(([, o]) => o > 0),
    `no zone EAST of UTC in the matrix (${describe}). A reader east of UTC is ` +
      "the case where the UTC day lags the reader's day.",
  );
});

test("the matrix keeps a zero-offset arm as the positive control", () => {
  const offsets = zonesInCi().map((zone) => [zone, offsetMinutes(zone, INSTANT)]);
  assert.ok(
    offsets.some(([, o]) => o === 0),
    "no zero-offset zone in the matrix — local-today.test.mjs documents UTC as " +
      "its positive control, the arm that must stay green, and without it a " +
      "total failure and a zone-specific one look the same.",
  );
});
