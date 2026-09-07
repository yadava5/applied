"""A confident rejection that names its role settles THAT card, not a sibling.

Why this file exists
--------------------

Issue #417 calls a board that still reads ``APPLIED`` for a role the user was
rejected from the single failure that matters more than any other. This is the
end-to-end lock for the composite that produces it, and every half of the
composite has to hold at once:

1. the rules layer scores the body a ``rejection`` at or above ``AUTO_FILE_GATE``;
2. ``resolve_employer`` names the employer from the subject's LEADING segment,
   because the sender is an ATS relay and its domain names no employer (#525);
3. ``role_from_message`` reads the role out of that same segment (#553, #561);
4. the employer already holds TWO applications, so ``partition_applications``
   rule 3 — "no role named, and the employer has exactly one cluster" — cannot
   place the message and refuses to guess.

Halves 2 and 3 landed a day apart and only the pair is sufficient. Measured on
this exact shape while diagnosing a queued production row:

    tree                                  resolve_employer  role_from_message  verdict
    4afb10fe (before both)                None              None               QUEUED
    fe448343 (#525, employer only)        Ironvale          None               QUEUED
    602e030a (#553/#561, employer+role)   Ironvale          Thermal Systems…   FILES

With ONE card at the employer the employer fix alone was already enough; the
role read is what the SECOND card makes load-bearing. That is why the seeded
board below carries a sibling, and why :func:`test_a_message_that_names_no_role_still_asks`
is here — a single-card fixture would pass against a tree with the role read
deleted, which is exactly a check that cannot fail.

Both arms, because one is not a result
--------------------------------------

``test_...settles_the_card_it_names`` seeds the matching card and asserts the
merge REPORTS ``updated`` and flips that row. ``test_...mints_a_card_when_the
_board_holds_none`` seeds no card at the employer and asserts the merge reports
``created``. A single arm cannot tell "filed onto the right card" from "filed
somewhere"; the two arms have to disagree, and the assertions pin which way.

Provenance of the fixture
-------------------------

**Real:** the WORDING of the body and the SHAPE of the subject
(``<Employer> Follow-Up for <Role> | <Candidate>``) — a Greenhouse-relayed
rejection, kept because it is the template the classifier and both identity
readers must read correctly, and nobody would have invented the fact that the
employer and the role share one segment.

**Invented:** the employer, both role titles, the candidate name, and the
sender's labels. The sender preserves the relay's STRUCTURE only —
``_domain_brand`` reads the second-from-last label, so
``us.greenhouse-mail.example`` yields ``greenhouse-mail`` exactly as the real
relay domain does, on a TLD RFC 2606 §2 reserves and which can never route.
Same convention as ``test_a_cut_fragment_is_not_an_employer.py``.
"""

from __future__ import annotations

import datetime
import uuid as _uuid

import pytest
from sqlmodel import select

from jobtracker.classifier.rules import get_rules_classifier
from jobtracker.cloud import applications as apps
from jobtracker.cloud import pipeline as p
from jobtracker.database.models import Application, ApplicationStatus, Email

USER = _uuid.UUID("3d7a1f60-9c24-4e8b-9a53-71c0be44e2f9")

# The relay's structure, on a reserved TLD. `_domain_brand` reads
# `greenhouse-mail` from this exactly as it does from the routable original,
# which is what puts `resolve_employer` on its ATS-relay branches at all.
ATS = "no-reply@us.greenhouse-mail.example"

EMPLOYER = "Ironvale Robotics"
ROLE = "Thermal Systems Engineer"
ROLE_TOKEN = "thermal systems engineer"
# A second opening at the SAME employer, already settled. Its only job is to
# make the employer hold two applications; nothing here may move it.
SIBLING_ROLE = "Controls Engineer"
SIBLING_TOKEN = "controls engineer"
CANDIDATE = "Dana Whitfield"

SUBJECT = f"{EMPLOYER} Follow-Up for {ROLE} | {CANDIDATE}"
BODY = (
    f"Hi Dana, Thank you so much for your interest in {EMPLOYER} and for the time "
    "and effort you have invested in our process. After consideration, we have "
    "decided not to move forward with your application"
)
# The same relay, the same employer, naming no role at all — the shape rule 3
# refuses to place once the employer holds more than one card.
ANONYMOUS_SUBJECT = f"{EMPLOYER} Follow-Up | {CANDIDATE}"

