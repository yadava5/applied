/**
 * The confidence gate: below this, nothing is auto-filed.
 *
 * It lives in its own module for one reason — it is a PRODUCT constant, and it
 * used to be defined in `lib/demo/sampleInbox.ts`, alongside the eleven
 * fixture emails that module exists to hold. `components/import/ImportMail.tsx`
 * imports it at the top level and renders on the public `/import` route, so
 * every reader of that page was served the invented mail as the price of one
 * float — the same defect `lib/gmail/transport.ts` documents having measured
 * in a production build, and the same one #495 fixed in
 * `lib/settings/transport.ts`. A number cannot be loaded behind an
 * `await import()` the way a fixture board can, so the fix is to give it a
 * home with nothing else in it.
 *
 * There is still exactly ONE definition: `lib/demo/sampleInbox.ts` re-exports
 * this binding rather than restating the value, and
 * `scripts/readme_facts.py`'s TypeScript gate census — which fails on an
 * unregistered copy — points at this file now.
 *
 * The value itself is `CONFIDENCE_AUTO` in the backend. Do not change it here
 * alone; `readme_facts.py` holds every copy across all three trees in lockstep.
 */
export const GATE = 0.85;
