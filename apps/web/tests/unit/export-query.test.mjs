/**
 * Unit tests for WHICH QUERY the export sends, and for the file it builds.
 *
 * `export.test.mjs` covers the paging loop, and covers it well — but
 * `collectApplications` is a pure function over an injected fetcher, so it
 * cannot see what that fetcher asks the backend for. That blind spot is
 * exactly where #217 lived: the route made one unparameterised pass,
 * `GET /applications` defaults `dismissed` to `false` and filters
 * `dismissed_at IS NULL`, so every removed-but-restorable application was
 * missing from a file the surface called "everything Applied holds for you".
 * `DELETE /account` deletes those rows regardless of `dismissed_at`, so the
 * documented "export before you delete" path lost them with no copy.
 *
 * These tests are therefore about the REQUEST, not the loop:
 *   - a `dismissed: true` pass is issued at all;
 *   - a row that exists only in that pass reaches the output;
 *   - a failure in either pass refuses instead of handing back half a file;
 *   - the mail pass exists and is paged by the same loop;
 *   - the downloaded file's envelope counts what is actually in it.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  EXPORT_PAGE_SIZE,
  buildExportFile,
  buildExportPages,
  collectMail,
} from "../../lib/applications/export.ts";

/**
 * A backend holding two disjoint sets — the live board and the removed rows —
 * behind the one exclusive `dismissed` filter the real endpoint applies, and
 * recording every query it was asked.
 */
function applicationsBackend({ live = 0, removed = 0 } = {}) {
  const liveRows = Array.from({ length: live }, (_, i) => ({
    id: i + 1,
    company: `Live ${i + 1}`,
    dismissed_at: null,
  }));
  const removedRows = Array.from({ length: removed }, (_, i) => ({
    id: 1000 + i + 1,
    company: `Removed ${i + 1}`,
    dismissed_at: "2026-08-01T12:00:00Z",
    dismissed_reason: "resync",
  }));
  const asked = [];
  return {
    asked,
    fetchPage: async (page, pageSize, dismissed) => {
      asked.push({ page, pageSize, dismissed });
      const rows = dismissed ? removedRows : liveRows;
      const start = (page - 1) * pageSize;
      return {
        ok: true,
        page: { applications: rows.slice(start, start + pageSize), total: rows.length },
      };
    },
  };
}

test("the export asks for the removed rows as well as the live board", async () => {
  // The assertion the whole issue turns on: without a second, dismissed pass
  // the removed rows are unreachable — no page size and no amount of paging
  // reaches them, because the backend's filter is exclusive.
  const be = applicationsBackend({ live: 3, removed: 2 });
  const result = await buildExportPages(be.fetchPage);

  assert.equal(result.ok, true);
  assert.deepEqual(
    be.asked.map((q) => q.dismissed),
    [false, true],
    "one live pass and one dismissed pass, in that order",
  );
  assert.deepEqual(be.asked, [
    { page: 1, pageSize: EXPORT_PAGE_SIZE, dismissed: false },
    { page: 1, pageSize: EXPORT_PAGE_SIZE, dismissed: true },
  ]);
});

test("a row that exists only in the dismissed pass is in the export", async () => {
  const be = applicationsBackend({ live: 3, removed: 2 });
  const result = await buildExportPages(be.fetchPage);

  assert.equal(result.ok, true);
  assert.equal(result.applications.length, 5);
  assert.deepEqual(
    result.applications.map((a) => a.id),
    [1, 2, 3, 1001, 1002],
  );
  // The removed rows arrive carrying the field that identifies them as
  // removed — the export does not tag them itself, so a reader can tell a
  // dismissal from a live row the same way every other surface does.
  const removedRows = result.applications.filter((a) => a.dismissed_at !== null);
  assert.equal(removedRows.length, 2);
  assert.equal(removedRows[0].dismissed_reason, "resync");
});

