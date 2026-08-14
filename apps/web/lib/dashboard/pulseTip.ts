/**
 * The pulse charts' tooltip vocabulary — one derivation for what a drawn unit
 * says when pointed at (#195). The native `title` these replace waited out the
 * OS's own hover delay and set `Tue Aug 11 — 17 filed` in one line at one
 * weight, so neither the figure nor its day read first. A tip is structured
 * instead: the FIGURE leads, the words that own it bind it forward (the band's
 * caption grammar), and the when/qualifier sits beneath as its label.
 *
 * This is the pointer's rendering only. The bars' aria-labels keep their own
 * label-first sentences — they read better spoken, and shell.spec pins two of
 * them — so the two are parallel voicings of the same values, built at the
 * same call sites.
 *
 * `.ts` import specifiers, same as `pulseFilter.ts`, so `node --test` can
 * load this under type stripping.
 */
import { QUIET_AFTER_DAYS, weekdayOf } from "./age.ts";
import { shortDate } from "./dates.ts";
import { DUE_SOON_WORDS, duePhrase, type DeadlineBin } from "./deadline.ts";

/** What a chart tip says: the figure, the words that own it, and the
 *  when/qualifier line beneath them (absent where the words already say when). */
export interface PulseTip {
  count: number;
  words: string;
  label?: string;
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

/** `Tue Aug 5` — weekday first, because weekday structure ("my Tuesdays are
 *  heavy") is half of what a daily chart is for. */
export function dayName(iso: string): string {
  const wd = weekdayOf(iso);
  return wd === null ? shortDate(iso) : `${WEEKDAYS[wd]} ${shortDate(iso)}`;
}

/** A momentum day bar: N filed, on the named day. */
export function momentumTip(date: string | null, count: number): PulseTip {
  return date === null ? { count, words: "filed" } : { count, words: "filed", label: dayName(date) };
}

/** An age histogram bin: N open, qualified by when they were filed. The
 *  overflow bin (≥ {@link QUIET_AFTER_DAYS}) is the same quiet threshold that
 *  tags the individual cards. */
export function ageTip(binAge: number, count: number): PulseTip {
  const label =
    binAge >= QUIET_AFTER_DAYS
      ? "filed 2 wk or more ago"
      : binAge === 0
        ? "filed today"
        : `filed ${binAge} d ago`;
  return { count, words: "open", label };
}

/** A runway column: `duePhrase`/the window words already say when, so a
 *  second label line would only repeat them. */
export function runwayTip(bin: DeadlineBin): PulseTip {
  if (bin.kind === "overdue") return { count: bin.count, words: "overdue" };
  if (bin.kind === "later") return { count: bin.count, words: `due after ${DUE_SOON_WORDS}` };
  return { count: bin.count, words: duePhrase(bin.days) };
}
