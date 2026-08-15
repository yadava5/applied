import type { CSSProperties, ReactNode } from "react";

import { QuietLine } from "@/components/boot/QuietLine";

/**
 * Instant pending state for /settings — the Triage boot's quiet form at the
 * rail + capped-cards geometry `page.tsx` renders. Settings holds no mail rows,
 * so the classify signal is abstracted: attention travels the cards as a
 * staggered hairline border lift (`boot-quiet-card`) rather than inventing
 * envelopes the content will never show. Before this surface existed a cold
 * navigation answered the click with NOTHING for the whole origin wait
 * (700–1150 ms measured, #203).
 *
 * COUNT FIRST, because that was the biggest error and it needed no
 * measurement. The page renders SIX sections — Profile, Appearance, Gmail,
 * Notifications, Data, Account — and `SettingsNav` defines six links. This
 * surface drew four cards and seven rail links, so the swap grew the column by
 * most of a screen and the reader was told the wrong shape of the page.
 *
 * HEIGHTS. Settings is a FLOW page inside the shell's scroll pane, so unlike
 * /dashboard and /inbox its total height is what content makes it and a
 * mismatch really does shove everything below. The six card heights here were
 * tuned against the real sections rendered at the width the shell gives them
 * at 1024 (309.5 / 268 / 179 / 236 / 124 / 175 px) on a production build. Two
 * honest caveats, because an unverified skeleton height is a claim:
 *
 *   - The Gmail slot is matched to `GmailCardFallback`, not to the resolved
 *     card. That is correct rather than a shortcut: the card is behind a
 *     Suspense boundary, so the fallback is what actually occupies the slot at
 *     the moment this surface hands over. The resolved card's height depends
 *     on the connection state and cannot be known here.
 *   - The other five vary with the account's own data (a long display name,
 *     a sign-in summary listing two providers). They are matched to a typical
 *     signed-in render, not derived from a constant, and a section that grows
 *     a control will drift from them silently. That wants a geometry check.
 *
 * The chrome around the numbers IS derived: every card transcribes
 * `SettingsSection`'s own `rounded-xl border p-5`, its `mb-4` heading block and
 * the `text-lg`/`text-sm` type its title and description are set in, so the
 * header band of each plate lands where the real one does whatever the theme's
 * metrics are.
 */

/** One card, at `SettingsSection`'s chrome. `body` is the tuned remainder. */
function QuietCard({
  index,
  title,
  described = false,
  children,
}: {
  index: number;
  title: string;
  described?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className="boot-quiet-card rounded-xl border border-line-soft p-5"
      style={{ "--i": index } as CSSProperties}
    >
      <div className="mb-4">
        <h2 className="text-lg font-medium">
          <QuietLine className={`${title} border-line-strong`} />
        </h2>
        {described ? (
          <p className="mt-1 text-sm">
            <QuietLine className="w-64" />
          </p>
        ) : null}
      </div>
      {children}
    </div>
  );
}

/** A labelled control — the repeated unit of every section on this page. */
function QuietField({ width = "w-24", control }: { width?: string; control: string }) {
  return (
    <div className="grid gap-1">
      <span className="label-caps">
        <QuietLine className={width} />
      </span>
      <div className={`rounded-lg border border-line-soft ${control}`} />
    </div>
  );
}

