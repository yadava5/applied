"""The /mail, /review and board indexes, verified where the planner lives.

Sibling of ``test_company_index_postgres.py``, and the same discipline. Issue
#293 names three missing indexes; revision ``c8f3a1d64b27`` adds them.

WHY THIS MODULE HAS TO BE A POSTGRES MODULE
-------------------------------------------
Everything here is a *planner* fact. Two of the three indexes are partial and
one carries an ``INCLUDE``, neither of which SQLite plans the same way — and
SQLite's ``EXPLAIN`` has no shape these assertions could read. A SQLite
assertion would be green whether or not the production index works, which is
the "check that cannot fail" shape.

WHAT IS ASSERTED, AND WHAT IS NOT
---------------------------------
NOT a production speed-up. ``applications`` holds 65 rows and ``emails`` 52 in
the owner's database, three orders of magnitude below where any planner prefers
an index to a scan, so no honest before/after timing exists there and none is
claimed. What is asserted is the property that matters before real users
arrive: given a table large enough to *want* an index, the planner uses each of
these, for the query it was added for.

EVERY INDEX HAS A NEGATIVE
---------------------------
An index that does not change a plan is dead weight — a write amplified on
every sync and storage against a 500 MB free tier, bought for nothing. So each
``test_the_planner_uses_...`` is paired with a ``..._would_not_have_worked``
that drops the index (or builds the alternative that was rejected) and asserts
the plan degrades. The green tests only mean something because the red ones
hold.

``test_the_board_index_the_issue_proposed_does_not_work`` is the sharpest of
them: it builds the exact index #293 specifies, shows the planner ignores it,
and shows it is still ignored with ``enable_seqscan = off``. That is why the
migration ships a partial index instead.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from tests.pg_support import reset_public_schema, resolve_admin_url, sync_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

sys.path.insert(0, str(BACKEND_DIR / "alembic" / "versions"))

MAIL_INDEX = "ix_emails_user_id_classified_as_received_at"
REVIEW_INDEX = "ix_emails_review_queue"
BOARD_INDEX = "ix_applications_user_id_created_at_live"

# Big enough that a sequential scan is genuinely the cheaper plan at production
# row counts. At 52 emails Postgres would correctly ignore every index here, and
# a test seeded that way would assert nothing.
SEED_ROWS = 200_000

USER = uuid.UUID("3c9f1b52-7d0a-4e63-9f18-5b2c84a7e011")
OTHER = uuid.UUID("7d1e2b93-4c5a-4f81-9a02-1e6d37b5c092")

ADMIN_URL, _OWNED_CONTAINER = resolve_admin_url()

# NO ``teardown_module`` stopping the container: it is SHARED (see
# tests/pg_support.py), so whichever module finished first would pull the server
# out from under the others. A throwaway container dies with the pytest process.

pytestmark = pytest.mark.skipif(
    not ADMIN_URL,
    reason=(
        "No Postgres available: set JOBTRACKER_TEST_PG_ADMIN_URL, or run Docker "
        "so a throwaway postgres:16 can be started. Skipping leaves the three "
        "read-path indexes UNVERIFIED — the SQLite suites have no comparable "
        "planner, so nothing else in this repo can see whether they work."
    ),
)


@pytest.fixture(scope="module")
def seeded_engine():
    """A migrated database with tables large enough to prefer an index.

    The schema comes from ``alembic upgrade head`` — the real chain, in a
    subprocess — so this tests the indexes the migration actually creates rather
    than ones the test typed out itself. A hand-written ``CREATE INDEX`` here
    would stay green if the revision were deleted.
    """

    url = sync_url(ADMIN_URL)
    engine = create_engine(url, future=True)
    reset_public_schema(engine, owner_ids=(USER, OTHER))

    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=str(BACKEND_DIR),
        env=dict(os.environ, DIRECT_URL=url),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"alembic upgrade head failed ({proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )

    with engine.begin() as conn:
        # RLS is FORCEd on both tables by the chain; the seeding role must not be
        # blocked by a policy that has no JWT to evaluate.
        for table in ("emails", "applications"):
            conn.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))

        # 90% live / 10% dismissed, spread over two years, two owners — so
        # ``user_id`` is selective but not unique and the sort is real work.
        conn.execute(
            text(
                "INSERT INTO applications "
                "(user_id, company, position, status, source, dismissed_at, "
                " created_at, updated_at) "
                "SELECT CASE WHEN i % 10 = 0 THEN :other ELSE :uid END, "
                "       'Corp' || (i % 9000) || ' Holdings', 'Engineer', "
                "       'APPLIED', 'gmail', "
                "       CASE WHEN i % 10 = 1 "
                "            THEN now() - (i || ' minutes')::interval ELSE NULL END, "
                "       now() - (i || ' minutes')::interval, now() "
                "FROM generate_series(1, :n) AS i"
            ),
            {"uid": USER, "other": OTHER, "n": SEED_ROWS},
        )
        first_app = conn.execute(
            text("SELECT min(id) FROM applications WHERE user_id = :uid"),
            {"uid": USER},
        ).scalar()

        # A mailbox-shaped category mix: mostly OTHER, a long tail of lifecycle
        # verdicts, ~8% NEEDS_REVIEW of which half are already settled — so the
        # partial predicate is genuinely narrower than the category alone and an
        # index on the category is not a stand-in for it.
        #
        # The labels are the enum's Postgres labels, i.e. the Python member
        # NAMES. The API's lowercase spelling is not a label; see
        # test_migrations_postgres::test_the_lowercase_spelling_is_rejected_by_the_type.
        conn.execute(
            text(
                "INSERT INTO emails "
                "(user_id, application_id, source_account, message_id, thread_id, "
                " subject, sender_name, sender_email, received_at, classified_as, "
                " is_reviewed, user_corrected, created_at, updated_at) "
                "SELECT CASE WHEN i % 10 = 0 THEN :other ELSE :uid END, "
                "       CASE WHEN i % 25 = 0 THEN :app + (i % 500) ELSE NULL END, "
                "       'GMAIL', 'msg-' || i, 'thr-' || (i / 3), 'Subject ' || i, "
                "       'Sender ' || (i % 5000), 's' || (i % 5000) || '@example.com', "
                "       now() - (i || ' minutes')::interval, "
                "       (CASE "
                "          WHEN i % 100 < 15 THEN 'APPLIED' "
                "          WHEN i % 100 < 25 THEN 'REJECTION' "
                "          WHEN i % 100 < 28 THEN 'INTERVIEW' "
                "          WHEN i % 100 = 28 THEN 'OFFER' "
                "          WHEN i % 100 = 29 THEN 'ASSESSMENT' "
                "          WHEN i % 100 < 38 THEN 'NEEDS_REVIEW' "
                "          ELSE 'OTHER' END)::emailcategory, "
                "       (i % 100) IN (34, 35, 36, 37), "
                "       false, now(), now() "
                "FROM generate_series(1, :n) AS i"
            ),
            {"uid": USER, "other": OTHER, "app": first_app, "n": SEED_ROWS},
        )

    # VACUUM cannot run inside a transaction block, and it is not optional: the
    # index-only scans below need the visibility map, which ANALYZE does not
    # populate. Production gets this from autovacuum.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("VACUUM ANALYZE emails"))
        conn.execute(text("VACUUM ANALYZE applications"))

    yield engine
    engine.dispose()


def _plan(engine, sql: str) -> str:
    with engine.connect() as conn:
        return "\n".join(
            r[0]
            for r in conn.execute(text(f"EXPLAIN (COSTS OFF) {sql}"), {"uid": USER})
        )


def _recreate(engine, name: str) -> None:
    """Rebuild one index from the MIGRATION's own DDL, not a retyped copy."""

    from c8f3a1d64b27_read_path_indexes import STATEMENTS

    statement = dict(STATEMENTS)[name]
    with engine.begin() as conn:
        conn.execute(text(statement))
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("VACUUM ANALYZE emails"))
        conn.execute(text("VACUUM ANALYZE applications"))


