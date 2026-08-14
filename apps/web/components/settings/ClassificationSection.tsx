import { SettingsSection } from "./SettingsSection";
import { AUTO_FILE_GATE } from "@/lib/dashboard/model";

const CATEGORIES = [
  "applied",
  "interview",
  "assessment",
  "offer",
  "rejection",
  "follow_up",
  "other",
  "needs_review",
];

/**
 * Classification: the rule the pipeline actually files by, and the categories
 * it predicts.
 *
 * There is no gate control here, and the one that used to be here never
 * worked. It wrote a per-user threshold into the user's Supabase metadata and
 * nothing on the backend ever read it (#208) — `AUTO_FILE_GATE` is a module
 * constant in `cloud/pipeline.py`, kept in lock-step with
 * `classifier/hybrid.py` and `api/classification.py` (and now by
 * `tests/test_confidence_gate_lockstep.py`, not by comment alone).
 *
 * Wiring it up would not have made its caption true either. "The rest
 * auto-file" was false at every position of the slider, because clearing the
 * gate is NECESSARY but not SUFFICIENT: `pipeline._qualifies_for_hard_row`
 * also demands a lifecycle category that is not `follow_up` and an employer
 * `resolve_employer` can name, and `collect_review_items` holds gated mail
 * that cannot be placed against one application. And the slider's lower half
 * was a regression dial — 0.85 is the fix for a named production defect ("far
 * too eager, low precision… 21 fake rows"), so `GATE_MIN = 0.5` sold the user
 * a way back into it.
 *
 * What replaces it is that rule, stated: written off `pipeline.py`'s precision
 * gate (:500-503), `_qualifies_for_hard_row` and `collect_review_items`'
 * docstring. The per-message override is the real control and it already
 * exists — held mail keeps `classified_as = NEEDS_REVIEW` with the proposal in
 * `suggested_category`, and a correction sets `user_corrected`, which
 * `applications.py:976` refuses to overwrite on the next sync.
 *
 * Propless on purpose: the signed-in page and the `/demo/settings` twin now
 * render literally the same output, so the two surfaces cannot drift.
 */
export function ClassificationSection() {
  return (
    <SettingsSection id="classification" title="Classification">
      <div className="space-y-5">
        <div>
          <div className="flex items-baseline justify-between">
            <span className="label-caps">auto-file gate</span>
            <span className="tabular font-mono text-lg font-semibold text-strong">
              {AUTO_FILE_GATE.toFixed(2)}
            </span>
          </div>
          <p className="mt-2 text-[13px] leading-relaxed text-muted">
            Applied sets a status on its own only when both are true: the classifier is at least{" "}
            <span className="tabular font-mono text-strong">{AUTO_FILE_GATE.toFixed(2)}</span>{" "}
            confident, and the employer can be named from the message itself. Job mail that misses
            either waits in your review queue with the category it proposed — you decide it, and
            your decision is kept through every later sync. Mail it can&rsquo;t read as job-search
            at all is left where it is; nothing is written.
          </p>
        </div>

        <div className="border-t border-line-soft pt-4">
          <p className="label-caps mb-2">categories the classifier predicts</p>
          <ul className="flex flex-wrap gap-1.5">
            {CATEGORIES.map((c) => (
              <li
                key={c}
                className="rounded-full border border-line px-2.5 py-0.5 text-xs text-muted"
              >
                {c}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </SettingsSection>
  );
}
