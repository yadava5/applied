"""An ALL-CAPS subject must not read its greeting as the job title (#962).

`_ROLE_PATTERNS[3]` reads the `<Role> - <Employer>` shape and its leading run is
`[A-Z][\\w/&.\\-]*`, which matches a fully upper-case word as readily as a
Title-Case one. So every word of an upper-case greeting qualifies, and the
pattern hands back prose:

    "WE REGRET TO INFORM YOU - NORTHWIND LABS"      -> "WE REGRET TO INFORM YOU"
    "DECISION ON YOUR APPLICATION - NORTHWIND LABS" -> "DECISION ON YOUR APPLICATION"

WHY IT IS NOT COSMETIC. `application_sub_key` is half an application's IDENTITY,
so a captured phrase becomes the CARD'S TITLE and then captures that
application's future mail — later rejections and interview invitations file onto
a card named "WE REGRET TO INFORM YOU". It is the class #525 and #537 fixed on
the EMPLOYER half, where `resolve_employer` was minting companies called
Invitation, Decision and Sorry; the role half was never given the same treatment.

THE FIX IS A HEAD TEST, NOT A CASE TEST, and the difference is the whole design.
Refusing upper case would take "BACKEND ENGINEER - NORTHWIND LABS" with it — a
real title in a real all-caps subject — trading this defect for a worse one. What
separates the two is the HEAD of the phrase: a job title begins with a noun or an
adjective, and prose begins with a pronoun, a verb or a determiner.

AND IT IS NOT `_COMPANY_STOPWORDS`, which is the same idea on the other half.
That set carries `software`, `engineer`, `developer`, `intern` — words that are
not companies and ARE how half of all job titles start. The two halves need
opposite vocabularies.

THE CORPUS CANNOT GRADE THIS and the production frequency is zero, both
measured. The independent corpus mints Title-Case employers and roles, so no
case carries an upper-case subject; and a read-only census of the owner's 96
stored subjects on 2026-09-09 found 0 fully upper-case and 0 with three
consecutive ALL-CAPS words. This is a latent identity hole with no observed
instance — which is why the controls below matter more than the defect cases: a
fix that cost real titles would be a regression paid for nothing.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud import pipeline

#: Prose that `_ROLE_PATTERNS[3]` captured as a job title. Each is a real ATS
#: subject shape spelled the way a legacy or non-English system sends it.
GREETINGS = [
    "THANK YOU FROM NORTHWIND LABS - JANE DOE - BACKEND ENGINEER",
    "DECISION ON YOUR APPLICATION - NORTHWIND LABS",
    "WE REGRET TO INFORM YOU - NORTHWIND LABS",
    "UPDATE ON YOUR CANDIDACY - NORTHWIND LABS",
    "IMPORTANT NOTICE ABOUT YOUR FILE - NORTHWIND LABS",
    "CONGRATULATIONS ON YOUR PROGRESS - NORTHWIND LABS",
]

#: Titles that must survive, and the reason each one is in the list.
TITLES = [
    # the all-caps control: same case as the defect, and a real title
    ("BACKEND ENGINEER - NORTHWIND LABS", "BACKEND ENGINEER"),
    # ordinary Title-Case, the common case
    ("Backend Engineer - Northwind Labs", "Backend Engineer"),
    # a title whose head is in `_COMPANY_STOPWORDS`, which is why that set
    # cannot be reused here
    ("Software Engineer - Northwind Labs", "Software Engineer"),
    ("Engineer II - Northwind Labs", "Engineer II"),
    ("Developer Advocate - Northwind Labs", "Developer Advocate"),
    ("Intern Platform Engineer - Northwind Labs", "Intern Platform Engineer"),
    ("Internship Program - Northwind Labs", "Internship Program"),
    # an acronym head and a slash, which a Title-Case-only test would refuse
    ("SDE II - Northwind Labs", "SDE II"),
    ("AI/ML Engineer - Northwind Labs", "AI/ML Engineer"),
    ("Senior SDE II - Northwind Labs", "Senior SDE II"),
    ("Data Scientist - Northwind Labs", "Data Scientist"),
    ("Staff Product Designer - Northwind Labs", "Staff Product Designer"),
    # MEASURED, NOT WISHED FOR. The pattern's optional `(?i:new\s+)?` eats the
    # leading word, so this yields "Grad Software Engineer" and did before this
    # change too. It is in the list precisely because the expectation is the
    # tree's answer rather than the one a reader would guess: a control written
    # from what the title OUGHT to be would red here for a reason that has
    # nothing to do with #962. The `New`-eating is a separate question.
    ("New Grad Software Engineer - Northwind Labs", "Grad Software Engineer"),
]


@pytest.mark.parametrize("subject", GREETINGS)
def test_a_greeting_is_not_a_job_title(subject: str) -> None:
    """The defect. Every one of these was captured before the fix."""

    assert pipeline._role_from_subject(subject) is None, (
        f"{subject!r} yielded a role; `application_sub_key` is half an "
        "application's identity, so this phrase becomes a card's title and "
        "captures that application's later mail"
    )


@pytest.mark.parametrize("subject,expected", TITLES)
def test_a_real_title_still_resolves(subject: str, expected: str) -> None:
    """THE CONTROLS, and there are more of them than defect cases on purpose.

    The production frequency of the defect is zero and the frequency of these
    shapes is not, so a fix that cost any of them would be a regression paid for
    nothing. The all-caps entry is the one that matters most: it has the same
    case as the defect and must not be refused with it.
    """

    assert pipeline._role_from_subject(subject) == expected


@pytest.mark.parametrize(
    "caps, title",
    [
        (
            "DECISION ON YOUR APPLICATION - NORTHWIND LABS",
            "Decision on your application - Northwind Labs",
        ),
        (
            "WE REGRET TO INFORM YOU - NORTHWIND LABS",
            "We regret to inform you - Northwind Labs",
        ),
        (
            "UPDATE ON YOUR CANDIDACY - NORTHWIND LABS",
            "Update on your candidacy - Northwind Labs",
        ),
    ],
)
def test_the_title_case_spelling_was_never_the_defect(caps: str, title: str) -> None:
    """The case control that separates the mechanism from the vocabulary.

    Title-Case prose already returned None before this fix, because the
    pattern's continuation run requires `[A-Z0-9]` on every word. So the defect
    is what an ALL-CAPS spelling reaches, and this asserts the other spelling's
    answer is unchanged rather than newly correct.

    THE PAIRS ARE TWO-SEGMENT ON PURPOSE, and the first draft was not. It used
    "Thank you from <Employer> - <Candidate> - <Role>" and asserted None for
    the Title-Case half — true when written, and false the moment #485's
    `_role_from_dash_run` lands, because that subject is EXACTLY the shape that
    reader exists for. Measured on a tree carrying both branches: this file was
    green alone, #485 was green alone, and assembled the Title-Case half
    returned "Backend Engineer". A control whose answer depends on which OTHER
    branch has landed is not a control.

    So the pairs here carry no trailing role segment at all. Neither spelling
    reaches any reader in either tree, which is the claim the case is actually
    making.
    """

    assert pipeline._role_from_subject(caps) is None
    assert pipeline._role_from_subject(title) is None


def test_the_refusal_is_the_head_set_and_not_something_else() -> None:
    """THE MUTATION CONTROL. Take the head out and its greeting returns.

    Without it every assertion above would pass for any reason at all — a
    pattern that stopped matching, a capture that got shorter — and would keep
    passing if `_NOT_A_ROLE_HEAD` were emptied. Removing exactly one word must
    restore exactly that one capture and leave the rest refused.
    """

    original = pipeline._NOT_A_ROLE_HEAD
    try:
        pipeline._NOT_A_ROLE_HEAD = original - {"we"}
        assert (
            pipeline._role_from_subject("WE REGRET TO INFORM YOU - NORTHWIND LABS")
            == "WE REGRET TO INFORM YOU"
        ), "removing the head word did not restore the defect, so the set is not what refuses it"
        assert (
            pipeline._role_from_subject("DECISION ON YOUR APPLICATION - NORTHWIND LABS")
            is None
        )
    finally:
        pipeline._NOT_A_ROLE_HEAD = original
    assert pipeline._role_from_subject("WE REGRET TO INFORM YOU - NORTHWIND LABS") is None


def test_the_identity_a_greeting_would_have_minted() -> None:
    """The consequence, asserted through the function that makes it an identity.

    `application_sub_key` is what turns a captured phrase into half a card's key,
    and it is the reason this is a correctness defect rather than a cosmetic one.
    Reading it here rather than describing it keeps the claim honest.
    """

    subject = "WE REGRET TO INFORM YOU - NORTHWIND LABS"
    assert "regret" not in (pipeline.application_sub_key(subject, "") or "")
    titled = "Backend Engineer - Northwind Labs"
    assert pipeline.application_sub_key(titled, "") == "backend engineer"
