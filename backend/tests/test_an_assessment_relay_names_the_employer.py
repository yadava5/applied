"""Issue #687 — an assessment invite filed under the assessment platform.

Two cards on the owner's board, same employer, filed apart:

    id 246   **Coderbyte**   ASSESSMENT   do-not-reply@coderbyte.example
             "Netic AI invites you to take an assessment"
    id 248   Netic           APPLIED      no-reply@ashbyhq.example
             "Thanks for your interest in joining Netic!"

EVERY ADDRESS BELOW CARRIES A RESERVED TLD, which is the test-data policy and
is also free of cost here: the resolver reads the registrable BRAND label
(``_domain_brand``), and ``coderbyte.example`` yields ``coderbyte`` exactly as
the real host does. The wording, the subjects and the display names are the real
ones; only the TLDs are invented. The corpus already writes vendor senders this
way (``no-reply@hackerrank.example``, ``tests/corpus/mail.py``).

Card 246 is Netic AI's assessment. The board instead showed an application at a
company the owner never applied to, while the real one sat on a separate card
that never advanced past APPLIED.

TWO DEFECTS, AND EITHER ONE ALONE LEAVES THE BUG. ``ATS_RELAY_DOMAINS`` had 62
members and not one assessment vendor, so ``coderbyte`` was taken as the
employer straight off the sender domain. But adding it to the relay set on its
own still answers ``coderbyte``: the subject puts the employer in LEAD position
— the grammatical subject of "invites you" — and every employer pattern in the
module reads the employer as the OBJECT of a preposition, so the subject matched
nothing and the resolver fell through to the sender display name, which is the
vendor's. Both halves are asserted below, and each has a mutation that reds only
its own assertions.

THE FENCES ARE WHAT MAKE THE SECOND HALF SAFE, and #535 is the record of what
their absence costs: a leading-capitals rule minted companies named "Invitation",
"Decision", "Sorry" and "Sarah Chen", every one of them above ``AUTO_FILE_GATE``
and so filed without a human seeing it. The reading here fires only when the
sentence is an invitation to an assessment, only for mail an ASSESSMENT VENDOR
relayed, and never when the capture names the vendor that sent it.

THE VENDOR FENCE IS NARROWER THAN "A RELAY" AND THAT IS THE WHOLE OF IT. A draft
of this fix fenced the reading to every platform relay — ATS and job board as
well as assessment vendor — on the argument that all of them front one employer
per message. Measured, that filed a RECRUITER as a company: through Greenhouse,
with no display name at all, "Sarah Chen invites you to a technical screening"
and four more wordings resolved ('sarah', 'Sarah Chen'). Those classify at
0.90-0.95, above ``AUTO_FILE_GATE``, so ``_qualifies_for_hard_row`` files them
without a human in the loop — #535 exactly, through a door #535 never had.
``test_an_ats_relay_never_reads_a_recruiters_name_as_the_employer`` is that
class, and it fails if the fence is ever widened back.

WHAT THIS DOES NOT DO. It does not touch the two live rows: a code fix does not
reach already-ingested mail, and repairing them is a separate owner-approved data
operation. Nor does it census the board for other cards filed at a vendor — that
needs a production query, which is out of bounds here.
"""

from __future__ import annotations

import re
import time

import pytest

from jobtracker.cloud import pipeline as p

# The message as stored (issue #687, cross-checked against Gmail:
# 2026-08-31T00:33:34Z). Subject, display name and body wording are the row's;
# the sender's TLD is reserved per the note above.
REPORTED_SENDER = "do-not-reply@coderbyte.example"
REPORTED_SUBJECT = "Netic AI invites you to take an assessment"
REPORTED_NAME = "Coderbyte"
REPORTED_BODY = (
    "Hi Ayush,\n\nYou have been invited by Netic AI to complete an assessment. "
    "Please use the link below to begin; it expires in 7 days.\n"
)

# Roblox sends its OWN assessments, so the platform and the employer are the same
# company and ``roblox`` is the right answer. The subject is the one already in
# the tree (test_application_identity.py, test_rules_classifier_assessment.py)
# rather than invented for this file; the sender is that file's, with the TLD
# reserved — the ``email.`` subdomain is kept because it is what makes this a
# brand-under-a-subdomain case, which is the part that could break.
ROBLOX_SENDER = "assessment@email.roblox.example"
ROBLOX_SUBJECT = "[Action Required] Your Roblox Assessments Invitation"

# An ATS relay and a scheduling relay: mail that fronts one employer, and whose
# subjects routinely carry a RECRUITER'S name. These are the senders the
# invitation reading must NOT be enabled for.
ATS_SENDER = "no-reply@us.greenhouse-mail.example"
SCHEDULING_SENDER = "no-reply@goodtime.example"

# The vendor senders the reading IS enabled for.
VENDOR_SENDER = "do-not-reply@coderbyte.example"


def test_the_reported_message_names_the_employer_and_not_the_platform() -> None:
    """#687 itself, at the two entry points that decide where a card goes.

    ``resolve_employer`` is the filing grade one — whatever it returns becomes a
    card — and ``company_key`` is what groups follow-ups and what the client
    relay path stores. Before this change both answered ``coderbyte``.
    """

    assert p.resolve_employer(REPORTED_SENDER, REPORTED_SUBJECT, REPORTED_NAME) == (
        "netic",
        "Netic AI",
    )
    assert p.company_key(REPORTED_SENDER, REPORTED_SUBJECT, REPORTED_NAME) == "netic ai"


