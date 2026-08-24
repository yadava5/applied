"""A legal notice is not a job title, and a courier is not an employer.

Two defects from #497, both visible on one real board after a single sync, and
both the same underlying mistake: an extractor took the first span that fit its
shape and nothing downstream asked whether the result was the KIND of thing the
column is for.

1. THE ROLE READ OUT OF AN EQUAL-OPPORTUNITY NOTICE. Google's acknowledgement
   closes by citing a poster by name. ``opportunity`` is the weakest of the five
   trailing keywords in ``_ROLE_BODY_PATTERNS``, and it sits inside that poster's
   title:

       ... please refer to the "Equal Employment Opportunity is the Law" poster
                               ^^^^^^^^^^^^^^^^^^ capture   ^^^^^^^^^^^ keyword

   The board's Google card carried the position ``"Equal Employment`` — leading
   double-quote included, which is the tell that the span was cut out of a
   quoted phrase rather than parsed.

2. THE ATS SUFFIX THAT SURVIVED INTO THE EMPLOYER NAME. An icims relay sets its
   From display name to ``Medpace, Inc. @ icims``. ``_employer_from_sender_name``
   already knew the ``@`` shape — but only in the other direction, where the
   employer is the TAIL (``Team Talent @ MotherDuck``). With the tail correctly
   rejected as the relay, the fallback took the whole raw string, so the card
   read ``Medpace, Inc. @ icims`` and grouped as a different employer from the
   same company reached through any other ATS.

NOT FIXED BY STRIPPING THE OBSERVED STRINGS, which #497 asks for explicitly.
Each rule is written against the class of text, and each is paired here with the
control that would fail if the rule were a blacklist instead:

  * the legal-notice stem is matched WHOLE, so ``Equal Employment Opportunity
    Specialist`` — a real job title — still extracts.
  * the ``@`` rule asks which SIDE names the relay, so the opposite convention
    still resolves to the employer.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud import pipeline


# ---------------------------------------------------------------------------
# 1. The role
# ---------------------------------------------------------------------------

# Synthetic wordings. The repo is public and real mailbox content never lands in
# a fixture; these reproduce the SHAPE, which is what the extractor sees.
_EEO_QUOTED = (
    "Hi Ayush, Thanks for applying! We appreciate your interest. For more "
    'information, please refer to the "Equal Employment Opportunity is the '
    'Law" poster.'
)
_EEO_BARE = "Please refer to the Equal Employment Opportunity poster for details."


@pytest.mark.parametrize("body", [_EEO_QUOTED, _EEO_BARE])
def test_an_equal_opportunity_notice_is_not_a_role(body):
    assert pipeline.role_from_message("Thanks for applying to Google", body) is None, (
        "a legal notice was extracted as the job title — this is the card that "
        "read '\"Equal Employment' on the real board"
    )


def test_the_quoted_form_is_caught_without_the_stem_list():
    """The two guards are independent, and each must stand alone.

    If only the stem list fired, a notice quoting some OTHER phrase would still
    ship a title with a stray quote in it. The unbalanced double quote is a
    structural fact about the capture, not a fact about equal-opportunity law.
    """

    # "refer to the" — the anchor MATTERS here. An earlier draft of this test
    # said "Please see the …", which the body patterns do not anchor on at all
    # ("see" is not in the preposition alternation), so no capture was ever
    # produced and the test passed with the guard deleted. It proved nothing.
    # This wording really does reach `_clean_role` with `"Some Other Policy`.
    body = 'Please refer to the "Some Other Policy Opportunity is the Law" poster.'
    assert pipeline.role_from_message("x", body) is None


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "Thank you for your interest in the Embedded Software Engineer, "
            "Access Control opportunity.",
            "Embedded Software Engineer, Access Control",
        ),
        (
            "Thank you so much for applying to the Backend Engineer, Alarms "
            "role at Verkada!",
            "Backend Engineer, Alarms",
        ),
        (
            "Thank you for applying to our role: Software Engineer I, Storage.",
            "Software Engineer I, Storage",
        ),
        (
            "We received your application for the Software Engineer - 2026 (US) "
            "(ID: 3177934) position.",
            "Software Engineer - 2026 (US)",
        ),
    ],
)
def test_real_titles_still_extract(body, expected):
    """CONTROLS. The first one uses the SAME `opportunity` keyword the defect
    rode in on, so a fix that simply removed that keyword fails here."""

    assert pipeline.role_from_message("x", body) == expected


def test_a_title_that_continues_past_the_stem_is_kept():
    """The anti-blacklist control, and the reason the stem is matched whole.

    "Equal Employment Opportunity Specialist" is a real job title. A prefix or
    substring test over the same stem list refuses it, which would trade one
    wrong answer for another.
    """

    body = "Thank you for applying to the Equal Employment Opportunity Specialist position."
    assert (
        pipeline.role_from_message("x", body)
        == "Equal Employment Opportunity Specialist"
    )


def test_a_balanced_quote_inside_a_title_survives():
    """Only an UNBALANCED quote indicates a span cut out of a quotation."""

    assert pipeline._clean_role('Engineer II ("Platform")') is not None


# ---------------------------------------------------------------------------
# 2. The employer
# ---------------------------------------------------------------------------

ICIMS = "medpace+autoreply@talent.icims.com"
ASHBY = "no-reply@ashbyhq.com"


def test_the_ats_suffix_does_not_survive_into_the_employer():
    resolved = pipeline.resolve_employer(ICIMS, "Thank you for your application", "Medpace, Inc. @ icims")

    assert resolved is not None, "the employer stopped resolving entirely"
    token, display = resolved
    assert token == "medpace"
    assert "icims" not in display.lower(), (
        f"the courier's name is still glued to the employer: {display!r}"
    )
    assert display == "Medpace, Inc"


def test_the_opposite_convention_still_resolves_to_the_employer():
    """CONTROL. ATS display names put the employer on EITHER side of the `@`.

    A fix that simply took the head would break this one, which is the shape
    `_employer_from_sender_name` was originally written for.
    """

    assert pipeline.resolve_employer(ASHBY, "x", "Team Talent @ MotherDuck") == (
        "motherduck",
        "MotherDuck",
    )


def test_a_display_name_with_no_at_sign_is_untouched():
    assert pipeline.resolve_employer(ASHBY, "x", "Crusoe Hiring Team") == (
        "crusoe",
        "Crusoe",
    )


def test_a_relay_on_both_sides_still_names_nobody():
    """Neither side carries an employer, so the precision gate must still refuse.

    Reading the head unconditionally would have invented one here.
    """

    assert pipeline.resolve_employer(ASHBY, "x", "Ashby @ ashbyhq") is None


def test_a_hostname_tail_is_still_not_a_name():
    """The pre-existing dot rule, pinned so the rewrite above did not drop it."""

    assert pipeline.resolve_employer(ASHBY, "x", "Careers @ ashbyhq.com") is None
