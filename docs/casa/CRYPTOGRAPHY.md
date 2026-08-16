# Cryptography in use

CASA AL1 evidence for **4.1.3** — the algorithms in use, how keys are managed,
and how they are rotated.

Read against production on **2026-08-15**. No key, token or ciphertext appears
in this document; where a value would have been quoted it is described instead
and the redaction is noted.

---

## 1. Summary

| Purpose | Algorithm | Key material | Managed by | Rotation |
| --- | --- | --- | --- | --- |
| Data in transit | TLS 1.3 (`AEAD-CHACHA20-POLY1305-SHA256` observed) | — | Vercel / Supabase | Provider-managed |
| Stored OAuth tokens & app passwords | Fernet — AES-128-CBC + HMAC-SHA256 | `JOBTRACKER_SECRET_ENCRYPTION_KEY` | This application | **Not implemented — see §3.3** |
| Session / API tokens | JWT, **ES256** (ECDSA P-256, SHA-256) | Supabase project signing key | Supabase Auth | Supabase-managed |
| Password storage | bcrypt (`$2a$`, 60-char digest) | per-password salt | Supabase Auth | n/a |
| Data at rest (volume) | AES-256 | — | Supabase / AWS | Provider-managed |
| OAuth `state` integrity | JWT, **HS256** (HMAC-SHA256) | `JOBTRACKER_SECRET_ENCRYPTION_KEY` — *the same key* | This application | shares §3.3's limitation |

The only cryptography this application implements itself is the Fernet
envelope over stored credentials. Everything else is a platform primitive,
which is deliberate.

---

## 2. Data in transit

All three legs are HTTPS: browser → Next.js, Next.js → FastAPI, FastAPI →
Supabase and → Google. Probed on 2026-08-15, `getapplied.vercel.app` negotiated
**TLS 1.3** with `AEAD-CHACHA20-POLY1305-SHA256`.

HSTS is declared for two years with subdomains and preload:

```
strict-transport-security: max-age=63072000; includeSubDomains; preload
```

(`vercel.json`, `headers` block; observed on the wire on the production
response.)

There is no plaintext transport anywhere in the deployed path. There is no
local process and no loopback listener in production.

---

## 3. Stored credentials — the one envelope this application owns

### 3.1 What is encrypted

Gmail OAuth tokens (`kind = "gmail_oauth"`) and iCloud app-specific passwords
(`kind = "icloud_mail"`), one row per `(user_id, kind)` in `user_credentials`.
These are the only user-owned secrets the system stores. Message bodies are not
stored at all — see
[`ARCHITECTURE-AND-TENANT-ISOLATION.md`](ARCHITECTURE-AND-TENANT-ISOLATION.md)
§2.2.

### 3.2 Algorithm

`cryptography.fernet.Fernet` (`backend/jobtracker/credentials/cloud.py:42`).
Fernet is a specified construction, not a bespoke one:

- **AES-128 in CBC mode** with PKCS7 padding for confidentiality,
- **HMAC-SHA256** over the whole token for integrity and authenticity,
- a **128-bit IV generated per message**, carried in the token itself,
- encrypt-then-MAC, verified before decryption, so a tampered ciphertext raises
  `InvalidToken` rather than returning damaged plaintext.

The key is 32 bytes, urlsafe-base64 encoded — 16 bytes of AES key and 16 bytes
of HMAC key. It is generated with `Fernet.generate_key()`.

The `nonce` column on `user_credentials` is stored as an **empty byte string**
and is not used. Fernet embeds its own IV in the token, so no separate nonce is
required. The column is reserved for a future AEAD upgrade (for example
ChaCha20-Poly1305) that would need one.
(`backend/jobtracker/credentials/cloud.py:24-27`)

Verified against production on 2026-08-15 — the stored state matches the
description exactly:

```sql
SELECT kind, key_id, length(nonce) AS nonce_len, length(ciphertext) AS ct_len
FROM user_credentials;
--  gmail_oauth | v1 | 0 | 804
```

