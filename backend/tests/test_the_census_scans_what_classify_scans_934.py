"""The reach census must search the text ``classify`` searches — #934.

``reach.scan_text`` decides what a pattern is "exercised by". Until this change
it returned the raw delivered text, while ``RulesClassifier.classify`` scores
``reflow_paragraphs(asserted_text(body))`` — quoted history deleted, and every
conditional clause cut from its marker to the end of its sentence. So a pattern
could be recorded as FIRED on text the engine masks away, and the census had no
way to tell that apart from real reach. The census is one of the numbers the
board row publishes, so the difference is not academic.

WHAT THIS FILE GRADES, and each test names the direction it fails in:

* the census gives ZERO credit for a match that lives only inside a mask, and
  the same probe gives hundreds of credits against the raw text — both halves
  asserted, so the pair cannot pass by both being empty;
* an injected pattern whose only reach is inside a mask moves FIRED ->
  NEVER_FIRED, which is the demonstration #934 item 2 asks for by name;
* the SUBJECT is left unmasked, because ``classify`` leaves it unmasked. A
  census stricter than the engine is the same error facing the other way;
* masking can only ever REMOVE reach, never add it.

THE PROBE PATTERN IS NOT INVENTED FOR THIS FILE. ``be in touch if`` is the
``|if`` alternation arm of ``be in touch (soon|shortly|if)``, deleted from
``rules.py`` in #928 for being unreachable. It is used here because the corpus
already contains the wording in quantity and because it is the arm whose
phantom credits found the defect.

Measured over the corpus at the size this file was written (18,980 cases):

    be in touch (soon|shortly|if)   raw 547   this census 20
    be in touch if                  raw 527   this census  0

so 527 of the three-arm pattern's 547 credits were for text no shipped
classifier can reach. The counts are recorded rather than asserted, because
they move with the corpus; what is asserted is the RELATIONSHIP, which does not.
"""

from __future__ import annotations

import re

import pytest

from jobtracker.classifier.rules import asserted_text, reflow_paragraphs
from tests.corpus_independent import reach
from tests.corpus_independent.generate import generate
from tests.corpus_independent.harness import as_classified

#: The deleted ``|if`` arm, on its own. Every match of it in this corpus sits
#: inside a conditional clause, which is what makes it a probe rather than a
#: pattern: the engine can never reach it, so any credit for it is phantom.
MASKED_ONLY = re.compile(r"be in touch if", re.IGNORECASE)

#: The surviving arms. They are reachable, so their credit must SURVIVE the
#: mask — without this the file would pass if ``scan_text`` returned "".
REACHABLE = re.compile(r"be in touch (soon|shortly)", re.IGNORECASE)

#: A floor, not the measured value. The measured count was 527 and it moves
#: whenever a family is added; what must never happen is a probe that finds
#: nothing and reads as a clean bill of health.
RAW_CREDIT_FLOOR = 100


@pytest.fixture(scope="module")
def cases() -> list:
    return generate()


@pytest.fixture(scope="module")
def scanned(cases) -> list[str]:
    """What the census searches, through the shipped function."""

    return [reach.scan_text(c.subject, c.delivered) for c in cases]


@pytest.fixture(scope="module")
def raw(cases) -> list[str]:
    """What the census USED to search: the delivered text, untouched."""

    return [f"{c.subject}\n{c.delivered}" for c in cases]


def _strong(text: str) -> list[str]:
    """Every ``strong`` positive pattern that matches ``text``."""

    return [
        pid.pattern
        for pid, rx in reach.positive_patterns()
        if pid.tier == "strong" and rx.search(text)
    ]


def _hits(rx: re.Pattern[str], texts: list[str]) -> int:
    return sum(1 for t in texts if rx.search(t))


def test_a_match_that_lives_only_inside_a_mask_earns_no_credit(scanned, raw) -> None:
    """The defect, stated as the two numbers that must differ.

    ``masked == 0`` alone would pass against a broken probe — a typo in the
    pattern, an empty corpus, a ``scan_text`` returning "". The raw arm is what
    proves the probe found the population it is supposed to find, so the zero
    means "the mask removed them" rather than "there was nothing there".
    """

    on_raw = _hits(MASKED_ONLY, raw)
    on_census = _hits(MASKED_ONLY, scanned)

    assert on_raw >= RAW_CREDIT_FLOOR, (
        f"the probe found only {on_raw} matches in the raw text; it is supposed "
        "to find hundreds. The corpus or the wording moved and this file is no "
        "longer measuring what it claims to."
    )
    assert on_census == 0, (
        f"{on_census} of the census's credits for {MASKED_ONLY.pattern!r} are "
        "for text `classify` masks away. `reach.scan_text` is not searching "
        "what the engine searches."
    )


