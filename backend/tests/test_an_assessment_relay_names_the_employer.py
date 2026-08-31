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
sentence is an invitation to an assessment, only for mail a PLATFORM relayed, and
never when the capture names the relay that sent it.

WHAT THIS DOES NOT DO. It does not touch the two live rows: a code fix does not
reach already-ingested mail, and repairing them is a separate owner-approved data
operation. Nor does it census the board for other cards filed at a vendor — that
needs a production query, which is out of bounds here.
"""

from __future__ import annotations

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

    # THE COST. Its own domain, subject naming nobody: was ('coderbyte',
    # 'Coderbyte'), is now None and goes to the review queue.
    assert (
        p.resolve_employer("careers@coderbyte.example", "Application Received", "Coderbyte Careers")
        is None
    )


def test_the_invitation_reading_refuses_the_shapes_535_minted() -> None:
    """The negative controls, from the issue that recorded this exact failure.

    #535's list is ordinary ATS subject lines that a loose leading-capitals rule
    turned into companies. They are run here through a PLATFORM relay, which is
    the population this reading is enabled for, so nothing about the sender is
    protecting them — the verb anchor and the assessment object are.
    """

    for subject in (
        "Invitation to interview | Acme",
        "Decision on your application | Acme",
        "Sorry for the delay in getting back to you | Acme",
        "Congratulations Ayush on your application | Acme",
        "Reminder: Complete your assessment | HackerRank",
        # An invitation whose object is not an assessment: the verb alone is not
        # enough, or every "X invites you to our webinar" becomes an employer.
        "Sarah Chen invites you to a coffee chat",
        "Sarah Chen invites you to connect on LinkedIn",
    ):
        assert (
            p.resolve_employer("no-reply@us.greenhouse-mail.example", subject, "no-reply") is None
        ), subject


def test_an_interview_invitation_is_not_read_as_an_employer() -> None:
    """The noun set carries the RIGHT members, which deletion cannot prove.

    An interview is the one thing on the object list a PERSON invites you to in
    their own name, and the scheduling tools that send those mails — GoodTime,
    ModernLoop — are already ATS relays, so the platform fence does not stand
    between them and this reading. Measured with "interviews?" in the set, all
    four shapes below resolved ('sarah', 'Sarah Chen') through Greenhouse, which
    is #535's exact tuple re-minted through a new door.

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
        assert (
            p.resolve_employer("no-reply@us.greenhouse-mail.example", subject, "no-reply") is None
        ), subject

    assert p.resolve_employer(
        "no-reply@us.greenhouse-mail.example",
        "Northwind Labs invites you to complete a technical screening",
        "no-reply",
    ) == ("northwind", "Northwind Labs")


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


def test_consumer_webmail_is_fenced_out_of_the_invitation_reading() -> None:
    """A display name — or a sentence subject — in a person's mail is a PERSON.

    The same fence steps 3 and 4 of ``resolve_employer`` already carry, applied
    to the new reading at BOTH entry points. Passing ``platform_relay=True`` by
    hand shows the fence is what refuses this and not some later guard.
    """

    sender, subject = "sarah.chen@gmail.example", "Sarah Chen invites you to take an assessment"

    assert p.resolve_employer(sender, subject, None) is None
    assert p.company_key(sender, subject, None) == "gmail"
    assert p._company_from_subject(subject, platform_relay=True) == "sarah chen"
    assert p._company_from_subject(subject) == ""


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
def test_the_reading_is_additive_and_moves_no_existing_answer(
    sender: str, subject: str, name: str, expected: tuple[str, str]
) -> None:
    """The new pattern is tried LAST, so nothing that resolved can move.

    One subject per rule that already answers — the anchored one, the
    thank-you-for-applying one, the at-sign one, the leading segment, and #508's
    Handshake row — because "purely additive" is a claim about the ORDER of the
    patterns and the order is only visible when something else matches first.
    """

    assert p.resolve_employer(sender, subject, name) == expected


def test_the_invitation_pattern_is_linear() -> None:
    """A subject is caller-supplied text, and this family has a ReDoS scar.

    Measured rather than argued, the way ``test_leading_run_is_linear`` does it:
    the capture is bounded to four words and the gap before the object noun is
    bounded to 40 characters, so a long run cannot make the engine retry more
    than a constant number of ways per start position.
    """

    blowup = 5_000
    budget_ms = 50.0

    for payload in (
        "A" + " " * blowup + "x",
        "A invites you to " + " " * blowup + "assessment",
        ("A invites you " * blowup),
    ):
        start = time.perf_counter()
        p._EMPLOYER_INVITES.search(payload)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < budget_ms, f"{elapsed_ms:.2f} ms, budget {budget_ms} ms"
