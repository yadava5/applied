"""THE LEADING SEGMENT OF AN ATS SUBJECT MAY CARRY A LIFECYCLE TAIL (#512, gap 2).

Reported on the real board, twice: "handshake, verkada, and anthropic still says
held for missing employer name!". Two of the three were fixed and this one was
not, and the issue was closed anyway.

The subject is a Greenhouse rejection in the standard shape

    <Employer> Follow-Up for <Role> | <Candidate>

and the employer is the first word of it. ``_EMPLOYER_LEAD_SEGMENT`` already
reads "the leading segment before a ``|`` or a spaced dash" — that is exactly
the shape here — but it requires the company to run UNBROKEN to the delimiter.
The lowercase "for" breaks the run, so the match fails entirely instead of
falling back to the Title-Case prefix, and a rejection the classifier scored at
0.95 produced no card.

WHY THE OBVIOUS FIX IS WRONG, measured rather than argued. "A leading
company-shaped run terminated by a lifecycle noun" reads well and mints job
titles as employers. Over a 28-subject hand trial it took

    "Senior Software Engineer Interview"     -> Senior Software Engineer
    "Machine Learning Engineer Offer"        -> Machine Learning Engineer
    "Product Designer Recruiting Update"     -> Product Designer

``_COMPANY_STOPWORDS`` does not save those: it is checked against the capture's
FIRST word, and "Senior", "Machine" and "Product" are not stopwords. This is the
filing path — whatever it returns becomes a card — so a rule that invents three
companies to rescue one is strictly worse than the bug.

THE DELIMITER IS THE SIGNAL, and it always was. Keeping the requirement that
the whole thing sit inside a leading SEGMENT — one that ends at a ``|`` or a
spaced dash — took the same 28-subject trial to 22 of 22 on the must-not-resolve
side, with no false positive at all. What it costs is subjects like "Stripe
Application Received", which have no delimiter and now still resolve to nothing.
That is the safe direction: the row goes to the review queue, where a person
decides, instead of onto the board under a name nobody chose. Every one of those
cases is invented; neither reported subject is among them.

Both halves are asserted below. The must-resolve cases are two, and the
must-not-resolve cases are twenty-two, because on this path the refusals are
the load-bearing half.

Measured over the 17,260-case independent corpus before shipping: 0 newly
resolved, 0 changed answers. The corpus has no subject of this shape, so it can
prove only that nothing regressed — this file is the gate that can fail on the
defect itself.

Every fixture is invented except the two real subject SHAPES, whose employer
names are public companies and whose role and candidate fields are redacted.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud.pipeline import resolve_employer

#: Greenhouse and Ashby relays — the only senders these rules are read for.
GREENHOUSE = "no-reply@us.greenhouse-mail.io"
ASHBY = "no-reply@ashbyhq.com"

#: A sender that is NOT a relay, to prove the branch stays fenced off it.
PERSONAL = "someone@gmail.com"


# ── the reported shape, and its sibling ──────────────────────────────────────


@pytest.mark.parametrize(
    "subject,expected",
    [
        ("Anthropic Follow-Up for <ROLE> | <CANDIDATE>", "anthropic"),
        ("Verkada Follow-Up for <ROLE> | <CANDIDATE>", "verkada"),
        # The same segment shape with a spaced dash, which the existing rule
        # already accepts as a delimiter.
        ("Northwind Labs Application Update - <ROLE>", "northwind"),
        # …and with the lifecycle word alone before the delimiter, which is the
        # case the ORIGINAL rule handles; asserted here so a rewrite that fixes
        # the new shape by breaking the old one cannot pass.
        ("Crusoe | Application Received", "crusoe"),
    ],
)
def test_the_employer_is_read_out_of_the_leading_segment(subject, expected):
    got = resolve_employer(GREENHOUSE, subject)
    assert got is not None, f"no employer resolved from {subject!r}"
    assert got[0] == expected


# ── the refusals: this is the filing path, so these are the important half ───


ROLE_SHAPED = [
    # A job title in the leading position is NOT an employer. These are the
    # three the first draft of this fix invented companies from.
    "Senior Software Engineer Interview | <CANDIDATE>",
    "Machine Learning Engineer Offer | <CANDIDATE>",
    "Product Designer Recruiting Update | <CANDIDATE>",
    "Software Engineer Application Received | <CANDIDATE>",
    "Staff Data Scientist Follow-Up for <TEAM> | <CANDIDATE>",
]

COURTESY_SHAPED = [
    # Every one of these opens with a capital, which is why "take the first
    # Title-Case run" was refused in #512 before it was tried. None of them
    # NAMES an employer, so none may produce one.
    "Thank You For Your Application | <CANDIDATE>",
    "Thank You For Your Interest In Our Opportunities | <CANDIDATE>",
    "Your Application Update | <CANDIDATE>",
    "An Update On Your Application | <CANDIDATE>",
]

NOT_A_SEGMENT = [
    # No delimiter: the lifecycle word alone is not enough, deliberately.
    "Senior Software Engineer Interview",
    "Machine Learning Engineer Offer",
    "Product Designer Recruiting Update",
    "Update on your application",
    "New Opportunities For You",
    "The Latest Careers Newsletter",
    "Our Careers Page Has Moved",
    "A Follow Up",
    "Follow-Up",
]


#: THE SHAPE THE WIDENING ACTUALLY ADMITTED, which no fixture above has.
#:
#: Every refusal above is either delimiter-less or an all-Title-Case segment.
#: None of them is "a capitalised word, then lowercase prose, then a delimiter"
#: — and that is exactly the shape the rule newly reads, because it is the shape
#: of the reported bug ("Anthropic Follow-Up FOR <Role> |"). The file asserted
#: the good case of that shape and never the bad one, so the widening shipped
#: green while these twelve subjects each minted a company on the AUTO-FILE
#: path: an interview invitation from any ATS resolved to a company literally
#: named "Invitation", at 0.95, straight onto the board.
#:
#: These are ordinary ATS subject lines, not adversarial constructions. Three of
#: them classify at 0.95 on the strongest tier, which is above ``AUTO_FILE_GATE``
#: — no human ever saw them before they became cards.
LEADING_CAPITAL_THEN_PROSE = [
    "Invitation to interview | <EMPLOYER>",
    "Decision on your application | <EMPLOYER>",
    "Take-Home Assignment for Backend Role | <EMPLOYER>",
    "Sorry for the delay in getting back to you | <EMPLOYER>",
    "Following up on your application | <EMPLOYER>",
    "Next steps in your application - <EMPLOYER>",
    "Scheduling your interview | <EMPLOYER>",
    "Reminder: Complete your assessment | <EMPLOYER>",
    # A person is not a company, and a greeting is not a company.
    "Sarah Chen from <EMPLOYER> - quick chat?",
    "Congratulations <CANDIDATE> on your application | <EMPLOYER>",
    # A newsletter that happens to carry a delimiter.
    "Tech Jobs Weekly: 25 New Roles | <EMPLOYER>",
    # The candidate's own name, off a job board's alert mail.
    "<CANDIDATE>, 12 new jobs for <ROLE> - <JOBBOARD>",
]


@pytest.mark.parametrize("subject", LEADING_CAPITAL_THEN_PROSE)
def test_a_capitalised_word_in_front_of_prose_is_not_a_company(subject):
    """The run must account for the whole segment, or be cut at its own lifecycle word.

    This is the assertion whose absence let the widening through. It fails on
    the code as it shipped — each of these returned a company — and passes once
    the leading run is required to explain the entire segment rather than merely
    to start it.
    """
    assert resolve_employer(GREENHOUSE, subject) is None, (
        f"{subject!r} minted an employer out of a leading capital followed by "
        "ordinary prose"
    )


def test_a_lifecycle_tail_is_still_forgiven_after_a_company():
    """THE CONTROL for the list above, and the reason it is not just "refuse more".

    The two differ by one thing only: whether a lifecycle word sits between the
    company and the remainder. Without this assertion the rule could satisfy
    every refusal above by returning None unconditionally, which is precisely
    the bug #512 reported.
    """
    got = resolve_employer(GREENHOUSE, "Northwind Follow-Up for <ROLE> | <CANDIDATE>")
    assert got is not None and got[0] == "northwind"


def test_the_card_is_named_for_the_company_not_the_company_plus_the_lifecycle():
    """The CUT reading must win when the run runs on past the company.

    Both readings are company-shaped here, and the uncut one groups to the same
    token — so a test that only checked the token would pass while the card on
    the board read "Verkada Interview Invitation".
    """
    got = resolve_employer(
        GREENHOUSE, "Verkada Interview Invitation for <ROLE> | <CANDIDATE>"
    )
    assert got == ("verkada", "Verkada")


@pytest.mark.parametrize("subject", ROLE_SHAPED + COURTESY_SHAPED + NOT_A_SEGMENT)
def test_a_subject_that_does_not_name_an_employer_resolves_to_nothing(subject):
    """Refusing is the safe answer here: the row goes to the queue, not the board."""
    assert resolve_employer(GREENHOUSE, subject) is None, (
        f"{subject!r} minted an employer — this is the filing path, so that is a "
        "card on the board under a name nobody chose"
    )


@pytest.mark.parametrize(
    "subject",
    [
        # These DO name the employer, in a connective the anchored rule reads
        # ("interest in X", "to X"). They are asserted here as the control for
        # the refusals above: a rule that refuses everything would satisfy that
        # list and destroy these, and the two cases look alike from a distance.
        "Thank you for your interest in Northwind, <CANDIDATE>",
        "Your Application to Northwind | <CANDIDATE>",
    ],
)
def test_a_courtesy_opener_that_really_does_name_the_employer_still_resolves(subject):
    got = resolve_employer(GREENHOUSE, subject)
    assert got is not None and got[0] == "northwind", (
        f"{subject!r} names Northwind and resolved to {got!r}"
    )


def test_a_subject_naming_the_relay_still_resolves_to_nothing():
    """The relay is never the employer, however the subject is shaped."""
    assert resolve_employer(GREENHOUSE, "Greenhouse Follow-Up for <ROLE> | <NAME>") is None


def test_the_branch_is_fenced_off_non_relay_senders():
    """Steps 3 and 4 are ATS-only, and this one inherits that fence.

    Off a relay the same shape is ordinary correspondence — a person's mail is
    where they occur — so the segment carries no claim about an employer.
    """
    assert resolve_employer(PERSONAL, "Anthropic Follow-Up for <ROLE> | <NAME>") is None


def test_the_ashby_relay_reads_the_same_segment():
    """Not Greenhouse-specific: the rule is about the SUBJECT's shape."""
    got = resolve_employer(ASHBY, "Northwind Labs Follow-Up for <ROLE> | <NAME>")
    assert got is not None and got[0] == "northwind"


def test_a_remainder_is_only_forgiven_when_it_is_the_lifecycle_word_s_object():
    """"Quick Update FROM Sarah" is not a company called Quick.

    Requiring the leading run to explain the whole segment is not enough on its
    own: a run that merely ENDS in a lifecycle word will forgive any remainder
    at all, and then offers the part in front of it. "Quick Update" ends in
    "Update", so "Quick" was offered and passed every downstream guard.

    "for" is what marks the remainder as the lifecycle word's object. This case
    resolved to nothing before the segment rule was widened, and must again.
    """
    assert resolve_employer(GREENHOUSE, "Quick Update from Sarah | <EMPLOYER>") is None


def test_a_legal_suffix_is_part_of_the_company_not_a_remainder():
    """THE CONTROL for the rule above, and a real employer it must not cost.

    "Salesforce, Inc." splits its Title-Case run at the comma, so the suffix
    reads as an unexplained remainder and a strict whole-segment rule would
    refuse an employer the resolver otherwise reads correctly.
    """
    got = resolve_employer(GREENHOUSE, "Salesforce, Inc. | Application Received")
    assert got is not None and got[0] == "salesforce"