One credential row exists, it is Gmail, it records key `v1`, its `nonce` is
zero bytes, and the ciphertext is opaque. **No plaintext, no key and no
ciphertext content was read to produce this — only lengths and the key
identifier**, which is why the query selects `length(...)` rather than the
columns themselves.

### 3.3 Key management, and the honest state of rotation

The key is supplied as the environment variable
`JOBTRACKER_SECRET_ENCRYPTION_KEY`, read through
`settings.secret_encryption_key`. It is injected by Vercel at **deploy time**,
is never written to the repository, and has exactly **one read site** in the
codebase: `_require_fernet()` at
`backend/jobtracker/credentials/cloud.py:64`. Every encrypt and every decrypt
goes through that function.

If the key is absent or malformed, `_require_fernet()` raises
`CredentialEncryptionError` with a message naming the variable and **not** its
value.

**Rotation is scaffolded but not implemented, and this document will not claim
otherwise.** The specifics:

- `ACTIVE_KEY_ID = "v1"` (`cloud.py:57`) is written to the `key_id` column on
  every credential row, so every ciphertext records which key produced it.
- The code builds **one** `Fernet` from **one** key. There is no `MultiFernet`,
  no key list, and no decrypt-with-old-then-re-encrypt path. The design for one
  is described in the module docstring (`cloud.py:29-32`) — decrypt tries the
  active key, falls back through old keys, and re-encrypts the row on a
  successful old-key decrypt — but that code does not exist today.

**The operational consequence, which is the real finding here.** Rotating
`JOBTRACKER_SECRET_ENCRYPTION_KEY` today invalidates every stored ciphertext at
once. The failure is not a crash: `get_gmail_credentials` catches
`InvalidToken`, logs a warning and returns `None`
(`cloud.py:285-295`), and the same shape applies to the iCloud path
(`cloud.py:372-382`). So the observable effect of a rotation is that **every
user silently appears to have no Gmail connection** and must reconnect. Because
Vercel injects environment variables at deploy time, the change also does not
take effect until a deployment runs.

Mitigating facts, offered as context and not as a substitute for rotation:

- The blast radius is bounded. The stored secret is an OAuth **refresh token
  scoped to `gmail.readonly`**, not a password and not a credential that grants
  write access to the user's mailbox. It can be revoked at Google independently
  of this key, and account deletion does exactly that before purging the row
  (`backend/jobtracker/cloud/account.py`).
- Recovery from a rotation is self-service: the user reconnects Gmail, and
  reconnecting also clears `revoked_at`, so a reconnected user is immediately
  visible to the scheduled sync again (`cloud.py:113-124`).

**Recommended remediation, not yet done:** implement `MultiFernet` with an
ordered key list read from a comma-separated environment variable, keyed by the
`key_id` column that already exists. This is additive and does not require a
schema change. Until it lands, the correct answer to "how do you rotate this
key" is "with a planned reconnection for every user", and that is what is
recorded here.

### 3.4 One key, two purposes — disclosed

`JOBTRACKER_SECRET_ENCRYPTION_KEY` is used for **two** unrelated cryptographic
jobs:

1. the Fernet envelope over stored credentials (§3.2), and
2. signing the Gmail OAuth `state` parameter, which is a JWT signed **HS256**
   (`backend/jobtracker/cloud/gmail_oauth.py:566`) and verified at `:594`.

Reusing one key across two constructions is not a break here — Fernet derives
distinct AES and HMAC halves from its 32 bytes, and PyJWT's HS256 takes the
same material as an opaque HMAC secret, so the two never produce colliding
outputs — but it is poor hygiene and it is disclosed rather than left to be
found. It also couples the two: the rotation problem in §3.3 would invalidate
in-flight OAuth `state` tokens as well as stored credentials. In-flight state
is short-lived, so that limb of the impact is minutes, not permanent.

**Recommended remediation, not yet done:** derive two subkeys via HKDF with
distinct info strings, or introduce a second environment variable for state
signing. Either is a small change; neither has been made.

