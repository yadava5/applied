"""One Gmail mailbox per user, asserted where the code actually decides it.

#296 asked which of two shapes the product commits to: one credential per user,
or many mailboxes per user as `sync_state`'s unique key would allow. The
deployed code has already chosen — in a type signature, not a comment — and
nothing said so out loud, so a future change could widen it by accident and no
test would notice.

These assertions are deliberately about the CONTRACT rather than about
behaviour. Each one is a place where adding a second mailbox would have to
change something, so a widening arrives as a red test and a decision instead of
as a silent capability.

The rejected alternative and its price are in `docs/DECISIONS.md`.
"""

import inspect

import sqlalchemy as sa

from jobtracker.credentials import cloud as credentials_cloud
from jobtracker.database.models import UserCredential


def test_the_credential_loader_takes_no_address():
    """`get_gmail_credentials(user_id)` — a user in, one credential out.

    This is the strongest evidence of the choice: seventeen call sites pass a
    user and nothing else, so there is no caller that could ask for a SECOND
    mailbox even if the rows existed. A many-mailbox world has to add a
    parameter here first, and that is what this test makes visible.
    """

    params = inspect.signature(credentials_cloud.get_gmail_credentials).parameters
    assert "user_id" in params
    assert not {"account_email", "address", "mailbox", "email"} & set(params), (
        "get_gmail_credentials gained an address-shaped parameter. That is the "
        "first move toward many mailboxes per user, which docs/DECISIONS.md "
        "prices and rejects — reopen #296 before widening it."
    )


def test_the_credential_table_is_keyed_one_per_user_and_kind():
    """`(user_id, kind)` is the primary key, so the database enforces it too.

    A contract that lives only in a signature is a convention; this is the half
    that cannot be worked around by a new call site.
    """

    pk = {c.name for c in sa.inspect(UserCredential).persist_selectable.primary_key}
    assert pk == {"user_id", "kind"}, (
        f"user_credentials' primary key is {sorted(pk)}. Widening it to admit a "
        "second Gmail row per user is the migration docs/DECISIONS.md rejects: "
        "it touches three RLS revisions and redefines what the Google "
        "restricted-scope connection cap counts."
    )


def test_nothing_claims_the_sync_ranking_supports_many_mailboxes():
    """The `min()` over `sync_state` is defensive, and must not read as a feature.

    Its docstring said "a user with more than one linked address still yields
    one value", which reads as a promise the product does not keep — a second
    row cannot be written, because the mail path derives `account_email` from
    the one stored credential. A reader who believed it would build on a
    capability that is not there.
    """

    from jobtracker.cloud import cron

    doc = inspect.getdoc(cron._probe_sync_position) or ""
    assert "more than one linked address still yields" not in doc, (
        "the multi-mailbox promise is back in _probe_sync_position's docstring"
    )
    assert "ONE MAILBOX PER USER IS THE CONTRACT" in doc, (
        "_probe_sync_position no longer states the contract it depends on"
    )
