import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";

/**
 * A native <details> fold for reference material — the standing-prose cut.
 *
 * Born on the Gmail connection card, where the safeguards brief and the
 * restricted-scope scale story used to render in full on every visit; that
 * wall was most of what "too much text for the user to read" was reacting
 * to. The rule it encodes: STANDING prose (reference material, mechanism,
 * reassurance) folds behind one summary line; STATE-CONDITIONAL prose
 * (errors, empty states, sync facts) stays inline, because its absence
 * would read as a different state.
 *
 * A native <details>/<summary>, not a JS toggletip or a hover tooltip: it
 * needs no hydration, it is keyboard-operable and announced for free, and
 * Chromium auto-expands it for find-in-page, so folded text stays findable.
 */
export function Disclosure({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="group border-t border-line-soft pt-3">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-muted transition-colors hover:text-strong [&::-webkit-details-marker]:hidden">
        <ChevronDown
          className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-180 motion-reduce:transition-none"
          aria-hidden
        />
        {summary}
      </summary>
      <div className="mt-3 space-y-3 pl-5">{children}</div>
    </details>
  );
}