def test_the_employer_read_here_converges_on_the_card_that_already_exists() -> None:
    """The issue's "what is NOT broken" clause, asserted rather than assumed.

    Card 248 is stored as "Netic". If the two readings did not match it, fixing
    the extraction would mint a THIRD card instead of merging the assessment
    onto the application — so the convergence is part of the fix, not a
    coincidence of it.
    """

    token, _ = p.resolve_employer(REPORTED_SENDER, REPORTED_SUBJECT, REPORTED_NAME)
    assert p.matches_company_token("Netic", token)
    assert p.matches_company_token(
        "Netic", p.company_key(REPORTED_SENDER, REPORTED_SUBJECT, REPORTED_NAME)
    )


def test_every_assessment_relay_on_the_list_is_covered() -> None:
    """One case per member of ``ASSESSMENT_RELAY_DOMAINS``, not one from it.

    Copied from ``test_relayed_follow_up_is_not_your_own.py``'s treatment of
    ``ATS_DOMAINS`` and for its reason: a clause proven on Coderbyte alone is
    proven on a fourteenth of the population, and iterating means a vendor added
    later arrives with this coverage rather than without it.

    Both directions are asserted per member — the employer IS read, and the
    vendor's own brand is NOT the answer — because a rule that resolved nothing
    would satisfy the second on its own.
    """

    assert len(p.ASSESSMENT_RELAY_DOMAINS) >= 14, "the list shrank; check what was removed"

    for domain in sorted(p.ASSESSMENT_RELAY_DOMAINS):
        sender = f"no-reply@{domain}.example"
        subject = "Northwind Labs invites you to take an assessment"
        resolved = p.resolve_employer(sender, subject, domain.title())
        assert resolved == ("northwind", "Northwind Labs"), domain
        assert p.company_key(sender, subject, domain.title()) == "northwind labs", domain
        assert domain in p.RELAY_DOMAINS, domain


def test_no_assessment_vendor_is_short_enough_to_be_refused_as_an_employer() -> None:
    """The invariant that keeps this set clear of #508's short-name trap.

    ``_names_the_relay`` refuses a candidate under four characters purely for
    being in the relay vocabulary, whatever carried the message — that is what
    stops "Gem" resolving as an employer through Ashby. Every member here is
    five characters or more, so no member can be refused that way, and a real
    application to one of them reached through a DIFFERENT relay still files.
    A three-letter vendor added later breaks that and this says so.
    """

    assert min(len(d) for d in p.ASSESSMENT_RELAY_DOMAINS) >= 4
    assert p._names_the_relay("karat", "us.greenhouse-mail") is False


def test_roblox_sends_its_own_assessments_and_still_files_as_roblox() -> None:
    """The regression this change is most likely to cause, pinned.

    Measured on the live board: Roblox assessment mail files as "Roblox" and
    that is CORRECT — Roblox is the employer AND the platform. The set must
    never grow into a company that mails its own candidates, so membership is
    asserted as well as the answer.
    """

    assert "roblox" not in p.RELAY_DOMAINS
    for subject in (
        ROBLOX_SUBJECT,
        "Your Roblox assessment",
        "Roblox invites you to take an assessment",
    ):
        assert p.resolve_employer(ROBLOX_SENDER, subject, "Roblox") == (
            "roblox",
            "Roblox",
        ), subject
        assert p.company_key(ROBLOX_SENDER, subject, "Roblox") == "roblox", subject


def test_a_platform_that_is_also_an_employer_can_still_be_applied_to() -> None:
    """#508's direction: someone really can apply to Coderbyte or HireVue.

    Every path a genuine application to one of these companies arrives by, and
    the one it no longer arrives by. The last case is a LOSS and is asserted as
    one rather than left for someone to discover: adding a brand to
    ``RELAY_DOMAINS`` means its own domain no longer names it, so a bare subject
    off that domain resolves to nothing and goes to the review queue. That is
    exactly how the set already treats Handshake — a Handshake-relayed message
    naming Handshake is refused, and ``_names_the_relay``'s comment calls that
    case its control — so this is the existing bargain applied to one more
    platform, not a new one.
    """

    # Its own domain, subject naming it: `_employer_from_subject` carries no
    # relay fence, so the ATS confirmation shape still reads the employer.
    assert p.resolve_employer(
        "careers@coderbyte.example", "Thank you for applying to Coderbyte", "Coderbyte"
    ) == ("coderbyte", "Coderbyte")
    assert p.resolve_employer(
        "no-reply@hirevue.example", "Thanks for your interest in HireVue!", "HireVue"
    ) == ("hirevue", "HireVue")

    # Through a DIFFERENT relay, named in the subject...
    assert p.resolve_employer(
        "no-reply@ashbyhq.example", "Your application to Coderbyte", "Coderbyte"
    ) == ("coderbyte", "Coderbyte")

    # ...named in the display name (this is the path #508 was filed about, and
    # the ">= 4 characters" invariant above is why the vocabulary cannot eat it)...
    assert p.resolve_employer(
        "no-reply@us.greenhouse-mail.example", "Application Received", "Karat Recruiting Team"
    ) == ("karat", "Karat")

    # ...and in the subject's leading segment.
    assert p.resolve_employer(
        "no-reply@us.greenhouse-mail.example", "HackerRank | Application Received", "no-reply"
    ) == ("hackerrank", "HackerRank")

    # THE COST, AND IT IS A CLASS RATHER THAN ONE SUBJECT SHAPE. Every subject
    # from the vendor's own domain that does not name the vendor as the object of
    # "applying to" / "interest in" now resolves to nothing. That includes the
    # LEADING-SEGMENT shape, which reads for every ATS: step 4 of
    # `resolve_employer` stays `if brand in ATS_RELAY_DOMAINS`, so
    # "Coderbyte | Application Received" off coderbyte's own domain is refused
    # where "Crusoe | Application Received" off Greenhouse is not.
    #
    # The bargain is the one the set already makes with Handshake — a
    # Handshake-relayed message naming Handshake is refused, and
    # `_names_the_relay`'s comment calls that case its control — but the SIZE of
    # it is stated here rather than left at one example.
    for subject in (
        "Application Received",
        "Coderbyte | Application Received",
        "Your application has been received",
        "Update on your application",
        "Next steps",
        "Coderbyte - interview scheduled",
    ):
        assert (
            p.resolve_employer("careers@coderbyte.example", subject, "Coderbyte Careers") is None
        ), subject


