import { NextResponse } from "next/server";

/**
 * What commit is this deployment running?
 *
 * WHY IT EXISTS. `scripts/check_production_drift.py` compares what production
 * is RUNNING against what `main` says it should be running, because merges to
 * this repository have produced no deployment, silently, more than once. For
 * `jobtracker-api` that comparison costs nothing: `GET /health` reports the
 * commit straight from Vercel's own `VERCEL_GIT_COMMIT_SHA`. The web app had
 * no equivalent, so its only answer came from the Vercel REST API — and that
 * needs a token.
 *
 * On 2026-08-22 the token stopped authenticating (HTTP 403, SAML re-auth for
 * scope `aesh0323-7401s-projects`) and every scheduled run has been red since,
 * twice an hour. The api half kept answering through the identical 403. That
 * asymmetry is the whole argument for this route: the fact worth knowing is
 * observable from outside Vercel, for free, and tying it to a credential made
 * the check fail for a reason that has nothing to do with what it watches.
 *
 * A MISSING ROUTE MUST STILL READ AS UNKNOWN. Until this deploys, production
 * 404s here — `running_commit_from_health` treats any non-answer as "no commit
 * observed", falls back to the Vercel API, and reports UNKNOWN rather than OK.
 * That is correct and it means one more red run after this merges, not a check
 * that suddenly passes.
 *
 * `VERCEL_GIT_COMMIT_SHA` is null for a CLI deploy, or where the project has
 * "Automatically expose System Environment Variables" turned off. Both are real
 * states rather than failures, and the detector says so; reporting null is
 * therefore better than inventing a fallback.
 */
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json(
    {
      commit: process.env.VERCEL_GIT_COMMIT_SHA ?? null,
      ref: process.env.VERCEL_GIT_COMMIT_REF ?? null,
      env: process.env.VERCEL_ENV ?? null,
    },
    {
      // The answer is per-deployment and the question is "what is running RIGHT
      // NOW", so a cached copy is the one thing this must never serve. A stale
      // sha here would make the detector report drift that had already been
      // fixed, or — far worse — silence real drift behind a CDN entry minted
      // before it happened.
      headers: { "Cache-Control": "no-store, max-age=0" },
    },
  );
}
