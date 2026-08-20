"use client";

import dynamic from "next/dynamic";

import { useWideViewport } from "@/components/marketing/scrub";

import type { Director } from "./director";
import { NarrowNote, TakeStage } from "./TakeStage";

/**
 * 01c — start at the end: a reverse crane. The take opens DEEP — one line
 * of one application's mail trail filling the frame — and pulls back
 * continuously: the line seats into its trail, the trail into its docked
 * pane, the pane beside its row, the row into its stage group, and the
 * groups into the whole board. The loss-aversion hero as camera grammar:
 * the record is the point, so the record is the establishing shot.
 *
 * The pane is opened by a real (silent) click on the real row before the
 * first frame settles — the state the camera pulls out of is the product's
 * own, not a composition built for the shot.
 */
const MarketingBoard = dynamic(
  () => import("@/components/marketing/MarketingBoard").then((m) => m.MarketingBoard),
  { ssr: false },
);

const take = async (d: Director) => {
  await d.waitFor(() => d.query('button[aria-label^="Open Northstar Systems"]'), 12000, "the board");
  // Stage the end-state with a real click — no pointer theatre; the camera
  // is already past that moment when the shot opens.
  d.find('button[aria-label^="Open Northstar Systems"]').click();
  await d.waitFor(() => d.query('[data-testid="application-detail"] li'), 6000, "the mail trail");
  const trailLine = () => d.query('[data-testid="application-detail"] li');
  await d.zoomTo(trailLine, 1.8, 0);
  d.say("One line of history: the reply that became an interview.");
  await d.hold(2100);

  d.say("Pull back — the line sits in a trail, every mail in order…");
  await d.zoomTo(() => d.query('[data-testid="application-detail"]'), 1.05, 2300);
  await d.hold(1500);

  d.say("…the trail belongs to a row, docked beside the work…");
  await d.zoomTo(() => d.query('[data-testid="worklist-pane"]'), 0.95, 2300);
  await d.hold(1300);

  d.say("…and the row to the board. Every card remembers how it got here.");
  await d.fitAll(2500);
  await d.hold(1200);
};

export function ReverseCrane() {
  const wide = useWideViewport();
  if (!wide) return <NarrowNote what="The reverse crane" />;
  return (
    <TakeStage
      take={take}
      height={560}
      frameLabel="live fixture data — the shipped board and pane, one continuous pull-back"
      opening="Open on a single line of history, then pull back until the whole board holds it."
    >
      <MarketingBoard />
    </TakeStage>
  );
}