def test_the_reachable_arms_keep_their_credit(scanned) -> None:
    """The other direction: the mask must not eat real reach.

    Without this, deleting the body from ``scan_text`` entirely would satisfy
    the test above.
    """

    assert _hits(REACHABLE, scanned) > 0, (
        "the surviving arms of the pattern lost all their reach, so the mask is "
        "removing text the engine does read"
    )


def test_a_pattern_reachable_only_inside_a_mask_moves_to_never_fired(
    cases, monkeypatch
) -> None:
    """#934 item 2, by name: show one moving.

    No pattern in ``rules.py`` today has ALL of its reach inside masks — the
    ``|if`` arm's two siblings score 20, which is why the ledger does not move
    and why this had to be demonstrated with an injected id rather than an
    existing one. The injection is the deleted arm.
    """

    injected = reach.PatternId(
        category="rejection", tier="strong", pattern=MASKED_ONLY.pattern
    )
    live = reach.positive_patterns()
    monkeypatch.setattr(
        reach, "positive_patterns", lambda: [*live, (injected, MASKED_ONLY)]
    )

    def triples(scan):
        return [
            (c.family, scan(c), reach.wording(c.subject, c.body)) for c in cases
        ]

    on_raw = reach.measure_texts(triples(lambda c: f"{c.subject}\n{c.delivered}"))
    on_census = reach.measure_texts(
        triples(lambda c: reach.scan_text(c.subject, c.delivered))
    )

    assert injected in on_raw.fired, (
        "the injected pattern did not fire even against the raw text, so this "
        "test proves nothing about the census"
    )
    assert injected not in on_census.fired, (
        "a pattern whose every match is inside a conditional clause is still "
        "recorded as exercised"
    )


def test_the_subject_is_left_unmasked(cases) -> None:
    """``classify`` transforms the body and never the subject; so does this.

    Asserted through a subject that IS a conditional clause. Masking it would
    make the census stricter than the engine — a rule the subject genuinely
    reaches would be reported as never exercised, which is #934's own defect
    pointing the other way.
    """

    subject = "If you are selected we will be in touch if a slot opens"
    assert reach.scan_text(subject, "").startswith(subject), (
        "the census masked the subject; `classify` does not"
    )


def test_masking_can_only_remove_reach(cases) -> None:
    """Whatever the census now credits, the raw text credited too.

    A pattern that fires ONLY after masking would mean the transform is
    inventing text rather than deleting it. ``asserted_text`` and
    ``reflow_paragraphs`` both only ever delete or join, so this is a property
    of the pair rather than of the corpus, and it is asserted here so a future
    substitution-style transform cannot be dropped in unnoticed.
    """

    def triples(scan):
        return [
            (c.family, scan(c), reach.wording(c.subject, c.body)) for c in cases
        ]

    on_raw = reach.measure_texts(triples(lambda c: f"{c.subject}\n{c.delivered}"))
    on_census = reach.measure_texts(
        triples(lambda c: reach.scan_text(c.subject, c.delivered))
    )

    gained = on_census.fired - on_raw.fired
    assert not gained, f"masking invented reach for {sorted(p.pattern for p in gained)}"


def test_the_census_body_is_the_engines_body() -> None:
    """The transform is production's own, not a re-implementation of it.

    Written as a behavioural coupling rather than as an equality against a
    copied expression: a body whose only lifecycle sentence is conditional must
    reach the census as text that no longer contains it. Compare the census's
    output against ``asserted_text``'s CONTRACT — the clause is gone — instead
    of against a second spelling of the same call, which would compare the file
    to itself.
    """

    body = (
        "Thanks for your interest. If our team decides to move forward we will "
        "be in touch if a slot opens. Best regards, the recruiting team."
    )
    text = reach.scan_text("Your application", body)

    assert "be in touch if" not in text.lower(), (
        "the conditional clause survived into the census's scan text"
    )
    assert "thanks for your interest" in text.lower(), (
        "the census lost text that sits OUTSIDE the conditional; the transform "
        "is cutting more than the engine does"
    )
    # ...and the engine agrees the clause is gone, which is the half that makes
    # this a coupling rather than an assertion about a string.
    assert "be in touch if" not in reflow_paragraphs(asserted_text(body)).lower()