RECEIVED = datetime.datetime(2026, 8, 26, 7, 8, 15)


def _card(position: str, role_token: str, status: ApplicationStatus, day: int) -> Application:
    return Application(
        user_id=USER,
        company=EMPLOYER,
        position=position,
        role_token=role_token,
        status=status,
        applied_date=datetime.date(2026, 8, day),
        source=apps.SOURCE_GMAIL_AUTO,
    )


def _item(subject: str = SUBJECT, message_id: str = "m-followup") -> p.PipelineItem:
    """One scanned message, built the way ``gmail_oauth._classify_messages`` builds it.

    The category and confidence come from the RULES layer rather than from a
    literal, so a pattern change that stopped scoring this body a confident
    rejection reds here instead of being papered over by a hardcoded 0.95.
    Production runs rules-only (``HybridClassifier._cloud_rules_only`` is set
    from ``settings.deployment == "cloud"``), so this is the layer that answers.
    """

    verdict = get_rules_classifier().classify(subject, BODY, ATS)
    return p.PipelineItem(
        message_id=message_id,
        category=verdict.category.value,
        sender_email=ATS,
        subject=subject,
        sender_name=None,
        received_at=RECEIVED,
        confidence=verdict.confidence,
        thread_id=f"th-{message_id}",
        snippet=BODY,
        identity_role=p.role_from_message(subject, BODY) or "",
        identity_req_id=p.extract_req_id(subject, BODY) or "",
        method=verdict.method if hasattr(verdict, "method") else "rules",
    )


async def _sync(session, items: list[p.PipelineItem]) -> apps.MergeResult:
    """One ordinary (additive) sync, wired exactly as ``POST /gmail/sync`` wires it.

    ``known_multi`` and ``known_threads`` are read from the board first, which is
    the whole point: a delta carrying one message cannot otherwise tell an
    employer with one card from an employer with four.
    """

    known_multi = await apps.employers_with_several_applications(session, USER)
    known_threads = await apps.threads_naming_one_application(session, USER)
    return await apps.sync_gmail_pipeline_additive(
        session,
        USER,
        p.roll_up_applications(items, known_multi, known_threads),
        p.collect_review_items(items, [], known_multi, known_threads),
    )


async def _rows(session) -> list[Application]:
    return list(
        (
            await session.exec(
                select(Application).where(
                    Application.user_id == USER, Application.dismissed_at.is_(None)
                )
            )
        ).all()
    )


async def _mail(session) -> list[Email]:
    return list((await session.exec(select(Email).where(Email.user_id == USER))).all())


def test_the_fixture_still_reproduces_the_shape_it_claims():
    """Guard the fixture itself, so the two arms below cannot pass vacuously.

    Every one of these is a precondition of the composite. If any stops holding
    the arms would still run — and would be measuring something else.
    """

    verdict = get_rules_classifier().classify(SUBJECT, BODY, ATS)
    assert verdict.category.value == "rejection"
    assert verdict.confidence >= p.AUTO_FILE_GATE, (
        "the body must clear the auto-file gate, or nothing below is about filing"
    )
    # #525: the employer is read from the subject's lead segment, not the domain.
    assert p.resolve_employer(ATS, SUBJECT, None) == ("ironvale", EMPLOYER)
    # #553 / #561: the role is read from that same segment.
    assert p.role_from_message(SUBJECT, BODY) == ROLE
    assert p.normalize_role_token(ROLE) == ROLE_TOKEN
    # And the anonymous variant really does name no role, or the directional
    # control below proves nothing.
    assert p.role_from_message(ANONYMOUS_SUBJECT, BODY) is None


