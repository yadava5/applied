import { gmailNoticeFor, NOTICE_TONE_CLASS } from "@/lib/gmail/notices";

/**
 * The one-line outcome of a Gmail connect round trip.
 *
 * Rendered by BOTH pages a callback can land on — Settings, where the user
 * pressed Connect, and the dashboard, where a consent chained off a first
 * sign-in returns (#510). Sharing the element and not just the strings keeps
 * the tone classes and the `role="status"` from drifting too.
 *
 * `role="status"` rather than `alert`: this is the result of something the
 * user just did and is already looking at, so it is announced politely at the
 * next opportunity instead of interrupting.
 */
export function GmailNotice({ flag }: { flag: string | undefined | null }) {
  const notice = gmailNoticeFor(flag);
  if (!notice) return null;

  return (
    <div
      role="status"
      data-testid="gmail-notice"
      className={`max-w-3xl rounded-xl border bg-surface px-4 py-3 text-sm ${NOTICE_TONE_CLASS[notice.tone]}`}
    >
      {notice.text}
    </div>
  );
}
