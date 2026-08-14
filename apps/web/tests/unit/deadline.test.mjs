/**
 * The deadline derivation every surface shares (`lib/dashboard/deadline.ts`):
 * the card tag, the detail sheet and the pulse cell all read `dueInfo` /
 * `duePhrase` / `deadlinePulse`, so what is asserted here is asserted for all
 * three at once.
 *
 * The properties that matter:
 *  - no `due_at`, no claim: absent/malformed input yields null, never a guess;
 *  - the state boundaries sit exactly on DUE_SOON_DAYS and on "yesterday";
 *  - `dueDayISO` writes the END of the picked day (a deadline is "by then",
 *    not "at midnight before it") and round-trips its calendar prefix;
 *  - the pulse buckets count only rows with usable deadlines and name the
 *    smallest-days-left row as most urgent (overdue outranks everything).
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  DUE_SOON_DAYS,
  deadlineCaption,
  deadlineCaptionText,
  deadlinePulse,
  deadlineRunway,
  dueDayISO,
  dueInfo,
  duePhrase,
  dueSourceLabel,
} from "../../lib/dashboard/deadline.ts";

const TODAY = "2026-08-11";

test("dueInfo: no date, no claim", () => {
  assert.equal(dueInfo(null, TODAY), null);
  assert.equal(dueInfo(undefined, TODAY), null);
  assert.equal(dueInfo("", TODAY), null);
  assert.equal(dueInfo("not-a-date", TODAY), null);
  assert.equal(dueInfo("2026-13-40T00:00:00Z", TODAY), null);
});

test("dueInfo: the three states and their exact boundaries", () => {
  assert.deepEqual(dueInfo("2026-08-10T23:59:59Z", TODAY), { state: "overdue", daysLeft: -1 });
  assert.deepEqual(dueInfo("2026-08-11T23:59:59Z", TODAY), { state: "soon", daysLeft: 0 });
  // The last "soon" day is exactly DUE_SOON_DAYS out…
  assert.deepEqual(dueInfo("2026-08-13T23:59:59Z", TODAY), {
    state: "soon",
    daysLeft: DUE_SOON_DAYS,
  });
  // …and one more day is "ahead".
  assert.deepEqual(dueInfo("2026-08-14T23:59:59Z", TODAY), { state: "ahead", daysLeft: 3 });
});

test("dueInfo reads the calendar day the string states, time and zone ignored", () => {
  // Same rule as dates.ts: the claim is the stated day, identically on server
  // and client — a time component must not shift the bucket.
  assert.deepEqual(dueInfo("2026-08-13", TODAY), dueInfo("2026-08-13T01:00:00Z", TODAY));
});

test("dueDayISO: end of the picked day, calendar prefix intact", () => {
  assert.equal(dueDayISO("2026-08-15"), "2026-08-15T23:59:59Z");
  assert.equal(dueDayISO(" 2026-08-15 "), "2026-08-15T23:59:59Z");
  assert.equal(dueDayISO(""), null);
  assert.equal(dueDayISO("08/15/2026"), null);
  assert.equal(dueDayISO("2026-99-15"), null);
});

test("duePhrase: arithmetic, not urgency inference", () => {
  assert.equal(duePhrase(-3), "overdue 3d");
  assert.equal(duePhrase(0), "due today");
  assert.equal(duePhrase(1), "due in 1d");
  assert.equal(duePhrase(9), "due in 9d");
});

test("dueSourceLabel: two claims, nothing else dressed up as either", () => {
  assert.equal(dueSourceLabel("user"), "set by you");
  assert.equal(dueSourceLabel("mail"), "from your mail");
  assert.equal(dueSourceLabel(null), null);
  assert.equal(dueSourceLabel("sync"), null);
});

test("deadlinePulse: buckets tracked rows only, most urgent named by smallest days-left", () => {
  const rows = [
    { company: "No Deadline Co" },
    { company: "Broken Co", due_at: "soon-ish" },
    { company: "Later Co", due_at: "2026-08-20T23:59:59Z" },
    { company: "Soon Co", due_at: "2026-08-13T23:59:59Z" },
    { company: "Overdue Co", due_at: "2026-08-09T23:59:59Z" },
    { company: "More Overdue Co", due_at: "2026-08-05T23:59:59Z" },
  ];
  const pulse = deadlinePulse(rows, TODAY);
  assert.deepEqual(pulse, {
    overdue: 2,
    soon: 1,
    later: 1,
    total: 4,
    // Soonest first, and the same four rows the counts above are made of —
    // the panel's list and its runway read THIS, so neither can name a row
    // the cell did not count.
    rows: [
      { company: "More Overdue Co", daysLeft: -6 },
      { company: "Overdue Co", daysLeft: -2 },
      { company: "Soon Co", daysLeft: 2 },
      { company: "Later Co", daysLeft: 9 },
    ],
    urgent: { company: "More Overdue Co", daysLeft: -6 },
  });
});

test("deadlinePulse: an empty board is honestly empty", () => {
  assert.deepEqual(deadlinePulse([], TODAY), {
    overdue: 0,
    soon: 0,
    later: 0,
    total: 0,
    rows: [],
    urgent: null,
  });
});

test("deadlinePulse: a tie keeps the board's own order", () => {
  // `urgent` is rows[0] now that the rows are sorted, so the tie-break is the
  // sort's stability — the row the board listed first, exactly as when the
  // most urgent row was picked by a strict `<` comparison.
  const same = "2026-08-13T23:59:59Z";
  const pulse = deadlinePulse(
    [
      { company: "First Co", due_at: same },
      { company: "Second Co", due_at: same },
    ],
    TODAY,
  );
  assert.deepEqual(pulse.urgent, { company: "First Co", daysLeft: 2 });
});

/**
 * The caption, in the band's caption grammar. Ayush reported this cell twice —
 * "it has the same issue with text that we fixed for other" — against
 * `2 overdue · 1 due ≤2d · 5 later`: a per-bucket recitation whose middle
 * claim put a bare `1` against the unit `≤2d`, and which ended on the one
 * bucket there is nothing to do about today.
 *
 * So these assert the shape of the fix, not just today's wording: at most two
 * claims, ordered by urgency, `later` silent while anything is urgent, and no
 * numeral left touching a unit.
 */
