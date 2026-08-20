"use client";

import dynamic from "next/dynamic";

import { useWideViewport } from "@/components/marketing/scrub";

import type { Director } from "./director";
import { NarrowNote, TakeStage } from "./TakeStage";

/**
 * 01a — the workday oner: one continuous take through a real working
 * session. The pointer opens the pulse's momentum panel, presses a real
 * day bar (the shipped filed-on-a-date filter — no control here is drawn
 * for the camera), the board narrows with its own glide, a row opens, the
 * pane docks, the filter clears, and the camera returns home.
 *
 * The camera follows the READING, not the pointer: it frames where the
 * story goes next — the survivors, then the pane — rather than chasing the
 * click that caused it.
 */
const MarketingBoard = dynamic(
  () => import("@/components/marketing/MarketingBoard").then((m) => m.MarketingBoard),
  { ssr: false },
);

/** The tallest day bar in the momentum panel — the fixture's heavy evening.
 *  Chosen by measurement, not by index, so a fixture reshuffle cannot make
 *  the take click an empty day. */
function tallestDayBar(d: Director): HTMLElement | null {
  const bars = Array.from(
    d
      .find('[data-testid="pulse-detail"]')
      .querySelectorAll<HTMLElement>('button[aria-label$="show these on the board"]'),
  );
  let best: HTMLElement | null = null;
  for (const bar of bars) {
    if (!best || bar.clientHeight > best.clientHeight) best = bar;
  }
  return best;
}

const take = async (d: Director) => {
  await d.waitFor(() => d.query('button[aria-label^="Open "]'), 12000, "the board");
  await d.fitAll(0);
  d.say("Monday. The whole search in one frame — ask it what happened.");
  await d.hold(1600);

  d.enterCursor();
  const pulseTrigger = () => d.query('button[aria-controls="pulse-detail"]');
  await d.moveTo(pulseTrigger);
  d.say("The pulse holds the answer: filings, day by day.");
  await d.click(pulseTrigger);
  await d.waitFor(() => d.query('[data-testid="pulse-detail"]'), 5000, "the pulse panel");
  await d.hold(900);

  d.say("Press the heavy evening —");
  await d.click(() => tallestDayBar(d));
  await d.hold(500); // the board's own glide carries the survivors into place
  d.say("— and the board narrows to the applications filed that day.");
  await d.zoomTo(() => d.query('[data-testid="worklist-pane"]'), 1, 1500);
  await d.hold(1600);

  const kestrel = () => d.query('button[aria-label^="Open Kestrel Dynamics"]');
  await d.click(kestrel);
  await d.waitFor(() => d.query('[data-testid="application-detail"]'), 6000, "the detail pane");
  d.say("Open one: the assessment, its deadline, and every mail that led here.");
  await d.zoomTo(() => d.query('[data-testid="application-detail"]'), 1, 1600);
  await d.hold(2600);

  const clear = () => d.query('[data-testid="pulse-filter-band"] button');
  await d.moveTo(clear);
  d.say("Clear the day —");
  await d.click(clear);
  await d.fitAll(1600);
  d.say("— and the whole board breathes back. One sitting, no tab-hopping.");
  await d.hold(1000);
  d.hideCursor();
};

export function WorkdayOner() {
  const wide = useWideViewport();
  if (!wide) return <NarrowNote what="The oner" />;
  return (
    <TakeStage
      take={take}
      height={560}
      frameLabel="live fixture data — the shipped board, a synthesized pointer"
      opening="A continuous working session: filter to a day, open a row, read its history, clear."
    >
      <MarketingBoard />
    </TakeStage>
  );
}