def test_an_ats_relay_never_reads_a_recruiters_name_as_the_employer() -> None:
    """THE FENCE, and the class a wider one filed as companies.

    Every subject here reaches ``_employer_from_subject`` and satisfies
    ``_EMPLOYER_INVITES`` completely — capture, verb, object noun, boundary. The
    only thing refusing them is that the sender is an ATS or a scheduling relay
    rather than an assessment vendor. Measured with the fence at
    ``ATS | ASSESSMENT``, every one of them resolved a PERSON:

        "Sarah Chen invites you to a technical screening"    ('sarah','Sarah Chen')
        "…to complete a take-home exercise"                  ('sarah','Sarah Chen')
        "…to take a test"                                    ('sarah','Sarah Chen')
        "…to complete a challenge"                           ('sarah','Sarah Chen')
        "Michael Rodriguez invites you to a phone screening" ('michael','Michael Rodriguez')

    ``sender_name=None`` throughout, deliberately: there is no display name to
    blame and no step-3 path to attribute it to. On the base commit all of these
    return None and go to the review queue, and they classify at 0.90-0.95 —
    above ``AUTO_FILE_GATE`` — so a resolved employer means a board card named
    after a recruiter that nobody approved.
    """

    for sender in (ATS_SENDER, SCHEDULING_SENDER):
        for subject in (
            "Sarah Chen invites you to a technical screening",
            "Sarah Chen invites you to complete a take-home exercise",
            "Sarah Chen invites you to take a test",
            "Sarah Chen invites you to complete a challenge",
            "Michael Rodriguez invites you to a phone screening",
            "Sarah Chen invites you to take an assessment",
        ):
            assert p.resolve_employer(sender, subject, None) is None, (sender, subject)
            assert not p.company_key(sender, subject, None).startswith(
                ("sarah", "michael")
            ), (sender, subject)

    # THE CONTROL, so this cannot be satisfied by a resolver that refuses
    # everything: the identical grammar, off a VENDOR, still reads the employer.
    assert p.resolve_employer(
        VENDOR_SENDER, "Northwind Labs invites you to a technical screening", None
    ) == ("northwind", "Northwind Labs")


def test_the_invitation_reading_refuses_a_non_assessment_invitation() -> None:
    """The object fence, off a vendor, where nothing else is refusing.

    THE SENDER IS A VENDOR ON PURPOSE. An earlier version of this test ran
    #535's own subject list through Greenhouse, and five of its seven rows were
    inert: "Invitation to interview | Acme", "Decision on your application |
    Acme", "Sorry for the delay…", "Congratulations Ayush…" and "Reminder:
    Complete your assessment | HackerRank" contain no "invites/invited you" at
    all, so they return None whatever this pattern does. That is precisely the
    critique #535 levelled at the test written for IT — "15 of the 18 already
    returned None" — reproduced in the fix for it. They are kept below, in the
    second block, labelled as what they are: they belong to the lead-segment
    rule, not to this one.
    """

    # (1) LIVE ROWS. These satisfy the capture, the verb and the boundary; only
    # the object noun is refusing them, so each one moves if that fence goes.
    for subject in (
        "Sarah Chen invites you to a coffee chat",
        "Sarah Chen invites you to connect on LinkedIn",
        "Northwind Labs invites you to our webinar",
        "Northwind Labs invites you to complete a survey",
        "Northwind Labs invites you to a product demo",
        "Northwind Labs invites you to our newsletter",
        "Northwind Labs invites you to a meetup",
    ):
        assert p.resolve_employer(VENDOR_SENDER, subject, None) is None, subject

    # (2) #535's own subjects, which this rule cannot see at all. Asserted as
    # regression cover for the lead-segment rule, and NOT as evidence about the
    # invitation reading — they carry no invitation verb, and the assertion
    # beside each one says so rather than letting a later reader assume it.
    for subject in (
        "Invitation to interview | Acme",
        "Decision on your application | Acme",
        "Sorry for the delay in getting back to you | Acme",
        "Congratulations Ayush on your application | Acme",
        "Reminder: Complete your assessment | HackerRank",
    ):
        assert p.resolve_employer(VENDOR_SENDER, subject, None) is None, subject
        assert re.search(r"invit(?:es|ed)\s+you", subject, re.IGNORECASE) is None, (
            f"{subject!r} now carries the invitation VERB, so it is no longer "
            "inert here and belongs in block (1) with the rest of the live rows. "
            "(The noun 'Invitation' is not the verb and does not reach this rule.)"
        )


