/**
 * The ONE reading of `GET /api/applications/{id}` — the application plus the
 * metadata-only mail it was derived from (backend `ApplicationDetailResponse`:
 * `{ application, messages }`).
 *
 * Defensive on purpose: the detail sheet renders whatever the response
 * actually said and nothing it didn't. A malformed message entry is dropped,
 * not rendered blank, and an absent field renders as absent — the sheet never
 * invents a subject or a date.
 *
 * Dependency-free (no React, no `@/` alias, no generated schema) so
 * `tests/unit/` can load it directly under Node's type stripping — the same
 * rule as `review.ts` and `sync-plan.ts`.
 */

/** One email behind the application, as the backend `MessageRefResponse` names it. */
export interface DetailMessage {
  message_id: string;
  subject: string | null;
  sender_name: string | null;
  sender_email: string | null;
  received_at: string | null;
  snippet: string | null;
  category: string | null;
  confidence: number | null;
  gmail_link: string | null;
}

/** The row itself — the fields the sheet displays. */
export interface DetailApplication {
  id: number;
  company: string;
  position: string;
  status: string;
  notes: string | null;
  created_at: string;
  applied_date: string | null;
  source: string | null;
  url: string | null;
}

/**
 * One proposed half of a merged row.
 *
 * TODO(backend): `split_candidates` is NOT in `ApplicationDetailResponse` yet.
 * It is the signal for the "this looks like N applications — split?" surface:
 * the entity-model branch will populate it when one row's mail spans several
 * requisitions (four Amazon roles filed as one card is the proven case). Until
 * the field exists this parses to `[]` and the split prompt renders nothing —
 * deliberately, so no fake candidates are ever shown.
 */
export interface SplitCandidate {
  position: string;
  message_ids: string[];
}

export interface ApplicationDetail {
  application: DetailApplication | null;
  messages: DetailMessage[];
  splitCandidates: SplitCandidate[];
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function readMessage(entry: unknown): DetailMessage | null {
  const m = asRecord(entry);
  if (typeof m.message_id !== "string" || m.message_id === "") return null;
  return {
    message_id: m.message_id,
    subject: str(m.subject),
    sender_name: str(m.sender_name),
    sender_email: str(m.sender_email),
    received_at: str(m.received_at),
    snippet: str(m.snippet),
    category: str(m.category),
    confidence: typeof m.confidence === "number" && Number.isFinite(m.confidence) ? m.confidence : null,
    gmail_link: str(m.gmail_link),
  };
}

function readSplitCandidate(entry: unknown): SplitCandidate | null {
  const c = asRecord(entry);
  if (typeof c.position !== "string" || c.position.trim() === "") return null;
  const ids = Array.isArray(c.message_ids)
    ? c.message_ids.filter((id): id is string => typeof id === "string")
    : [];
  return { position: c.position, message_ids: ids };
}

/** Read a detail response body into what the sheet renders. */
export function readApplicationDetail(body: unknown): ApplicationDetail {
  const data = asRecord(body);
  const app = asRecord(data.application);

  const application: DetailApplication | null =
    typeof app.id === "number" && typeof app.company === "string"
      ? {
          id: app.id,
          company: app.company,
          position: str(app.position) ?? "",
          status: str(app.status) ?? "",
          notes: str(app.notes),
          created_at: str(app.created_at) ?? "",
          applied_date: str(app.applied_date),
          source: str(app.source),
          url: str(app.url),
        }
      : null;

  const messages = (Array.isArray(data.messages) ? data.messages : [])
    .map(readMessage)
    .filter((m): m is DetailMessage => m !== null);

  const splitCandidates = (Array.isArray(data.split_candidates) ? data.split_candidates : [])
    .map(readSplitCandidate)
    .filter((c): c is SplitCandidate => c !== null);

  return { application, messages, splitCandidates };
}
