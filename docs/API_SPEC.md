# API Specification

Base URL: `https://<your-vercel-host>` (the web app reads it server-side as
`BACKEND_API_URL`; it never reaches the browser).

All endpoints return JSON.

> **This file used to document two contracts.** Everything under
> `## Auth (desktop)`, `## Sync`, `## Emails`, `## Classification and Review`,
> the desktop `## Applications` router, `## WebSocket` (`WS /ws/sync-status`)
> and `## Optional Analytics` described `backend/jobtracker/api/`, which was
> deleted with the macOS client (issue #73). Those routes now 404. They are
> removed rather than marked deprecated, because a spec for endpoints that do
> not exist is worse than no spec.
>
> **The authority is the generated document, not this page.**
> `scripts/generate_api_schema.sh` builds the OpenAPI spec by importing
> `jobtracker.main_cloud` and writes `apps/web/lib/api/schema.d.ts`;
> `e2e-ci.yml` fails on any diff. This file is prose for the parts that are
> easier to state than to read out of a schema, and it can go stale where the
> generated bindings cannot.

## Authentication (required on every endpoint except `/health` and `/`)

Cloud requests must include a Supabase-issued JWT:

```
Authorization: Bearer <supabase-jwt>
```

- **Signing.** HS256 with the Supabase project JWT secret
  (`JOBTRACKER_SUPABASE_JWT_SECRET` on the backend).
- **Claims.** The backend requires `sub` (user UUID), `aud` =
  `"authenticated"`, and a non-expired `exp`. Other Supabase
  claims (`role`, `iat`, `session_id`) are accepted but not checked.
- **Failure modes.** Missing header, non-`Bearer` scheme, bad
  signature, expired token, wrong audience, or `sub` that is not a
  UUID → `401 Unauthorized` with body
  `{"detail": "<short reason>"}` and header `WWW-Authenticate:
  Bearer`.

There is no unauthenticated read path. Every router under
`jobtracker/cloud/` is mounted with a router-level `require_user()`
dependency, so a handler cannot skip auth by forgetting a decorator.

### `GET /auth/me`

Echoes the authenticated user UUID. Use as a smoke check after deploy
to prove the JWT is decoding correctly.

Response:

```json
{ "user_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "authenticated": true }
```

### `GET /applications`

Returns applications owned by the authenticated user. Rows created
by other users are never visible (enforced by both the
application-level `user_id` filter and Postgres RLS).

Response:

```json
{
  "applications": [
    { "id": 1, "user_id": "...", "company": "Acme", "position": "SWE", "status": "applied", "notes": null, "created_at": "2026-04-18T..." }
  ],
  "total": 1
}
```

### `POST /applications`

Creates an application scoped to the authenticated user. The
`user_id` column is set from the JWT `sub` claim; any `user_id`
sent in the request body is ignored.

Request:

```json
{ "company": "Acme", "position": "SWE", "status": "applied", "notes": null }
```

## Health

### `GET /health`

Returns backend, DB, account, and classifier status. Unauthenticated (no
`Authorization` header required) so uptime monitors can probe it.

### `GET /health/schema`

Reports whether the database schema is at the revision the running code
expects.

## The full route table

Enumerated from the app `api/index.py` serves, by walking `app.routes` and
resolving each handler to its defining module. **28 routes, four modules.**
Regenerate rather than hand-edit this list if it looks wrong — the walk is in
`backend/tests/test_the_deployed_app_is_the_cloud_app.py`, which also fails the
build if any route arrives from a module outside `jobtracker.cloud`.

| Method | Path | Defined in |
| --- | --- | --- |
| `GET` | `/` | `main_cloud` |
| `GET` | `/auth/me` | `main_cloud` |
| `GET` | `/health` | `main_cloud` |
| `GET` | `/health/schema` | `main_cloud` |
| `GET` `POST` | `/applications` | `cloud.applications` |
| `GET` | `/applications/mail` | `cloud.applications` |
| `GET` | `/applications/review` | `cloud.applications` |
| `POST` | `/applications/review/{message_id}/classify` | `cloud.applications` |
| `GET` | `/applications/statuses` | `cloud.applications` |
| `GET` | `/applications/summary` | `cloud.applications` |
| `GET` `PATCH` `DELETE` | `/applications/{application_id}` | `cloud.applications` |
| `PUT` | `/applications/{application_id}/deadline` | `cloud.applications` |
| `POST` | `/applications/{application_id}/dismiss` | `cloud.applications` |
| `POST` | `/applications/{application_id}/restore` | `cloud.applications` |
| `PUT` | `/applications/{application_id}/role` | `cloud.applications` |
| `POST` | `/applications/{application_id}/split` | `cloud.applications` |
| `GET` `POST` | `/cron/sync` | `cloud.cron` |
| `GET` | `/auth/gmail/authorize` | `cloud.gmail_oauth` |
| `GET` | `/auth/gmail/callback` | `cloud.gmail_oauth` |
| `POST` | `/auth/gmail/disconnect` | `cloud.gmail_oauth` |
| `GET` | `/auth/gmail/status` | `cloud.gmail_oauth` |
| `GET` | `/gmail/inbox` | `cloud.gmail_oauth` |
| `POST` | `/gmail/pipeline` | `cloud.gmail_oauth` |
| `POST` | `/gmail/sync` | `cloud.gmail_oauth` |
| `DELETE` | `/account` | `cloud.account` |

`/applications/statuses` is declared above `GET /{application_id}` on purpose,
so it is not parsed as an application whose id is the string `statuses`.

`GET /openapi.json`, `/docs` and `/redoc` are **opt-in** and absent unless
`JOBTRACKER_ENABLE_DOCS` is set — see
`backend/tests/test_api_docs_are_opt_in.py`.