def test_every_invitation_object_noun_is_covered() -> None:
    """One case per member of ``_INVITATION_OBJECT``, both directions.

    The domain set gets this treatment and the noun set did not, which left
    ``exercises?``, ``tests?`` and ``challenges?`` carried by no assertion at
    all — three of five members, free to be deleted or misspelled in silence.
    Singular and plural are both exercised because the pattern spells the plural
    with ``s?`` and a member could lose it without any other case noticing.

    The refusals are the other half: a noun that is NOT on the list must not
    resolve, or the fence is "any invitation" and "…invites you to our webinar"
    becomes an employer.
    """

    for noun in ("assessment", "test", "challenge", "screening", "exercise"):
        for spelling in (noun, noun + "s"):
            subject = f"Northwind Labs invites you to complete a {spelling}"
            assert p.resolve_employer(VENDOR_SENDER, subject, None) == (
                "northwind",
                "Northwind Labs",
            ), spelling

    for noun in ("webinar", "newsletter", "survey", "meetup", "demo", "interview"):
        subject = f"Northwind Labs invites you to a {noun}"
        assert p.resolve_employer(VENDOR_SENDER, subject, None) is None, noun


def test_an_interview_invitation_is_not_read_as_an_employer() -> None:
    """"interview" is off the object list, and this is why.

    An interview is the one thing on that list a PERSON invites you to in their
    own name — and two of the fourteen vendors the reading IS fenced to, Karat
    and HireVue, sell exactly that, so the vendor fence does not cover it.
    Measured with "interviews?" in the set, the first three shapes below resolved
    ('sarah', 'Sarah Chen'). The fourth resolved ('acme', 'Acme') — correctly,
    which is why it is the COST of the removal and not a fifth defect.

    The control at the end is what stops this being satisfiable by refusing
    everything: the same grammar with an assessment object still reads.
    """

    for subject in (
        "Sarah Chen invites you to interview",
        "Sarah Chen invites you to an interview next week",
        "Sarah Chen invites you to schedule an interview",
        # The cost, asserted as a cost: a genuine employer using the vendor's own
        # word for its assessment reads nothing and goes to the review queue.
        "Acme invites you to complete an on-demand interview",
    ):
        assert p.resolve_employer("scheduling@karat.example", subject, None) is None, subject

    assert p.resolve_employer(
        "scheduling@karat.example",
        "Northwind Labs invites you to complete a technical screening",
        None,
    ) == ("northwind", "Northwind Labs")


def test_the_invitation_verb_reads_both_tenses_and_the_auxiliary() -> None:
    """``invit(?:es|ed)`` and the optional ``has``/``have``, one case each.

    Written as four branches in one alternation and covered by one wording, so
    three of them were free to be deleted in silence. Real invitation mail uses
    all four.
    """

    for verb in (
        "invites you to take an assessment",
        "invited you to take an assessment",
        "has invited you to take an assessment",
        "have invited you to take an assessment",
    ):
        assert p.resolve_employer(VENDOR_SENDER, f"Netic AI {verb}", REPORTED_NAME) == (
            "netic",
            "Netic AI",
        ), verb

    # The control: a verb that is not an invitation names nobody.
    assert (
        p.resolve_employer(VENDOR_SENDER, "Netic AI expects you to take an assessment", None)
        is None
    )


def test_every_boundary_character_is_load_bearing() -> None:
    """One case per member of the boundary class, plus the refusal it exists for.

    The prefix is LOWERCASE on purpose. Behind a Title-Case word the capture can
    swallow "." and "-" itself (``_COMPANY_CAPTURE`` admits both inside a token),
    so a Title-Case probe would pass for two members without the class containing
    them at all — the class would be wider than anything under test. A lowercase
    prefix cannot start a capture, so each character below is the only thing
    letting the match begin.
    """

    for char in "|:;,.!?])>\u2013\u2014-":
        subject = f"your invitation{char} Netic AI invites you to take an assessment"
        assert p.resolve_employer(VENDOR_SENDER, subject, REPORTED_NAME) == (
            "netic",
            "Netic AI",
        ), char

    # The refusal the class exists for: no boundary, no match. Without this the
    # test above is satisfied by a pattern with no boundary requirement at all.
    assert (
        p.resolve_employer(
            VENDOR_SENDER, "your invitation Netic AI invites you to take an assessment", None
        )
        is None
    )


def test_the_gap_between_the_verb_and_the_object_is_bounded() -> None:
    """``[^\n]{0,40}?`` measured at the bound, not asserted as a constant.

    38 characters of filler puts the gap at exactly 40 and reads; 39 puts it at
    41 and reads nothing. That is a threshold with a case sitting ON it, which is
    what makes widening the bound to 400 — or dropping it entirely — a change
    this file can see. The linearity test beside it could not: measured, an
    unbounded gap ran in 0.26 ms against a 50 ms budget, so every mutation of the
    bound passed it.
    """

    def _subject(filler_len: int) -> str:
        return f"Netic AI invites you {'x' * filler_len} assessment"

    assert p.resolve_employer(VENDOR_SENDER, _subject(38), REPORTED_NAME) == (
        "netic",
        "Netic AI",
    )
    assert p.resolve_employer(VENDOR_SENDER, _subject(39), REPORTED_NAME) is None


