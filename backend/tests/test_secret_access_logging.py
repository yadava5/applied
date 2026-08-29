"""Every access to a stored secret is logged, and the log never holds the secret.

Why this file exists
--------------------

CASA AL1 control 6.7.1 (secrets management) has a limb that reads "access to
secrets is logged". ``jobtracker.credentials.cloud`` is the only place in this
deployment where a secret is at rest: Gmail OAuth tokens and iCloud app-specific
passwords, Fernet-encrypted in ``user_credentials``. Every decrypt in the
product goes through ``get_gmail_credentials`` or ``get_icloud_credentials``,
and every write and delete goes through their save/delete siblings. Those are
the sites the control is about, and this file is the evidence that they emit a
record.

The dangerous half is the second sentence, not the first. A secret-access log
is a compliance artefact that gets shipped to a log aggregator and read by
people who are not entitled to the secret, so a line that carries the token it
is reporting on is worse than no line at all. The method is the one
``test_body_is_never_persisted.py`` uses: a SENTINEL that appears nowhere else,
asserted ABSENT from every emitted record — plus, because an absence proves
nothing on its own, positive controls that the decrypt really happened and that
the instrument really captured the product's own records.

Three things must never appear, and all three are checked rather than the
obvious one alone:

  * the PLAINTEXT token (the sentinel),
  * the CIPHERTEXT, read back out of the database row after the save (both its
    decoded form and its ``repr``, because bytes reach a log either way),
  * the FERNET KEY itself.

The sweep reads ``record.msg``, ``record.args`` and ``record.getMessage()``
together. ``record.args`` is the load-bearing one here: the module logs with
lazy ``%s`` formatting, so a secret handed to a logging call as an argument
never appears in ``record.msg`` at all.

Proven able to fail: adding ``+ " plaintext=%s"`` with the decrypted value to
the success line in ``get_gmail_credentials`` reddens
``test_no_log_record_carries_the_secret`` (and only that test), through the
``record.args`` limb.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

import pytest
from cryptography.fernet import Fernet

from jobtracker.credentials.types import GmailCredentials, ICloudCredentials

# Generated per run rather than hardcoded: this is a real Fernet key and a
# literal one in the tree is both a secret-scanner hit and a value that would
# still be a valid key if it ever escaped into a fixture somewhere else.
ENC_KEY = Fernet.generate_key().decode()

# Appears nowhere else in the repo. If it turns up in a log record, the access
# log is carrying the credential it exists to report on.
SENTINEL = "ZZQX-secret-access-sentinel-must-never-be-logged-7c1e9b"

LOGGER_NAME = "jobtracker.credentials.cloud"


@pytest.fixture
async def cloud_env(monkeypatch: pytest.MonkeyPatch):
    """The proven fixture from ``test_credentials_cloud.py``, unchanged in shape.

    The reload of ``jobtracker.credentials.cloud`` after the config reload is
    not optional: the module binds ``settings`` at import, so without it
    ``secret_encryption_key`` is invisible here whenever an earlier test file
    imported the module against a keyless settings object.
    """

    import jobtracker.auth.supabase_jwt as auth_module
    import jobtracker.config as config_module
    import jobtracker.credentials.cloud as cloud_module
    import jobtracker.database.connection as connection_module

    # Every settings instance the request path holds, de-duplicated by object
    # identity -- not ``importlib.reload(jobtracker.config)``, which minted a
    # new one and left the verifier holding the old (#582).
    holders = {
        id(module.settings): module.settings
        for module in (config_module, auth_module, connection_module, cloud_module)
    }
    for instance in holders.values():
        monkeypatch.setattr(instance, "secret_encryption_key", ENC_KEY)

    from jobtracker.database import init_db

    await init_db()

    yield cloud_module


@pytest.fixture
def user_id() -> uuid.UUID:
    # Fresh per test: conftest's in-memory SQLite engine is a session singleton,
    # so rows would otherwise bleed between tests.
    return uuid.uuid4()


@pytest.fixture
def gmail_credentials() -> GmailCredentials:
    return GmailCredentials(
        access_token=SENTINEL,
        refresh_token=f"refresh-{SENTINEL}",
        token_expiry=datetime(2026, 5, 1, 12, 0, 0),
        email="owner@example.test",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )


async def _stored_ciphertext(user_id: uuid.UUID, kind: str) -> bytes:
    """The exact bytes sitting in the row, so the sweep can search for them."""

    from sqlmodel import select

    from jobtracker.database import get_session
    from jobtracker.database.models import UserCredential

    async with get_session() as session:
        result = await session.exec(
            select(UserCredential).where(
                UserCredential.user_id == user_id,
                UserCredential.kind == kind,
            )
        )
        row = result.first()

    assert row is not None, "nothing was stored — the sweep would prove nothing"
    row = row[0] if hasattr(row, "__getitem__") else row
    return row.ciphertext


def _haystacks(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Every emitted record, rendered three ways.

    ``msg`` + ``args`` matter as much as ``getMessage()``: this module formats
    lazily, so a secret passed as a logging ARGUMENT lives only in ``args``
    until something renders it downstream.
    """

    return [
        f"{r.name} {r.levelname} {r.msg!r} {r.args!r} {r.getMessage()}"
        for r in caplog.records
    ]


