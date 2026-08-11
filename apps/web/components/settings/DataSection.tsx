"use client";

import Link from "next/link";
import { useState } from "react";
import { Download, Upload } from "lucide-react";

import { SettingsSection } from "./SettingsSection";
import { secondaryBtnClass } from "@/components/ui/formStyles";
import { localTodayISO } from "@/lib/dashboard/age";

type ExportState = "idle" | "working" | "error";

/**
 * Data: export everything Applied holds for you, and the on-device mail
 * import path. Export pulls your rows from the server-side proxy (which carries
 * your JWT) and downloads them as JSON entirely in the browser — no third party,
 * nothing emailed.
 */
export function DataSection() {
  const [state, setState] = useState<ExportState>("idle");

  async function exportData() {
    setState("working");
    try {
      const res = await fetch("/api/applications", { headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(`export failed (${res.status})`);
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      // The user's own day, not UTC. `toISOString()` here put tomorrow's date
      // on the file for anyone west of Greenwich after their evening cutoff —
      // a New York export at 9pm was stamped with the next day. Same defect as
      // the deadline bucketing, in a filename rather than a card.
      a.download = `applied-applications-${localTodayISO()}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setState("idle");
    } catch {
      setState("error");
    }
  }

  return (
    <SettingsSection title="Your data" description="Take it with you, or bring more in.">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={exportData} disabled={state === "working"} className={secondaryBtnClass}>
          <Download className="h-4 w-4" aria-hidden="true" />
          {state === "working" ? "Preparing…" : "Export applications (JSON)"}
        </button>
        <Link href="/import" className={secondaryBtnClass}>
          <Upload className="h-4 w-4" aria-hidden="true" />
          Import mail
        </Link>
      </div>
      {state === "error" ? (
        <p role="alert" className="mt-3 text-xs text-reject">
          Couldn’t prepare the export — the backend may be unreachable. Try again shortly.
        </p>
      ) : (
        <p className="mt-3 text-[12px] leading-relaxed text-dim">
          Export downloads your application rows as JSON, in your browser. Import classifies your own
          mail on-device — nothing is uploaded.
        </p>
      )}
    </SettingsSection>
  );
}