def test_a_prefix_before_the_employer_is_read_through() -> None:
    """The boundary fence, on the prefixes real subjects actually carry.

    Fence 3 is what keeps an ordinary Title-Case opener out of the capture, and
    it is only worth having if it still reads the employer behind a bracket, a
    colon or a comma — which is how every observed prefix is punctuated.
    """

    for subject in (
        "[Action Required] Netic AI invites you to take an assessment",
        "Action Required: Netic AI invites you to take an assessment",
        "Reminder: Netic AI invites you to take an assessment",
        "Hi Ayush, Netic AI invites you to take an assessment",
    ):
        assert p.resolve_employer(REPORTED_SENDER, subject, REPORTED_NAME) == (
            "netic",
            "Netic AI",
        ), subject


def test_a_vendor_that_names_itself_names_the_courier() -> None:
    """The fourth fence: the capture must not be the relay that sent the mail.

    An assessment vendor writes its own name into the sentence-subject position
    constantly — it is its own product mail. Without this the fix would swap one
    wrong employer for the same wrong employer by a longer route.
    """

    for domain, display in (
        ("coderbyte", "Coderbyte"),
        ("hackerrank", "HackerRank"),
        ("hirevue", "HireVue"),
        ("codesignal", "CodeSignal"),
    ):
        subject = f"{display} invites you to take an assessment"
        assert p.resolve_employer(f"do-not-reply@{domain}.example", subject, display) is None, domain


def test_the_grouping_key_carries_the_same_fence_as_the_resolver() -> None:
    """``company_key`` is the second entry point and gets the identical fence.

    Both callers pass ``brand in ASSESSMENT_RELAY_DOMAINS``; neither re-derives
    it. Calling ``_company_from_subject`` with the flag forced ON shows what the
    fence is holding back — the person's name — so a reader can see the fence is
    what refuses this and not some later guard, and a mutation that swaps the set
    at either call site reds here.
    """

    subject = "Sarah Chen invites you to take an assessment"

    for sender, expected_key in (
        ("sarah.chen@gmail.example", "gmail"),  # consumer webmail: a name is a PERSON
        (ATS_SENDER, "greenhouse-mail"),  # an ATS: a name is a RECRUITER
        (SCHEDULING_SENDER, "goodtime"),
    ):
        assert p.resolve_employer(sender, subject, None) is None, sender
        assert p.company_key(sender, subject, None) == expected_key, sender

    assert p._company_from_subject(subject, assessment_relay=True) == "sarah chen"
    assert p._company_from_subject(subject) == ""

    # ...and the direction that must still work.
    assert p.company_key(VENDOR_SENDER, REPORTED_SUBJECT, REPORTED_NAME) == "netic ai"


def test_the_body_names_the_employer_at_display_grade() -> None:
    """The other half of the reported message: "invited by <Employer>".

    DISPLAY GRADE ONLY, and stated plainly: this does NOT fix card 246. The
    relay set and the subject reading do all of that work. What this adds is a
    review-queue row that names the employer instead of one that says we could
    not, for the invites whose subject names nobody — and it is fenced exactly
    like the body pattern beside it, refusing a capture that names the sender.
    """

    assert p.employer_named_in_body(REPORTED_BODY, REPORTED_SENDER) == ("netic", "Netic AI")

    # The vendor naming itself, refused by the same relay check.
    assert (
        p.employer_named_in_body(
            "You have been invited by Coderbyte to complete an assessment.", REPORTED_SENDER
        )
        is None
    )
    # An invitation to something that is not an assessment names nothing.
    assert (
        p.employer_named_in_body(
            "You have been invited by Northwind Labs to our summer barbecue.",
            "no-reply@us.greenhouse-mail.example",
        )
        is None
    )
    # The pattern this was added beside still answers what it answered.
    assert p.employer_named_in_body(
        "Thank you so much for your interest in Northwind Labs. After careful review...",
        "no-reply@us.greenhouse-mail.example",
    ) == ("northwind", "Northwind Labs")


def test_the_body_reader_refuses_a_vendor_name_when_no_relay_sent_it() -> None:
    """The consumer of ``RELAY_DOMAINS`` that adding to the set also moves.

    ``employer_named_in_body`` passes ``brand if brand in RELAY_DOMAINS else ""``
    to ``_names_the_relay``, whose no-brand branch falls back to the VOCABULARY.
    So growing the vocabulary by fourteen names changes this function too, and
    the change is a REFUSAL:

        "…your interest in Karat", from a corporate domain
            before  ('karat', 'Karat')
            after    None

    That is not an oversight; it is the decision, and it is asserted in both
    directions so it cannot drift back silently. It is kept because on that path
    the vocabulary is the only signal there is and the population is real — "you
    have been invited by HackerRank to complete an assessment", sent from an
    employer's own domain, names the COURIER. It costs a queue row with no
    suggested name where there used to be a correct one, and this function is
    display grade, so it cannot cost a card.
    """

    for vendor in ("Karat", "HireVue", "Woven", "Coderbyte", "Mettl"):
        body = f"Thank you for your interest in {vendor}. After careful review..."

        # No relay sent it, so the vocabulary decides — and now refuses.
        assert p.employer_named_in_body(body, "talent@northwindlabs.example") is None, vendor

        # Through a relay a BRAND is known, the precise question gets asked, and
        # #508's direction is intact: a vendor named through a different courier
        # is an employer.
        assert p.employer_named_in_body(body, "no-reply@ashbyhq.example") == (
            vendor.lower(),
            vendor,
        ), vendor

    # The control: a name that is on no list is unaffected on either path.
    plain = "Thank you for your interest in Northwind Labs. After careful review..."
    assert p.employer_named_in_body(plain, "talent@northwindlabs.example") == (
        "northwind",
        "Northwind Labs",
    )