def _access_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == LOGGER_NAME and r.getMessage().startswith("secret_access ")
    ]


# =============================================================================
# (i) the access itself is recorded
# =============================================================================


async def test_a_successful_decrypt_emits_an_access_line(
    cloud_env, caplog, user_id: uuid.UUID, gmail_credentials: GmailCredentials
) -> None:
    """A read that returns a credential names who, which secret and the outcome.

    This is the control's actual requirement. ``outcome=hit`` is what
    distinguishes it from the miss below — an access log that cannot tell a
    successful read from an empty one does not answer the question an assessor
    is asking.
    """

    caplog.set_level(logging.DEBUG)

    assert await cloud_env.save_gmail_credentials(user_id, gmail_credentials) is True
    caplog.clear()

    retrieved = await cloud_env.get_gmail_credentials(user_id)

    # POSITIVE CONTROL: the decrypt genuinely happened. Everything below is
    # about a read that succeeded, and a `None` here would make it vacuous.
    assert retrieved is not None
    assert retrieved.access_token == SENTINEL

    lines = _access_lines(caplog)
    assert len(lines) == 1, f"expected exactly one access line, got {lines}"
    line = lines[0]
    assert f"user_id={user_id}" in line
    assert f"kind={cloud_env.KIND_GMAIL}" in line
    assert "op=read" in line
    assert "outcome=hit" in line
    # The key VERSION is named — that is the field a rotation audit reads. The
    # key itself is not, and cannot be: see the sweep below.
    assert f"key_id={cloud_env.ACTIVE_KEY_ID}" in line


async def test_a_miss_is_logged_as_a_miss(cloud_env, caplog, user_id: uuid.UUID) -> None:
    """An access attempt against a user with no credential is still an access.

    Previously this path logged at DEBUG, which is off in production — so the
    most common access attempt on the deployment emitted nothing at all.
    """

    caplog.set_level(logging.DEBUG)

    assert await cloud_env.get_gmail_credentials(user_id) is None
    assert await cloud_env.get_icloud_credentials(user_id) is None

    lines = _access_lines(caplog)
    assert len(lines) == 2, lines
    assert all("outcome=miss" in line for line in lines)
    assert any(f"kind={cloud_env.KIND_GMAIL}" in line for line in lines)
    assert any(f"kind={cloud_env.KIND_ICLOUD}" in line for line in lines)
    assert all(f"user_id={user_id}" in line for line in lines)
    # INFO, not DEBUG: a line the deployment's log level discards is not a log.
    misses = [r for r in caplog.records if "outcome=miss" in r.getMessage()]
    assert all(r.levelno >= logging.INFO for r in misses), [
        r.levelname for r in misses
    ]


async def test_the_write_and_the_delete_are_logged_too(
    cloud_env, caplog, user_id: uuid.UUID, gmail_credentials: GmailCredentials
) -> None:
    """Creation and destruction of a secret, not only reads.

    An assessor asks when a secret came into existence and when it stopped
    existing. Reads alone answer neither.
    """

    caplog.set_level(logging.DEBUG)

    await cloud_env.save_gmail_credentials(user_id, gmail_credentials)
    await cloud_env.save_icloud_credentials(
        user_id, ICloudCredentials(email="owner@icloud.test", app_password=SENTINEL)
    )
    await cloud_env.delete_gmail_credentials(user_id)
    await cloud_env.delete_icloud_credentials(user_id)
    await cloud_env.clear_all_credentials(user_id)

    lines = _access_lines(caplog)
    ops = [line for line in lines if "op=write" in line]
    assert len(ops) == 2, lines
    assert all("outcome=written" in line for line in ops)

    deletes = [line for line in lines if "op=delete" in line]
    assert len(deletes) == 2, lines
    assert all("outcome=deleted" in line for line in deletes)

    clears = [line for line in lines if "op=clear" in line]
    assert len(clears) == 1, lines
    assert "kind=all" in clears[0]