### 3.5 Access to the encrypted material

Access to `user_credentials` is logged; the policy, the log shape and the
compensating controls for the key itself are in
[`SECRET-ACCESS-POLICY.md`](SECRET-ACCESS-POLICY.md).

Row access is additionally constrained by RLS: `user_credentials` carries
`ENABLE` + `FORCE ROW LEVEL SECURITY` and 4 policies, and production connects
as `jobtracker_app`, which is `NOBYPASSRLS`.

---

## 4. Identity tokens

Supabase issues a JWT per signed-in user. The backend verifies it on **every**
request; there is no session cache and no trust-on-first-use.

Production signs with **ES256**. Read live from the project's JWKS on
2026-08-15:

```
GET https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json
→ { "alg": "ES256", "kty": "EC", "crv": "P-256", "use": "sig", "key_ops": ["verify"], … }
```

(The key's `kid` and public coordinates are omitted here only for brevity —
they are public by construction and safe to disclose.)

Verification is in `backend/jobtracker/auth/supabase_jwt.py`. Two properties
matter for assessment:

- **The algorithm is dispatched strictly, and the accepted set is a
  whitelist.** ES256 tokens verify against the project JWKS
  (`_SUPABASE_ASYMMETRIC_ALGORITHMS = ["ES256"]`, `:86`); HS256 tokens verify
  against the shared secret (`_SUPABASE_ALGORITHMS = ["HS256"]`, `:85`). The
  unverified header `alg` selects which branch runs, but it can never widen the
  set passed to `jwt.decode`, so `alg: none` and algorithm-confusion
  substitution are both rejected. `backend/tests/test_auth_supabase_jwt.py:169`
  (`test_alg_none_rejected`) mints a genuinely signature-less token with
  `algorithm="none"` and asserts a 401.
- If an ES256 token arrives and `JOBTRACKER_SUPABASE_JWKS_URL` is not
  configured, verification **fails closed** with an explicit error rather than
  falling back to the symmetric path (`:134-141`).

JWKS keys are cached for 3600 seconds (`:96`).

---

## 5. Password storage

Passwords are held by Supabase Auth, never by this application — the backend
never sees a password and has no password-handling code path.

Read live on 2026-08-15, both password-backed users carry a 60-character
`$2a$`-prefixed digest, which is **bcrypt** with a per-password salt:

```sql
SELECT substr(encrypted_password,1,4) AS hash_prefix,
       length(encrypted_password)     AS hash_len,
       count(*)
FROM auth.users WHERE encrypted_password IS NOT NULL GROUP BY 1,2;
--  $2a$ | 60 | 2
```

Google is also available as an identity provider (`auth.identities`: `email` ×
2, `google` × 1), in which case no password exists for that identity at all.

---

## 6. Residual risk, stated plainly

1. **No key rotation capability (§3.3).** This is the material gap in this
   control. It is a design limitation, it is known, and the remediation is
   specified but not built.
2. **AES-128-CBC + HMAC-SHA256 is not an AEAD.** Fernet is a sound,
   widely-reviewed construction and encrypt-then-MAC is the correct ordering,
   but a modern design would use ChaCha20-Poly1305 or AES-GCM. The `nonce`
   column exists precisely to make that migration possible without a schema
   change. This is a preference, not a vulnerability.
3. **The Fernet key's lifetime is unbounded.** Because rotation is not
   implemented, the key in production has been in use since the feature
   shipped. No compromise is known or suspected; the point is that the age is
   not bounded by policy.
4. **One key serves two cryptographic purposes (§3.4).** Not exploitable as
   built, but it widens the impact of a compromise from "stored credentials"
   to "stored credentials and OAuth state integrity".

---

*Prepared 2026-08-15. No key, token, ciphertext or password digest is
reproduced in this document. Where a live value was read to establish a fact —
the JWKS key material, the bcrypt digest prefix — only the non-sensitive
discriminator is shown.*
