"""The role at the end of a hyphen run — #485, and what it refuses.

Lever writes the job title into its rejection subject:

    <lifecycle prose> from <Employer> - <Candidate Name> - <Role>

and until `_role_from_dash_run` nothing read it. `application_sub_key` returned
None, so the message carried no identity at all and was PLACED only by having
none — `_pick_application` rule 3 carries a role-less message onto an
employer's single cluster. That works right up until the employer has two.

WHAT THIS FILE IS MOSTLY ABOUT IS THE REFUSALS, and that is not modesty about
coverage, it is where the risk lives. The 18,980-case corpus grades the
RESOLVE direction — 29 fire, 29 exact, 0 wrong, and every firing case reads no
role today, so nothing that resolved before resolves differently. But all 29
come from ONE transcribed wording in one family. The corpus can say the reader
does not fire wrongly across the mail it holds; it cannot say the reader reads
the Lever family, because it holds one member of it.

So every refusal below is a case written alongside the rule, by its author, and
each one is a subject that CAPTURED A ROLE from an earlier draft. They are
named as drafts rather than as hypotheticals because that is what they were:

  * `<Role> - Boston`               -> captured "Backend Engineer - Boston"
  * `<Role> - <Candidate Name>`     -> captured "Backend Engineer - Jane Doe"
  * `Sarah Chen from <E> - <Title>` -> captured the RECRUITER'S own job title
  * `Referral from <Person> - ...`  -> read a person as the employer
  * `Working from Home - <Role>...` -> read a place as the employer

The first two are the shape #553 measured and refused for the leading-segment
reader: a spaced dash is not a boundary a subject can license on its own, and
`_post_head_is_introduced` accepts one as a title continuation, so extending a
capture rightward to the end of the subject swallows whatever is there. The
last three are why "from" cannot be the whole licence — this module has already
adjudicated it twice as the preposition that introduces a person as readily as
an employer.

THE RESIDUAL IS PINNED RATHER THAN FIXED. A candidate whose surname is a job
title head noun reads as a role, and nothing in a subject separates that from a
real title. `test_a_name_that_looks_like_a_title_is_the_known_residual` asserts
the current behaviour so the limitation is visible in the suite instead of
discovered later.

PLACEMENT IS NOT GRADED HERE AND THE CORPUS COULD NOT GRADE IT EITHER. That
sentence used to read the other way round, and the correction is the whole
reason this file has a sibling. `_may_join` returns False when a cluster's
`role_token` is None and an item's is not, so a captured role can mint a rival
cluster beside a card the board already has. Measured over the whole corpus by
building the pipeline items both ways, that never happened: clusters 10,215
both ways, unplaced 370 both ways, nine clusters swapping `role_token=None` for
the correct role and nothing else moving. Equal counts across 18,980 cases were
read as "the reader is safe" and they were not — `_observed_rejections` draws a
fresh employer per case and pairs one confirmation with one rejection, so the
corpus holds NO employer with two anonymous rows, which is precisely the
composition #485 opens with. A measurement that cannot return positive for a
defect is not evidence about it. Constructed directly, the reader alone mints
the rival card and silences the queue row.

So the reader ships with a placement ladder, and that ladder is asserted in
`test_an_identified_update_does_not_mint_a_rival_485.py` against eight
compositions plus its own boundaries — including the five that the ladder's
FIRST version, which was a measured net regression, answered differently from
`main` for the worse.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud import pipeline

#: One employer, one candidate, one role, reused everywhere below so a case
#: that resolves and a case that refuses differ in ONE thing. Invented, per
#: `docs/TEST_DATA_POLICY.md`; the corpus's own transcribed template carries a
#: real name and is not copied here.
EMPLOYER = "Northwind Labs"
CANDIDATE = "Jane Doe"
ROLE = "Backend Engineer"


def _read(subject: str) -> str | None:
    """Through `_role_from_subject`, not the new reader directly.

    The reader runs LAST of three and only sees a subject the other two
    declined. Asserting on it in isolation would grade a function that is not
    the one the pipeline calls.
    """
    return pipeline._role_from_subject(subject)


# ---------------------------------------------------------------- resolves

def test_the_three_segment_shape_is_read() -> None:
    assert _read(f"Thank you from {EMPLOYER} - {CANDIDATE} - {ROLE}") == ROLE


def test_the_two_segment_shape_is_read() -> None:
    """The variant #485 names, where the candidate's name is absent.

    It matters that this resolves through the SAME rule: the role is the last
    segment either way, so there is no second reading that could disagree with
    the first about which segment holds the title.
    """
    assert _read(f"Thank you from {EMPLOYER} - {ROLE}") == ROLE


def test_prose_other_than_thanks_still_licenses_it() -> None:
    """The licence is "prose, then from, then a company", not one greeting."""
    assert _read(f"An update from {EMPLOYER} - {CANDIDATE} - {ROLE}") == ROLE


# ---------------------------------------------------------------- refusals

def test_a_trailing_location_is_not_part_of_the_title() -> None:
    """A draft captured "Backend Engineer - Boston".

    The guards cannot see it: a spaced dash IS a licensed title continuation
    (`_post_head_is_introduced`), and no list closes place names. What refuses
    it is structural — the role is the LAST segment and nothing else.
    """
    assert _read(f"Thank you from {EMPLOYER} - {CANDIDATE} - {ROLE} - Boston") is None


def test_the_candidates_name_after_the_role_is_not_captured() -> None:
    """The failure the issue names by name: a card titled after the user.

    Same three segments as the resolving case, in a different order. That is
    the whole difference — a control that varies one thing.
    """
    assert _read(f"Thank you from {EMPLOYER} - {ROLE} - {CANDIDATE}") is None


def test_a_recruiters_signature_title_is_not_the_job() -> None:
    """"Sarah Chen from <Employer> - Talent Acquisition Specialist".

    A draft captured `Talent Acquisition Specialist`: "specialist" is a title
    head noun, the region after it is empty, and every guard passes. What
    refuses it is the second half of the licence — the material in front of
    "from" must contain a lowercase word, i.e. be prose rather than a name.
    """
    assert _read(f"Sarah Chen from {EMPLOYER} - Talent Acquisition Specialist") is None


def test_a_person_is_not_an_employer() -> None:
    """`_valid_company_token` cannot tell a surname from a company."""
    assert _read(f"Referral from John Smith - {ROLE}") is None


def test_a_place_is_not_an_employer() -> None:
    assert _read("Working from Home - Software Engineer, Best Practices") is None


def test_a_trailing_segment_that_is_not_a_role_reads_nothing() -> None:
    """The control the issue asks for: no head noun, no capture."""
    assert _read(f"Thank you from {EMPLOYER} - {CANDIDATE} - Application Received") is None


def test_two_role_shaped_segments_refuse_rather_than_choose() -> None:
    """If two segments look like titles the reader cannot say which job it is."""
    assert _read(f"Thank you from {EMPLOYER} - Systems Engineer - {ROLE}") is None


def test_a_parenthetical_on_the_role_refuses() -> None:
    """Matching `_role_from_trailing_segment`, and for its surviving reason.

    `normalize_role_token` deletes the brackets and KEEPS the words, so
    "<Role>, Platform (Boston)" and "<Role>, Platform" are two tokens for one
    job. Place names are an open set no vocabulary closes, so this is
    structural: any parenthetical, not a listed one.

    It costs the cohort parenthetical — a real title of the form
    "Software Engineer I (Graduation Date: ...)" now reads as nothing and the
    row goes to the queue. Recall not gained rather than recall lost: every
    subject of this shape read nothing at all before this reader existed.
    """
    assert _read(f"Thank you from {EMPLOYER} - {CANDIDATE} - {ROLE}, Platform (Boston)") is None


def test_a_work_arrangement_after_the_head_noun_refuses() -> None:
    assert _read(f"Thank you from {EMPLOYER} - {CANDIDATE} - {ROLE}, Remote") is None


def test_the_pipe_readers_keep_their_shape() -> None:
    """Disjoint by construction, not by ordering.

    This reader's first refusal is a pipe, so a subject either of the other two
    answers can never reach it. Asserted with the Greenhouse shape #553 reads,
    which must come back unchanged.
    """
    greenhouse = f"{EMPLOYER} Follow-Up for {ROLE} | {CANDIDATE}"
    assert _read(greenhouse) == ROLE
    assert pipeline._role_from_dash_run(greenhouse) is None


# ---------------------------------------------------------------- residuals

def test_a_name_that_looks_like_a_title_is_the_known_residual() -> None:
    """PINNED, NOT FIXED, and deliberately visible.

    "Priya Lead" in the last segment reads as a role because "lead" is a title
    head noun. Nothing in a subject separates a person whose surname is an
    occupation from a job title, and no guard here can. Asserted so the
    limitation is a line in the suite rather than something a future reader
    discovers from a card named after somebody.
    """
    assert _read(f"Thank you from {EMPLOYER} - {CANDIDATE} - Priya Lead") == "Priya Lead"


def test_a_lifecycle_stem_in_the_region_refuses_a_real_title() -> None:
    """The shared guard's cost, recorded rather than worked around.

    "Software Engineer, Early Career" is a real title and three corpus cases
    carry it; `_LIFECYCLE_IN_REGION` matches the stem "Career" and refuses.
    That refusal belongs to the shared guard set both other readers use, not to
    this rule, and widening it would need its own measurement across all three.
    """
    assert _read(f"Thank you from {EMPLOYER} - {CANDIDATE} - Software Engineer, Early Career") is None


# ---------------------------------------------------------------- the corpus

@pytest.mark.parametrize(
    "subject,expected",
    [
        (f"Thank you from {EMPLOYER} - {CANDIDATE} - {ROLE}", ROLE),
        (f"Thank you from {EMPLOYER} - {ROLE} - {CANDIDATE}", None),
    ],
)
def test_the_pair_that_differs_only_in_order(subject: str, expected: str | None) -> None:
    """Both halves in one parametrization so neither can be deleted alone.

    A refusal test on its own passes against a reader that refuses everything;
    a resolve test on its own passes against one that captures anything. The
    pair is the assertion.
    """
    assert _read(subject) == expected
