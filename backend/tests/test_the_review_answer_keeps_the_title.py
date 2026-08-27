"""Answering a review item files the mail and drops the job title it named (#546).

A message the classifier is unsure of goes to the review queue. The card it
belongs to keeps whatever title it already had — usually none, because the
message that opened the card was a role-less acknowledgement.

When the user answers the queue, ``classify_review_item`` derives the role two
lines before it decides where the message goes, and then writes it **only on the
branch that mints a row**. The branch that resolves onto an existing row updates
the stage and the source and never touches ``position``.
``reconcile_orphaned_classifications`` has the same shape.

So the user does the thing the queue asked them to do, the message lands on the
right application, and the card still shows no job. Nothing repairs it later
either: the message is linked, so the orphan catch-up's own predicate excludes
it, and a below-gate message never joins a rolled cluster, so the sync upsert's
title write is never reached for it. The role was in the product's hands and was
dropped.

Measured over the 9,252-card independent corpus: **26 cards** whose title is
readable, sits in the review queue, and never arrives. On the owner's live board
on 2026-08-27, **8 of 57 cards show no job title** and every one of them has
``position_source`` NULL — nobody typed those, and nobody cleared them.

WHAT THIS FILE PINS, and the second half is the reason it exists. Filling a
blank title is the easy direction; the assertions that matter are the ones
saying which titles must NOT be touched, because the condition next door in
:func:`upsert_applications_for_user` is deliberately more permissive and copying
it verbatim here would rename cards under the user off a single uncertain
message.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlmodel import select

from jobtracker.cloud import applications as apps
from jobtracker.cloud import pipeline as p
from jobtracker.database.models import (
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
    EmailSource,
)

USER = uuid.UUID("22222222-2222-2222-2222-222222222222")
BASE = datetime.datetime(2026, 8, 11, 2, 0)

#: Two employers, because the catch-up loops over orphans and the bug this file
#: is most worried about only shows when the loop carries something from one
#: iteration into the next.
ACME_SENDER = "noreply@mail.amazon.jobs"
ACME_SUBJECT = "Thank you for Applying to Amazon!"
ACME_TOKEN = "amazon"

OTHER_SENDER = "careers@northwindlabs.com"
OTHER_SUBJECT = "Thank you for Applying to Northwind Labs!"
OTHER_TOKEN = "northwindlabs"

ROLE = "Backend Engineer"
REQ = "4471002"


def _named(role: str, req: str) -> str:
    """A confirmation that names the role, in the shape the extractor reads."""

    return (
        "Hi Ayush, Thanks for applying! We've received your "
        f"application for the {role} (ID: {req}) position. What happens next?"
    )


def _silent() -> str:
    """The same genre of message, naming no job at all.

    This is not a contrived string: it is the wording that produces most of the
    blank cards on the real board, and the reason the corpus had to stop
    asserting a title for mail like it (#533).
    """

    return (
        "Hi Ayush, thank you for your interest in potential opportunities with "
        "us. Your details have been added to our database and we will be in "
        "touch if a suitable role opens up."
    )


def _row(
    *,
    company: str,
    position: str = "",
    position_source: str | None = None,
    source: str = apps.SOURCE_GMAIL_AUTO,
    req_id: str | None = None,
    role_token: str | None = None,
    status: ApplicationStatus = ApplicationStatus.APPLIED,
) -> Application:
    return Application(
        user_id=USER,
        company=company,
        position=position,
        position_source=position_source,
        status=status,
        source=source,
        req_id=req_id,
        role_token=role_token,
    )


def _mail(
    message_id: str,
    *,
    sender: str,
    subject: str,
    body: str,
    category: EmailCategory,
    minutes: int = 0,
    reviewed: bool = False,
    application_id: int | None = None,
    identity_role: str | None = None,
    identity_req_id: str | None = None,
) -> Email:
    return Email(
        user_id=USER,
        application_id=application_id,
        source_account=EmailSource.GMAIL,
        message_id=message_id,
        thread_id=None,
        subject=subject,
        sender_email=sender,
        body_snippet=body,
        received_at=BASE + datetime.timedelta(minutes=minutes),
        classified_as=category,
        classification_confidence=0.75,
        is_reviewed=reviewed,
        user_corrected=reviewed,
        identity_role=identity_role,
        identity_req_id=identity_req_id,
    )


async def _seed(session, *rows) -> None:
    for row in rows:
        session.add(row)
    await session.commit()


async def _reload(session, app_id: int) -> Application:
    row = (await session.exec(select(Application).where(Application.id == app_id))).first()
    await session.refresh(row)
    return row


# ── the premise, asserted before anything depends on it ──────────────────────


def test_the_fixtures_say_what_this_file_thinks_they_say() -> None:
    """Every assertion below is worth exactly this much.

    A fixture whose role the extractor cannot read makes every "the title
    arrives" test exercise ``role=None``, where writing nothing is correct — so
    they would pass against a completely unfixed product. The silent fixture has
    the mirror problem: if it accidentally named a role, the control tests would
    be asserting that a title was withheld for the wrong reason.
    """

    assert p.role_from_message(ACME_SUBJECT, _named(ROLE, REQ)) == ROLE
    assert p.extract_req_id(ACME_SUBJECT, _named(ROLE, REQ)) == REQ
    assert p.role_from_message(OTHER_SUBJECT, _silent()) is None
    assert p.extract_req_id(OTHER_SUBJECT, _silent()) is None
    assert p.resolve_employer(ACME_SENDER, ACME_SUBJECT)[0] == ACME_TOKEN
    assert p.resolve_employer(OTHER_SENDER, OTHER_SUBJECT)[0] == OTHER_TOKEN


# ── the review queue ─────────────────────────────────────────────────────────


async def test_answering_a_review_item_gives_the_card_the_title_it_named(test_session):
    """The reported defect, at the review path."""

    row = _row(company="Amazon")
    await _seed(test_session, row)
    await _seed(
        test_session,
        _mail(
            "rv-title",
            sender=ACME_SENDER,
            subject=ACME_SUBJECT,
            body=_named(ROLE, REQ),
            category=EmailCategory.NEEDS_REVIEW,
        ),
    )

    result = await apps.classify_review_item(
        test_session, USER, "rv-title", EmailCategory.APPLIED
    )
    await test_session.commit()

    # THE LOAD-BEARING ASSERTION, and it is not the one about the title. Without
    # it the test could be satisfied by the MINT branch, which has always
    # written the title, and would stay green against an unfixed product.
    assert result["application_id"] == row.id, "the mail minted a card instead of joining one"

    after = await _reload(test_session, row.id)
    assert after.position == ROLE, (
        "the user answered the queue, the mail landed on the right card, and the "
        "card still shows no job"
    )
    # The sync still owns the field: nobody typed this, so a later extraction
    # improvement must still be allowed to correct it.
    assert after.position_source is None


async def test_a_review_answer_stamps_the_identity_it_read(test_session):
    """A titled row that is still identity-less mints a duplicate on the next sync.

    ``_pick_application`` rule 3 adopts an anonymous row only when it is the
    employer's ONLY anonymous row; with two it refuses and a second card is
    minted beside the one just titled. Displaying a title while remaining
    unidentified to the resolver is the state that produces "a second Amazon
    appeared", so the identity is stamped with the same value the title came
    from.

    Live board, 2026-08-27: one employer already holds three rows with both
    identity columns NULL, so this is reachable and not hypothetical.
    """

    row = _row(company="Amazon")
    await _seed(test_session, row)
    await _seed(
        test_session,
        _mail(
            "rv-ident",
            sender=ACME_SENDER,
            subject=ACME_SUBJECT,
            body=_named(ROLE, REQ),
            category=EmailCategory.NEEDS_REVIEW,
        ),
    )

    await apps.classify_review_item(test_session, USER, "rv-ident", EmailCategory.APPLIED)
    await test_session.commit()

    after = await _reload(test_session, row.id)
    assert after.role_token == p.normalize_role_token(ROLE)
    assert after.req_id == REQ


async def test_a_review_answer_never_overwrites_an_identity_the_row_already_has(
    test_session,
):
    """Fill-if-empty, never rewrite. The control for the test above.

    A row already keyed to a requisition is a row the product has decided about.
    One below-gate message is not evidence enough to re-key it, and re-keying is
    how a card stops matching its own future mail.
    """

    row = _row(company="Amazon", req_id="9999999", role_token="platform engineer")
    await _seed(test_session, row)
    # THE MESSAGE MUST ACTUALLY LAND ON THAT ROW, and saying so is the whole
    # test. Written without this the mail names requisition 4471002, the row
    # carries 9999999, and `_pick_application`'s contradiction guard refuses to
    # file across them — so the message MINTS A SECOND CARD, `_adopt_mail_identity`
    # is never called on `row` at all, and the two assertions below pass against
    # a row nothing touched. That version survived deleting both `is None`
    # guards it claims to pin: 9 passed with the identity columns overwriting
    # unconditionally. Found by an adversarial review of this branch on
    # 2026-08-27 and reproduced before this rewrite.
    #
    # `application_id` is the route the product itself uses: the resolver
    # consults a message's existing link before any inference (LANDED_LINKED),
    # which is how an already-filed message reaches an already-keyed row.
    await _seed(
        test_session,
        _mail(
            "rv-keyed",
            sender=ACME_SENDER,
            subject=ACME_SUBJECT,
            body=_named(ROLE, REQ),
            category=EmailCategory.NEEDS_REVIEW,
            application_id=row.id,
        ),
    )

    result = await apps.classify_review_item(
        test_session, USER, "rv-keyed", EmailCategory.APPLIED
    )
    await test_session.commit()

    assert result["application_id"] == row.id, (
        "the message did not reach the keyed row, so nothing below is a test of "
        "what happens when it does"
    )
    after = await _reload(test_session, row.id)
    assert after.req_id == "9999999"
    assert after.role_token == "platform engineer"
    assert after.position == "", (
        "a contradicted requisition let the title through, so the row now wears "
        "one application's number and another's job"
    )


async def test_a_title_the_user_typed_survives_a_review_answer(test_session):
    """A human's words are theirs, including when extraction finally works."""

    row = _row(
        company="Amazon",
        position="The Job I Actually Applied For",
        position_source=apps.ROLE_FROM_USER,
    )
    await _seed(test_session, row)
    await _seed(
        test_session,
        _mail(
            "rv-typed",
            sender=ACME_SENDER,
            subject=ACME_SUBJECT,
            body=_named(ROLE, REQ),
            category=EmailCategory.NEEDS_REVIEW,
        ),
    )

    await apps.classify_review_item(test_session, USER, "rv-typed", EmailCategory.APPLIED)
    await test_session.commit()

    after = await _reload(test_session, row.id)
    assert after.position == "The Job I Actually Applied For"
    assert after.position_source == apps.ROLE_FROM_USER


async def test_one_review_answer_does_not_rename_a_card_that_already_has_a_title(
    test_session,
):
    """The decision this file exists to record, and the reason the fix is not a
    copy of the sync's condition.

    :func:`upsert_applications_for_user` rewrites an auto row's non-blank title
    when extraction produces something different, deliberately, so that
    improvements reach rows already on the board. That clause is defensible
    there because it re-reads the message's whole cluster. It is not defensible
    here: this is ONE message, the classifier was unsure enough about it to ask
    a human, and the human was asked what the message is — not what the
    application is called.

    Copying the sync's condition verbatim would also make the outcome depend on
    whether the stage happened to move in the same request, because that branch
    flips ``source`` to ``gmail_user`` a few lines later. A rule whose effect
    depends on an unrelated coincidence is not a rule.
    """

    row = _row(company="Amazon", position="Platform Engineer")
    await _seed(test_session, row)
    await _seed(
        test_session,
        _mail(
            "rv-named",
            sender=ACME_SENDER,
            subject=ACME_SUBJECT,
            body=_named(ROLE, REQ),
            category=EmailCategory.NEEDS_REVIEW,
        ),
    )

    await apps.classify_review_item(test_session, USER, "rv-named", EmailCategory.APPLIED)
    await test_session.commit()

    after = await _reload(test_session, row.id)
    assert after.position == "Platform Engineer", (
        "a card the user has already read was renamed off one message they were "
        "asked about because the classifier could not tell"
    )


# ── the orphan catch-up ──────────────────────────────────────────────────────


async def test_the_catch_up_gives_the_card_the_title_it_named(test_session):
    """The same defect at the other call site."""

    row = _row(company="Amazon")
    await _seed(test_session, row)
    await _seed(
        test_session,
        _mail(
            "orphan-title",
            sender=ACME_SENDER,
            subject=ACME_SUBJECT,
            body=_named(ROLE, REQ),
            category=EmailCategory.APPLIED,
            reviewed=True,
        ),
    )

    created = await apps.reconcile_orphaned_classifications(test_session, USER)
    await test_session.commit()

    assert created == 0, "it belongs to the existing row, not a new one"
    after = await _reload(test_session, row.id)
    assert after.position == ROLE


async def test_the_catch_up_never_carries_one_employer_s_title_onto_another(test_session):
    """THE TRAP, and the only test here that separates two plausible fixes.

    ``reconcile_orphaned_classifications`` loops over orphans, and ``role`` is
    bound INSIDE the branch that mints a row. Add the title write to the other
    branch without moving that binding and the loop carries the previous
    orphan's role forward: the first orphan mints a card at one employer, the
    second lands on a blank card at a DIFFERENT employer, and the second card is
    titled with the first employer's job.

    It does not raise, it does not fail any existing test, and it puts a job the
    user never applied for onto a real card. A single-orphan test cannot see it,
    which is why this one seeds two at two employers and asserts the SILENT one
    stays blank.
    """

    other = _row(company="Northwindlabs")
    await _seed(test_session, other)
    await _seed(
        test_session,
        # First: names a role, at an employer with no card, so it MINTS.
        _mail(
            "orphan-first",
            sender=ACME_SENDER,
            subject=ACME_SUBJECT,
            body=_named(ROLE, REQ),
            category=EmailCategory.APPLIED,
            minutes=0,
            reviewed=True,
        ),
        # Second: names NO role, at the employer whose blank card exists.
        _mail(
            "orphan-second",
            sender=OTHER_SENDER,
            subject=OTHER_SUBJECT,
            body=_silent(),
            category=EmailCategory.APPLIED,
            minutes=60,
            reviewed=True,
        ),
    )

    await apps.reconcile_orphaned_classifications(test_session, USER)
    await test_session.commit()

    after = await _reload(test_session, other.id)
    assert after.position == "", (
        f"the blank card at one employer was titled {after.position!r}, which is "
        "the job named by a different employer's mail earlier in the same loop"
    )
    assert after.role_token is None, "and its identity was stamped from that mail too"


async def test_the_catch_up_leaves_a_typed_title_alone(test_session):
    """The stickiness rule holds at this call site too."""

    row = _row(
        company="Amazon",
        position="The Job I Actually Applied For",
        position_source=apps.ROLE_FROM_USER,
    )
    await _seed(test_session, row)
    await _seed(
        test_session,
        _mail(
            "orphan-typed",
            sender=ACME_SENDER,
            subject=ACME_SUBJECT,
            body=_named(ROLE, REQ),
            category=EmailCategory.APPLIED,
            reviewed=True,
        ),
    )

    await apps.reconcile_orphaned_classifications(test_session, USER)
    await test_session.commit()

    after = await _reload(test_session, row.id)
    assert after.position == "The Job I Actually Applied For"


# ── the blind landing: filing is not the same as knowing ─────────────────────
#
# `_email_identity_parts` PREFERS the stored `identity_*` columns, which are
# written from the whole body where one was fetched. `_resolve_application_for_email`
# re-derives from subject + the first ~200 characters. So the case where the
# cascade reads nothing — rule 4, "pick the employer's oldest row rather than
# mint a fourth card" — is exactly the case where the caller may still hold a
# body-grade role. Stamping it there writes one application's title onto
# another's card, and 24 of the 26 cards #546 is about are rejections, whose
# snippet reliably ends mid-preamble.
#
# Raised by an adversarial review of this branch on 2026-08-27, as the fix's own
# worst case. The pair below is the gate: the refusal, and the control that
# stops "refuse everything" from satisfying it.

BLIND_SUBJECT = "Update on your application"
BLIND_SNIPPET = "Thank you for taking the time to apply. After careful review,"


def _blind_mail(message_id: str, *, application_id: int | None = None) -> Email:
    """Names no job anywhere the cascade looks, and one where it does not."""

    return _mail(
        message_id,
        sender=ACME_SENDER,
        subject=BLIND_SUBJECT,
        body=BLIND_SNIPPET,
        category=EmailCategory.NEEDS_REVIEW,
        application_id=application_id,
        identity_role=ROLE,
        identity_req_id=REQ,
    )


async def test_a_tie_break_between_two_cards_does_not_title_either(test_session):
    """Two anonymous rows at one employer, and a message that names neither.

    The resolver files it on the oldest — deliberately, because minting a third
    card to answer "which of your two?" is worse. But that choice is a
    tie-break, not a reading, and a title stamped on it is a guess wearing the
    authority of a fact.
    """

    first = _row(company="Amazon")
    second = _row(company="Amazon")
    await _seed(test_session, first, second)
    await _seed(test_session, _blind_mail("rv-blind"))

    result = await apps.classify_review_item(
        test_session, USER, "rv-blind", EmailCategory.REJECTION
    )
    await test_session.commit()

    assert result["application_id"] in (first.id, second.id), (
        "the message minted a card instead of landing on one of the two, so this "
        "is not a test of the tie-break"
    )
    for row in (first, second):
        after = await _reload(test_session, row.id)
        assert after.position == "", (
            "a card was titled off a tie-break: the resolver read nothing in "
            "this message and picked a row by age, and the title came from a "
            "column it never looked at"
        )
        assert after.req_id is None and after.role_token is None


async def test_the_same_message_titles_the_card_when_there_is_only_one(test_session):
    """THE CONTROL. One row, so nothing is being broken between.

    Without it the test above is satisfied by never adopting at all, which is
    the bug #546 was filed for. The mail is byte-identical; the only difference
    is how many cards the employer holds.
    """

    only = _row(company="Amazon")
    await _seed(test_session, only)
    await _seed(test_session, _blind_mail("rv-single"))

    await apps.classify_review_item(
        test_session, USER, "rv-single", EmailCategory.REJECTION
    )
    await test_session.commit()

    after = await _reload(test_session, only.id)
    assert after.position == ROLE
    assert after.req_id == REQ


async def test_the_user_picking_the_card_is_never_a_blind_landing(test_session):
    """They were shown the board and chose. That outranks every inference.

    Asserted because the refusal above is keyed on HOW the row was reached, and
    the chosen-card path must not be swept up in it — otherwise the one case
    where the product asked the question and got an answer is the one case it
    refuses to act on.
    """

    first = _row(company="Amazon")
    second = _row(company="Amazon")
    await _seed(test_session, first, second)
    await _seed(test_session, _blind_mail("rv-chosen"))

    await apps.classify_review_item(
        test_session,
        USER,
        "rv-chosen",
        EmailCategory.REJECTION,
        application_id=second.id,
    )
    await test_session.commit()

    after = await _reload(test_session, second.id)
    assert after.position == ROLE
    assert (await _reload(test_session, first.id)).position == ""


async def test_a_matching_requisition_still_does_not_re_key_the_row(test_session):
    """The fill-if-empty guards, pinned where the contradiction guard cannot hide them.

    THIS TEST EXISTS BECAUSE THE OBVIOUS ONE DOES NOT WORK. Pointing a
    CONTRADICTING requisition at a keyed row proves nothing about
    ``app.req_id is None`` / ``app.role_token is None``: the contradiction guard
    returns first, so deleting both `is None` clauses leaves that test green.
    Measured on 2026-08-27 — the unconditional-overwrite mutant survived the
    whole file until this case was added.

    So the requisition AGREES here, which is a real state: the sync keyed this
    row from one wording of the title, and a below-gate message words it
    differently. Re-keying on that is how a card stops matching its own future
    mail — the same reason the sync's own upsert fills these columns and never
    rewrites them.
    """

    row = _row(company="Amazon", req_id=REQ, role_token="platform engineer")
    await _seed(test_session, row)
    await _seed(
        test_session,
        _mail(
            "rv-agrees",
            sender=ACME_SENDER,
            subject=ACME_SUBJECT,
            body=_named(ROLE, REQ),
            category=EmailCategory.NEEDS_REVIEW,
        ),
    )

    result = await apps.classify_review_item(
        test_session, USER, "rv-agrees", EmailCategory.APPLIED
    )
    await test_session.commit()

    assert result["application_id"] == row.id, (
        "the message did not land on the keyed row, so the guards below were "
        "never reached"
    )
    after = await _reload(test_session, row.id)
    assert after.req_id == REQ
    assert after.role_token == "platform engineer", (
        "the row was re-keyed off one below-gate message, so it no longer "
        "matches the mail the sync keyed it for"
    )
    # The title is still filled: that is the fix, and it is what separates
    # "never rewrite the KEY" from "never write anything".
    assert after.position == ROLE
