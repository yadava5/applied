"""indexes the /mail, /review and board reads can actually use

Revision ID: c8f3a1d64b27
Revises: b3e91c47da05
Create Date: 2026-08-15 09:00:00.000000

Three indexes for issue #293, and a fourth that was **measured and rejected**.

Every plan below comes from ``postgres:16`` at ``en_US.utf8`` with 200,000
seeded ``emails`` and 200,000 seeded ``applications`` rows, ``VACUUM ANALYZE``d,
under ``EXPLAIN (ANALYZE, BUFFERS)``. Production holds 65 applications and 52
emails — three orders of magnitude below the point where any planner prefers an
index to a scan — so **no production speed-up is measured or claimed here**.
What is verified is the property that matters before real users arrive: that the
planner *can* use each of these, and that each one changes a plan. An index that
does not change a plan is write amplification and storage against the 500 MB
free tier, bought for nothing.
``tests/test_read_path_indexes_postgres.py`` is that verification, and it holds
a negative for every index: drop it, and the plan degrades back.

1. ``ix_emails_user_id_classified_as_received_at``
--------------------------------------------------
``(user_id, classified_as, received_at DESC, id DESC)``.

``GET /applications/mail`` filters ``(user_id, classified_as)`` and orders
``received_at DESC, id DESC``. Production has ``ix_emails_classified_as``
(global, one column) and ``ix_emails_user_id_received_at``; neither combines the
predicate with the sort, so the page walked the **global** ``received_at`` index
backwards and re-checked every row against both predicates::

    Limit -> Incremental Sort -> Index Scan Backward using ix_emails_received_at
      Filter: user_id = ... AND classified_as = 'REJECTION'
      Rows Removed by Filter: 470          Buffers: shared hit=19

That cost is proportional to how deep the scan must walk to find a page of one
category, so it is worst for the categories a user has *least* of — the rare
verdict is the expensive query. Measured at 200k rows: a common category cost
19 buffers, a rare one (``OFFER``, 1%) 149, and page 41 of a common one 663.
With the index all three become an ordered index scan with no sort and no
filter: **7/53/282 buffers**, and ``Rows Removed by Filter`` disappears because
both predicates are index conditions.

The listing's ``total`` count gains more. It was a bitmap scan over the global
category index plus a heap re-check of 20,000 rows (2,345 buffers, 5.5 ms); it
becomes an **index-only** scan, ``Heap Fetches: 0`` — **133 buffers, 3.2 ms**.

The trailing ``id`` is not decoration: the handler's ``ORDER BY`` carries it as
the tiebreak that keeps paging deterministic, and without it in the index the
plan keeps an Incremental Sort on top.

NOT covered, deliberately: the category-count chips (``GROUP BY classified_as``
over all of one user's mail) still choose a parallel sequential scan with this
index present — measured, unchanged. They are not in #293 and nothing here
claims to fix them.

2. ``ix_emails_review_queue`` — partial, with INCLUDE
-----------------------------------------------------
``(user_id, received_at DESC) INCLUDE (thread_id, message_id)``
``WHERE classified_as = 'NEEDS_REVIEW' AND application_id IS NULL
  AND is_reviewed = false``

``GET /applications/review`` and the ``needs_review`` tile on
``GET /applications/summary`` shared all four predicates WHEN THIS WAS WRITTEN.
The queue was reading the global ``received_at`` index and discarding 3,231
rows to find 100 (101 buffers); with this index it was 36 buffers and no
filter at all.

**NEITHER OF THEM DOES ANY MORE, AND NOTHING ELSE DOES EITHER (#826, DEC-007).**
Measured on a 200k-row corpus with every reader checked: the queue moved to a
``NOT EXISTS`` anti-join in #587/#597, the tile has no ``classified_as``
predicate at all, ``_reset_review_queue`` omits ``classified_as``, and
``linker.py``'s category list excludes ``NEEDS_REVIEW``. A partial index is
usable only while its predicate is implied by the query's, so this one is dead
coverage maintained on every write.

It is kept rather than dropped, and DEC-007 in ``docs/DECISIONS.md`` records
why: the cost is 856 kB at 200k rows and invisible at production's scale,
where dropping it means executing a revision against the production database
for a saving nobody can measure — and the only remaining readers of the index
are the two ``*_THE_INDEX_WAS_CUT_FOR`` literals in
``tests/test_read_path_indexes_postgres.py``, which are the sole surviving
evidence of what it was for.

**The ``INCLUDE`` is load-bearing.** Without it the summary tile's plan does not
change *at all* — the planner keeps its bitmap scan and its 2,312-buffer heap
re-check, because the tile counts
``DISTINCT coalesce(thread_id, message_id)`` and those two columns are only in
the heap. With them included the tile becomes an index-only scan: **52 buffers,
8.1 ms** against 2,312 buffers, 11.2 ms. Measured both ways; do not drop the
``INCLUDE`` as noise.

An index-only scan needs the visibility map, so a continuously-written table
pays some ``Heap Fetches`` between autovacuums. That degrades gradually — it
never falls back to the sequential scan.

**The partial predicate had to stay byte-identical to the handler's filter,
and no longer can: there is no handler filter left that implies it (#826,
DEC-007). Kept for the record of what it once matched.** It matches what
SQLAlchemy emits for
``Email.classified_as == EmailCategory.NEEDS_REVIEW``,
``Email.application_id.is_(None)`` and ``Email.is_reviewed == False`` (Postgres
renders the last as ``NOT is_reviewed`` in the plan and still matches). A future
refactor that changes one of those filters un-matches the index silently: the
queries keep working, the index goes dead, and every test stays green. The
Postgres suite asserts on the *plan* for exactly that reason.

``'NEEDS_REVIEW'`` is spelled in the enum's **label**, which is the Python member
NAME and not the API's lowercase value — see
``tests/test_migrations_postgres.py::test_the_lowercase_spelling_is_rejected_by_the_type``.
``'needs_review'`` here would be accepted by SQLite (which has no enum type) and
refused by Postgres on ``alembic upgrade head`` against production.

3. ``ix_applications_user_id_created_at_live`` — partial
--------------------------------------------------------
``(user_id, created_at DESC, id DESC) WHERE dismissed_at IS NULL``

The board's default sort. It was a parallel sequential scan of the whole table
plus a top-N heapsort — 2,942 buffers, 18.1 ms — i.e. one user's rows sorted in
memory on every board load. With this index the plan is an ordered index scan
that stops at the page size: **4 buffers, 0.04 ms**.

WHAT WAS MEASURED AND REJECTED
-------------------------------
#293 proposes ``(user_id, dismissed_at, created_at DESC, id DESC)`` for this.
Built and measured, it **does not change the board's plan**: Postgres keeps the
parallel sequential scan and the sort. Forced with ``enable_seqscan = off`` it
*still* refuses an ordered scan of that index and picks a bitmap scan over
``ix_applications_user_id`` plus a top-N sort instead. Reported as the
observation it is — an ``IS NULL`` leading column did not yield an ordered scan
here — rather than as a theory about the planner's internals; the fact is what
decides the index, and a wrong mechanism in a migration docstring outlives the
PR.

Its only measurable effect was on the ``dismissed=true`` branch (10.5 ms →
6.9 ms, still with a sort), which is the undo surface, not a hot read. An 11 MB
index for that is not a trade worth making, so it is not here.

DEPLOY
------
Additive and index-only. No column changes meaning, no data is rewritten, and
old code simply never uses them — whichever of the migration workflow and the
Vercel deploy wins the race, both halves work.

LOCK BEHAVIOUR, since this runs against production on merge. A plain
``CREATE INDEX`` takes a ``SHARE`` lock on the table: concurrent **reads** are
unaffected, concurrent **writes** (the Gmail sync's upserts) block for the
duration of the build. At 65 applications rows and 52 emails rows that build is
microseconds, so the exposure is a write that arrives inside the same instant as
the migration. ``CONCURRENTLY`` is deliberately NOT used and could not be:
it cannot run inside a transaction block and ``alembic/env.py`` wraps the whole
chain in one. Same reasoning, and same conclusion, as ``e7a1c4d92b30``. A table
large enough for the build to be slow would need that split — this one is not,
and pretending otherwise would trade a real lock for a chain that cannot run.

POSTGRES ONLY. Partial indexes with an enum literal, and ``INCLUDE``, are not
SQLite shapes, and the test suite's ``alembic check`` drift test runs on SQLite.
Guarding the dialect keeps the metadata and the chain in agreement there rather
than inventing second index definitions only one engine could build — again the
precedent ``e7a1c4d92b30`` set. The indexes are therefore NOT declared in
``__table_args__``.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8f3a1d64b27"
down_revision: str | Sequence[str] | None = "b3e91c47da05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MAIL_INDEX = "ix_emails_user_id_classified_as_received_at"
REVIEW_INDEX = "ix_emails_review_queue"
BOARD_INDEX = "ix_applications_user_id_created_at_live"

# Kept as module constants so the Postgres suite asserts against the SAME text
# the migration executes. A test that retyped the DDL would stay green if this
# revision were deleted.
STATEMENTS = (
    (
        MAIL_INDEX,
        f"CREATE INDEX IF NOT EXISTS {MAIL_INDEX} ON emails "
        "(user_id, classified_as, received_at DESC, id DESC)",
    ),
    (
        REVIEW_INDEX,
        f"CREATE INDEX IF NOT EXISTS {REVIEW_INDEX} ON emails "
        "(user_id, received_at DESC) INCLUDE (thread_id, message_id) "
        "WHERE classified_as = 'NEEDS_REVIEW' "
        "AND application_id IS NULL AND is_reviewed = false",
    ),
    (
        BOARD_INDEX,
        f"CREATE INDEX IF NOT EXISTS {BOARD_INDEX} ON applications "
        "(user_id, created_at DESC, id DESC) WHERE dismissed_at IS NULL",
    ),
)


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    """Create the three read-path indexes (Postgres only)."""

    if not _is_postgres():
        return
    for _name, statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Drop them. Losing an index costs speed, never data."""

    if not _is_postgres():
        return
    for name, _statement in STATEMENTS:
        op.execute(f"DROP INDEX IF EXISTS {name}")
