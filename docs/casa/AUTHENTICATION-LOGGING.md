# Authentication logging — systems of record and a sample

CASA AL1 evidence for **6.5.1** — a login/authentication log sample.

Read against production on **2026-08-15**; the audit-log evidence in §2.1 and
§3.1 was read on **2026-08-16** and the database figures re-run the same day.

**Nothing in this document is synthetic.** The samples in §3 are drawn from real
production events and rows; the direct identifiers are redacted at the query, and
§3.3 says exactly what was removed and how an assessor can see the unredacted
originals.

---

## 1. Where authentication happens

Applied does not implement authentication. Identity is Supabase Auth (GoTrue);
the application never sees a password and holds no password-handling code. Two
identity providers are configured — email/password and Google.

Consequently the authentication log is **Supabase's**, not the application's.
The application's own logs record authorisation decisions and secret access
(see [`SECRET-ACCESS-POLICY.md`](SECRET-ACCESS-POLICY.md)), not logins.

---

## 2. The three systems of record

| # | System | What it records | Where | Retention |
| --- | --- | --- | --- | --- |
| 1 | **`auth_audit_logs`** (log stream) | GoTrue's audit events — `login`, `token_refreshed`, `token_revoked` — each with actor identity, user agent and request id | Supabase Logs Explorer | plan-dependent; see §4 |
| 2 | `auth.sessions` (Postgres) | one row per established session: user, creation time, last refresh, IP, user agent, assurance level | production database | until session revocation/expiry; **17 rows** on 2026-08-15 |
| 3 | `auth_logs` (log stream) | GoTrue server logs — per-request auth activity, including sign-in **failures**, which the audit stream does not carry | Supabase Logs Explorer | plan-dependent; see §4 |
| 4 | `auth.audit_log_entries` (Postgres) | GoTrue's audit trail *when Postgres storage is enabled* — it is not enabled here | production database | **empty; not a system of record for this project — see §2.1** |

`auth.refresh_tokens` (53 rows) and `auth.flow_state` (22 rows) carry
supporting detail but are not the primary record.

### 2.1 The empty table, and why it is not the gap it looks like

**`auth.audit_log_entries` contains zero rows**, despite both users having
signed in and the most recent sign-in being 2026-08-15:

```sql
SELECT count(*) AS total, min(created_at) AS earliest, max(created_at) AS latest
FROM auth.audit_log_entries;
--  0 | NULL | NULL
```

```sql
SELECT count(*) AS users, count(last_sign_in_at) AS with_signin,
       max(last_sign_in_at) AS most_recent_signin
FROM auth.users;
--  2 | 2 | 2026-08-15 05:44:10+00
```

Both re-run 2026-08-16; both unchanged.

