"use client";

import { useMemo, useState } from "react";

import { SaveStatus, SettingsSection } from "./SettingsSection";
import { primaryBtnClass } from "@/components/ui/formStyles";
import { GATE_MAX, GATE_MIN } from "@/lib/dashboard/model";
import { DEMO_REVIEW_QUEUE } from "@/lib/demo/demoData";
import { createClient } from "@/lib/supabase/client";

type SaveState = "idle" | "saving" | "saved" | "error";

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
 * Classification preferences. The auto-file gate is the one knob with a
 * defensible user-facing meaning: below it, a verdict is held for human review
 * instead of auto-filed. The slider shows a LIVE, honest consequence — how many
 * of a fixed sample batch would be held at the chosen gate — and the value
 * persists to the user's metadata. The caption is explicit that the hosted
 * classifier still files at the shipped 0.85 gate today.
 */
export function ClassificationSection({ initialGate }: { initialGate: number }) {
  const [gate, setGate] = useState(initialGate);
  const [state, setState] = useState<SaveState>("idle");

  const held = useMemo(
    () => DEMO_REVIEW_QUEUE.filter((v) => v.confidence < gate).length,
    [gate],
  );

  async function save() {
    setState("saving");
    const supabase = createClient();
    const { error } = await supabase.auth.updateUser({ data: { gate_threshold: gate } });
    setState(error ? "error" : "saved");
  }

  return (
    <SettingsSection
      title="Classification"
      description="How Applied decides what to auto-file versus hold for you."
    >
      <div className="space-y-5">
        <div>
          <div className="flex items-baseline justify-between">
            <span className="label-mono">auto-file gate</span>
            <span className="tabular font-mono text-lg font-semibold text-strong">
              {gate.toFixed(2)}
            </span>
          </div>
          <input
            type="range"
            min={GATE_MIN}
            max={GATE_MAX}
            step={0.01}
            value={gate}
            onChange={(e) => {
              setGate(Number(e.target.value));
              setState("idle");
            }}
            aria-label="Auto-file confidence gate"
            className="mt-2 w-full accent-[var(--viz-embeddings)]"
          />
          <p className="mt-2 text-[12px] leading-relaxed text-muted">
            At <span className="tabular font-mono text-strong">{gate.toFixed(2)}</span>,{" "}
            <span className="tabular font-mono text-review">{held}</span> of{" "}
            {DEMO_REVIEW_QUEUE.length} sample messages would wait for your review; the rest auto-file.
            Higher = more caution, more manual review.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={save}
            disabled={state === "saving" || gate === initialGate}
            className={primaryBtnClass}
          >
            Save gate
          </button>
          <SaveStatus state={state} />
        </div>

        <div className="border-t border-line-soft pt-4">
          <p className="label-mono mb-2">categories the classifier predicts</p>
          <ul className="flex flex-wrap gap-1.5">
            {CATEGORIES.map((c) => (
              <li
                key={c}
                className="rounded-full border border-line px-2.5 py-0.5 font-mono text-[11px] text-muted"
              >
                {c}
              </li>
            ))}
          </ul>
        </div>

        <p className="text-[12px] leading-relaxed text-dim">
          Your gate is stored on your account. The hosted classifier files at the shipped{" "}
          <span className="font-mono text-muted">0.85</span> gate today and honors your value as
          per-user tuning rolls out.
        </p>
      </div>
    </SettingsSection>
  );
}
