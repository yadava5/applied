/**
 * Fixtures for the needs-review queue — the held verdicts the LOCKED
 * /demo/shell twin mounts through `PipelineBoard`'s `beforeList`/`afterList`
 * slots, which is exactly how the signed-in dashboard mounts the real one.
 *
 * They exist because the twin rendered a strict SUBSET of the page it stands
 * in for: the frame, the pulse and the worklist, but never the queue. That is
 * harder to see than ordinary drift — there is no mismatched component to
 * diff, only an absent one — and it let a real defect through with every gate
 * green. `ReviewQueue` positions nothing of its own, so its `sr-only` labels
 * resolved against the INITIAL containing block and planted a box at document
 * scale; no ancestor's `overflow` clips a box whose containing block it is not,
 * so the viewport became the scroll container and the signed-in dashboard
 * scrolled as a whole document (fixed in #149). `tests/e2e/shell.spec.ts` was
 * already asserting the document does not scroll, correctly, at three
 * viewports — it just never had this subtree in front of it.
 *
 * Functions, not constants, for the same reason as `demoData.ts`: `received_at`
 * is RELATIVE and has to be resolved during a render, against the same clock
 * read the rest of the store is dated with. Frozen at module load it would bake
 * the process's start day into HTML the browser hydrates with today's.
 *
 * What makes these queue rows rather than board rows is the CONFIDENCE, and
 * `ReviewQueue` states the contract: a verdict is held either because it fell
 * under the auto-file gate (`AUTO_FILE_GATE`, 0.85 — "your call decides it"),
 * or because it cleared the gate and no employer could be named ("held for a
 * missing employer name"). Both branches are seeded, so the line that tells the
 * user WHICH question they are being asked renders in both of its forms. The
 * existing `DEMO_REVIEW_QUEUE` in `demoData.ts` is deliberately not reused: two
 * thirds of its rows are confident, auto-filed verdicts (0.99 offer, 0.97
 * digest) that describe the classifier's output as a whole, and a queue full of
 * them would contradict what the queue is.
 */
import type { ReviewItem } from "@/components/dashboard/ReviewQueue";
import { todayISO } from "@/lib/dashboard/age";
import { daysBefore } from "@/lib/demo/demoData";

/** A held message before its date is resolved: an age, not a calendar day. */
interface HeldSeed {
  subject: string;
  /** Null where the mail carried no display name — the live rows' normal case,
   *  and the fallback-to-address branch of the row's sender line. */
  senderName: string | null;
  senderEmail: string;
  snippet: string;
  /** The classifier's own number, as `/applications/review` reports it. */
  confidence: number;
  /** Whole days before "today" the message arrived. */
  receivedDaysAgo: number;
  /** Which application the mail names, where it names one. Null is the common
   *  case and is the row's no-role branch. */
  role?: string | null;
}

/**
 * Seven held messages, cycled to whatever length the harness asks for. Most sit
 * in the uncertain band under the gate; one cleared it and is held for a
 * missing employer name, which is the branch the amber/green split in the row's
 * confidence line exists to distinguish.
 *
 * The last TWO are one shape and belong together: an applicant tracking system
 * sends every acknowledgement for an employer under one subject from one
 * no-reply address, so the queue can hold several entries whose subject and
 * sender are byte-identical and which are nevertheless different applications.
 * Since the queue began keying on (conversation, application) rather than the
 * conversation alone, that is a state a real reader reaches, and the only thing
 * telling the two rows apart is the role. Seeding it here is what keeps the
 * twin from being a strict subset of the page it stands in for — the omission
 * this file's header is about, in its next form.
 */