export default function SettingsLoading() {
  return (
    <section
      aria-busy="true"
      // "Loading…" is half of BootOverlay's PENDING_SELECTOR, not just a label.
      aria-label="Loading settings"
      className="boot-quiet relative space-y-6"
    >
      {/* The PageHeader band (#297): childless here, so it is `lg`-only — just
          the ⋯ session menu's square on the right, at the loaded row's 36px. */}
      <div className="hidden justify-end lg:flex">
        <div className="h-9 w-9 rounded-lg border border-line" />
      </div>

      <div className="lg:grid lg:grid-cols-[10rem_minmax(0,48rem)] lg:gap-8">
        {/* `SettingsNav`'s desktop rail, transcribed: six links on the same
            hairline spine, at the same `py-1 text-[13px]` measure. */}
        <div className="hidden lg:block">
          <div className="space-y-0.5 border-l border-line-soft">
            {["w-12", "w-20", "w-12", "w-24", "w-16", "w-16"].map((w, i) => (
              <div key={i} className="-ml-px block border-l border-transparent py-1 pl-3 text-[13px]">
                <QuietLine className={w} />
              </div>
            ))}
          </div>
        </div>

        <div className="max-w-3xl space-y-6 lg:max-w-none">
          {/* Profile — name field, the two-up read-only identity grid, save. */}
          <QuietCard index={0} title="w-16">
            <div className="space-y-4">
              <QuietField width="w-20" control="h-[38px]" />
              <div className="grid gap-4 sm:grid-cols-2">
                <QuietField width="w-14" control="h-5" />
                <QuietField width="w-24" control="h-5" />
                <QuietField width="w-20" control="h-5" />
              </div>
              <div className="flex items-center gap-3">
                <span className="h-9 w-24 rounded-lg border border-line-soft" />
              </div>
            </div>
          </QuietCard>

          {/* Appearance — the theme segmented control, its note, then the
              ambient row under its own rule. */}
          <QuietCard index={1} title="w-28" described>
            <div className="inline-block rounded-lg border border-line-soft p-1">
              {["w-14", "w-10", "w-12"].map((w, i) => (
                <span key={i} className="inline-block rounded-md px-4 py-1.5 text-sm">
                  <QuietLine className={w} />
                </span>
              ))}
            </div>
            {/* One <p> PER LINE. A QuietLine set to `block` stops being an
                inline box in a line box and collapses to its own 2px — the
                strut is what gives it the real line's height, so two lines are
                two paragraphs, never two blocks in one. */}
            <div className="mt-3 text-[12px] leading-relaxed">
              <p>
                <QuietLine className="w-full" />
              </p>
              <p>
                <QuietLine className="w-3/5" />
              </p>
            </div>
            <div className="mt-4 border-t border-line-soft pt-4">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0 flex-1 text-[12px] leading-relaxed">
                  <p>
                    <QuietLine className="w-4/5" />
                  </p>
                  <p>
                    <QuietLine className="w-2/5" />
                  </p>
                </div>
                <div className="h-6 w-11 shrink-0 rounded-full border border-line" />
              </div>
            </div>
          </QuietCard>

          {/* Gmail — transcribed from `GmailCardFallback` box for box, because
              that fallback is what really holds this slot while the backend
              answers, and it carries no `mb-4` heading block of its own. */}
          <div
            className="boot-quiet-card rounded-xl border border-line-soft p-5"
            style={{ "--i": 2 } as CSSProperties}
          >
            <div className="h-6 w-24 rounded border border-line-strong" />
            <div className="mt-2 h-4 w-full max-w-sm rounded border border-line" />
            <div className="mt-4 h-4 w-40 rounded border border-line" />
            <div className="mt-6 border-t border-line-soft pt-4">
              <div className="h-4 w-56 rounded border border-line" />
            </div>
          </div>

          {/* Notifications — the preference rows on their own hairlines, then
              the save-status line the section reserves under them. */}
          <QuietCard index={3} title="w-32">
            <div className="divide-y divide-line-soft">
              {["w-56", "w-44", "w-48"].map((w, i) => (
                <div key={i} className="flex items-center justify-between gap-3 py-3 first:pt-0">
                  <p className="min-w-0 flex-1 text-sm">
                    <QuietLine className={w} />
                  </p>
                  <div className="h-5 w-9 shrink-0 rounded-full border border-line" />
                </div>
              ))}
            </div>
            <div className="mt-2 min-h-4" />
          </QuietCard>

          {/* Your data — export and import, side by side. */}
          <QuietCard index={4} title="w-24">
            <div className="flex flex-wrap items-center gap-3">
              <span className="h-[38px] w-32 rounded-lg border border-line-soft" />
              <span className="h-[38px] w-28 rounded-lg border border-line-soft" />
            </div>
          </QuietCard>

          {/* Account — sign out and delete, then the standing caveat line. */}
          <QuietCard index={5} title="w-20">
            <div className="flex flex-wrap items-center gap-3">
              <span className="h-[38px] w-28 rounded-lg border border-line-soft" />
              <span className="h-[38px] w-36 rounded-lg border border-line-soft" />
            </div>
            <div className="mt-3 text-[12px] leading-relaxed">
              <p>
                <QuietLine className="w-full" />
              </p>
              <p>
                <QuietLine className="w-2/5" />
              </p>
            </div>
          </QuietCard>
        </div>
      </div>
    </section>
  );
}