# The queries the three handlers issue. Kept as literals rather than built from
# the ORM so a refactor of a handler cannot quietly change what is measured —
# and so a refactor that changes a PREDICATE (which would un-match the partial
# index) shows up here as a plan change rather than silently.
MAIL_PAGE = (
    "SELECT * FROM emails WHERE user_id = :uid AND classified_as = 'REJECTION' "
    "ORDER BY received_at DESC, id DESC LIMIT 50"
)
MAIL_COUNT = (
    "SELECT count(*) FROM emails WHERE user_id = :uid AND classified_as = 'REJECTION'"
)
REVIEW_QUEUE = (
    "SELECT * FROM emails WHERE user_id = :uid AND classified_as = 'NEEDS_REVIEW' "
    "AND application_id IS NULL AND is_reviewed = false "
    "ORDER BY received_at DESC LIMIT 100"
)
SUMMARY_TILE = (
    "SELECT count(DISTINCT coalesce(thread_id, message_id)) FROM emails "
    "WHERE user_id = :uid AND classified_as = 'NEEDS_REVIEW' "
    "AND application_id IS NULL AND is_reviewed = false"
)
BOARD_PAGE = (
    "SELECT * FROM applications WHERE user_id = :uid AND dismissed_at IS NULL "
    "ORDER BY created_at DESC, id DESC LIMIT 50"
)

