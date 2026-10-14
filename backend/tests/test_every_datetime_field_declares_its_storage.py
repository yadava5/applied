"""Every ``datetime`` field on a table class must name its own storage.

Why this file exists
--------------------

Up to sqlmodel 0.0.44 a plain ``datetime`` annotation compiled to
``DateTime(timezone=False)`` — ``timestamp without time zone``, which is what
16 of this schema's 20 datetime columns are in Postgres. From 0.0.45 the same
annotation compiles to ``UTCDateTime``, sqlmodel's own ``TypeDecorator`` over
``DateTime(timezone=True)``, and that type **refuses a naive value on write**:
SQLAlchemy raises a ``StatementError`` wrapping a ``ValueError``. This codebase
writes ``datetime.utcnow()`` everywhere, and the upgrade migrates no columns,
so a bare annotation turns every insert on those tables into an error against a
column that did not change. The root ``requirements.txt`` carried only
``sqlmodel>=0.0.42``, so this was not hypothetical — a fresh install resolved
0.0.48.

``models.py`` therefore says ``sa_type=sa.DateTime(timezone=False)`` on the
naive fields and carries the four ``timestamptz`` columns in an explicit
``sa_column``. This test is what keeps that true for the next field somebody
adds, since the bare form is the one that is easier to type.

WHY IT READS FIELD DEFINITIONS AND NOT COMPILED METADATA
--------------------------------------------------------

Below 0.0.45 an annotated field and a bare one compile to the *same* Column:
``DateTime()`` either way, ``timezone=False`` either way, identical DDL. A test
that introspected ``SQLModel.metadata`` would therefore be green on the capped
version no matter what the source said — green from birth and green forever,
which is this repository's recurring defect shape. So the assertion is about
the **declaration**: the ``FieldInfo`` carries an ``sa_type``, or it carries an
``sa_column`` whose type is a real ``sa.DateTime``. Both of those are things a
human wrote; neither can arrive by default.

The same reasoning is why the rule is "is it declared" and not "is it naive".
Four columns are legitimately ``timestamptz``
(``user_credentials.{revoked_at,created_at,updated_at}`` and
``gmail_sync_enrollment.enrolled_at``) and a gate demanding naive storage would
be wrong about them. What is never acceptable is leaving the choice to whatever
sqlmodel's default happens to be this month.

Proven able to fail
-------------------

ALL FOUR assertions here, because three of them would otherwise be the
"green from birth" shape this repository keeps finding. Two take a source
mutation and two can only be mutated at runtime, since nothing an author can
write in ``models.py`` reaches them.

``test_every_datetime_field_declares_its_storage`` — source. Deleting
``sa_type=sa.DateTime(timezone=False)`` from ``Application.due_at`` (an
``Optional[datetime]`` field) reds it naming ``Application.due_at``; the same
deletion on ``Email.received_at`` (a plain ``datetime`` field) reds it naming
``Email.received_at``. Both were run on sqlmodel 0.0.44 AND 0.0.48 — a gate
that only reds on one side of the break would not be guarding what broke — and
each deletion was confirmed to have actually applied (``git diff --numstat``
non-empty) rather than assumed, because a mutation that silently no-ops prints
exactly like a gate that survived it.

``test_the_discovery_finds_the_fields_it_is_supposed_to_find`` — source.
Pointing ``_MUST_BE_FOUND`` at a field that does not exist reds it, naming the
missing pair and listing all 20 it did find.

``test_every_table_class_is_reachable_from_the_registry`` — runtime. Adding a
bare ``sa.Table`` to ``SQLModel.metadata`` reds it: "9 mapped classes against
10 tables in the metadata".

``test_the_declared_storage_matches_the_column_it_compiles_to`` — runtime, two
ways. Repointing ``Application.__table__.c.due_at.type`` at
``DateTime(timezone=True)`` reds it with "declared timezone=False but the
column compiled to timezone=True"; repointing it at ``String()`` reds it with
"declared DateTime() but the column compiled to String()", which is the
not-a-DateTime case a ``UTCDateTime`` would present as. Reverting either
returns it to green.
"""

from __future__ import annotations

import types
import typing
from datetime import datetime

import sqlalchemy as sa
from pydantic_core import PydanticUndefined
from sqlmodel import SQLModel

# Importing the models module populates ``SQLModel.metadata`` and the mapper
# registry with every table.
from jobtracker.database import models  # noqa: F401

# A few fields that MUST turn up in the discovered set. Without this, an
# iteration that silently found nothing — a renamed registry attribute, an
# annotation shape this module does not recognise — would report a pass.
# Deliberately one of each shape the discovery has to handle: a plain
# ``datetime`` field, an ``Optional[datetime]`` one, a field inherited from
# ``TimestampMixin`` rather than declared on the table class, and one whose
# storage is declared through ``sa_column`` instead of ``sa_type``.
_MUST_BE_FOUND = {
    ("Email", "received_at"),
    ("Application", "due_at"),
    ("Application", "created_at"),
    ("UserCredential", "revoked_at"),
}


def _table_classes() -> list[type[SQLModel]]:
    """Every mapped SQLModel table class, by way of the mapper registry.

    ``SQLModel.metadata.tables`` answers for TABLES; this has to answer for
    CLASSES, because the declaration being checked lives on the class and not
    on the table. The two counts are asserted equal below so a class cannot
    drop out of this iteration while its table stays in the schema.
    """

    return sorted(
        {mapper.class_ for mapper in SQLModel._sa_registry.mappers},
        key=lambda cls: cls.__name__,
    )


