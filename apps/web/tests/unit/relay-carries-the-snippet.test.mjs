/**
 * The live-scan relay must forward the preview it already holds (#484).
 *
 * WHAT WAS WRONG. `PipelineItem` declared seven fields and `toPipelineItems`
 * forwarded seven. `snippet` was not among them, although `InboxVerdict.snippet`
 * exists, the mine returns one on every verdict, and the backend's
 * `PipelineItemIn.snippet` has accepted one (bounded at 2000) all along. So the
 * client held Gmail's ~200 characters and dropped them on the way to
 * `/gmail/sync`, the field took its `""` default server-side, and the row that
 * path wrote stored an empty `body_snippet`.
 *
 * That is worse than the "snippet-grade" fallback every server-side comment on
 * this path describes. Measured against the shipped backend, on a row the relay
 * wrote:
 *
 *     PipelineItemIn.snippet = '' len 0
 *     stored body_snippet    = ''
 *     identity_parts(...)    -> (None, None)
 *     identity_parts(same subject, the real 180-char preview)
 *                            -> ('Backend Platform Engineer', None)
 *
 * THIS FILE IS THE GATE FOR THAT FIX. The backend needed no change, so no
 * backend test can red on it: a Python test posting a relay item with a snippet
 * passes identically before and after. The only thing that distinguishes fixed
 * from broken is what this function puts on the wire.
 *
 * NULL IS NOT A SPELLING OF EMPTY HERE. `InboxVerdict.snippet` is
 * `string | null | undefined` and null is its documented value for a message
 * with no preview. `PipelineItemIn.snippet` is a plain `str`. `undefined`
 * is harmless — `JSON.stringify` drops the key and the default applies — but a
 * literal `null` is a 422, and `SyncRequest.items` is a homogeneous list, so ONE
 * preview-less message would reject the whole batch and file nothing. Verified
 * against the shipped schema: `PipelineItemIn(snippet=None)` raises
 * `Input should be a valid string`. Hence `?? ""`, and hence the serialization
 * assertions below rather than a bare deepEqual — a bug that only exists after
 * `JSON.stringify` needs to be looked for after `JSON.stringify`.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { toPipelineItems } from "../../lib/gmail/transport.ts";

/** Gmail's preview, at the length Gmail actually emits — and it names the job. */
const PREVIEW =
  "Thank you for applying to the Backend Platform Engineer position at " +
  "Northwind Labs. Our recruiting team has received your application and " +
  "will review it over the next several days.";

/** One verdict as `GET /gmail/inbox` reports it. */
const verdict = (overrides = {}) => ({
  message_id: "m-1",
  subject: "Your application to Northwind Labs",
  sender_email: "careers@northwind.test",
  sender_name: "Northwind Labs",
  category: "applied",
  confidence: 0.95,
  method: "rules",
  needs_review: false,
  received_at: "2026-08-01T12:00:00Z",
  company: "northwind",
  snippet: PREVIEW,
  ...overrides,
});

test("the relay forwards the preview the mine already handed it", () => {
  const [item] = toPipelineItems([verdict()]);

  assert.equal(item.snippet, PREVIEW);
  // On the wire, not just in the object: this is what the endpoint parses.
  assert.equal(JSON.parse(JSON.stringify(item)).snippet, PREVIEW);
});

test("a message with no preview relays an empty string, never null", () => {
  // Both shapes are reachable: `null` is what the mine reports for a message
  // Gmail gives no preview for, and the key is absent entirely on a verdict
  // rehydrated from a session snapshot that predates the field.
  const absent = verdict();
  delete absent.snippet;

  for (const source of [verdict({ snippet: null }), absent]) {
    const [item] = toPipelineItems([source]);
    const wire = JSON.parse(JSON.stringify(item));

    assert.equal(item.snippet, "");
    assert.equal(typeof wire.snippet, "string");
    assert.equal(wire.snippet, "");
  }
});

test("the relay states nothing about which application a message names", () => {
  // `PipelineItemIn` refuses `identity_role`/`identity_req_id` on purpose —
  // they decide which application a message is filed against and how the review
  // queue groups decisions, so a client that could state them could reshape
  // dedup keys and file its own mail onto whichever application it named. This
  // is an exact key list rather than two absence checks, because the field that
  // must not appear next is one nobody has thought of yet.
  const [item] = toPipelineItems([
    verdict({ identity_role: "Chief Executive", identity_req_id: "REQ-0" }),
  ]);

  assert.deepEqual(Object.keys(item).sort(), [
    "category",
    "confidence",
    "message_id",
    "received_at",
    "sender_email",
    "sender_name",
    "snippet",
    "subject",
  ]);
});

test("every other relayed field is unchanged", () => {
  // The regression guard for this commit: adding a field must not disturb the
  // seven that gate persistence. `confidence` in particular — omitting it once
  // meant every relayed item scored 0.0 and nothing was ever filed.
  const [item] = toPipelineItems([verdict()]);

  assert.deepEqual(item, {
    message_id: "m-1",
    category: "applied",
    sender_email: "careers@northwind.test",
    subject: "Your application to Northwind Labs",
    sender_name: "Northwind Labs",
    received_at: "2026-08-01T12:00:00Z",
    confidence: 0.95,
    snippet: PREVIEW,
  });
});
