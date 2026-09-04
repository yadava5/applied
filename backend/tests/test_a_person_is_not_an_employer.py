"""A recruiter's name must never become a filed company (#733).

`resolve_employer` had two independent doors that would mint a filing-grade
employer out of any Title-Case run, with no notion that such a run might be a
person. Measured on the base commit, three messages through
`roll_up_applications` produced:

    token='northwind'   display='Northwind Labs'   interviewing   1 msg
    token='sarah'       display='Sarah Chen'       interviewing   2 msgs

A board card named after a human being, at 0.95 — above `AUTO_FILE_GATE`, so
filed rather than queued — and a second message GROUPED onto it.

WHY THIS MODULE EXISTS SEPARATELY FROM THE CORPUS. `labrat` measured the guard
against both corpora and the independent one moved **zero of 18,200 rows**. That
sounds like coverage and is not: the corpora are generated from employer-shaped
inputs, so they measure the guard's COST and are structurally unable to produce
the defect it prevents. The committed classifier gate is blinder still —
`evaluate_classifier.py` contains no occurrence of `employer` or `company`, and
forcing the guard to refuse EVERY employer leaves its output byte-identical:

    accuracy: 0.9896 | macro_f1: 0.9896 | misclassified: 1 -> PASS

So the green of every existing instrument is silent about this. These tests are
the only thing that speaks.
"""

from __future__ import annotations

import datetime

import pytest

from jobtracker.cloud import pipeline as p

# `.example` keeps these un-routable for the test-data gate while leaving the
# brand intact: `_domain_brand` reads the second-from-last label, so
# `us.greenhouse-mail.example` yields `greenhouse-mail` exactly as the real
# domain does. Same constants the sibling module uses.
ATS = "no-reply@us.greenhouse-mail.example"
SCHEDULING = "no-reply@goodtime.example"


#: Names of people. Each of these resolved to itself as a company on the base
#: commit — `('sarah', 'Sarah Chen')` and so on.
PEOPLE = [
    pytest.param("Sarah Chen", id="two-words"),
    pytest.param("Michael Rodriguez", id="longer-surname"),
    pytest.param("Priya Raman", id="non-anglo"),
    pytest.param("Sarah Chen-Li", id="hyphenated-surname"),
    pytest.param("Mary Anne Van Der Berg", id="five-words-the-closed-hole"),
    pytest.param("Kleiner Perkins Caufield Byers", id="four-words"),
]


@pytest.mark.parametrize("name", PEOPLE)
@pytest.mark.parametrize("sender", [ATS, SCHEDULING])
def test_a_personal_display_name_is_not_an_employer(name: str, sender: str) -> None:
    """Door one: the sender display name, `_employer_from_sender_name`."""

    assert p.resolve_employer(sender, "Next steps", name) is None


@pytest.mark.parametrize("name", PEOPLE)
def test_a_personal_name_in_the_subject_is_not_an_employer(name: str) -> None:
    """Door two, and the reason guarding door one alone is not a fix.

    These carry NO display name at all. `"Sarah Chen - quick chat?"` reached
    `_employer_from_subject_segment` and resolved `('sarah', 'Sarah Chen')` on
    the base commit. A fix that guards only the display name moves the defect
    one door down rather than closing it.
    """

    for subject in (f"{name} - quick chat?", f"{name} - Interview confirmation"):
        assert p.resolve_employer(ATS, subject, None) is None, subject


#: Every form of positive corporate evidence, one case each, so a reader can see
#: what the rule accepts and a mutation that drops one arm reds by name.
COMPANIES = [
    pytest.param("Stripe", ("stripe", "Stripe"), id="single-word"),
    pytest.param("Netic AI", ("netic", "Netic AI"), id="acronym-token"),
    pytest.param("IBM", ("ibm", "IBM"), id="all-acronym"),
    pytest.param("3M", ("3m", "3M"), id="digit-token"),
    pytest.param("Path Robotics", ("path", "Path Robotics"), id="corporate-word"),
    pytest.param("Palo Alto Networks", ("palo", "Palo Alto Networks"), id="three-words-corporate"),
    pytest.param("Crusoe Hiring Team", ("crusoe", "Crusoe"), id="role-tail-stripped"),
    pytest.param(
        "Northwind Labs Recruiting", ("northwind", "Northwind Labs"), id="tail-plus-corporate"
    ),
]


@pytest.mark.parametrize("name,expected", COMPANIES)
def test_a_company_display_name_still_files(name: str, expected: tuple[str, str]) -> None:
    """The control. A guard that refused everything would pass every test above."""

    assert p.resolve_employer(ATS, "Next steps", name) == expected


def test_the_at_shape_survives_on_the_one_word_rule_not_on_the_at() -> None:
    """Pinning what actually carries `Team Talent @ MotherDuck`, because the
    docstring first credited the wrong rule.

    `_employer_from_sender_name` splits on the `@` BEFORE the guard runs and
    passes the bare tail, so `"@" in display` cannot fire at that site.
    `MotherDuck` survives because it is one word. `Basalt Row` is two bare
    words and is refused — a real cost, and one the earlier prose claimed was
    handled by an `@` branch that never executes.
    """

    assert p.resolve_employer(ATS, "Next steps", "Team Talent @ MotherDuck") == (
        "motherduck",
        "MotherDuck",
    )
    assert p.resolve_employer(ATS, "Next steps", "Team Talent @ Basalt Row") is None
    assert p._clean_sender_display_name("Team Talent @ MotherDuck") == "Team Talent @ MotherDuck"


def test_no_person_named_card_is_minted_end_to_end() -> None:
    """The measurement the issue was filed on, as a test.

    Not `resolve_employer` in isolation — the card. Two person-messages that
    used to GROUP onto one `Sarah Chen` row, and one control that must still
    produce its company.
    """

    def item(mid: str, subject: str, sender_name: str | None) -> p.PipelineItem:
        return p.PipelineItem(
            message_id=mid,
            category="interview",
            sender_email=ATS,
            subject=subject,
            sender_name=sender_name,
            received_at=datetime.datetime(2026, 9, 3, 12, 0),
            confidence=0.95,
        )

    rolled = p.roll_up_applications(
        [
            item("m1", "Next steps", "Sarah Chen"),
            item("m2", "Sarah Chen - quick chat?", None),
            item("m3", "Thanks for applying to Northwind Labs", "Northwind Labs Recruiting"),
        ]
    )

    names = {r.company_display for r in rolled}
    assert "Sarah Chen" not in names, (
        f"a card named after a person was minted: {sorted(names)}. Both person "
        "messages used to group onto one such row at 0.95, above the auto-file "
        "gate."
    )
    assert "Northwind Labs" in names, "the control stopped filing; the guard refuses too much"


def test_grouping_is_deliberately_untouched() -> None:
    """`company_key` is NOT guarded, and that is the design.

    Grouping a stray message under a recruiter's token is invisible and
    reversible; NAMING a board card after them is neither. The guard is applied
    at filing grade only, so `company_key` still answers for grouping and the
    two entry points deliberately disagree here.
    """

    assert p.company_key(ATS, "Next steps", "Sarah Chen") == "sarah chen"
    assert p.resolve_employer(ATS, "Next steps", "Sarah Chen") is None