async def test_a_failed_decrypt_is_logged_at_error_without_the_token(
    cloud_env, caplog, user_id: uuid.UUID, gmail_credentials: GmailCredentials
) -> None:
    """The `decrypt_failed` outcome, driven by a real undecryptable row.

    The row is overwritten with a token minted under a DIFFERENT key, which is
    what a botched rotation or a tampered row actually looks like — not a
    monkeypatched raise. That matters because the assertion is about what the
    real ``InvalidToken`` handler emits.
    """

    from sqlmodel import select

    from jobtracker.database import get_session
    from jobtracker.database.models import UserCredential

    caplog.set_level(logging.DEBUG)
    await cloud_env.save_gmail_credentials(user_id, gmail_credentials)

    foreign = Fernet(Fernet.generate_key()).encrypt(SENTINEL.encode())
    async with get_session() as session:
        result = await session.exec(
            select(UserCredential).where(
                UserCredential.user_id == user_id,
                UserCredential.kind == cloud_env.KIND_GMAIL,
            )
        )
        row = result.first()
        row = row[0] if hasattr(row, "__getitem__") else row
        row.ciphertext = foreign
        session.add(row)
        await session.commit()

    caplog.clear()
    assert await cloud_env.get_gmail_credentials(user_id) is None

    failures = [
        r
        for r in caplog.records
        if r.name == LOGGER_NAME and "outcome=decrypt_failed" in r.getMessage()
    ]
    assert len(failures) == 1, _access_lines(caplog)
    record = failures[0]
    assert record.levelno == logging.ERROR, record.levelname
    assert f"user_id={user_id}" in record.getMessage()
    assert "error=InvalidToken" in record.getMessage()

    # And the undecryptable bytes are NOT in the line. This is the site most
    # likely to be "improved" with the offending token attached for debugging.
    for haystack in _haystacks(caplog):
        assert foreign.decode() not in haystack
        assert repr(foreign) not in haystack


# =============================================================================
# (ii) and the log holds none of the three things it must never hold
# =============================================================================


async def test_no_log_record_carries_the_secret(
    cloud_env, caplog, user_id: uuid.UUID, gmail_credentials: GmailCredentials
) -> None:
    """The whole point. Plaintext, ciphertext and key, across a full round trip.

    Driven end to end — save, read, read again after delete — because the leak
    this guards against is a secret reaching a log line nobody thought to
    assert on, and each of those paths emits a different line.

    Mutation (verified RED before this was committed): appending
    ``+ " plaintext=%s"`` with the decrypted value to the ``outcome=hit`` line
    in ``get_gmail_credentials`` fails this test on the plaintext limb.
    """

    caplog.set_level(logging.DEBUG)

    await cloud_env.save_gmail_credentials(user_id, gmail_credentials)
    await cloud_env.save_icloud_credentials(
        user_id, ICloudCredentials(email="owner@icloud.test", app_password=SENTINEL)
    )

    gmail_ct = await _stored_ciphertext(user_id, cloud_env.KIND_GMAIL)
    icloud_ct = await _stored_ciphertext(user_id, cloud_env.KIND_ICLOUD)

    # POSITIVE CONTROL on the FIXTURE: the ciphertext is real, non-trivial, and
    # is not itself the plaintext. Searching for an empty or sentinel-bearing
    # byte string would make the ciphertext limb meaningless.
    assert len(gmail_ct) > 32 and len(icloud_ct) > 32
    assert SENTINEL.encode() not in gmail_ct

    retrieved = await cloud_env.get_gmail_credentials(user_id)
    # POSITIVE CONTROL on the SUBJECT: the plaintext genuinely passed through
    # the code under test. If the decrypt had failed, the sentinel would be
    # absent from the logs for a reason that proves nothing.
    assert retrieved is not None and retrieved.access_token == SENTINEL
    icloud = await cloud_env.get_icloud_credentials(user_id)
    assert icloud is not None and icloud.app_password == SENTINEL

    await cloud_env.clear_all_credentials(user_id)
    assert await cloud_env.get_gmail_credentials(user_id) is None

    # POSITIVE CONTROL on the INSTRUMENT: an absence assertion over an empty
    # capture is free. caplog only sees records that propagate to root, so
    # "captured nothing" is the likely failure, not a far-fetched one.
    assert caplog.records, "caplog captured nothing — this test proves nothing"
    assert any(r.name == LOGGER_NAME for r in caplog.records), (
        "no record from the credential store reached caplog; the module's own "
        f"logging is invisible here: {sorted({r.name for r in caplog.records})}"
    )
    assert _access_lines(caplog), "no secret_access line was emitted at all"

    forbidden = {
        "plaintext": SENTINEL,
        "gmail ciphertext": gmail_ct.decode(),
        "gmail ciphertext repr": repr(gmail_ct),
        "icloud ciphertext": icloud_ct.decode(),
        "icloud ciphertext repr": repr(icloud_ct),
        "fernet key": ENC_KEY,
    }

    for haystack in _haystacks(caplog):
        for label, needle in forbidden.items():
            assert needle not in haystack, (
                f"the {label} reached a log record: {haystack[:300]}"
            )