test("both totals are reported, and they add up to the rows handed back", async () => {
  const be = applicationsBackend({ live: 46, removed: 4 });
  const result = await buildExportPages(be.fetchPage);

  assert.equal(result.ok, true);
  assert.equal(result.live, 46);
  assert.equal(result.removed, 4);
  assert.equal(result.total, 50);
  assert.equal(result.applications.length, result.total, "no total standing over a longer array");
});

test("each pass is paged in full, not just its first page", async () => {
  const be = applicationsBackend({ live: 1250, removed: 600 });
  const result = await buildExportPages(be.fetchPage);

  assert.equal(result.ok, true);
  assert.equal(result.applications.length, 1850);
  assert.equal(result.pagesRead, 5, "3 live pages + 2 dismissed pages");
});

test("a failing dismissed pass refuses the whole export", async () => {
  // The live pass succeeding is not permission to ship its half. A 200 over a
  // file missing every removed row is the defect this issue is about, wearing
  // a different hat.
  const be = applicationsBackend({ live: 3, removed: 2 });
  const result = await buildExportPages(async (page, size, dismissed) => {
    if (dismissed) return { ok: false, status: 503, detail: "removed rows unavailable" };
    return be.fetchPage(page, size, dismissed);
  });

  assert.equal(result.ok, false);
  assert.equal(result.status, 503);
  assert.equal(result.detail, "removed rows unavailable");
  assert.equal(result.applications, undefined);
});

test("a failing live pass never even asks for the dismissed rows", async () => {
  const asked = [];
  const result = await buildExportPages(async (page, size, dismissed) => {
    asked.push(dismissed);
    return { ok: false, status: 401, detail: "not signed in" };
  });

  assert.equal(result.ok, false);
  assert.equal(result.status, 401);
  assert.deepEqual(asked, [false]);
});

test("the mail pass reads every stored message, through the same loop", async () => {
  const messages = Array.from({ length: 1200 }, (_, i) => ({ message_id: `m${i + 1}` }));
  const asked = [];
  const result = await collectMail(async (page, pageSize) => {
    asked.push({ page, pageSize });
    const start = (page - 1) * pageSize;
    return {
      ok: true,
      page: { messages: messages.slice(start, start + pageSize), total: messages.length },
    };
  });

  assert.equal(result.ok, true);
  assert.equal(result.messages.length, 1200);
  assert.equal(result.total, 1200);
  assert.equal(result.pagesRead, 3);
  assert.deepEqual(asked[0], { page: 1, pageSize: EXPORT_PAGE_SIZE });
});

test("a mail failure refuses too, rather than exporting applications alone", async () => {
  const result = await collectMail(async () => ({
    ok: false,
    status: 502,
    detail: "mail listing unreachable",
  }));

  assert.equal(result.ok, false);
  assert.equal(result.status, 502);
  assert.equal(result.messages, undefined);
});

test("the downloaded file names what is in it, and counts it from the rows", async () => {
  const at = new Date("2026-08-14T21:07:00.000Z");
  const file = buildExportFile(
    {
      applications: [
        { id: 1, dismissed_at: null },
        { id: 2 },
        { id: 3, dismissed_at: "2026-08-01T12:00:00Z" },
      ],
      messages: [{ message_id: "m1" }, { message_id: "m2" }],
    },
    at,
  );

  assert.equal(file.source, "Applied");
  assert.equal(file.exported_at, "2026-08-14T21:07:00.000Z");
  // Derived from the arrays, so the summary and the contents cannot disagree.
  assert.deepEqual(file.counts, {
    applications: 3,
    applications_removed: 1,
    messages: 2,
  });
  assert.equal(file.applications.length, 3);
  assert.equal(file.messages.length, 2);
  // The file states where it stops — the credentials line is the one that
  // matters, because "everything Applied holds for you" would have implied it.
  assert.match(String(file.about.excluded), /credentials/i);
});

test("an empty account still produces a described file, not a bare array", async () => {
  const file = buildExportFile({ applications: [], messages: [] });

  assert.deepEqual(file.counts, { applications: 0, applications_removed: 0, messages: 0 });
  assert.equal(typeof file.exported_at, "string");
  assert.deepEqual(file.applications, []);
  assert.deepEqual(file.messages, []);
});
