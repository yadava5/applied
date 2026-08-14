/**
 * Unit tests for `lib/applications/export.ts` — the paging loop behind
 * Settings → "Export applications and mail (JSON)".
 *
 * These exist because the fix shipped without one. The loop was inline in
 * `app/api/applications/route.ts`, which needs the Next runtime and a Supabase
 * cookie jar to run, so the code deciding whether a user receives all of their
 * data or a silently truncated file was covered by types and review only. The
 * original defect was a single unparameterised call answered with the backend's
 * DEFAULT_PAGE_SIZE of 100 — a user with 250 applications got 100 and no
 * indication anything was missing. It never fired on the owner's account
 * because it holds 25 rows, which is the whole reason it needs a test rather
 * than an eyeball.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  EXPORT_MAX_PAGES,
  EXPORT_PAGE_SIZE,
  collectApplications,
} from "../../lib/applications/export.ts";

/** A backend holding `total` rows, served in pages, recording what was asked. */
function backend(total) {
  const rows = Array.from({ length: total }, (_, i) => ({ id: i + 1 }));
  const asked = [];
  return {
    asked,
    fetchPage: async (page, pageSize) => {
      asked.push({ page, pageSize });
      const start = (page - 1) * pageSize;
      return {
        ok: true,
        page: { applications: rows.slice(start, start + pageSize), total },
      };
    },
  };
}

test("an account that fits in one page is read in exactly one call", async () => {
  const be = backend(25);
  const result = await collectApplications(be.fetchPage);

  assert.equal(result.ok, true);
  assert.equal(result.applications.length, 25);
  assert.equal(result.pagesRead, 1);
  assert.deepEqual(be.asked, [{ page: 1, pageSize: EXPORT_PAGE_SIZE }]);
});

test("the export keeps paging until it has everything the backend counted", async () => {
  // 1,250 rows over a 500-row page size: the case the original one-shot call
  // got wrong, and the reason this function exists.
  const be = backend(1250);
  const result = await collectApplications(be.fetchPage);

  assert.equal(result.ok, true);
  assert.equal(result.applications.length, 1250);
  assert.equal(result.pagesRead, 3);
  // Every row exactly once, in order — no gaps and no duplicates across pages.
  assert.deepEqual(
    result.applications.map((a) => a.id),
    Array.from({ length: 1250 }, (_, i) => i + 1),
  );
});

test("a mid-export failure refuses rather than handing back a short file", async () => {
  // The important one. Returning the first page here would produce a
  // plausible-looking export missing an arbitrary tail, with a 200 on it.
  const be = backend(1250);
  const result = await collectApplications(async (page, size) => {
    if (page === 2) return { ok: false, status: 503, detail: "backend fell over" };
    return be.fetchPage(page, size);
  });

  assert.equal(result.ok, false);
  assert.equal(result.status, 503);
  assert.equal(result.detail, "backend fell over");
  assert.equal(result.applications, undefined);
});

test("a failure on the very first page is reported, not turned into an empty export", async () => {
  const result = await collectApplications(async () => ({
    ok: false,
    status: 401,
    detail: "not signed in",
  }));

  assert.equal(result.ok, false);
  assert.equal(result.status, 401);
});

test("a backend whose total lies is bounded, not looped forever", async () => {
  // `total` claims a million rows but every page comes back empty. Without the
  // no-progress break this spins to EXPORT_MAX_PAGES; without the page cap it
  // never stops at all.
  let calls = 0;
  const result = await collectApplications(async () => {
    calls += 1;
    return { ok: true, page: { applications: [], total: 1_000_000 } };
  });

  assert.equal(result.ok, true);
  assert.equal(result.applications.length, 0);
  assert.equal(calls, 2, "stops as soon as a page makes no progress");
});

test("a total that never resolves cannot exceed the page ceiling", async () => {
  // Every page returns one row while claiming a million: progress is real, so
  // the no-progress break never fires and only EXPORT_MAX_PAGES stops it.
  let calls = 0;
  const result = await collectApplications(async () => {
    calls += 1;
    return { ok: true, page: { applications: [{ id: calls }], total: 1_000_000 } };
  });

  assert.equal(result.ok, true);
  assert.equal(calls, EXPORT_MAX_PAGES);
  assert.equal(result.applications.length, EXPORT_MAX_PAGES);
});

test("the page size asked for is the backend's own ceiling", () => {
  // Asking for more than MAX_PAGE_SIZE is a 422, so this constant is a
  // contract with the backend and not a tuning knob.
  assert.equal(EXPORT_PAGE_SIZE, 500);
});