# --------------------------------------------------------------------------
# The two mechanisms, measured on the two families that move.
#
# #934 predicted one (the conditional mask) and asked for a pattern to be shown
# moving FIRED -> NEVER_FIRED. What the fix actually surfaced is TWO mechanisms
# and 420 messages, and neither of them moves a pattern: they move the
# DISCOVERY RATE, which is the census's third metric and the one that says how
# much of this corpus the engine has no rule for. Both are asserted below,
# separately, because a single total would let either one regress unseen.
# --------------------------------------------------------------------------

#: Recorded in ``test_corpus_reach.RECORDED_FAMILIES`` as this file was written.
#: Asserted as a floor rather than an equality — the corpus grows — but the
#: floor is what makes a silent return to zero impossible.
QUOTED_HISTORY_FLOOR = 260
PAST_THE_CAP_FLOOR = 160


def test_a_strong_match_inside_a_quote_is_not_reach(cases) -> None:
    """Mechanism one: quoted history.

    ``rescinded-offer`` pairs an offer with the note that withdraws it, and the
    withdrawal QUOTES the offer. The only ``strong`` pattern the withdrawal
    matched was inside that quote — ``extend.{0,20}(job |employment )?offer``,
    written by the sender of the earlier message. ``classify`` strips quoted
    history before any pattern sees a body, so the engine reaches nothing on
    these, and its verdict is ``other`` at 0.50 against a ground truth of
    ``rejection``.

    Both directions asserted: the raw text DID credit them (so the probe found
    its population) and the census does not (so the credit is gone).
    """

    family = [c for c in cases if c.family == "rescinded-offer"]
    assert family, "the family this test is about is not in the corpus"

    quoted_only = [
        c
        for c in family
        if _strong(f"{c.subject}\n{c.delivered}")
        and not _strong(reach.texts_of(c)[1])
    ]
    assert len(quoted_only) >= QUOTED_HISTORY_FLOOR, (
        f"only {len(quoted_only)} of {len(family)} rescind messages were "
        "credited through their quote; the family or the census moved and this "
        "test is no longer measuring the mechanism it names"
    )


def test_a_strong_match_past_the_body_cap_is_not_reach(cases) -> None:
    """Mechanism two: the 4,000-character cap, and it is NOT the same bug.

    ``normalise_body_text`` cuts a body at 4,000 characters before ``classify``
    ever sees it. #767 fixed the classifier half of this corpus to respect that
    (``harness.as_classified``); the census kept reading the whole body, so the
    one family built to measure the cap — ``verdict-past-the-body-cap``, whose
    verdict sentence sits deliberately outside the window — was the one family
    the census read past.

    Asserted separately from the quote mechanism above on purpose: a single
    combined count would stay green if one of the two regressed and the other
    grew.
    """

    family = [c for c in cases if c.family == "verdict-past-the-body-cap"]
    assert family, "the family this test is about is not in the corpus"

    past_the_cap = [
        c
        for c in family
        if _strong(f"{c.subject}\n{c.delivered}")
        and not _strong(reach.texts_of(c)[1])
    ]
    assert len(past_the_cap) >= PAST_THE_CAP_FLOOR, (
        f"only {len(past_the_cap)} of {len(family)} messages lost a credit the "
        "cap denies the engine; the census is reading past the cap again"
    )


def test_the_census_scans_the_text_the_classifier_was_handed(cases) -> None:
    """The coupling, made structural: ``texts_of`` must call ``as_classified``.

    ASSERTED ON CONTENT, NOT ON LENGTH, and the first draft of this test was
    written on length and was worthless. ``normalise_body_text`` and
    ``reflow_paragraphs`` both collapse whitespace, and these bodies are mostly
    whitespace: reflowing the WHOLE 7,351-character body yields 3,802
    characters, which is under the 4,000 the cap hands over. So "the census
    scanned no more than the classifier was handed" was true of a ``texts_of``
    mutated back to ``case.delivered``, and the mutation survived.

    What separates them is what the text SAYS. This family puts its verdict
    sentence deliberately past the cap, so the strong pattern that verdict
    carries is present in the raw body and absent from the 4,000 characters
    production hands over. That cannot be satisfied by collapsing whitespace.
    """

    cut = [c for c in cases if len(as_classified(c)) < len(c.delivered) - 1000]
    assert cut, "no case in this corpus is cut by the cap; nothing to check"

    for case in cut[:50]:
        raw_hits = _strong(f"{case.subject}\n{case.delivered}")
        assert raw_hits, (
            "this case was chosen because its verdict sits past the cap; if the "
            "raw body matches no strong pattern the fixture moved"
        )
        assert not _strong(reach.texts_of(case)[1]), (
            f"the census credited {raw_hits} on a {case.family} message whose "
            "verdict sentence production never hands the classifier"
        )