# The shape #293 proposed for the board, measured and rejected. Named here so
# the rejection is reproducible rather than a claim in a docstring.
REJECTED_BOARD_INDEX = "ix_applications_user_id_dismissed_created"


def test_the_migration_creates_all_three(seeded_engine):
    """They exist, in the shapes the fix depends on."""

    with seeded_engine.connect() as conn:
        defs = dict(
            conn.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE indexname = ANY(:names)"
                ),
                {"names": [MAIL_INDEX, REVIEW_INDEX, BOARD_INDEX]},
            ).all()
        )

    assert set(defs) == {MAIL_INDEX, REVIEW_INDEX, BOARD_INDEX}, (
        f"the chain created {sorted(defs)}"
    )
    assert "classified_as" in defs[MAIL_INDEX] and "received_at" in defs[MAIL_INDEX]
    # The INCLUDE is load-bearing — without it the summary tile's plan does not
    # change at all. Asserted structurally so it cannot be dropped as noise.
    assert "INCLUDE" in defs[REVIEW_INDEX].upper(), defs[REVIEW_INDEX]
    assert "thread_id" in defs[REVIEW_INDEX] and "message_id" in defs[REVIEW_INDEX]
    assert "WHERE" in defs[REVIEW_INDEX].upper(), defs[REVIEW_INDEX]
    assert "dismissed_at IS NULL" in defs[BOARD_INDEX], defs[BOARD_INDEX]


def test_the_enum_label_in_the_partial_predicate_is_the_one_postgres_stores(
    seeded_engine,
):
    """The trap this migration had to avoid, asserted rather than remembered.

    The partial predicate names ``'NEEDS_REVIEW'``. Postgres stores the enum's
    Python member NAME, not the API's lowercase value — so ``'needs_review'``
    would have been accepted by every SQLite suite and refused by
    ``alembic upgrade head`` against production. This asserts both halves: the
    label exists, and the lowercase spelling is not a label at all.
    """

    with seeded_engine.connect() as conn:
        labels = list(conn.execute(text("SELECT unnest(enum_range(NULL::emailcategory))")).scalars())

    assert "NEEDS_REVIEW" in labels, labels
    assert "needs_review" not in labels, (
        "the lowercase spelling IS a label here, so the migration's predicate "
        "would have been accepted either way and this gate proves nothing"
    )


# =============================================================================
# 1. /mail — (user_id, classified_as, received_at DESC, id DESC)
# =============================================================================