@pytest.mark.parametrize(
    ("sender", "subject", "name", "expected"),
    [
        ("no-reply@ashbyhq.example", "Your application to Stripe", "Ashby", ("stripe", "Stripe")),
        (
            "no-reply@us.greenhouse-mail.example",
            "Thank you for applying to Together AI",
            "Greenhouse",
            ("together", "Together AI"),
        ),
        (
            "no-reply@ashbyhq.example",
            "Systems Research Engineer, GPU Programming @ Together AI",
            "Ashby",
            ("together", "Together AI"),
        ),
        ("no-reply@ashbyhq.example", "Crusoe | Application Received", "no-reply", ("crusoe", "Crusoe")),
        (
            "no-reply@ashbyhq.example",
            "Update on Backend Engineer with Handshake",
            "Handshake Recruiting Team",
            ("handshake", "Handshake"),
        ),
    ],
)
def test_the_existing_subject_readings_are_untouched(
    sender: str, subject: str, name: str, expected: tuple[str, str]
) -> None:
    """Regression cover for the rules this change sits beside — and NOT for the
    ordering claim, which is the test below.

    THESE SENDERS CANNOT REACH THE NEW PATTERN. ``ashbyhq`` and
    ``greenhouse-mail`` are ATS relays, so ``_employer_from_subject`` never puts
    ``_EMPLOYER_INVITES`` in the tuple for them and no ordering is exercised
    here at all. That is worth saying in place rather than leaving to be
    rediscovered: this file's first draft made exactly this claim with exactly
    these senders while the fence was ``ATS | ASSESSMENT``, and NARROWING the
    fence to assessment vendors stranded the test without touching it. A
    reorder mutation reddened nothing. The next person to narrow a fence will
    strand a test the same way, so the rule is: a test named for a code path has
    to be re-checked against the fence that path sits behind.
    """

    assert p.resolve_employer(sender, subject, name) == expected


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        # `_EMPLOYER_INTEREST_IN` — the invitation reading would say Netic AI.
        (
            "Thanks for your interest in Acme Corp - Netic AI invites you to take an assessment",
            ("acme", "Acme"),
        ),
        # `_EMPLOYER_ANCHORED` — the invitation reading would say Stripe.
        (
            "Stripe invites you to take an assessment for your application to Netic AI",
            ("netic", "Netic AI"),
        ),
        # `_EMPLOYER_ON_BEHALF` — the invitation reading would say Netic AI.
        (
            "Netic AI invites you to take an assessment on behalf of Acme Corp",
            ("acme", "Acme"),
        ),
        # `_EMPLOYER_BARE_AT` — the invitation reading would say Northwind Labs.
        (
            "Northwind Labs invites you to take an assessment at Stripe",
            ("stripe", "Stripe"),
        ),
    ],
)
def test_the_invitation_reading_is_tried_last(
    subject: str, expected: tuple[str, str]
) -> None:
    """"Purely additive" is a claim about ORDER, and this is where it is tested.

    Every subject satisfies ``_EMPLOYER_INVITES`` AND one older pattern, and the
    two disagree — so the answer is decided by which runs first and nothing
    else. Measured, moving the new pattern from last to first changes three of
    these four; asserting the older pattern's answer is what makes that
    reordering a red.

    THE SENDER IS A VENDOR, deliberately. It is the only kind of sender that
    reaches this pattern at all, so any sender that does not cross that fence
    asserts nothing about ordering however carefully the subject is built (see
    the test above).

    ``_EMPLOYER_AT_SIGN`` is absent from this list because it cannot be
    exercised here: it is prepended only for ATS relays, so off a vendor it is
    not in the tuple. Its ordering against ``_EMPLOYER_ANCHORED`` is #325's and
    is covered in ``test_cloud_pipeline.py``.
    """

    assert p.resolve_employer(VENDOR_SENDER, subject, REPORTED_NAME) == expected


def test_the_object_noun_is_matched_on_word_boundaries() -> None:
    """``\b`` on BOTH sides of the object noun, one case per side.

    Without the leading one, "assessment" matches inside "reassessment", "test"
    inside "pretest" and "contest", and an ordinary sentence becomes an
    invitation to an assessment round. Without the trailing one,
    "assessmentathon" does the same. Both were survivors: nothing in the file
    distinguished ``\bassessments?\b`` from ``assessments?``.

    NOT COVERED, AND THE DISAGREEMENT IS REAL RATHER THAN A GAP IN THIS TEST:
    "a self-assessment" DOES resolve here, because "self-assessment" contains a
    word boundary in front of "assessment". ``classifier/rules.py`` explicitly
    vetoes ``\bself[- ]assessments?\b`` for ASSESSMENT, so the two lists
    disagree about that phrase — the classifier says it is not an assessment and
    this reader says the sentence names an employer. A leading ``\b`` cannot
    close it; excluding it needs a lookbehind and a decision about what a
    self-assessment invitation means, which is not this change's to make. Stated
    here rather than pinned, because asserting today's answer would freeze a
    behaviour nobody has chosen.
    """

    for subject in (
        "Netic AI invites you to a reassessment of your file",
        "Netic AI invites you to review the pretest results",
        "Netic AI invites you to enter a contest",
        "Netic AI invites you to an assessmentathon",
    ):
        assert p.resolve_employer(VENDOR_SENDER, subject, REPORTED_NAME) is None, subject

    # The control: the same sentence with the noun standing on its own.
    assert p.resolve_employer(
        VENDOR_SENDER, "Netic AI invites you to an assessment of your skills", REPORTED_NAME
    ) == ("netic", "Netic AI")


