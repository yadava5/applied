"""Deleting an account must clear every table that holds the user's rows.

Why this file exists
--------------------

``jobtracker/cloud/account.py`` purges a user by iterating a hand-written tuple,
``_DELETION_ORDER``. That tuple is referenced nowhere else in the codebase — no
test, no invariant, nothing. So the correctness of "Delete account" rests
entirely on a future author remembering to add their new table to a list they
have no reason to look at.

The failure mode is silent and it is the bad kind: the endpoint deletes what it
knows about, commits, logs success and answers **200** with
``tables_cleared: 8``, while the forgotten table keeps the user's rows forever.
A user who asked to be deleted, and was told they were, would not be. This is
not hypothetical — the cascade was added in the first place after it was found
orphaning rows.

So the assertion here is deliberately not "the tuple has eight entries", which
would be a restatement. It derives the required set from the schema itself: any
table carrying a ``user_id`` column is tenant-owned by construction, and must be
purged. A new tenant table fails this test on the commit that introduces it,
which is the only moment the omission is cheap to fix.

The ordering property is asserted too, because it is load-bearing for a
different reason: the foreign keys default to RESTRICT, so a parent deleted
before its children raises and the whole purge rolls back. Verified by mutation
rather than by reading: appending ``_DELETION_ORDER = tuple(reversed(...))``
turns that assertion red and names all four offending edges
(``contacts→applications``, ``email_embeddings→emails``, ``emails→applications``,
``interviews→applications``).

One note on how this file was written, because it is the defect it guards
against in miniature. The ordering test first hardcoded four pairs using
guessed singular table names — ``email``, ``application`` — where the schema
says ``emails``, ``applications``. Every case hit its ``pytest.skip`` guard and
the run reported **3 passed, 4 skipped**: four tests that looked fine and could
not fail. Deriving the pairs from the metadata is what fixed it, and that is
why nothing in here is a hand-written list of names.
"""

from __future__ import annotations

import pytest
from sqlmodel import SQLModel

# Importing the models module populates ``SQLModel.metadata`` with every table.
from jobtracker.database import models  # noqa: F401
from jobtracker.cloud.account import _DELETION_ORDER


# Tables that carry a ``user_id`` but are NOT the user's own data to purge.
# Empty today. Anything added here needs a reason in this comment, because the
# whole point of the test is that membership is derived, not chosen.
_NOT_TENANT_DATA: frozenset[str] = frozenset()


def _tenant_tables() -> set[str]:
    """Every table in the schema with a ``user_id`` column."""

    return {
        name
        for name, table in SQLModel.metadata.tables.items()
        if "user_id" in table.columns and name not in _NOT_TENANT_DATA
    }


def _purged_tables() -> set[str]:
    """Every table ``delete_account`` actually issues a DELETE against."""

    return {model.__tablename__ for model in _DELETION_ORDER}


def test_every_tenant_table_is_purged_on_account_deletion():
    """The set the endpoint clears must cover the set the schema defines."""

    missed = _tenant_tables() - _purged_tables()
    assert not missed, (
        "these tables hold rows owned by a user and would SURVIVE account "
        f"deletion: {sorted(missed)}. Add them to `_DELETION_ORDER` in "
        "jobtracker/cloud/account.py, children before parents. The endpoint "
        "would otherwise answer 200 and report success while leaving this "
        "user's data behind."
    )


def test_the_deletion_order_names_no_table_that_does_not_exist():
    """The converse: a stale entry would raise at request time, not import time."""

    unknown = _purged_tables() - set(SQLModel.metadata.tables)
    assert not unknown, f"_DELETION_ORDER names tables not in the schema: {sorted(unknown)}"


def test_no_model_is_listed_twice():
    """A duplicate is harmless but means the list was edited without reading it."""

    names = [model.__tablename__ for model in _DELETION_ORDER]
    assert len(names) == len(set(names)), f"_DELETION_ORDER repeats a table: {names}"


def _tenant_foreign_keys() -> list[tuple[str, str]]:
    """Every (child, parent) edge between two tenant tables, read from the schema.

    Derived rather than listed. The first version of this test hardcoded four
    pairs using guessed table names (``email``, ``application``) instead of the
    real ones (``emails``, ``applications``), and every case silently
    ``pytest.skip``-ed — four green-looking tests that could not fail. Reading
    the edges out of the metadata removes the class of mistake entirely: a new
    foreign key is covered the moment it exists, and a renamed table cannot
    quietly drop its own constraint from the check.
    """

    tenant = _tenant_tables()
    edges: list[tuple[str, str]] = []
    for name, table in SQLModel.metadata.tables.items():
        if name not in tenant:
            continue
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent in tenant and parent != name:
                edges.append((name, parent))
    return sorted(set(edges))


def test_the_foreign_key_graph_is_not_empty():
    """Guards the guard: an empty edge list would make the next test vacuous."""

    edges = _tenant_foreign_keys()
    assert edges, (
        "no foreign keys found between tenant tables — either the schema "
        "changed shape or this test is no longer reading it correctly, and "
        "the ordering assertion below has quietly become a no-op"
    )


def test_children_are_deleted_before_their_parents():
    """Order is not cosmetic — the foreign keys default to RESTRICT.

    Deleting an ``Application`` while its ``Email`` rows still point at it
    raises, the transaction rolls back, and the user's deletion request fails
    outright — so a user who asked to be deleted gets an error instead, or
    worse, a partial purge.
    """

    order = [model.__tablename__ for model in _DELETION_ORDER]
    wrong = [
        (child, parent)
        for child, parent in _tenant_foreign_keys()
        if child in order and parent in order and order.index(child) > order.index(parent)
    ]
    assert not wrong, (
        "these children are deleted AFTER the parent they reference: "
        f"{wrong}. The foreign keys are RESTRICT, so the parent delete raises "
        "and the entire purge rolls back. Reorder `_DELETION_ORDER` in "
        "jobtracker/cloud/account.py so children come first."
    )