def test_the_planner_uses_the_mail_index_for_the_page(seeded_engine):
    """Both predicates become index conditions and the sort disappears."""

    plan = _plan(seeded_engine, MAIL_PAGE)

    assert MAIL_INDEX in plan, f"the mail page fell back to another scan:\n{plan}"
    assert "Sort" not in plan, (
        f"the page is still sorting; the index does not cover the ORDER BY:\n{plan}"
    )
    assert "Filter:" not in plan, (
        f"a predicate is being re-checked per row rather than seeked:\n{plan}"
    )


def test_the_mail_count_becomes_an_index_only_scan(seeded_engine):
    """``total`` never touches the heap — it was a 2,345-buffer bitmap re-check."""

    plan = _plan(seeded_engine, MAIL_COUNT)

    assert "Index Only Scan" in plan and MAIL_INDEX in plan, (
        f"the listing count still reads the heap:\n{plan}"
    )


def test_without_the_mail_index_the_page_sorts_the_global_received_at_index(
    seeded_engine,
):
    """PROVE THE INSTRUMENT. Drop it and the old plan comes back.

    Without this, the two green tests above are only "some index exists".
    """

    with seeded_engine.begin() as conn:
        conn.execute(text(f"DROP INDEX {MAIL_INDEX}"))
    try:
        plan = _plan(seeded_engine, MAIL_PAGE)
        assert MAIL_INDEX not in plan
        assert "Sort" in plan and "Filter:" in plan, (
            "without the index the page was expected to fall back to sorting a "
            f"filtered scan; it did not, so the index buys nothing:\n{plan}"
        )
        count_plan = _plan(seeded_engine, MAIL_COUNT)
        assert "Index Only Scan" not in count_plan, (
            f"the count was index-only WITHOUT the new index:\n{count_plan}"
        )
    finally:
        _recreate(seeded_engine, MAIL_INDEX)


# =============================================================================
# 2. /review + the summary tile — the partial index, with INCLUDE
# =============================================================================


def test_the_planner_uses_the_partial_index_for_the_review_queue(seeded_engine):
    """All four predicates are in the index, so none is left as a Filter."""

    plan = _plan(seeded_engine, REVIEW_QUEUE)

    assert REVIEW_INDEX in plan, f"the review queue fell back to a scan:\n{plan}"
    assert "Filter:" not in plan, (
        f"the queue is still re-checking rows it read for another reason:\n{plan}"
    )


def test_the_summary_tile_becomes_an_index_only_scan(seeded_engine):
    """The half the ``INCLUDE`` buys, and the reason it is in the index."""

    plan = _plan(seeded_engine, SUMMARY_TILE)

    assert "Index Only Scan" in plan and REVIEW_INDEX in plan, (
        f"the needs-review tile still bitmap-scans and re-checks the heap:\n{plan}"
    )


def test_the_partial_index_without_include_does_not_help_the_tile(seeded_engine):
    """PROVE THE ``INCLUDE`` EARNS ITS PLACE — measured, not assumed.

    Rebuilds the same partial index WITHOUT the two included columns. The review
    queue still uses it (it only needs the ordering), but the tile falls back to
    its bitmap heap scan, because ``count(DISTINCT coalesce(thread_id,
    message_id))`` cannot be answered from an index that does not carry those
    columns. Without this test the ``INCLUDE`` reads as superstition and the
    next person deletes it.
    """

    with seeded_engine.begin() as conn:
        conn.execute(text(f"DROP INDEX {REVIEW_INDEX}"))
        conn.execute(
            text(
                f"CREATE INDEX {REVIEW_INDEX} ON emails (user_id, received_at DESC) "
                "WHERE classified_as = 'NEEDS_REVIEW' AND application_id IS NULL "
                "AND is_reviewed = false"
            )
        )
    with seeded_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("VACUUM ANALYZE emails"))
    try:
        queue_plan = _plan(seeded_engine, REVIEW_QUEUE)
        assert REVIEW_INDEX in queue_plan, queue_plan

        tile_plan = _plan(seeded_engine, SUMMARY_TILE)
        assert "Index Only Scan" not in tile_plan, (
            "the tile was index-only WITHOUT the included columns, so the "
            f"INCLUDE buys nothing and should come out:\n{tile_plan}"
        )
    finally:
        with seeded_engine.begin() as conn:
            conn.execute(text(f"DROP INDEX {REVIEW_INDEX}"))
        _recreate(seeded_engine, REVIEW_INDEX)


