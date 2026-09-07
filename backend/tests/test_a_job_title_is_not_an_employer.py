"""A subject that names a ROLE must not put that role on the board as a company.

The defect
----------
``resolve_employer`` reads the subject at step 2 (:func:`_employer_from_subject`)
and the leading segment at step 3b
(:func:`_employer_from_subject_segment`). Only 3b refused a capture whose head
noun is a job title. Step 2 runs FIRST and outranks both 3b and the sender
display name, so the guard sat behind the branch that needed it most::

    "Final Interview for Data Scientist | Larkspur"      -> ('data', 'Data Scientist')
    ...with sender_name "Larkspur Recruiting"            -> ('data', 'Data Scientist')

``interview`` is an anchor word in ``_EMPLOYER_ANCHORED`` and ``for`` is one of
its connectives, so ``Interview for <Role>`` reads the role straight into the
company capture. A correct display name naming the real employer lost to it.

Why the fix is a shared function and not a second copy
------------------------------------------------------
The test 3b already had is the right test — last word, because a title is
right-headed, and ``continue`` rather than ``return None`` so a refusal only
refuses THIS reading. It was extracted to
:func:`_names_a_role_not_an_employer` and called from both readers, rather than
spelled twice. Two spellings of one rule is two answers waiting to disagree,
which is the shape #596 was.

``_ROLE_HEAD_NOUNS`` is also the set the ROLE half uses, and ``_TITLE_SHAPED``'s
note claims the two halves "cannot end up disagreeing about what a job title
looks like". Before this change they did, on step 2. That sentence is now true.

Why it is not written into ``_valid_company_token``
----------------------------------------------------
:func:`_employer_from_subject`'s own docstring proposed that and rejected the
whole fix on it: ``_valid_company_token`` is also what the USER-TYPED company
path goes through, so a company whose name reads like a title would stop being
enterable by hand. Refusing per-reading inside the loop — exactly where
:func:`_names_the_relay` already sits — costs the typed path nothing.

What it costs, measured rather than asserted
---------------------------------------------
Nothing on the corpus. Every one of the 18,200 independent-corpus cases was run
through ``resolve_employer`` before and after, by swapping the module file:

    cases 18200 | OLD resolves an employer for 17797 | DIFFERENCES 0

The 17,797 is the control — an instrument that resolved nothing would also
report zero differences.

The real cost is a company whose name ENDS in a title head noun
("Analyst Group" does not; "Acme Engineer" would), which now falls through to
the display name and then to the review queue rather than being filed. That is
the direction this module takes everywhere: a person decides, instead of a
board row nobody chose.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud.pipeline import (
    _employer_from_subject,
    _employer_from_subject_segment,
    _names_a_role_not_an_employer,
    resolve_employer,
)

RELAY = "noreply@ashbyhq.com"
EMPLOYER_NAME = "Larkspur Recruiting"


# ---------------------------------------------------------------------------
# The defect: a role reached the board, and beat a correct display name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subject",
    [
        "Final Interview for Data Scientist | Larkspur",
        "Interview for Machine Learning Engineer | Larkspur",
        "Onsite Interview for Product Designer",
        "Your application for the Senior Data Analyst role",
    ],
)
def test_a_role_named_in_the_subject_is_never_the_employer(subject: str) -> None:
    """No reading of these subjects may answer with the job title.

    Asserted against the ROLE WORDS rather than against a single expected
    tuple, because the acceptable answers differ per subject — the real
    employer, or nothing — and both are correct. What is never correct is the
    title.
    """
    answer = resolve_employer(RELAY, subject, None)

    if answer is not None:
        token, display = answer
        assert "scientist" not in display.lower()
        assert "engineer" not in display.lower()
        assert "designer" not in display.lower()
        assert "analyst" not in display.lower()


@pytest.mark.parametrize(
    "subject",
    [
        "Final Interview for Data Scientist | Larkspur",
        "Interview for Machine Learning Engineer | Larkspur",
        "Onsite Interview for Product Designer",
    ],
)
def test_the_display_name_wins_once_the_role_reading_is_refused(subject: str) -> None:
    """The half that makes this a fix rather than a refusal.

    Step 2 declining hands the subject to step 3, where the relay's display
    name names the real employer. Before the change step 2 answered with the
    title and step 3 never ran.
    """
    assert resolve_employer(RELAY, subject, EMPLOYER_NAME) == ("larkspur", "Larkspur")


# ---------------------------------------------------------------------------
# The controls: everything that resolved before still resolves, unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject", "sender_name", "expected"),
    [
        ("Crusoe | Application Received", None, ("crusoe", "Crusoe")),
        ("MotherDuck | Interview Request", None, ("motherduck", "MotherDuck")),
        ("Thank you for applying to Verkada", None, ("verkada", "Verkada")),
        ("Thank you for your interest in Verkada, there", None, ("verkada", "Verkada")),
        ("Your application to Stripe", None, ("stripe", "Stripe")),
        # #512's shape: the cut ALONE at index 0, which is the case the
        # one-word exemption exists for. It must survive this change.
        (
            "Northwind Follow-Up for Backend Engineer | Someone",
            None,
            ("northwind", "Northwind"),
        ),
        ("Thanks for applying", EMPLOYER_NAME, ("larkspur", "Larkspur")),
    ],
)
def test_a_real_employer_still_resolves(subject, sender_name, expected) -> None:
    """Seven arrangements that must be byte-identical before and after.

    The sixth is load-bearing: "<Employer> Follow-Up for <Role>" is the same
    ``<Word> <Lifecycle> for <Role>`` shape as the defect above, and the
    employer is in the position the defect's title occupies. A guard that
    refused on shape rather than on the head noun would take this with it.
    """
    assert resolve_employer(RELAY, subject, sender_name) == expected


# ---------------------------------------------------------------------------
# The predicate itself, in both directions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "display",
    ["Data Scientist", "Machine Learning Engineer", "Product Designer", "Phone Interview"],
)
def test_the_predicate_refuses_a_title(display: str) -> None:
    assert _names_a_role_not_an_employer(display) is True


@pytest.mark.parametrize(
    "display",
    # The first three are the names the guard's own comment promises to keep;
    # "Lead Bank" is a real company whose FIRST word is a head noun, which is
    # exactly what testing every word instead of the last one would destroy.
    ["Team Liquid", "People Data Labs", "Cedar Labs", "Lead Bank", "Crusoe", "Stripe"],
)
def test_the_predicate_keeps_a_company_that_merely_contains_a_title_word(
    display: str,
) -> None:
    assert _names_a_role_not_an_employer(display) is False


def test_the_predicate_is_total_on_an_empty_capture() -> None:
    """``display`` is falsy at one caller before its own guard runs."""
    assert _names_a_role_not_an_employer("") is False


# ---------------------------------------------------------------------------
# The invariant the two halves are supposed to hold
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subject",
    [
        "Interview for Machine Learning Engineer | Larkspur",
        "Senior Software Engineer Interview | Someone",
    ],
)
def test_both_subject_readers_refuse_the_same_title(subject: str) -> None:
    """Neither reader may answer with a title, whichever one is asked.

    This is the sentence ``_TITLE_SHAPED``'s note asserts. It is pinned
    behaviourally rather than by asserting both call the helper, because a
    call-site census goes green on a call whose result is discarded.
    """
    assert _employer_from_subject(subject, ats_relay=True, relay_brand="ashbyhq") is None
    from_segment = _employer_from_subject_segment(subject, "ashbyhq")
    if from_segment is not None:
        assert "engineer" not in from_segment[1].lower()


# ---------------------------------------------------------------------------
# A DISCLOSED LEAK, pinned so it cannot move silently
# ---------------------------------------------------------------------------


def test_a_lifecycle_modifier_alone_is_still_minted_as_a_company() -> None:
    """NOT fixed here, and pinned as the wrong answer it currently gives.

    With no display name, "Final Interview for Data Scientist | Larkspur"
    leaves ``_lead_segment_candidates`` a SINGLE reading, ``['Final']`` — the
    lowercase "for" breaks the Title-Case run, so the one-word fragment
    arrives at index 0 and takes the exemption #829 gave to a first reading.

    This change did not create it; it exposed it. Before, step 2 answered the
    same subject with 'Data Scientist', so the segment reader never ran and a
    different wrong company was filed instead. Both are wrong and neither is
    worse, which is why this is recorded rather than traded.

    It is NOT fixable by position: "Final Interview for Data Scientist" and
    #512's "Northwind Follow-Up for Backend Engineer" are the same
    ``<Word> <Lifecycle> for <Role>`` shape with the same single-candidate
    list, and only vocabulary separates a lifecycle modifier from a proper
    noun. Adding "final"/"phone"/"next" to ``_COMPANY_STOPWORDS`` refuses
    Final Draft, Phone2Action and Next Insurance — the cost #539's body
    already priced. That decision belongs to #830.
    """
    assert resolve_employer(RELAY, "Final Interview for Data Scientist | Larkspur", None) == (
        "final",
        "Final",
    )