def _is_datetime_annotation(annotation: object) -> bool:
    """True for ``datetime`` and ``Optional[datetime]``, false for ``date``.

    ``date`` is excluded deliberately: ``applications.applied_date`` is a
    ``DATE`` column and none of this applies to it. The union handling covers
    both spellings — ``typing.Optional[datetime]``, which this module uses, and
    ``datetime | None``, which ruff's UP045 would rewrite it to.
    """

    if annotation is datetime:
        return True
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return any(arg is datetime for arg in typing.get_args(annotation))
    return False


def _declared_storage(field) -> sa.DateTime | None:
    """The ``DateTime`` this field definition names, or ``None`` if it names none.

    Two legal spellings, and no third. ``sa_type`` is sqlmodel's documented
    "Keep Naive Storage" escape and is the only one that works on a mixin — one
    ``Column`` object cannot attach to the four tables that inherit
    ``TimestampMixin``. ``sa_column`` carries its type inside the ``Column``,
    and is what the ``timestamptz`` fields use.

    The ``isinstance`` check is the load-bearing part rather than "is it not
    Undefined": on sqlmodel >= 0.0.45 the *default* for a bare field is
    ``UTCDateTime``, a ``TypeDecorator`` that is not a ``DateTime`` subclass, so
    a looser check would accept exactly the thing this file exists to refuse.
    """

    sa_type = getattr(field, "sa_type", PydanticUndefined)
    if sa_type is not PydanticUndefined and isinstance(sa_type, sa.DateTime):
        return sa_type

    sa_column = getattr(field, "sa_column", PydanticUndefined)
    if sa_column is not PydanticUndefined:
        column_type = getattr(sa_column, "type", None)
        if isinstance(column_type, sa.DateTime):
            return column_type

    return None


def _datetime_fields() -> list[tuple[str, str, object]]:
    """``(class name, field name, FieldInfo)`` for every datetime field."""

    return [
        (cls.__name__, name, field)
        for cls in _table_classes()
        for name, field in cls.model_fields.items()
        if _is_datetime_annotation(field.annotation)
    ]


def test_every_table_class_is_reachable_from_the_registry():
    """One mapped class per table, so nothing escapes the iteration below."""

    classes = _table_classes()
    tables = SQLModel.metadata.tables

    assert len(classes) == len(tables), (
        f"{len(classes)} mapped classes against {len(tables)} tables in the "
        f"metadata: {sorted(cls.__name__ for cls in classes)} vs "
        f"{sorted(tables)}. A table whose class is not reachable here is a "
        f"table this gate does not check."
    )


def test_the_discovery_finds_the_fields_it_is_supposed_to_find():
    """The positive control: an empty iteration must not read as a pass."""

    found = {(cls_name, field_name) for cls_name, field_name, _ in _datetime_fields()}

    assert found >= _MUST_BE_FOUND, (
        f"the datetime-field discovery missed {sorted(_MUST_BE_FOUND - found)}. "
        f"It found {sorted(found)}. Either the annotation shape changed or the "
        f"registry walk does, and in both cases every assertion in this file "
        f"is reporting on a set it never looked at."
    )


def test_every_datetime_field_declares_its_storage():
    """No datetime field may inherit its column type from sqlmodel's default."""

    undeclared = [
        f"{cls_name}.{field_name}"
        for cls_name, field_name, field in _datetime_fields()
        if _declared_storage(field) is None
    ]

    assert not undeclared, (
        "these datetime fields declare no storage: "
        + ", ".join(undeclared)
        + ". Add `sa_type=sa.DateTime(timezone=False)` to keep the naive "
        "`timestamp without time zone` column the migrations created, or an "
        "explicit `sa_column=Column(..., sa.DateTime(timezone=True))` if the "
        "column really is `timestamptz`. Left bare, the field's type is "
        "whatever sqlmodel's default is: `DateTime(timezone=False)` up to "
        "0.0.44 and `UTCDateTime` (tz-aware, and it refuses naive writes) from "
        "0.0.45, so the column silently changes meaning on a dependency bump."
    )


def test_the_declared_storage_matches_the_column_it_compiles_to():
    """The declaration and the compiled column must not disagree.

    A second assertion rather than part of the one above, because it checks the
    other direction: the first says a human chose a type, this one says the
    choice is what reached the table.

    NO EDIT TO ``models.py`` CAN MAKE THIS FAIL, and that is not a defect in
    it — it is what the test is for. The column is BUILT from the declaration,
    so under a sqlmodel that honours ``sa_type`` the two agree by construction.
    What it guards is the library: a future sqlmodel release that ignores
    ``sa_type``, or honours it differently, would leave `models.py` looking
    correct while the compiled column moved underneath it. That is exactly the
    shape of the 0.0.45 change this whole file exists because of, and the one
    thing the declaration-side assertion above cannot see.

    Because of that it is mutated at RUNTIME rather than in source — see
    "Proven able to fail" in the module docstring.
    """

    disagreements = []
    for cls_name, field_name, field in _datetime_fields():
        declared = _declared_storage(field)
        if declared is None:
            continue  # the test above owns this case
        cls = next(c for c in _table_classes() if c.__name__ == cls_name)
        column = cls.__table__.columns[field_name]
        if not isinstance(column.type, sa.DateTime):
            disagreements.append(
                f"{cls_name}.{field_name}: declared {declared!r} but the column "
                f"compiled to {column.type!r}"
            )
        elif bool(column.type.timezone) != bool(declared.timezone):
            disagreements.append(
                f"{cls_name}.{field_name}: declared timezone="
                f"{declared.timezone!r} but the column compiled to timezone="
                f"{column.type.timezone!r}"
            )

    assert not disagreements, "\n".join(disagreements)