def test_a_changed_handler_predicate_would_silently_un_match_the_partial_index(
    seeded_engine,
):
    """The failure mode a partial index has and a plain one does not.

    The index is only usable while its predicate implies the query's. Change one
    filter in the handler — here, drop ``is_reviewed = false`` — and the index
    goes dead while every functional test stays green, because the query still
    returns correct rows. This is why the assertions in this module are on the
    PLAN, and it is the thing to check first if the review queue ever gets slow
    again.
    """

    # The contrast is the test. Without this line the assertion below would also
    # hold on a database where the index simply does not exist.
    assert REVIEW_INDEX in _plan(seeded_engine, REVIEW_QUEUE)

    widened = (
        "SELECT * FROM emails WHERE user_id = :uid AND classified_as = 'NEEDS_REVIEW' "
        "AND application_id IS NULL ORDER BY received_at DESC LIMIT 100"
    )
    plan = _plan(seeded_engine, widened)

    assert REVIEW_INDEX not in plan, (
        "a query missing one of the partial predicates still used the partial "
        f"index; the predicate match is not what this module thinks it is:\n{plan}"
    )


# =============================================================================
# 3. the board sort — a PARTIAL index, and why not the one the issue proposed
# =============================================================================


def test_the_planner_uses_the_board_index_for_the_default_sort(seeded_engine):
    """One user's rows stop being sorted in memory on every board load."""

    plan = _plan(seeded_engine, BOARD_PAGE)

    assert BOARD_INDEX in plan, f"the board sort fell back to a scan:\n{plan}"
    assert "Sort" not in plan, f"the board is still sorting:\n{plan}"
    assert "Seq Scan" not in plan, plan


def test_without_the_board_index_the_sort_is_a_parallel_seq_scan(seeded_engine):
    """PROVE THE INSTRUMENT: drop it and the sequential scan returns."""

    with seeded_engine.begin() as conn:
        conn.execute(text(f"DROP INDEX {BOARD_INDEX}"))
    try:
        plan = _plan(seeded_engine, BOARD_PAGE)
        assert "Seq Scan" in plan and "Sort" in plan, (
            f"without the index the board did not degrade:\n{plan}"
        )
    finally:
        _recreate(seeded_engine, BOARD_INDEX)


def test_the_board_index_the_issue_proposed_does_not_work(seeded_engine):
    """THE MEASURED REJECTION, reproducible rather than asserted in prose.

    #293 proposes ``(user_id, dismissed_at, created_at DESC, id DESC)``. Built
    here, with the shipped partial index dropped so the planner has only it to
    choose from, the board sort keeps its sequential scan and its top-N sort —
    and keeps them even with ``enable_seqscan = off``, where the planner reaches
    for a bitmap scan over ``ix_applications_user_id`` plus a sort rather than an
    ordered scan of the proposed index.

    Reported as the observation it is: a leading ``IS NULL`` column did not yield
    an ordered index scan here. The migration ships the partial index because of
    this measurement, and an index that does not change a plan is dead weight.
    """

    with seeded_engine.begin() as conn:
        conn.execute(text(f"DROP INDEX {BOARD_INDEX}"))
        conn.execute(
            text(
                f"CREATE INDEX {REJECTED_BOARD_INDEX} ON applications "
                "(user_id, dismissed_at, created_at DESC, id DESC)"
            )
        )
    with seeded_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("VACUUM ANALYZE applications"))
    try:
        plan = _plan(seeded_engine, BOARD_PAGE)
        assert REJECTED_BOARD_INDEX not in plan, (
            "the index #293 proposed DID serve the board sort on this database. "
            "The rejection recorded in c8f3a1d64b27's docstring no longer holds "
            f"— re-measure before trusting it:\n{plan}"
        )
        assert "Sort" in plan, plan

        with seeded_engine.connect() as conn:
            conn.execute(text("SET enable_seqscan = off"))
            forced = "\n".join(
                r[0]
                for r in conn.execute(
                    text(f"EXPLAIN (COSTS OFF) {BOARD_PAGE}"), {"uid": USER}
                )
            )
        assert "Sort" in forced, (
            "with sequential scans disabled the proposed index produced an "
            f"ordered scan after all:\n{forced}"
        )
    finally:
        with seeded_engine.begin() as conn:
            conn.execute(text(f"DROP INDEX {REJECTED_BOARD_INDEX}"))
        _recreate(seeded_engine, BOARD_INDEX)


