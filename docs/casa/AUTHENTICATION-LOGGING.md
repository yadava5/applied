# Authentication logging — systems of record and a sample

CASA AL1 evidence for **6.5.1** — a login/authentication log sample.

Read against production on **2026-08-15**.

**Nothing in this document is synthetic.** The sample in §3 is drawn from real
production rows; the direct identifiers are redacted at the query, and §3.2
says exactly what was removed and how an assessor can see the unredacted rows.

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
| 1 | `auth.sessions` (Postgres) | one row per established session: user, creation time, last refresh, IP, user agent, assurance level | production database | until session revocation/expiry; **17 rows** on 2026-08-15 |
| 2 | Supabase Auth logs | per-request auth events — sign-in attempts including **failures**, token refresh, sign-out | Supabase dashboard → Logs Explorer | **plan-dependent; see §4** |
| 3 | `auth.audit_log_entries` (Postgres) | GoTrue's own audit trail | production database | **empty — see §4** |

`auth.refresh_tokens` (53 rows) and `auth.flow_state` (22 rows) carry
supporting detail but are not the primary record.

### 2.1 The important caveat, stated up front

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

So the table that looks like the authentication audit log is not serving as
one. It is listed here because an assessor will query it and must not conclude
the answer is being hidden. What is actually load-bearing is `auth.sessions`
(§3) and the Supabase Auth logs (§4).

---

## 3. The sample

### 3.1 Six most recent sessions, redacted

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

### 3.2 What was redacted, and how to see it unredacted

| Field | In the table | Actually stored |
| --- | --- | --- |
| `user_id` | `user-<first 8 of md5>` | the real UUID |
| `ip` | presence + address family only | the full source IP |
| `user_agent` | first token only | the full UA string |
| `session id` | omitted | the real UUID |

The redaction is applied **in the query**, so the values above are the only
ones this repository has ever held. The unredacted rows are one `SELECT *`
away for an assessor with database access, and the owner can demonstrate that
live in a screen-share rather than committing personal data — including a
third party's IP address — to a git repository. That choice is deliberate:
committing a raw authentication log would create the disclosure the control
exists to prevent.

---

## 4. Retention — the open item

`auth.sessions` rows persist until the session is revoked or expires; the
oldest row in the sample is from 2026-07-18, so the effective window today is
about four weeks and is a function of user behaviour rather than a configured
policy.

Supabase Auth logs in the Logs Explorer are retained on a **plan-dependent
schedule** (short on the free tier, longer on paid tiers). **The owner must
confirm the project's current plan and the retention window that goes with it
before this control is filed** — it is the obvious follow-up question and this
document should not guess at the answer. This is flagged as an open item, not
answered.

That `auth.audit_log_entries` is empty (§2.1) most likely reflects the same
retention machinery, but that is an inference and is not asserted as fact.

---

## 5. Residual risk, stated plainly

- **Failed sign-in attempts are not visible in the database.** `auth.sessions`
  only records sessions that were *established*. Failures exist only in the
  Supabase Auth logs, under whatever retention §4 resolves to. There is no
  application-side record of a failed login and no alerting on repeated
  failures.
- **No MFA.** Every session in the sample is `aal1`. Supabase supports MFA;
  it is not enabled for this project.
- **The population is 2 users.** This log is evidence that the mechanism
  records what it should, not evidence of behaviour at scale.
- **`auth.audit_log_entries` being empty means the richest available audit
  shape is unavailable at query time**, leaving the dashboard as the only route
  to authentication *events* as opposed to authentication *outcomes*.

---

*Prepared 2026-08-15. Sample rows are real; direct identifiers were redacted in
the query and the redaction is enumerated in §3.2.*
