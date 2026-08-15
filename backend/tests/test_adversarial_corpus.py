"""Regression gate over the adversarial mail corpus.

What this file asserts, and — just as importantly — what it does NOT.

It pins the failure modes THIS branch fixed:

* no MERGE in either layer (two applications must never collapse onto one
  card), and
* a requisition code must never be read as an employer.

It deliberately does NOT pin the total split count. Most remaining splits come
from the leftmost-anchor runaway in ``_ROLE_BODY_PATTERNS``, which PR #334
fixes on its own branch; asserting ``splits == 27`` here would turn green into
red the day that merges, and a gate that fails for a fix is a gate someone
disables. The anchor family is REPORTED by ``scripts/run_mail_corpus.py``
instead, where a human reads it.

Runtime is about a second, so it belongs in CI rather than in a script nobody
runs.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud import pipeline as p
from jobtracker.cloud.applications import (
    SOURCE_GMAIL_AUTO,
    Application,
    _pick_application,
)
from tests.corpus.generator import generate
from tests.corpus.harness import score_in_scan, score_incremental


@pytest.fixture(scope="module")
def cases():
    return generate()


def test_corpus_is_deterministic() -> None:
    """A corpus that differs between runs cannot be a regression gate."""

    a = [(c.item.message_id, c.item.subject, c.item.snippet, c.identity) for c in generate()]
    b = [(c.item.message_id, c.item.subject, c.item.snippet, c.identity) for c in generate()]
    assert a == b
    # And a different seed must still produce the same corpus, because every
    # case is enumerated rather than sampled — the seed is there for future
    # randomised axes, and this pins that nothing silently became random.
    assert [x[0] for x in a] == [c.item.message_id for c in generate(seed=1)]


def test_corpus_actually_reaches_the_clusterer(cases) -> None:
    """The self-check the whole instrument rests on.

    ``_qualifies_for_hard_row`` requires a lifecycle category, a confidence at
    or above ``AUTO_FILE_GATE`` and a nameable employer. A corpus that fails it
    produces zero clusters, therefore zero failures, and looks perfect. This
    estate has a documented history of checks that could not fail; this one
    says out loud how much mail got through.
    """

    gated = sum(1 for c in cases if p._qualifies_for_hard_row(c.item) is not None)
    assert gated > 120, f"only {gated} of {len(cases)} messages cleared the gate"


def test_no_two_applications_collapse_onto_one_card(cases) -> None:
    """MERGE is the strictly worse failure: it destroys a record silently.

    Nothing on the board says a second application ever existed, so the user
    cannot even know to look. A split leaves two cards to merge by hand.
    """

    for score in (score_in_scan(cases), score_incremental(cases)):
        merges = [f for f in score.failures if f.mode == "MERGE"]
        assert score.merges == 0, (
            f"{score.layer}: {score.merges} merge(s): "
            + "; ".join(f.detail for f in merges)
        )


def test_differing_req_ids_at_one_employer_stay_two_applications() -> None:
    """The cascade's rule 1, which the code used to contradict in both files.

    Two openings at one employer routinely share a title and differ only by the
    employer's own requisition number. OR-ing the id and role clauses let the
    role match win and collapsed them.
    """

    def _msg(mid: str, req: str) -> p.PipelineItem:
        return p.PipelineItem(
            message_id=mid,
            category="applied",
            sender_email="no-reply@myworkday.com",
            sender_name="Eastvale Robotics",
            subject="Thank you for applying to Eastvale Robotics",
            confidence=0.95,
            snippet=f"Thank you for your interest in the Mechanical Engineer position ({req}).",
        )

    clusters, _unplaced = p.partition_applications([_msg("a", "R-40881"), _msg("b", "R-40882")])
    assert len(clusters) == 2, f"expected two applications, got {len(clusters)}"
    assert {c.req_id for c in clusters} == {"R-40881", "R-40882"}

    # The same rule on the persistent side, or a cluster and its stored row
    # disagree about what they are.
    row = Application(
        user_id=None,
        company="Eastvale Robotics",
        status="applied",
        source=SOURCE_GMAIL_AUTO,
        req_id="R-40881",
        role_token="mechanical engineer",
    )
    row.id = 1
    row.dismissed_at = None
    assert _pick_application([row], "R-40881", "mechanical engineer") is row
    assert _pick_application([row], "R-40882", "mechanical engineer") is None


def test_a_message_still_carries_the_half_of_the_identity_the_other_lacked() -> None:
    """The guard must not break the confirmation/interview pairing.

    The confirmation brings the requisition id, the interview invite that
    follows brings only the title. They are one application, and a guard that
    fired on "one side is None" would split every such pair.
    """

    confirmation = p.PipelineItem(
        message_id="a",
        category="applied",
        sender_email="no-reply@myworkday.com",
        sender_name="Pinewhistle",
        subject="Thank you for applying to Pinewhistle",
        confidence=0.95,
        snippet="Thank you for your interest in the Robotics Software Engineer position (Job ID: JR0093214).",
    )
    invite = p.PipelineItem(
        message_id="b",
        category="interview",
        sender_email="no-reply@myworkday.com",
        sender_name="Pinewhistle",
        subject="Interview at Pinewhistle",
        confidence=0.95,
        snippet="We would like to interview you for the Robotics Software Engineer position.",
    )
    clusters, _unplaced = p.partition_applications([confirmation, invite])
    assert len(clusters) == 1
    assert clusters[0].req_id == "JR0093214"
    assert len(clusters[0].items) == 2


def test_a_requisition_code_is_never_an_employer() -> None:
    """"Interview for JR0093214 at Pinewhistle" minted a card named JR0093214.

    The subject company pattern looks for a capitalised token after
    "interview for", and a Workday requisition code sits exactly there. The
    result was a row for a company that does not exist, AND the real
    application split in two.
    """

    resolved = p.resolve_employer(
        "no-reply@myworkday.com",
        "Interview for JR0093214 at Pinewhistle",
        "Pinewhistle",
    )
    assert resolved is not None
    assert resolved[0] == "pinewhistle", f"employer resolved to {resolved!r}"

    # The token validator is the chokepoint, so pin it directly too.
    assert p._valid_company_token("jr0093214") is False
    assert p._valid_company_token("r 77120") is False
    assert p._valid_company_token("req 40881") is False
    # ...without rejecting real-looking company tokens.
    assert p._valid_company_token("pinewhistle") is True
    assert p._valid_company_token("northwind robotics") is True


def test_noise_and_sub_gate_mail_never_reaches_a_card(cases) -> None:
    """Mail with no lifecycle verdict, or below the gate, mints nothing.

    Scoped honestly: these cases are stamped ``other`` / sub-gate confidence,
    so this pins the GATE, not the classifier. See the note in
    ``tests/corpus/generator.py::_axis_non_job_mail``.
    """

    for score in (score_in_scan(cases), score_incremental(cases)):
        assert score.minted_from_noise == 0, score.layer


def test_role_less_mail_at_a_multi_application_employer_goes_to_review(cases) -> None:
    """Guessing here settles the wrong application terminally.

    ``advance_application_status`` treats a terminal state as final, so a
    rejection attributed to the wrong one of two live applications freezes it
    against every later interview or offer.
    """

    score = score_in_scan(cases)
    assert score.wrong_review == 0, [f.detail for f in score.failures if "REVIEW" in f.mode]


def test_relay_only_mail_names_no_employer(cases) -> None:
    """The applying-TO versus applying-THROUGH distinction, pinned harder.

    A bare relay with no employer in the display name or subject must resolve
    to None — never a "Joinhandshake" or "Pageuppeople" row. The counterpart
    (an employer named THROUGH a relay, which must win) is the ``ats-relay``
    axis and is covered by the split/merge scoring.
    """

    for case in cases:
        if case.axis != "no-employer":
            continue
        assert (
            p.resolve_employer(
                case.item.sender_email, case.item.subject, case.item.sender_name
            )
            is None
        ), f"{case.item.sender_email} / {case.item.subject!r} named an employer"