# =============================================================================
# …and the SQL above is the SQL the handlers actually emit
# =============================================================================


def test_the_orm_emits_the_predicates_these_indexes_were_measured_against(
    seeded_engine,
):
    """CLOSE THE LITERAL-VS-ORM GAP. Otherwise every test above can be green
    while all three indexes are dead in production.

    The queries in this module are literals on purpose — a refactor of a handler
    must not quietly change what is measured. The risk runs the other way too:
    if SQLAlchemy compiles something the indexes do not match, nothing here
    would say so. So this builds the statements the way the handlers build them,
    compiles them for Postgres, and EXPLAINs *that* — not a retyped copy.

    The sharpest case is ``Email.is_reviewed == False``. Postgres renders it as
    ``NOT is_reviewed`` in a plan while the partial index's predicate says
    ``is_reviewed = false``; they match, and this is the assertion that keeps
    knowing so.
    """

    from sqlalchemy import func
    from sqlalchemy.dialects import postgresql
    from sqlmodel import select

    from jobtracker.database.models import Application, Email, EmailCategory

    review_predicates = (
        Email.user_id == USER,
        Email.classified_as == EmailCategory.NEEDS_REVIEW,
        Email.application_id.is_(None),
        Email.is_reviewed == False,  # noqa: E712
    )

    statements = {
        MAIL_INDEX: (
            select(Email)
            .where(Email.user_id == USER, Email.classified_as == EmailCategory.REJECTION)
            .order_by(Email.received_at.desc(), Email.id.desc())
            .offset(0)
            .limit(50),
            select(func.count())
            .select_from(Email)
            .where(Email.user_id == USER, Email.classified_as == EmailCategory.REJECTION),
        ),
        REVIEW_INDEX: (
            select(Email)
            .where(*review_predicates)
            .order_by(Email.received_at.desc())
            .limit(100),
            select(
                func.count(
                    func.distinct(func.coalesce(Email.thread_id, Email.message_id))
                )
            )
            .select_from(Email)
            .where(*review_predicates),
        ),
        BOARD_INDEX: (
            select(Application)
            .where(Application.user_id == USER, Application.dismissed_at.is_(None))
            .order_by(Application.created_at.desc(), Application.id.desc())
            .offset(0)
            .limit(50),
        ),
    }

    for index_name, group in statements.items():
        for statement in group:
            sql = str(
                statement.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
            with seeded_engine.connect() as conn:
                plan = "\n".join(
                    r[0] for r in conn.execute(text(f"EXPLAIN (COSTS OFF) {sql}"))
                )
            assert index_name in plan, (
                "the statement the HANDLER compiles does not use "
                f"{index_name}, even though the literal in this module does — "
                f"the index is dead in production:\n{sql}\n\n{plan}"
            )


def test_the_collation_is_the_production_one(seeded_engine):
    """Pin the fixture's assumption, as the company-index module does.

    Nothing here is collation-dependent the way ``text_pattern_ops`` was, but a
    ``C`` database differs from Supabase's ``en_US.utf8`` in enough planner
    respects that a conclusion drawn on one should not be quoted about the
    other.
    """

    with seeded_engine.connect() as conn:
        collation = conn.execute(
            text("SELECT datcollate FROM pg_database WHERE datname = current_database()")
        ).scalar()

    assert collation and not collation.startswith("C"), (
        f"test database collation is {collation!r}; production (Supabase) is "
        "en_US.utf8 and this suite's conclusions do not transfer"
    )