def test_the_body_reader_accepts_every_auxiliary_and_refuses_a_future_one() -> None:
    """One case per branch of the body pattern's auxiliary, plus the refusal.

    Four branches — ``have been``, ``has been``, ``were``, ``are`` — carried by
    a single wording, so three of them could be deleted in silence; measured,
    narrowing the alternation to ``have been`` alone reddened nothing.

    The refusal is the other half and it is not cosmetic. A FUTURE invitation is
    not an invitation: "you will be invited by <Employer> once the team has
    reviewed your application" names an employer in a message that is not an
    assessment invite, and widening the alternation to admit it was also a
    survivor.
    """

    for aux in ("have been", "has been", "were", "are"):
        body = f"Hi Alex, You {aux} invited by Netic AI to complete an assessment."
        assert p.employer_named_in_body(body, VENDOR_SENDER) == ("netic", "Netic AI"), aux

    for aux in ("will be", "would be", "shall be"):
        body = f"Hi Alex, You {aux} invited by Netic AI to complete an assessment."
        assert p.employer_named_in_body(body, VENDOR_SENDER) is None, aux


def test_the_body_reader_tries_the_interest_in_sentence_first() -> None:
    """The body loop's ORDER, on a message where the two patterns disagree.

    Same claim as ``test_the_invitation_reading_is_tried_last`` and it needs the
    same kind of case: a body carrying BOTH sentences, naming two different
    companies. The rejection preamble this function was built for keeps the
    answer it has always given, and the invitation reading only ever adds one
    where there was none. Swapping the tuple was a survivor.
    """

    both = (
        "Thank you for your interest in Acme Corp. "
        "You have been invited by Netic AI to complete an assessment."
    )
    assert p.employer_named_in_body(both, VENDOR_SENDER) == ("acme", "Acme")

    # ...and each sentence alone still answers, so the test above is about ORDER
    # rather than about one pattern having stopped working.
    assert p.employer_named_in_body(
        "Thank you for your interest in Acme Corp. We will be in touch.", VENDOR_SENDER
    ) == ("acme", "Acme")
    assert p.employer_named_in_body(
        "You have been invited by Netic AI to complete an assessment.", VENDOR_SENDER
    ) == ("netic", "Netic AI")


def test_the_body_gap_is_bounded_like_its_subject_twin() -> None:
    """``[^\n]{0,40}?`` in the BODY pattern, measured at the bound.

    The subject half got this and the body half did not, so an unbounded body
    gap was a survivor: a noun 55 characters from the verb started reading and
    no assertion moved. 38 characters of filler puts the gap at exactly 40 and
    reads; 39 puts it at 41 and reads nothing.
    """

    def _body(filler_len: int) -> str:
        return f"You have been invited by Netic AI {'x' * filler_len} assessment"

    assert p.employer_named_in_body(_body(38), VENDOR_SENDER) == ("netic", "Netic AI")
    assert p.employer_named_in_body(_body(39), VENDOR_SENDER) is None
    assert p.employer_named_in_body(_body(55), VENDOR_SENDER) is None


#: The BODY pattern with its gap left unbounded, for the control below.
_UNBOUNDED_INVITED_BY_BODY = re.compile(
    r"(?i:\byou\s+(?:have\s+been|has\s+been|were|are)\s+invited\s+by\s+)"
    r"(" + p._COMPANY_CAPTURE_SENTENCE + r")"
    r"(?i:[^\n]*?\b" + p._INVITATION_OBJECT + r"\b)"
)


def test_the_body_pattern_is_linear() -> None:
    """A BODY is longer than a subject, so the ReDoS surface is bigger, not smaller.

    The subject twin got a real payload and a control; this one had neither. A
    body made of repeated "you were invited by Acme" gives the engine one start
    position per repetition, each matching the auxiliary and the capture and
    then hunting an object noun that is not there: bounded it gives up after 40
    characters, unbounded it scans to the end. Measured at 25,000 characters,
    5 ms against 1,245 ms, and x4 on each doubling.
    """

    payload = "you were invited by Acme " * 1_000
    budget_ms = 60.0
    min_slowdown = 20.0

    start = time.perf_counter()
    p._EMPLOYER_INVITED_BY_BODY.search(payload)
    bounded_ms = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    _UNBOUNDED_INVITED_BY_BODY.search(payload)
    unbounded_ms = (time.perf_counter() - start) * 1000

    ratio = unbounded_ms / bounded_ms if bounded_ms > 0 else float("inf")
    assert ratio > min_slowdown, (
        f"the unbounded body gap was only {ratio:.0f}x the bounded one "
        f"({unbounded_ms:.2f} ms vs {bounded_ms:.3f} ms). Below {min_slowdown:.0f}x "
        "this payload can no longer tell the two apart, so the budget below would "
        "pass either way."
    )
    assert bounded_ms < budget_ms, f"{bounded_ms:.2f} ms, budget {budget_ms} ms"


#: The same pattern with the gap left UNBOUNDED — what removing ``{0,40}`` gives.
#: Built here rather than imported so the comparison below is against a real
#: alternative and not against a constant somebody can edit into agreement.
_UNBOUNDED_INVITES = re.compile(
    r"(?:^|[|:;,.!?\]\)>\u2013\u2014-])\s*"
    r"(" + p._COMPANY_CAPTURE + r")"
    r"(?i:\s+(?:has\s+|have\s+)?invit(?:es|ed)\s+you\b"
    r"[^\n]*?\b" + p._INVITATION_OBJECT + r"\b)"
)


