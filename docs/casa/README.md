# CASA AL1 evidence pack

Written narrative evidence for the CASA assessment that accompanies Applied's
Google restricted-scope review. A control passing is not the same as a control
being filable; these are the documents an assessor asks for and that did not
previously exist in written form.

| Document | Controls | State |
| --- | --- | --- |
| [`ARCHITECTURE-AND-TENANT-ISOLATION.md`](ARCHITECTURE-AND-TENANT-ISOLATION.md) | 3.1.1, 3.1.2, 3.1.3 | met |
| [`CRYPTOGRAPHY.md`](CRYPTOGRAPHY.md) | 4.1.3 | met, with no key rotation |
| [`AUTHENTICATION-LOGGING.md`](AUTHENTICATION-LOGGING.md) | 6.5.1 | met — the sample is the live audit event stream, not the empty `auth.audit_log_entries` table |
| [`SECRET-ACCESS-POLICY.md`](SECRET-ACCESS-POLICY.md) | 6.7.1 | **partially met** |
| [`SESSION-COOKIES.md`](SESSION-COOKIES.md) | 2.3.1, 2.3.2 | **partially met** |

The Google-facing restricted-scope justification is a separate document with a
different audience — it is written to be pasted into the OAuth verification
form — and lives at
[`../google/RESTRICTED-SCOPE-JUSTIFICATION.md`](../google/RESTRICTED-SCOPE-JUSTIFICATION.md).

## How to read these

Every one of them was written against **production**, read on **2026-08-15**,
not against the migrations or the source alone. Three conventions hold
throughout:

- **Live figures carry their `N` and their query.** Where a number is a
  snapshot of production data rather than an invariant, it says so and the SQL
  is reproduced inline so it can be re-run.
- **Claims cite `file:line`.** A reviewer should never have to take a
  behavioural claim on trust when a citation would settle it.
- **Each document ends with a "residual risk" section that is meant to be
  read.** Known gaps — no key rotation, one non-user-scoped policy, no
  tamper-evident archive of secret access — are stated in the documents rather
  than left for an assessor to discover. Anything marked **open item** needs a
  decision from the owner before filing.
- **A control the deployment does not have is not claimed.** Where a
  compensating control turned out to be a plan-gated product this account has
  no access to, it was deleted and the gap stated, not reworded into something
  that reads like coverage. Two such corrections are recorded in place:
  `SECRET-ACCESS-POLICY.md` §3.2 and `AUTHENTICATION-LOGGING.md` §2.1.

## Open items, collected

| Item | Where |
| --- | --- |
| Fernet key rotation is not implemented; rotating today forces every user to reconnect | `CRYPTOGRAPHY.md` §3.3 |
| One key serves both credential encryption and OAuth `state` signing | `CRYPTOGRAPHY.md` §3.4 |
| `anon` retains a grant on `gmail_sync_enrollment` — inert, but drift | `ARCHITECTURE-AND-TENANT-ISOLATION.md` §4.1 |
| Logs Explorer retention is plan-dependent; the plan and its window must be read from the dashboard and recorded — no number is asserted | `AUTHENTICATION-LOGGING.md` §4 |
| The auth audit-log **database-write toggle** was not read; the mechanism explains the empty table but the setting itself is unconfirmed | `AUTHENTICATION-LOGGING.md` §2.1 |
| No independent tamper-evident archive of secret access, and no export or SIEM streaming at this tier — Vercel's Activity Log is a vendor event feed with no documented retention | `SECRET-ACCESS-POLICY.md` §3.2, §4 |
| Organization Audit Logs (Supabase) and Audit Logs (Vercel) are both Enterprise/Team-tier products this deployment does not have, so platform configuration changes are unaudited | `AUTHENTICATION-LOGGING.md` §4, `SECRET-ACCESS-POLICY.md` §3.2 |
| `HttpOnly` cannot be set on the auth cookie without re-architecting authentication | `SESSION-COOKIES.md` §3 |
| The CSP allows `script-src 'unsafe-inline'`, weakening the main compensating control for the above | `SESSION-COOKIES.md` §3.1 |
| No seeded test account, so no CI test ever exercises a signed-in session | `SESSION-COOKIES.md` §5 |
| `ml/demo/space/jobtracker/credentials/cloud.py` is a vendored copy of the credential module and does not carry the access logging | `SECRET-ACCESS-POLICY.md` §3.1 |
