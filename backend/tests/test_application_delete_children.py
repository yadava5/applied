"""Deleting ONE application must take its children with it — the cloud path.

Why this file exists
--------------------

``DELETE /applications/{id}`` is the deployed hard-delete. Before this suite it
deleted the row's ``emails`` and nothing else, so on Postgres — where every
foreign key in ``d7da4461f034`` is declared without ``ondelete``, i.e. NO
ACTION/RESTRICT — the request had two ways to fail:

- a ``contacts`` or ``interviews`` row still pointing at the application. Both
  declare ``application_id`` as a NOT NULL FK, so SQLAlchemy's default
  "de-associate the children" cascade tries ``SET application_id = NULL`` and
  the flush raises. The user gets a 500 and the application stays.
- an ``email_embeddings`` row still pointing at one of the doomed ``emails``.
  ``email_embeddings.email_id`` is likewise a NOT NULL FK, and the bulk
  ``DELETE FROM emails`` is Core, not ORM — no cascade runs at all, so the
  database itself refuses the delete.

The account-wide purge (``jobtracker/cloud/account.py``) already answered the
ordering question for this schema: ``EmailEmbedding → Contact → Interview →
Email → Application``. This suite asserts the per-application delete uses the
SAME answer rather than inventing a second one.

The FK pragma is the trap here
------------------------------

SQLite does not enforce foreign keys unless ``PRAGMA foreign_keys=ON`` is set
on the connection. ``conftest.py``'s ``test_engine`` fixture builds its own
engine and never sets it; only ``init_db()`` does. A test written against a
pragma-off connection would report the embedding case as passing on both the
broken and the fixed code — a check that cannot fail. So
:func:`test_foreign_keys_are_enforced_in_this_harness` is a positive control and
runs first: if it goes red, every FK assertion below is meaningless and must not
be read as evidence.
"""

from __future__ import annotations

import ast
import inspect
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, text
from sqlmodel import select

from jobtracker.database.models import (
    Contact,
    ContactRole,
    Email,
    EmailCategory,
    EmailEmbedding,
    EmailSource,
    Interview,
    InterviewStatus,
    InterviewType,
    TrainingData,
)

