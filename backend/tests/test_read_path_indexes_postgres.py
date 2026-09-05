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

WHAT ``ix_emails_review_queue`` MEASURES NOW
--------------------------------------------
Not the review queue, and not the summary tile. Its partial predicate names
``application_id IS NULL``; both readers stopped asking that in #587 and now ask
"no application of mine answers this"
(:func:`~jobtracker.cloud.applications._not_filed_on_an_application_that_answers`),
which does not imply it — so the partial index is unusable on both paths. The
two constants below named ``…_THE_INDEX_WAS_CUT_FOR`` are the shapes it does
still serve, kept because they are the only demonstration that the shipped index
and its ``INCLUDE`` work at all. What the handlers compile TODAY is measured
separately, off the handler's own predicate builder, in
``test_the_orm_emits_the_predicates_these_indexes_were_measured_against``.
Keeping both is the point: one says the shipped index works, the other says
nothing in the product reaches it. This module claimed the opposite for months,
which is #590.
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


# The /mail queries the handler issues. Kept as literals rather than built from
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

# …and that last sentence is exactly what did NOT happen for the next two, which
# is why they are named for what they are rather than for handlers that stopped
# issuing them (#590). Both were once "the review queue" and "the summary tile":
#
#   * the queue's ``application_id IS NULL`` became a NOT EXISTS in #587 and was
#     widened again in #597. See
#     :func:`~jobtracker.cloud.applications._filed_on_an_application_that_answers`,
#     section "THE INDEX COST, MEASURED", which carries the before/after and the
#     decision to leave the index as it is rather than re-cut it;
#   * the tile stopped counting ``DISTINCT coalesce(thread_id, message_id)`` in
#     #454 — it selects the keying columns and dedups in Python now, through
#     ``pipeline.review_dedup_key``, because the key needs the subject and
#     snippet and SQL here cannot parse those.
#
# A literal notices neither, which is the defect #590 names. They are kept, under
# honest names, because they remain the only demonstration that the SHIPPED
# partial index works for the query it was cut for and that its ``INCLUDE``
# earns its place. The handlers' real statements are compiled from the ORM, off
# the imported predicate, in
# ``test_the_orm_emits_the_predicates_these_indexes_were_measured_against``.
# DEC-007: these two literals are the ONLY remaining readers of
# `ix_emails_review_queue`. No product query implies its predicate any more
# (#826), so they are what proves the shipped index still works at all — a
# negative control, kept deliberately rather than deleted with the coverage.
# Dropping the index would delete this evidence along with it.
QUEUE_THE_INDEX_WAS_CUT_FOR = (
    "SELECT * FROM emails WHERE user_id = :uid AND classified_as = 'NEEDS_REVIEW' "
    "AND application_id IS NULL AND is_reviewed = false "
    "ORDER BY received_at DESC LIMIT 100"
)
TILE_THE_INDEX_WAS_CUT_FOR = (
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
# 2. the partial index, with INCLUDE — for the queries it was CUT for
#
# Which are no longer the queries the review queue and the summary tile issue;
# see the constants above and the ORM test at the end of this file. These three
# cases are facts about the shipped index, not about either handler.
# =============================================================================


def test_the_planner_uses_the_partial_index_for_the_query_it_was_cut_for(seeded_engine):
    """All four predicates are in the index, so none is left as a Filter."""

    plan = _plan(seeded_engine, QUEUE_THE_INDEX_WAS_CUT_FOR)

    assert REVIEW_INDEX in plan, f"the cut-for queue query fell back to a scan:\n{plan}"
    assert "Filter:" not in plan, (
        f"the query is still re-checking rows it read for another reason:\n{plan}"
    )


def test_the_tile_query_the_index_was_cut_for_becomes_an_index_only_scan(seeded_engine):
    """The half the ``INCLUDE`` buys, and the reason it is in the index.

    ``count(DISTINCT coalesce(thread_id, message_id))`` is the shape the tile
    issued until #454, not what it issues today — so this is what the INCLUDE
    was bought for, and it is still the only thing that exercises it.
    """

    plan = _plan(seeded_engine, TILE_THE_INDEX_WAS_CUT_FOR)

    assert "Index Only Scan" in plan and REVIEW_INDEX in plan, (
        f"the cut-for tile query still bitmap-scans and re-checks the heap:\n{plan}"
    )


def test_the_partial_index_without_include_does_not_help_that_tile_query(seeded_engine):
    """PROVE THE ``INCLUDE`` EARNS ITS PLACE — measured, not assumed.

    Rebuilds the same partial index WITHOUT the two included columns. The
    cut-for queue query still uses it (it only needs the ordering), but the
    cut-for tile query falls back to its bitmap heap scan, because
    ``count(DISTINCT coalesce(thread_id, message_id))`` cannot be answered from
    an index that does not carry those columns. Without this test the
    ``INCLUDE`` reads as superstition and the next person deletes it.

    What it does NOT establish, since #454 and #587 moved both handlers off
    these shapes: that either column earns its place for a query the product
    issues. No statement the product compiles can use this index at all — a
    property of the index rather than of this module, and the reason this case
    is worded about the query rather than about the tile.
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
        queue_plan = _plan(seeded_engine, QUEUE_THE_INDEX_WAS_CUT_FOR)
        assert REVIEW_INDEX in queue_plan, queue_plan

        tile_plan = _plan(seeded_engine, TILE_THE_INDEX_WAS_CUT_FOR)
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

    WHAT THIS CASE DOES NOT SEE, said out loud because its name suggests
    otherwise: the handler. The predicate it changes is the widened literal
    below, not
    :func:`~jobtracker.cloud.applications._not_filed_on_an_application_that_answers`,
    so it demonstrates the failure mode rather than detecting an instance of
    one — and it stayed green through the real instance, twice (#587's rename,
    and a mutation that deleted the handler's application filter outright). The
    case that reads the handler is
    ``test_the_orm_emits_the_predicates_these_indexes_were_measured_against``.
    """

    # The contrast is the test. Without this line the assertion below would also
    # hold on a database where the index simply does not exist.
    assert REVIEW_INDEX in _plan(seeded_engine, QUEUE_THE_INDEX_WAS_CUT_FOR)

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
# …and what the handlers actually emit, which for two of them is no longer the
# SQL above
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
    off the handler's OWN predicate builder, compiles them for Postgres, and
    EXPLAINs *that* — not a retyped copy.

    The sharpest case is ``Email.is_reviewed == False``. Postgres renders it as
    ``NOT is_reviewed`` in a plan while the partial index's predicate says
    ``is_reviewed = false``; they match, and this is the assertion that keeps
    knowing so.

    WHY THE TWO REVIEW CASES DO NOT EXPECT ``ix_emails_review_queue``
    -----------------------------------------------------------------
    Because the handlers can no longer use it, and this module said otherwise
    for months — which is #590.
    :func:`~jobtracker.cloud.applications._not_filed_on_an_application_that_answers`
    is a ``NOT EXISTS`` over ``applications``; a partial index is usable only
    while its predicate is implied by the query's, and that one does not imply
    ``application_id IS NULL``. So the queue plans as an anti join whose outer
    side is the MAIL index and whose inner probe is ``applications_pkey``, and
    the expectations below encode exactly that. An expectation the codebase
    abandoned is not coverage; changing this one to match the plan is not the
    same act as loosening it, and the negatives are what keep the difference
    visible — a re-cut index, or a predicate that goes back to
    ``application_id IS NULL``, reds this case rather than sliding through.

    THE COST OF THAT MOVE IS RECORDED WHERE THE DECISION IS, NOT HERE. See
    :func:`~jobtracker.cloud.applications._filed_on_an_application_that_answers`,
    section "THE INDEX COST, MEASURED": it carries the before/after buffers,
    says whose measurement they are, and records "left as it is rather than
    re-cut". Cited rather than copied — a second copy of a number drifts the way
    a second copy of a predicate does, and nothing here re-measured them.

    WHAT IS STILL RETYPED, AND WHAT WOULD FIX IT
    ---------------------------------------------
    The tile's projection. Its PREDICATE is imported, which is the half that
    moves a plan, but the ``select()`` itself is built inline inside
    :func:`~jobtracker.cloud.applications.application_summary_cloud` and there is
    no statement to import — so those six columns are a copy, and a copy is the
    thing this issue is about. What would close it is a
    ``_review_queue_rows_statement(user_id)`` in ``applications.py`` that the
    endpoint and this test both call; that is a production refactor for a test's
    benefit and is deliberately NOT done here. Until it exists this projection is
    checked by a human against ``applications.py``, and saying which half is
    imported beats letting the import at the top imply both.
    """

    from sqlalchemy import func
    from sqlalchemy.dialects import postgresql
    from sqlmodel import select

    from jobtracker.cloud.applications import (
        _not_filed_on_an_application_that_answers,
    )
    from jobtracker.database.models import Application, Email, EmailCategory

    # IMPORTED, NOT RETYPED, and that is the whole point of #590. This file
    # used to spell `Email.application_id.is_(None)` here — a second copy of a
    # predicate the handler owns. A copy cannot see the original change: the
    # handler's entire application filter was deleted in a mutation run and
    # every case in this module still passed, including the one named
    # `test_a_changed_handler_predicate_would_silently_un_match_the_partial_index`.
    #
    # Importing the accessor makes that impossible rather than merely
    # discouraged, which is the same argument `_not_filed_on_an_application_that_answers`
    # makes for being the mechanical negation of its own partner (#596).
    # `Email.is_reviewed == False` stays alongside it because the handler keeps
    # it alongside too — that is stated in the accessor's own docstring.
    review_predicates = (
        Email.user_id == USER,
        Email.classified_as == EmailCategory.NEEDS_REVIEW,
        _not_filed_on_an_application_that_answers(USER),
        Email.is_reviewed == False,  # noqa: E712
    )

    # (the handler, its statement, fragments the plan MUST carry, fragments it
    # must NOT). Keyed by handler rather than by index now: two of these five no
    # longer reach the index this file names for them, and a dict keyed by index
    # name cannot say that.
    cases = (
        (
            "GET /mail — the page",
            select(Email)
            .where(Email.user_id == USER, Email.classified_as == EmailCategory.REJECTION)
            .order_by(Email.received_at.desc(), Email.id.desc())
            .offset(0)
            .limit(50),
            (MAIL_INDEX,),
            (),
        ),
        (
            "GET /mail — the total",
            select(func.count())
            .select_from(Email)
            .where(Email.user_id == USER, Email.classified_as == EmailCategory.REJECTION),
            (MAIL_INDEX,),
            (),
        ),
        (
            "GET /applications/review — the queue",
            select(Email)
            .where(*review_predicates)
            .order_by(Email.received_at.desc())
            .limit(100),
            # The whole access path, not "some index was used": the anti join,
            # the mail index on its outer side, the pkey probe on its inner. The
            # ORDER BY + LIMIT is what makes this a nested loop rather than a
            # statistics question, so naming both sides is safe here.
            ("Anti Join", MAIL_INDEX, "applications_pkey"),
            (REVIEW_INDEX,),
        ),
        (
            "GET /applications/summary — the needs_review tile",
            # RETYPED PROJECTION, IMPORTED PREDICATE — see the docstring. The
            # columns are ``pipeline.review_dedup_key``'s inputs; the tile stopped
            # counting DISTINCT coalesce(thread_id, message_id) in #454 because
            # that key cannot be computed in SQL.
            select(
                Email.message_id,
                Email.thread_id,
                Email.subject,
                Email.body_snippet,
                Email.identity_role,
                Email.identity_req_id,
            ).where(*review_predicates),
            # No ORDER BY and no LIMIT, so WHICH join and WHICH scan the planner
            # picks here is a fact about this corpus's statistics rather than
            # about the handler. Asserted only at the level that is about the
            # handler: applications is joined, anti, on every call.
            ("Anti Join", "applications"),
            (REVIEW_INDEX,),
        ),
        (
            "GET /applications — the board page",
            select(Application)
            .where(Application.user_id == USER, Application.dismissed_at.is_(None))
            .order_by(Application.created_at.desc(), Application.id.desc())
            .offset(0)
            .limit(50),
            (BOARD_INDEX,),
            (),
        ),
    )

    for handler, statement, expected, forbidden in cases:
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

        for fragment in expected:
            assert fragment in plan, (
                f"{handler}: the statement the HANDLER compiles no longer shows "
                f"{fragment!r} in its plan. Its access path has moved, which is "
                "the event this module exists to notice — measure the new one "
                "and change this expectation deliberately, rather than dropping "
                f"the fragment:\n{sql}\n\n{plan}"
            )
        for fragment in forbidden:
            assert fragment not in plan, (
                f"{handler}: the statement the HANDLER compiles used "
                f"{fragment!r}. For {REVIEW_INDEX} that means either the "
                "readers' predicate implies `application_id IS NULL` again, or "
                "the index was re-cut around the NOT EXISTS. Both reverse the "
                "decision recorded in `_filed_on_an_application_that_answers` "
                "under 'THE INDEX COST, MEASURED', and neither should land "
                f"silently:\n{sql}\n\n{plan}"
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