**The auditing is not off — only the Postgres copy of it is.** Supabase stores
auth audit logs in two places by default: this table, and an external log store
reachable as the `auth_audit_logs` source in the Logs Explorer. Writing to the
table is a **per-project toggle** — Authentication → Audit Logs →
Configuration, *"Disable writing auth audit logs to project database"* — and
disabling it leaves the external stream intact
([Supabase: Auth Audit Logs](https://supabase.com/docs/guides/auth/audit-logs)).
The external stream is populated: **44 events in the last 24 hours**, including
a real `login` (§3.1).

Two things follow, and both matter to an assessor:

- The empty table is a **storage-destination** fact, not a retention fact and
  not evidence that authentication events go unrecorded. An earlier draft of
  this document guessed that plan-based retention explained the emptiness. That
  guess was wrong — retention governs the Logs Explorer collections, not this
  table — and it has been removed rather than re-hedged.
- **This document does not cite `auth.audit_log_entries` as evidence for
  anything.** Citing an empty table would be a false claim regardless of the
  explanation for why it is empty. It is listed only because an assessor will
  query it and must not conclude the answer is being hidden.

**Open item — the toggle's current state was not read.** The behaviour above is
Supabase's documented mechanism and the observed outcome is consistent with it,
but confirming *which* setting is in force needs the project dashboard or a
management API token, and neither was used for this pass. The owner should read
Authentication → Audit Logs → Configuration and record the setting here.

---

## 3. The sample

Two views of the same authentications: the audit events (§3.1) and the sessions
they established (§3.2). Both are redacted in the query; §3.3 enumerates what
was removed.

### 3.1 The authentication audit events

Read from the `auth_audit_logs` source on **2026-08-16**, covering the
preceding 24 hours. Every event carries the same field set — all 44 events have
`action`, `log_type`, `actor_id`, `actor_username`, `actor_name`,
`actor_via_sso`, `user_agent`, `request_id`, `audit_log_id` and `created_at`;
`traits.provider` appears on the `login` alone.

```sql
SELECT log_attributes['auth_audit_event.action']   AS action,
       log_attributes['auth_audit_event.log_type'] AS log_type,
       count() AS n
FROM logs WHERE source = 'auth_audit_logs'
GROUP BY action, log_type ORDER BY n DESC;
```

| action | log_type | n |
| --- | --- | --- |
| `token_refreshed` | token | 36 |
| `token_revoked` | token | 7 |
| **`login`** | **account** | **1** |

The `login` event, redacted in the query with the same pseudonym function used
in §3.2:

| field | value |
| --- | --- |
| `created_at` | 2026-08-15T05:44:10Z |
| `action` | `login` |
| `log_type` | `account` |
| `actor_id` | `user-148bb673` (pseudonym) |
| `actor_username` | present — redacted, it is a real email address |
| `actor_name` | present — redacted |
| `actor_via_sso` | `false` |
| `traits.provider` | `email` |
| `user_agent` | `Mozilla…` (first token only) |
| `request_id` | present — redacted |
| `audit_log_id` | present — redacted |
| `level` | `info` |

**This is the sample control 6.5.1 asks for**: a successful authentication,
attributable to an actor, with the provider that authenticated it, a user
agent, a request id and a timestamp.

It also cross-checks against the other two systems of record. The same
authentication appears three times, consistently: as this `login` event, as the
newest `auth.sessions` row in §3.2, and as `auth.users.last_sign_in_at` — all
three at `2026-08-15T05:44:10Z` for the same pseudonym. The `token_refreshed`
and `token_revoked` events at `2026-08-16T01:37:43Z` are refresh-token
rotation on the long-lived `node` session, which is the same behaviour §3.2
reads off that row's `refreshed_at`.

**What this source does *not* record: failed sign-ins.** GoTrue's documented
action list has no failure action, and none of the 44 observed events is one.
Failures are visible in `auth_logs`, not here — see §5.

### 3.2 Six most recent sessions, redacted

```sql
SELECT to_char(created_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"')        AS created_at,
       ('user-' || substr(md5(user_id::text),1,8))             AS user_pseudonym,
       aal::text,
       (ip IS NOT NULL)                                        AS ip_recorded,
       family(ip)                                              AS ip_family,
       split_part(split_part(user_agent,' ',1),'/',1)          AS ua_product,
       to_char(refreshed_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"')      AS refreshed_at
FROM auth.sessions ORDER BY created_at DESC LIMIT 6;
```

| created_at | user_pseudonym | aal | ip_recorded | ip_family | ua_product | refreshed_at |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-08-15T05:44:10Z | user-148bb673 | aal1 | true | 4 | Mozilla | — |
| 2026-08-14T23:27:46Z | user-148bb673 | aal1 | true | 4 | Mozilla | — |
| 2026-08-14T06:30:47Z | user-148bb673 | aal1 | true | 4 | Mozilla | — |
| 2026-08-12T02:55:35Z | user-148bb673 | aal1 | true | 4 | node | 2026-08-16T01:37:43Z |
| 2026-07-18T01:04:36Z | user-c6a06885 | aal1 | true | 4 | Mozilla | — |
| 2026-07-18T01:00:08Z | user-c6a06885 | aal1 | true | 4 | curl | — |

Reading it: two distinct users; every session records a source IP and a user
agent; all sessions are `aal1` (single factor — see §5); the `node` and `curl`
user agents are the owner's own tooling against production, and the
`refreshed_at` on the `node` row shows refresh-token rotation working on a
session established four days earlier.

### 3.3 What was redacted, and how to see it unredacted

| Field | In the tables above | Actually stored |
| --- | --- | --- |
| `user_id` / `actor_id` | `user-<first 8 of md5>` | the real UUID |
| `ip` | presence + address family only | the full source IP |
| `user_agent` | first token only | the full UA string |
| `session id` | omitted | the real UUID |
| `actor_username`, `actor_name` | presence only | a real email address, and a display name |
| `request_id`, `audit_log_id` | presence only | the real identifiers |

The redaction is applied **in the query**, so the values above are the only
ones this repository has ever held. The unredacted rows are one `SELECT *`
away for an assessor with database access, and the owner can demonstrate that
live in a screen-share rather than committing personal data — including a
third party's IP address — to a git repository. That choice is deliberate:
committing a raw authentication log would create the disclosure the control
exists to prevent.

---

## 4. Retention — the open item

Three different things are called "audit logs" around Supabase, and conflating
them is what produced the wrong inference this document previously carried. They
are separated here.

| Product | What it is | State for this project |
| --- | --- | --- |
| `auth_audit_logs` (Logs Explorer) | GoTrue's authentication audit events — the §3.1 sample | **Available and populated.** Retention is plan-dependent and **unconfirmed** |
| `auth.audit_log_entries` (Postgres) | the optional in-database copy of the same events | **Empty** — storage destination, not retention (§2.1) |
| Organization Audit Logs | the *platform* audit trail: who changed project settings, members, keys | **Not available.** The owner's dashboard reads: "Organization Audit Logs are not available on Free or Pro plans. Upgrade to Team or Enterprise to view up to 62 days of Audit Logs for your organization" |

`auth.sessions` rows persist until the session is revoked or expires; the
oldest row in the sample is from 2026-07-18, so the effective window today is
about four weeks and is a function of user behaviour rather than a configured
policy.

**Retention for the Logs Explorer collections is plan-dependent and no number
is asserted here.** The organisation is on Free or Pro — the dashboard message
above establishes that much, since the platform audit log is withheld on both —
but the exact tier and the retention window that follows from it were not read.
**The owner should record the plan and its log retention window before this
control is filed.** This document will not guess at it; naming a window that
turned out to be wrong is the failure mode this section exists to avoid.

Two further limits on the audit stream, both from Supabase's own
documentation: there may be a short delay before events appear, and query
access is through the dashboard's interface rather than a general export.

---

## 5. Residual risk, stated plainly

- **Failed sign-in attempts appear in no audit record.** `auth.sessions` only
  records sessions that were *established*, and the `auth_audit_logs` stream
  carries no failure action (§3.1). Failures are visible only in the `auth_logs`
  server logs, under whatever retention §4 resolves to. There is no
  application-side record of a failed login and no alerting on repeated
  failures.
- **No MFA.** Every session in the sample is `aal1`. Supabase supports MFA;
  it is not enabled for this project.
- **The population is 2 users.** This log is evidence that the mechanism
  records what it should, not evidence of behaviour at scale.
- **The authentication audit trail is vendor-held and not exportable to an
  independent archive at this tier.** Because the Postgres copy is not being
  written (§2.1), `auth_audit_logs` in the dashboard is the only route to
  authentication *events* as opposed to authentication *outcomes* — it cannot
  be joined against application data in SQL, and its retention is unconfirmed
  (§4). The same structural limitation is recorded for secret access in
  [`SECRET-ACCESS-POLICY.md`](SECRET-ACCESS-POLICY.md) §4.
- **No platform audit trail.** Organization Audit Logs — who changed project
  settings, rotated a key, or added a member — are not available on this plan
  (§4). Changes to the Supabase project's own configuration are therefore not
  audited at all.

---

*Prepared 2026-08-15. Sample rows are real; direct identifiers were redacted in
the query and the redaction is enumerated in §3.3.*