def test_the_invitation_pattern_is_linear() -> None:
    """A subject is caller-supplied text, and this family has a ReDoS scar.

    THE PAYLOAD IS THE WHOLE TEST, and the first version of this file got it
    wrong. It timed three strings that had no punctuation in them, so only ``^``
    could ever start a match, so there was exactly ONE start position and the
    gap bound could not matter: an unbounded gap ran in 0.26 ms against a 50 ms
    budget, and mutating the bound to 400, to greedy, or away entirely reddened
    nothing. A budget assertion that cannot fail is worse than no assertion.

    A comma before every candidate gives the engine 2,000 start positions. Each
    one matches the capture and the verb and then looks for the object noun that
    is not there: bounded, it gives up after 40 characters; unbounded, it scans
    to the end of the string, which is quadratic and measurable — 3 ms against
    770 ms here, and 4x that when the payload doubles.

    The ratio is asserted for the reason ``_assert_control`` exists in
    ``test_company_name_regexes_are_linear.py``: it is what proves the budget
    below is measuring the bound rather than the machine.
    """

    payload = ",A invites you " * 2_000
    budget_ms = 50.0
    min_slowdown = 20.0

    start = time.perf_counter()
    p._EMPLOYER_INVITES.search(payload)
    bounded_ms = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    _UNBOUNDED_INVITES.search(payload)
    unbounded_ms = (time.perf_counter() - start) * 1000

    ratio = unbounded_ms / bounded_ms if bounded_ms > 0 else float("inf")
    assert ratio > min_slowdown, (
        f"the unbounded gap was only {ratio:.0f}x the bounded one "
        f"({unbounded_ms:.2f} ms vs {bounded_ms:.3f} ms). Below {min_slowdown:.0f}x "
        "this payload can no longer tell a bounded gap from an unbounded one, so "
        "the budget assertion below would pass either way — which is exactly the "
        "defect this test was rewritten to fix."
    )
    assert bounded_ms < budget_ms, f"{bounded_ms:.2f} ms, budget {budget_ms} ms"


# ---------------------------------------------------------------------------
# The set has to hold the domain the vendor actually SENDS from
# ---------------------------------------------------------------------------

#: Vendors whose real candidate-mail domain yields a brand that the set did not
#: contain. Each was verified against the vendor's own documentation and DNS,
#: not inferred from the product name — which is the whole point, because the
#: product name is what made the wrong entry look right.
#:
#: `.example` on the end keeps these un-routable for the test-data gate while
#: leaving the brand intact: `_domain_brand` reads the second-from-last label,
#: so `woventeams.example` yields `woventeams` exactly as `woventeams.com` does.
VENDOR_SENDING_BRANDS = [
    pytest.param(
        "woventeams",
        "Woven sends candidate mail from woventeams.com, evidenced by Greenhouse's "
        "own Woven integration doc and by live MX/SPF/DMARC. `woven.com` is a "
        "different entity and `woven.io` is parked, so the plain `woven` entry "
        "never matched a real message and nothing existed to notice it.",
        id="woven-sends-as-woventeams",
    ),
    pytest.param(
        "skillpanel",
        "DevSkiller renamed to SkillPanel in September 2025; devskiller.com 301s "
        "to skillpanel.com. Both remain live senders on different stacks, which "
        "is why the old brand stays too.",
        id="devskiller-is-skillpanel-now",
    ),
    pytest.param(
        "mercermettl",
        "Mettl's EU region sends from mercermettl.eu, which publishes an SPF "
        "including amazonses.com.",
        id="mettl-sends-as-mercermettl",
    ),
]


@pytest.mark.parametrize("brand,why", VENDOR_SENDING_BRANDS)
def test_the_vendors_real_sending_brand_reads_the_employer(brand: str, why: str) -> None:
    """A vendor absent from the set files a card at the vendor — #687, still live.

    Measured on the base commit, each of these resolved to the VENDOR:
    `('woventeams', 'Woventeams')`, `('skillpanel', 'Skillpanel')`,
    `('mercermettl', 'Mercermettl')`. That is the defect #687 was filed for,
    surviving for three vendors because the set was populated from product
    names rather than from sending domains.
    """

    assert brand in p.ASSESSMENT_RELAY_DOMAINS, why
    assert p.resolve_employer(
        f"noreply@{brand}.example",
        "Netic AI invites you to take an assessment",
        None,
    ) == ("netic", "Netic AI"), why


def test_mercer_is_not_in_the_relay_vocabulary() -> None:
    """The correction this audit REFUSED to make, pinned so nobody makes it.

    Mettl's Indian region sends from an `admin.mettl` mailbox on Mercer's own domain, so the brand that
    would catch it is `mercer`. Mercer is a large real employer that sends its
    own recruiting mail, and putting it in a relay set would push every genuine
    Mercer application onto the display-name and subject fallbacks — the
    person-as-employer class this module exists to fight.

    So that address is unreachable by a brand-keyed set, on purpose. Catching it
    needs a full-address exception, which is a product decision.
    """

    assert "mercer" not in p.ASSESSMENT_RELAY_DOMAINS
    assert "mercer" not in p.RELAY_DOMAINS
    assert p.resolve_employer("careers@mercer.example", "Thanks for applying", "Mercer") == (
        "mercer",
        "Mercer",
    )