const HELD_SEEDS: HeldSeed[] = [
  {
    subject: "Quick question about your background",
    senderName: "Maya Ellison",
    senderEmail: "maya@summit.dev",
    snippet:
      "Saw your work on the analytics side and wanted to ask a couple of questions before we go further.",
    confidence: 0.61,
    receivedDaysAgo: 1,
  },
  {
    subject: "Re: your note — a few thoughts",
    senderName: "Priya Raman",
    senderEmail: "priya@cedarlabs.com",
    snippet: "Thanks for reaching out. A few thoughts on where this could go, and one caveat.",
    confidence: 0.74,
    receivedDaysAgo: 2,
  },
  {
    subject: "Scheduling — are you around next week?",
    senderName: null,
    senderEmail: "scheduling@northstar.dev",
    snippet: "Looking at Tuesday or Wednesday afternoon. Let me know what works on your end.",
    confidence: 0.79,
    receivedDaysAgo: 3,
  },
  {
    subject: "Following up on the role we discussed",
    senderName: "Dan Okafor",
    senderEmail: "dan@harboranalytics.com",
    snippet: "Wanted to close the loop on the conversation from a couple of weeks back.",
    confidence: 0.68,
    receivedDaysAgo: 5,
  },
  {
    // Above the gate — this one is held because the mail names no employer at
    // all, which is the queue's second, differently-worded question.
    subject: "Thank you for your interest",
    senderName: "Recruiting",
    senderEmail: "no-reply@applicant-mail.net",
    snippet: "We have received your materials and will be in touch if there is a fit.",
    confidence: 0.92,
    receivedDaysAgo: 8,
  },
  {
    subject: "Thank you for applying to Verkada",
    senderName: "Verkada",
    senderEmail: "no-reply@us.greenhouse-mail.io",
    snippet:
      "Thank you so much for applying to the Backend Engineer, Alarms role at Verkada. We are excited to receive your application and will review it as soon as we can.",
    confidence: 0.78,
    receivedDaysAgo: 9,
    role: "Backend Engineer, Alarms",
  },
  {
    // Byte-identical subject and sender to the row above, and a DIFFERENT
    // application. Without the role these two are one question asked twice.
    subject: "Thank you for applying to Verkada",
    senderName: "Verkada",
    senderEmail: "no-reply@us.greenhouse-mail.io",
    snippet:
      "Thank you so much for applying to the Frontend Engineer - Access Control role at Verkada. We are excited to receive your application and will review it as soon as we can.",
    confidence: 0.78,
    receivedDaysAgo: 9,
    role: "Frontend Engineer - Access Control",
  },
];

/**
 * `count` held verdicts, dated against `today`.
 *
 * The count is the caller's, not the fixture list's: /demo/shell's `?review=N`
 * knob already tells the pulse band "N held for review", and a queue that
 * showed a different number would make the twin say two things at once. Seeds
 * cycle, each pass one day older than the last, and the index is suffixed onto
 * `message_id` — that id is the React key AND backs the per-row `cat-…` /
 * `company-…` element ids, so a repeated seed must never repeat its id.
 *
 * `gmail_link` is null on purpose. The real queue renders an "open in gmail"
 * link to the reader's own thread; /demo reads no inbox and has no reader, so
 * pointing an anonymous visitor at someone else's mail URL is the dead end the
 * pulse's own deep-link note already refuses. The API models the field as
 * optional and the row renders nothing for it.
 */
export function demoReviewQueueAsApi(count: number, today: string = todayISO()): ReviewItem[] {
  return Array.from({ length: Math.max(0, count) }, (_, index) => {
    const seed = HELD_SEEDS[index % HELD_SEEDS.length]!;
    const pass = Math.floor(index / HELD_SEEDS.length);
    return {
      message_id: `demo-held-${index + 1}`,
      subject: seed.subject,
      sender_name: seed.senderName ?? null,
      sender_email: seed.senderEmail,
      // Noon UTC, the same shape `asApplications.ts` gives `created_at`, so the
      // calendar day a reader sees is the day the seed asked for everywhere.
      received_at: `${daysBefore(today, seed.receivedDaysAgo + pass)}T12:00:00.000Z`,
      snippet: seed.snippet,
      confidence: seed.confidence,
      gmail_link: null,
      role: seed.role ?? null,
    };
  });
}