/** `TODAY` shifted by whole calendar days — fixtures only, day maths in one place. */
const isoDaysFrom = (day, days) =>
  new Date(Date.parse(`${day}T00:00:00Z`) + days * 86400000).toISOString().slice(0, 10);

/** A board described by its deadlines' days-left, captioned. */
const captionOf = (offsets) =>
  deadlineCaptionText(
    deadlinePulse(
      offsets.map((days, i) => ({
        company: `Co ${i}`,
        due_at: dueDayISO(isoDaysFrom(TODAY, days)),
      })),
      TODAY,
    ),
  );

test("deadlineCaption: nothing due says so, and says where a deadline comes from", () => {
  assert.equal(captionOf([]), "nothing due · set one in a card");
});

test("deadlineCaption: one deadline inside the window — the live board's own line", () => {
  assert.equal(captionOf([2]), "1 due within 2 days");
});

test("deadlineCaption: overdue leads, and the window is the only other claim", () => {
  // The reported string was `2 overdue · 1 due ≤2d · 5 later` on exactly this
  // board. Two claims, both bound forward by their words; `later` is silent.
  assert.equal(captionOf([-3, -1, 1, 6, 7, 8, 9, 10]), "2 overdue · 1 due within 2 days");
  assert.equal(captionOf([-3, -1, 6, 7]), "2 overdue");
});

test("deadlineCaption: nothing urgent states the bound they all clear", () => {
  assert.equal(captionOf([4, 6, 9, 11, 20]), "all 5 due after 2 days");
  // "all 1" is not English; one deadline states itself.
  assert.equal(captionOf([9]), "1 due after 2 days");
});

test("deadlineCaption: never a bucket recitation, never a numeral against a unit", () => {
  for (const offsets of [[], [2], [0, 1, 2], [-1, 2, 9], [-4, -1], [3, 4, 5, 6, 7, 8]]) {
    const caption = captionOf(offsets);
    assert.ok(!caption.includes("≤"), `"${caption}" still abbreviates the window`);
    assert.ok(!/\d(?=[a-z])/.test(caption), `"${caption}" leaves a numeral touching a unit`);
    assert.ok(
      caption.split(" · ").length <= 2,
      `"${caption}" is a recitation, not a claim (two at most)`,
    );
    // "later" is the bucket nobody acts on today: it may never take a claim
    // beside an urgent one.
    if (/overdue|within/.test(caption)) {
      assert.ok(!caption.includes("later"), `"${caption}" spends a claim on the later bucket`);
    }
  }
});

test("deadlineCaption: each claim carries the ink its card tag already wears", () => {
  const claims = deadlineCaption(
    deadlinePulse(
      [
        { company: "Overdue Co", due_at: "2026-08-09T23:59:59Z" },
        { company: "Soon Co", due_at: "2026-08-13T23:59:59Z" },
        { company: "Later Co", due_at: "2026-08-20T23:59:59Z" },
      ],
      TODAY,
    ),
  );
  assert.deepEqual(
    claims.map((claim) => [claim.count, claim.words, claim.tone]),
    [
      [1, "overdue", "overdue"],
      [1, "due within 2 days", "soon"],
    ],
  );
});

test("deadlineRunway: one bin per position, and every row lands in exactly one", () => {
  const pulse = deadlinePulse(
    [
      { company: "Late Co", due_at: "2026-08-04T23:59:59Z" },
      { company: "Late Too Co", due_at: "2026-08-10T23:59:59Z" },
      { company: "Today Co", due_at: "2026-08-11T23:59:59Z" },
      { company: "Edge Co", due_at: "2026-08-13T23:59:59Z" },
      { company: "Ahead Co", due_at: "2026-08-30T23:59:59Z" },
    ],
    TODAY,
  );
  const runway = deadlineRunway(pulse.rows);
  assert.deepEqual(runway, [
    { kind: "overdue", count: 2 },
    { kind: "day", days: 0, count: 1 },
    { kind: "day", days: 1, count: 0 },
    { kind: "day", days: 2, count: 1 },
    { kind: "later", count: 1 },
  ]);
  assert.equal(
    runway.reduce((sum, bin) => sum + bin.count, 0),
    pulse.total,
  );
});