# 32+ bytes so PyJWT does not warn; the value is irrelevant as long as the
# fixture and the token helper agree on it.
JWT_SECRET = "delete-children-test-secret-at-least-32-bytes-long-hs256"
USER_A = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _token_for(user_id: str) -> str:
    """A Supabase-shaped HS256 JWT for ``user_id``."""

    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud FastAPI app on the in-memory SQLite DB, with auth enabled.

    Deliberately NOT the env-var-plus-``importlib.reload`` fixture that
    ``tests/test_user_id_scoping.py`` uses, because that one does not clean up
    after itself and this file sits before the auth suite in collection order.
    Reloading ``jobtracker.config`` mints a NEW settings instance while every
    ``from jobtracker.config import settings`` binding still points at the old
    one, so the test JWT secret outlives the fixture: running
    ``test_user_id_scoping.py`` immediately before ``test_auth_supabase_jwt.py``
    fails 12 of its 12 tests today. Reloading the auth module on the way out is
    not a fix either — it rebinds ``AuthError``, and a ``pytest.raises`` holding
    the previous class object stops matching.

    ``settings`` is a singleton every module holds BY REFERENCE, so patching
    three attributes on it reaches all of them and ``monkeypatch`` undoes it
    exactly. ``database_url`` is a property derived from ``environment``, so the
    in-memory URL follows from the same patch; resetting ``_engine`` is what
    makes the next ``get_engine()`` build against it. ``init_db()`` then creates
    the schema and — the part this file depends on — turns ``PRAGMA
    foreign_keys`` ON for the single StaticPool connection.
    """

    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    monkeypatch.setattr(config_module.settings, "environment", "test")
    monkeypatch.setattr(config_module.settings, "deployment", "cloud")
    monkeypatch.setattr(config_module.settings, "supabase_jwt_secret", JWT_SECRET)

    connection_module._engine = None

    from jobtracker.database import init_db

    await init_db()

    import jobtracker.main_cloud as main_cloud_module

    yield main_cloud_module.app

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None


@pytest.fixture
async def client(cloud_app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cloud-test") as c:
        yield c


@pytest.fixture
def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token_for(USER_A)}"}


async def _create_application(client: AsyncClient, headers: dict[str, str]) -> int:
    resp = await client.post(
        "/applications",
        json={"company": "Acme", "position": "Backend Engineer"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _seed_children(
    application_id: int,
    *,
    contact: bool = False,
    interview: bool = False,
    email: bool = False,
    embedding: bool = False,
    training: bool = False,
) -> dict[str, int]:
    """Attach the requested child rows to ``application_id``.

    Written directly against the session rather than through the API because
    the cloud API has no endpoints for contacts or interviews — they are
    written by the desktop linker (``jobtracker/tracking/linker.py``) into the
    same schema, and by anything that talks to the database. The FK is the
    thing under test, not the writer.
    """

    from jobtracker.database import get_session

    owner = uuid.UUID(USER_A)
    ids: dict[str, int] = {}
    now = datetime.utcnow()

    async with get_session() as session:
        if contact:
            row = Contact(
                user_id=owner,
                application_id=application_id,
                name="Dana Recruiter",
                email="dana@acme.example",
                role=ContactRole.RECRUITER,
                notes="Prefers email in the morning.",
            )
            session.add(row)
            await session.flush()
            ids["contact"] = row.id
        if interview:
            row = Interview(
                user_id=owner,
                application_id=application_id,
                type=InterviewType.TECHNICAL,
                scheduled_at=now,
                location="https://meet.example/abc",
                notes="Bring the take-home.",
                status=InterviewStatus.SCHEDULED,
            )
            session.add(row)
            await session.flush()
            ids["interview"] = row.id
        if email or embedding or training:
            mail = Email(
                user_id=owner,
                application_id=application_id,
                source_account=EmailSource.GMAIL,
                message_id=f"<delete-children-{application_id}@test>",
                received_at=now,
                subject="Thanks for applying to Acme",
                sender_email="jobs@acme.example",
                body_snippet="We received your application.",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.91,
                classification_method="rules",
            )
            session.add(mail)
            await session.flush()
            ids["email"] = mail.id
            if embedding:
                emb = EmailEmbedding(
                    user_id=owner,
                    email_id=mail.id,
                    label="applied",
                    embedding=b"\x00" * 8,
                )
                session.add(emb)
                await session.flush()
                ids["embedding"] = emb.id
            if training:
                example = TrainingData(
                    user_id=owner,
                    email_id=mail.id,
                    label="applied",
                    subject=mail.subject,
                    body_text=mail.body_snippet,
                    source="user_correction",
                )
                session.add(example)
                await session.flush()
                ids["training"] = example.id
        await session.commit()

    return ids


async def _count(model, **filters) -> int:
    from jobtracker.database import get_session

    async with get_session() as session:
        stmt = select(func.count()).select_from(model)
        for column, value in filters.items():
            stmt = stmt.where(getattr(model, column) == value)
        return (await session.exec(stmt)).one()


async def test_foreign_keys_are_enforced_in_this_harness(cloud_app) -> None:
    """Positive control. Without this, half the suite below cannot fail.

    SQLite ignores foreign keys unless the connection has
    ``PRAGMA foreign_keys=ON``. If this returns 0, the ``email_embeddings``
    assertions pass on broken code too and prove nothing.
    """

    from jobtracker.database import get_session

    async with get_session() as session:
        enforced = (await session.exec(text("PRAGMA foreign_keys"))).one()

    # ``exec`` hands back a Row for a textual statement and a scalar for a
    # scalar select; unwrap either without pretending to know which.
    value = enforced if isinstance(enforced, int) else enforced[0]
    assert value == 1, (
        "foreign keys are NOT enforced on this connection, so every FK "
        "assertion in this module is vacuous. init_db() sets the pragma; a "
        "harness that builds its own engine does not."
    )


async def test_delete_takes_contacts_and_interviews_with_it(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    """The production 500: NOT NULL children the delete never touched.

    ``Contact.application_id`` and ``Interview.application_id`` are
    non-Optional, so SQLAlchemy's default cascade (de-associate the children by
    nulling their FK) cannot succeed. There is no null-out answer available for
    these two: it is delete-with-the-parent or refuse the delete, and DELETE is
    already the explicitly-final action — ``dismiss``/``restore`` is the
    reversible one.
    """

    application_id = await _create_application(client, headers)
    await _seed_children(application_id, contact=True, interview=True)

    resp = await client.delete(f"/applications/{application_id}", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] is True
    assert await _count(Contact, application_id=application_id) == 0
    assert await _count(Interview, application_id=application_id) == 0


async def test_delete_takes_the_embedding_of_a_deleted_email_with_it(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    """The second production 500, one table further down.

    The handler deletes the row's ``emails`` with a Core bulk DELETE, so no ORM
    cascade runs, and ``email_embeddings.email_id`` is a NOT NULL FK onto them.
    On Postgres the database refuses the DELETE outright. An embedding is a
    derived artefact — regenerable from the message it was computed for — so it
    dies with its email; it is not a user record like a contact.
    """

    application_id = await _create_application(client, headers)
    ids = await _seed_children(application_id, email=True, embedding=True)

    resp = await client.delete(f"/applications/{application_id}", headers=headers)

    assert resp.status_code == 200, resp.text
    assert await _count(Email, application_id=application_id) == 0
    assert await _count(EmailEmbedding, email_id=ids["email"]) == 0


async def test_delete_keeps_the_training_example_but_unlinks_it(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    """A human's label survives; its dangling provenance does not.

    ``training_data.email_id`` is a bare indexed integer — no foreign key — so
    the database will not clean up after a deleted email and an untouched row
    would keep naming an ``emails`` id that no longer exists. The example itself
    carries the subject and body it was labelled from, so it stays inspectable;
    only the claim of an origin it no longer has is dropped.
    """

    from jobtracker.database import get_session

    application_id = await _create_application(client, headers)
    ids = await _seed_children(application_id, email=True, training=True)

    resp = await client.delete(f"/applications/{application_id}", headers=headers)
    assert resp.status_code == 200, resp.text

    async with get_session() as session:
        example = (
            await session.exec(
                select(TrainingData).where(TrainingData.id == ids["training"])
            )
        ).first()

    assert example is not None, "the user's label must survive the delete"
    assert example.email_id is None, "it must stop naming a deleted email"
    assert example.label == "applied"
    assert example.subject == "Thanks for applying to Acme"


async def test_delete_clears_every_child_at_once(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    """All four children together — the shape a real row actually has."""

    application_id = await _create_application(client, headers)
    ids = await _seed_children(
        application_id,
        contact=True,
        interview=True,
        email=True,
        embedding=True,
        training=True,
    )

    resp = await client.delete(f"/applications/{application_id}", headers=headers)
    assert resp.status_code == 200, resp.text

    assert await _count(Contact, application_id=application_id) == 0
    assert await _count(Interview, application_id=application_id) == 0
    assert await _count(Email, application_id=application_id) == 0
    assert await _count(EmailEmbedding, email_id=ids["email"]) == 0
    # Derived rows die with the application; the human's label does not.
    assert await _count(TrainingData, id=ids["training"]) == 1

    detail = await client.get(f"/applications/{application_id}", headers=headers)
    assert detail.status_code == 404


async def test_delete_does_not_reach_another_applications_children(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    """The cascade is scoped to ONE application, not to the employer.

    One company can hold several applications, so a delete that widened to the
    company — or forgot the ``application_id`` predicate — would silently take a
    sibling's contacts and interviews with it.
    """

    doomed = await _create_application(client, headers)
    keeper = await _create_application(client, headers)
    await _seed_children(doomed, contact=True, interview=True)
    await _seed_children(keeper, contact=True, interview=True)

    resp = await client.delete(f"/applications/{doomed}", headers=headers)
    assert resp.status_code == 200, resp.text

    assert await _count(Contact, application_id=keeper) == 1
    assert await _count(Interview, application_id=keeper) == 1


async def test_dismiss_and_restore_destroy_nothing(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    """The reversible path must stay reversible.

    ``dismiss`` only stamps ``dismissed_at``/``dismissed_reason`` and ``restore``
    only clears them, so neither has the delete's hole. Asserted rather than
    read off the source, because "I checked and it does not delete anything" is
    exactly the claim that gets quietly falsified by a later edit — a restore
    that hands back an application whose contacts are gone is worse than a
    delete that fails loudly.
    """

    application_id = await _create_application(client, headers)
    ids = await _seed_children(
        application_id, contact=True, interview=True, email=True, embedding=True
    )

    dismissed = await client.post(
        f"/applications/{application_id}/dismiss", headers=headers
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json() == {"dismissed": True, "restorable": True}

    # Nothing may be gone WHILE it is dismissed — that is the window in which a
    # destructive dismiss would be invisible.
    assert await _count(Contact, application_id=application_id) == 1
    assert await _count(Interview, application_id=application_id) == 1
    assert await _count(Email, application_id=application_id) == 1
    assert await _count(EmailEmbedding, email_id=ids["email"]) == 1

    restored = await client.post(
        f"/applications/{application_id}/restore", headers=headers
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["dismissed_at"] is None
    assert restored.json()["dismissed_reason"] is None

    assert await _count(Contact, application_id=application_id) == 1
    assert await _count(Interview, application_id=application_id) == 1
    assert await _count(Email, application_id=application_id) == 1
    assert await _count(EmailEmbedding, email_id=ids["email"]) == 1


# =============================================================================
# The ordering contract, read out of the source rather than restated
# =============================================================================
#
# The three tests below do not exercise the endpoint; they check that the
# per-application delete and the account-wide purge give the SAME answer to
# "which children, in what order". Derived from the source and from
# ``SQLModel.metadata`` on purpose — a hand-written expectation would be a copy
# of the thing it is checking, and would keep passing after the code drifted.


def _application_source() -> str:
    import jobtracker.cloud.applications as cloud_applications

    return inspect.getsource(cloud_applications)


def _function_node(name: str) -> ast.AST:
    for node in ast.walk(ast.parse(_application_source())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(
        f"cloud/applications.py has no function named {name!r} — this test is "
        "reading a name that no longer exists and can no longer fail"
    )


def _tables_deleted_in(name: str) -> list[str]:
    """Tables ``name`` issues a ``sa_delete(Model)`` against, in source order."""

    from jobtracker.database import models as db_models

    hits: list[tuple[int, str]] = []
    for child in ast.walk(_function_node(name)):
        if not isinstance(child, ast.Call):
            continue
        func_node = child.func
        called = (
            func_node.id
            if isinstance(func_node, ast.Name)
            else getattr(func_node, "attr", None)
        )
        if called != "sa_delete" or not child.args:
            continue
        arg = child.args[0]
        if not isinstance(arg, ast.Name):
            continue
        model = getattr(db_models, arg.id, None)
        if model is not None:
            hits.append((child.lineno, model.__tablename__))
    return [table for _, table in sorted(hits)]


def _orm_delete_lineno(name: str) -> int | None:
    """Line of the ``session.delete(...)`` that removes the parent row."""

    for child in ast.walk(_function_node(name)):
        if not isinstance(child, ast.Call):
            continue
        func_node = child.func
        if (
            isinstance(func_node, ast.Attribute)
            and func_node.attr == "delete"
            and isinstance(func_node.value, ast.Name)
            and func_node.value.id == "session"
        ):
            return child.lineno
    return None


def _child_tables_of(parent: str) -> set[str]:
    """Every table with a foreign key onto ``parent``, read from the schema."""

    from sqlmodel import SQLModel

    from jobtracker.database import models  # noqa: F401  (populates metadata)

    return {
        name
        for name, table in SQLModel.metadata.tables.items()
        if name != parent
        and any(fk.column.table.name == parent for fk in table.foreign_keys)
    }


def test_the_source_reader_finds_anything_at_all() -> None:
    """Guards the two guards below: a reader that finds nothing passes them."""

    assert _tables_deleted_in("delete_application"), (
        "no sa_delete(Model) call found in delete_application — the AST reader "
        "has stopped working and the ordering assertions below are vacuous"
    )
    assert _orm_delete_lineno("delete_application") is not None, (
        "no session.delete(...) found in delete_application — the parent row "
        "is no longer deleted the way this test assumes"
    )
    assert _child_tables_of("applications"), (
        "no foreign keys onto applications found in the schema metadata"
    )


def test_the_per_application_delete_agrees_with_the_account_purge() -> None:
    """One answer to "children before parents", not two.

    ``cloud/account.py::_DELETION_ORDER`` already encodes the order this schema
    requires, and ``tests/test_account_deletion_covers_every_table.py`` derives
    from the foreign-key graph that it is correct. The per-application delete
    clears a subset of the same RESTRICT-constrained edges, so it must use the
    same relative order — if the two ever disagree, one of them is wrong and
    nothing else in the system would notice.
    """

    from jobtracker.cloud.account import _DELETION_ORDER

    account_order = [model.__tablename__ for model in _DELETION_ORDER]
    child_order = _tables_deleted_in("delete_application")

    assert child_order == [
        name for name in account_order if name in set(child_order)
    ], (
        "delete_application clears child tables in a different order than the "
        f"account purge does. account: {account_order}; per-application: "
        f"{child_order}. Both delete the same RESTRICT edges; they cannot both "
        "be right."
    )

    last_child = max(
        child.lineno
        for child in ast.walk(_function_node("delete_application"))
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == "sa_delete"
    )
    parent = _orm_delete_lineno("delete_application")
    assert parent is not None and parent > last_child, (
        "the parent application is deleted BEFORE its children "
        f"(session.delete at line {parent}, last child delete at line "
        f"{last_child}). The foreign keys are RESTRICT; that is a 500."
    )


def _functions_deleting(table: str) -> set[str]:
    """Every function in cloud/applications.py that deletes from ``table``."""

    names: set[str] = set()
    for node in ast.walk(ast.parse(_application_source())):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if table in _tables_deleted_in(node.name):
            names.add(node.name)
    return names


def test_every_email_delete_also_clears_that_email_s_embedding() -> None:
    """The RESTRICT edge one table below the one the bug was reported at.

    ``email_embeddings.email_id`` is NOT NULL with no ``ondelete``, and every
    place this module removes ``emails`` does it with a Core bulk DELETE — which
    runs no ORM cascade. So on Postgres the DELETE is refused, and on a SQLite
    connection without ``PRAGMA foreign_keys`` it silently orphans instead.
    Applies to ``_reset_review_queue`` exactly as it does to
    ``delete_application``; both are checked here so a third one cannot be added
    without noticing.
    """

    deleters = _functions_deleting("emails")
    assert deleters, "the AST reader found no function deleting emails at all"

    missing = sorted(
        name for name in deleters if "email_embeddings" not in _tables_deleted_in(name)
    )
    assert not missing, (
        f"these functions delete `emails` rows without first clearing the "
        f"`email_embeddings` that point at them: {missing}. The foreign key is "
        "NOT NULL with no ondelete, and a Core bulk DELETE runs no ORM cascade, "
        "so Postgres refuses the statement."
    )


def test_delete_application_covers_every_restrict_edge_it_can_hit() -> None:
    """Derived from the schema: a new child table fails on the commit that adds it.

    Anything with a foreign key onto ``applications`` must be cleared. And
    because this handler also deletes the row's ``emails``, anything with a
    foreign key onto ``emails`` inherits the same requirement — that is the
    ``email_embeddings`` edge, which nothing was clearing.
    """

    deleted = set(_tables_deleted_in("delete_application"))
    required = _child_tables_of("applications")
    if "emails" in deleted:
        required |= _child_tables_of("emails")
    required.discard("applications")

    missing = required - deleted
    assert not missing, (
        f"delete_application leaves these child tables behind: {sorted(missing)}. "
        "Every foreign key in this schema is declared without `ondelete` "
        "(migration d7da4461f034), so on Postgres they are RESTRICT and the "
        "delete raises rather than orphaning. Clear them in "
        "jobtracker/cloud/applications.py, children before parents, in the "
        "same order as cloud/account.py's _DELETION_ORDER."
    )
