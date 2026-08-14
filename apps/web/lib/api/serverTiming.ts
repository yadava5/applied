/**
 * Carry the backend's `Server-Timing` header through the same-origin proxy.
 *
 * The FastAPI app has reported where each request's time went since #203 —
 * `app`, `db_connect;desc="n=N"`, `db_query;desc="n=N"`, emitted on every
 * response by `_ServerTimingMiddleware` in `backend/jobtracker/main_cloud.py`.
 * The browser never saw any of it: the route handlers under `app/api/**`
 * answer with a `NextResponse.json(...)` built from the PARSED body, which is
 * a brand-new response with brand-new headers, so the instrument was only
 * readable by curling the backend directly — exactly the reach that #203's
 * measurements had to be taken by hand (#269).
 *
 * WHAT THE NUMBERS MEAN AFTER THE COPY. They are the BACKEND's time, not this
 * request's: the same-origin hop (Vercel edge → this handler → FastAPI → back)
 * is not in them, so `app;dur` read in devtools is always smaller than the
 * network panel's timing for the `/api/...` call. That gap is the thing worth
 * seeing — it is where the platform routing #203 measured separately at
 * ~130 ms lives.
 *
 * The phase names are copied VERBATIM — not prefixed, not namespaced. A
 * `backend_app` here and an `app` on a direct curl would be two names for one
 * measurement, and the first question anyone asks of this header is whether
 * the proxy's number matches the backend's. It only reads as the same number
 * if it is spelled the same way.
 *
 * NOTHING IS SYNTHESIZED. When there is no backend response — an unauthenticated
 * short-circuit, a network failure, a bad id rejected before the fetch — the
 * proxied response is returned untouched. A header invented here would be a
 * measurement of nothing wearing the name of a real one.
 *
 * Deliberately NOT applied to `app/api/applications/route.ts`'s GET (the data
 * export): that handler fans out into as many backend reads as the account has
 * pages, and one `Server-Timing` cannot describe N round trips. Copying any
 * single page's header there would ship a number whose name lies about what it
 * measured.
 */

/** Lower-case because `Headers` matches case-insensitively; this is the wire spelling. */
const SERVER_TIMING = "server-timing";

/**
 * Copy `Server-Timing` from the backend response onto the response this proxy
 * is about to return, and hand that response back so it can be returned inline:
 *
 * ```ts
 * const r = await getReviewQueue();
 * return withServerTiming(r.response, NextResponse.json(r.data ?? {}, { status: r.status }));
 * ```
 *
 * `backend` is typed structurally rather than as `Response` so it accepts both
 * transports this app proxies through: the raw `fetch` responses the helpers in
 * `lib/applications/server.ts` and `lib/gmail/server.ts` hand back, and
 * openapi-fetch's `res.response`.
 */
export function withServerTiming<T extends Response>(
  backend: { headers: Headers } | null | undefined,
  proxied: T,
): T {
  const timing = backend?.headers.get(SERVER_TIMING);
  if (timing) proxied.headers.set(SERVER_TIMING, timing);
  return proxied;
}
