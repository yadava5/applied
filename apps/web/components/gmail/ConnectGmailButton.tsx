import { Mail } from "lucide-react";

import { primaryBtnClass } from "@/components/ui/formStyles";
import { cn } from "@/lib/utils";

/**
 * The canonical "Connect Gmail" affordance.
 *
 * A single top-level navigation to the server-side authorize route
 * (`/api/gmail/authorize`), which carries the caller's Supabase JWT to the
 * backend, resolves the Google consent URL, and 302s the browser to Google —
 * so the token and `BACKEND_API_URL` never touch the client. Shared by the
 * Settings connection card and the not-connected `/inbox` empty state so the
 * connect action can never drift between the two surfaces, and it wears the
 * same `Mail` glyph as the dashboard's "Connect Gmail" tile so the three
 * surfaces read as one affordance.
 *
 * A plain <a> (not next/link): the target is a route handler that issues a
 * cross-origin redirect to accounts.google.com — a full navigation, not a
 * client-side transition.
 *
 * `configured` gates the control. When the backend reports Gmail isn't enabled
 * on this deployment it renders as an inert <span> — NOT a `pointer-events-none`
 * link, which stays keyboard-focusable and Enter-navigable and so would
 * dead-end. The `/inbox` not-connected state only arises once the backend has
 * confirmed Gmail IS configured (a 409 "linked?" answer, not a 503), so the
 * default is `true`.
 */
export function ConnectGmailButton({
  configured = true,
  className,
}: {
  configured?: boolean;
  className?: string;
}) {
  if (!configured) {
    return (
      <span
        aria-disabled="true"
        className={cn(
          "inline-flex cursor-not-allowed items-center justify-center gap-2 rounded-lg border border-line px-4 py-2 text-sm font-medium text-dim opacity-60",
          className,
        )}
      >
        <Mail className="h-4 w-4" aria-hidden="true" />
        Connect Gmail
      </span>
    );
  }

  return (
    <a href="/api/gmail/authorize" className={cn(primaryBtnClass, className)}>
      <Mail className="h-4 w-4" aria-hidden="true" />
      Connect Gmail
    </a>
  );
}