async def test_the_rejection_settles_the_card_it_names(test_session):
    """ARM A. The employer holds the matching card; the message must settle it."""

    test_session.add(_card(ROLE, ROLE_TOKEN, ApplicationStatus.APPLIED, 10))
    test_session.add(_card(SIBLING_ROLE, SIBLING_TOKEN, ApplicationStatus.REJECTED, 4))
    await test_session.commit()
    named = {r.position: r.id for r in await _rows(test_session)}

    result = await _sync(test_session, [_item()])

    # It ADVANCED a row rather than minting one. This is the half that differs
    # from arm B, and asserting both directions is what makes the pair a control.
    assert (result.created, result.updated) == (0, 1)
    assert result.needs_review == 0, "a message this confident must not reach the queue"

    rows = {r.position: r for r in await _rows(test_session)}
    assert rows[ROLE].status is ApplicationStatus.REJECTED, (
        "the card for the role the subject names still reads APPLIED — #417"
    )
    assert rows[ROLE].id == named[ROLE], "it must settle the EXISTING card, not a new one"
    assert rows[SIBLING_ROLE].id == named[SIBLING_ROLE]
    assert len(rows) == 2, "no third card at an employer that already had two"

    [mail] = await _mail(test_session)
    assert mail.application_id == named[ROLE], "filed onto the sibling, not the named role"
    assert mail.is_reviewed is False


async def test_the_same_message_mints_a_card_when_the_board_holds_none(test_session):
    """ARM B, the control. No card at that employer — the outcome must DIFFER."""

    test_session.add(
        Application(
            user_id=USER,
            company="Northwind Systems",
            position="Backend Engineer",
            role_token="backend engineer",
            status=ApplicationStatus.APPLIED,
            applied_date=datetime.date(2026, 8, 10),
            source=apps.SOURCE_GMAIL_AUTO,
        )
    )
    await test_session.commit()

    result = await _sync(test_session, [_item()])

    # Inverted against arm A. If these two ever agree, the harness is not
    # measuring the board state it claims to.
    assert (result.created, result.updated) == (1, 0)
    assert result.needs_review == 0

    rows = {r.company: r for r in await _rows(test_session)}
    assert set(rows) == {EMPLOYER, "Northwind Systems"}
    assert rows[EMPLOYER].status is ApplicationStatus.REJECTED
    assert rows[EMPLOYER].position == ROLE
    assert rows["Northwind Systems"].status is ApplicationStatus.APPLIED


async def test_a_message_that_names_no_role_still_asks(test_session):
    """The directional half: WITHOUT the role, two cards send it to the queue.

    This is what makes the arms above a test of the role read rather than of the
    employer read. Same employer, same relay, same confident rejection — only
    the role is missing, and the message must not be attributed to whichever of
    the two cards happens to sort first. ``advance_application_status`` treats a
    terminal status as final, so a wrong guess here freezes a live application
    against every later interview and offer.
    """

    test_session.add(_card(ROLE, ROLE_TOKEN, ApplicationStatus.APPLIED, 10))
    test_session.add(_card(SIBLING_ROLE, SIBLING_TOKEN, ApplicationStatus.REJECTED, 4))
    await test_session.commit()

    result = await _sync(test_session, [_item(subject=ANONYMOUS_SUBJECT, message_id="m-anon")])

    assert (result.created, result.updated) == (0, 0)
    assert result.needs_review == 1, "an unplaceable rejection must reach the queue"

    rows = {r.position: r for r in await _rows(test_session)}
    assert rows[ROLE].status is ApplicationStatus.APPLIED, (
        "a role-less rejection must not settle either card by tie-break"
    )
    assert rows[SIBLING_ROLE].status is ApplicationStatus.REJECTED

    [mail] = await _mail(test_session)
    assert mail.application_id is None
    # The queue's stored shape: `needs_review` is the typed null and the
    # verdict rides in `suggested_category`.
    assert mail.suggested_category is not None


@pytest.mark.parametrize("siblings", [1, 2])
async def test_the_named_role_files_at_either_sibling_count(test_session, siblings):
    """Naming the role must place the message whether the employer holds one card or two.

    The one-card case is what the employer fix alone already bought; the
    two-card case is what needed the role read. Pinning both stops a future
    change from restoring the one-card behaviour and reading as a pass.
    """

    test_session.add(_card(ROLE, ROLE_TOKEN, ApplicationStatus.APPLIED, 10))
    if siblings == 2:
        test_session.add(_card(SIBLING_ROLE, SIBLING_TOKEN, ApplicationStatus.REJECTED, 4))
    await test_session.commit()

    result = await _sync(test_session, [_item()])

    assert (result.created, result.updated, result.needs_review) == (0, 1, 0)
    rows = {r.position: r for r in await _rows(test_session)}
    assert rows[ROLE].status is ApplicationStatus.REJECTED
