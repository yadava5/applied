"""A CONTACT-FORM AUTORESPONDER IS NOT AN APPLICATION EVENT.

Reported on the owner's real board: a company he had cold-emailed sat in the
review queue as though it were an application update. He had applied to them
separately, days earlier, and that confirmation had already filed its own card
correctly. The queue was asking him about a robot saying "thanks, we got your
message".

THE MECHANISM, reproduced before anything was changed. The mail is a reply to
HIS OWN outreach, so the client copied HIS subject onto it — and his subject
said, in the first person, that he had applied for the role. Scored:

    {applied: 2, everything else: 0}
    [STRONG-SUBJECT] applied.{0,20}(for|to).{0,40}(position|role|job)

One match, on words he wrote himself, and nothing else in the message
contributed at all. That is 0.70 — exactly ``REVIEW_FLOOR`` — so the product
queued it.

THE FIX IS ONE RULE, NOT TWO. The pattern never said WHOSE application it
meant. An employer writes "you applied for the X role"; a candidate writes
"applied for the X role". It matched both, so a first-person sentence was read
as an employer's assertion about the reader. It is anchored in the second
person now, and the pronoun has to run STRAIGHT INTO the verb — cold outreach
says "you" and "your" constantly, so mere proximity is defeated by the exact
text the anchor exists to refuse.

This is NOT the same repair as #348, which demoted
``your application for <Role> at <Company>`` OUT of ``strong``: that phrasing
is a thread subject every reply inherits and it must stay weak, which is why
``your`` is deliberately absent from the anchor. Measured before touching
either, and RE-DERIVED at the corpus's current size rather than left as the
number a smaller corpus gave: the anchored pattern matches 0 of the 18,480
independent-corpus cases (it read "0 of 17,260" when the fix shipped — the
claim survived the re-run, the number did not), and the sibling
``application.{0,20}(for|to)...`` matches 1,948 and is untouched.

A SECOND RULE WAS MEASURED AND NOT SHIPPED, AND #521 HAS NOW SETTLED IT.
"Thank you for getting in touch" acknowledges a message rather than an
application, and adding it to ``applied``'s genre filters looked obvious. When
this file was written the phrase appeared 0 times in the independent corpus, so
neither of its two risks could be weighed and the rule was deferred rather than
judged.

The corpus has the family now — ``outreach-autoresponder``, 160 messages built
both ways round — and the phrase appears 160 times in 18,480 cases. All three
placements were run per case, and the last block of tests in this file is that
measurement rather than a description of it:

    (a) not shipped   40 autoresponders sit at `applied` 0.70, in the queue
    (b) in _NOISE_NEGATIVES   0 of the 40 move; 40 genuine confirmations drop
    (c) out of it     the 40 are fixed; 55 genuine confirmations are destroyed

(b) is inert for the reason it always was — every one of those 40 carries a
strong `applied` BODY match, so ``has_strong_body`` exempts the negative in the
case it was written for. (c) works and costs more than it buys. So the rule
STAYS OUT, the defect is pinned at its size in ``RECORDED["wrong"]``, and
``rules.py`` carries the same table beside the list so it is not re-proposed as
new.

WHAT MUST NOT BREAK: the real confirmation from the same employer, and the
second-person phrasing an employer actually uses. Both are asserted below
against the same fixtures, so a fix that buys this one by breaking those cannot
pass.

Every fixture here is invented. The shape is the owner's; the words are not.
"""

from __future__ import annotations

import re

import pytest

from jobtracker.classifier import rules as rules_module
from jobtracker.classifier.rules import get_rules_classifier
from jobtracker.cloud.pipeline import AUTO_FILE_GATE, REVIEW_FLOOR
from jobtracker.database.models import EmailCategory
from tests.corpus_independent.generate import generate

#: The employer's own contact inbox — a plus-addressed no-reply, NOT an ATS.
CONTACT_INBOX = "info+noreply@haldensystems.example"
ATS = "no-reply@greenhouse.io"

#: The subject is the OWNER'S, quoted back by the reply. First person: it says
#: an application happened, and never says whose.
OUTREACH_REPLY_SUBJECT = (
    "Re: Built an agentic compiler for embedded targets, applied for the "
    "Platform Engineer role"
)

#: A canned acknowledgement of a MESSAGE. Nothing here is about an application.
CONTACT_FORM_ACK = (
    "Thank you for getting in touch with us at Halden Systems! We appreciate "
    "you taking the time to connect with our team. While we aren't always able "
    "to send an individual response to every message, please know that we read "
    "them all."
)

#: The same employer's real confirmation, which filed its own card correctly.
REAL_CONFIRMATION_SUBJECT = "Thanks for applying to Halden Systems!"
REAL_CONFIRMATION_BODY = (
    "Thanks for applying to Halden Systems! We have received your application "
    "for the Platform Engineer position and our team will review it shortly."
)

#: The phrasing an EMPLOYER uses for the same fact — second person, and it must
#: keep scoring after the anchor lands.
EMPLOYER_SECOND_PERSON = (
    "Hi Ayush, you applied for the Platform Engineer position at Halden "
    "Systems on Monday. Here is what happens next."
)

#: THE HARDER OUTREACH SHAPE, and the one that makes the anchor load-bearing on
#: its own. Cold outreach is written TO somebody, so it says "you" and "your"
#: constantly — a pronoun merely NEAR "applied" is therefore no anchor at all,
#: it is the same text the pattern is supposed to refuse. Its body says nothing
#: job-related at all, so the anchor is the ONLY thing standing between this
#: message and the review queue at 0.70.
OUTREACH_REPLY_SUBJECT_SECOND_PERSON = (
    "Re: Loved what your team is building and what you have shipped, applied "
    "for the Platform Engineer role"
)
NEUTRAL_AUTOREPLY = (
    "This mailbox is monitored during business hours. Someone will review your "
    "note and respond if there is a fit."
)


@pytest.fixture()
def rules():
    return get_rules_classifier()


def test_an_autoresponder_to_the_owners_outreach_never_reaches_the_queue(rules):
    """THE DEFECT. Held at 0.70 on one match, in words the owner wrote."""
    result = rules.classify(OUTREACH_REPLY_SUBJECT, CONTACT_FORM_ACK, CONTACT_INBOX)

    assert result.confidence < REVIEW_FLOOR, (
        "a canned reply to the owner's own outreach reached the review queue: "
        f"{result.category} at {result.confidence}. Matched: "
        f"{result.matched_patterns}"
    )


def test_the_first_person_subject_is_not_an_employers_claim(rules):
    """The narrow half: the quoted subject alone must not name a category."""
    result = rules.classify(OUTREACH_REPLY_SUBJECT, "", CONTACT_INBOX)

    assert result.category is not EmailCategory.APPLIED, (
        "a subject the OWNER wrote about his own application was read as the "
        f"employer asserting it: {result.matched_patterns}"
    )


# ── the controls: none of this may be bought by breaking a real confirmation ──


def test_the_same_employers_real_confirmation_still_auto_files(rules):
    result = rules.classify(REAL_CONFIRMATION_SUBJECT, REAL_CONFIRMATION_BODY, ATS)

    assert result.category is EmailCategory.APPLIED
    assert result.confidence >= AUTO_FILE_GATE, (
        f"the genuine confirmation stopped clearing the gate: {result.confidence}"
    )


def test_an_employer_saying_you_applied_still_scores(rules):
    """The anchor keeps the phrasing an employer actually uses."""
    result = rules.classify(
        "An update on your application", EMPLOYER_SECOND_PERSON, ATS
    )

    assert result.category is EmailCategory.APPLIED, (
        f"second-person employer phrasing stopped matching: {result.matched_patterns}"
    )


def test_a_second_person_pitch_does_not_smuggle_the_subject_back_in(rules):
    """Proximity is not an anchor; same-clause contiguity is.

    This subject says "your" and "you have" within a few words of "applied", so
    a pronoun-nearby rule passes it — and cold outreach reads like this
    constantly, which makes it the shape the anchor most has to refuse. The
    body is a neutral away-message with no job wording at all, so nothing else
    can rescue the verdict: if this comes back APPLIED, the anchor is doing no
    work.
    """

    result = rules.classify(
        OUTREACH_REPLY_SUBJECT_SECOND_PERSON, NEUTRAL_AUTOREPLY, CONTACT_INBOX
    )

    assert result.confidence < REVIEW_FLOOR, (
        "a pitch that happens to say 'you' scored as the employer's own claim: "
        f"{result.category} at {result.confidence} — {result.matched_patterns}"
    )


# ── #521: the corpus family, and the decision it settles ─────────────────────

#: The rule that was proposed and is NOT shipped. Written here as the source
#: string the arms below insert, so the arms and the prose cannot drift apart.
CONTACT_FORM_NEGATIVE = r"thank(s| you) for (getting in touch|reaching out|contacting)"
_COURTESY = re.compile(CONTACT_FORM_NEGATIVE, re.IGNORECASE)

FAMILY = "outreach-autoresponder"

#: What the family is, pinned so a shrunk family cannot quietly stop grading.
PAIRS = 80


@pytest.fixture(scope="module")
def family():
    """The family's cases in build order: refusal, twin, refusal, twin, …"""

    cases = [c for c in generate() if c.family == FAMILY]
    assert len(cases) == PAIRS * 2, f"the family is {len(cases)} messages"
    return list(zip(cases[0::2], cases[1::2], strict=True))


def _one_slot(a: str, b: str) -> tuple[str, str, str, str]:
    """Longest common prefix, the two differing spans, longest common suffix.

    ONE SPAN IS A PROPERTY OF THIS FUNCTION, NOT A FINDING — stripping a common
    prefix and a common suffix leaves exactly one span for ANY two strings, and
    claiming it as evidence would be a check that cannot fail. What the caller
    asserts is WHERE that span is and WHAT is in it.
    """

    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    j = 0
    while j < n - i and a[len(a) - 1 - j] == b[len(b) - 1 - j]:
        j += 1
    return a[:i], a[i : len(a) - j], b[i : len(b) - j], a[len(a) - j :]


def test_each_pair_in_the_family_varies_exactly_one_thing(family):
    """THE CONTROL DISCIPLINE, asserted rather than described.

    A pair exists to prove one distinction: whether the message acknowledges a
    MESSAGE or an APPLICATION. If anything else moves with it — the sender, the
    subject, the employer, the courtesy opener — the pair proves neither half,
    and the family is two unrelated samples with a big number on it.

    Four claims, each pinned with equality where equality is meant:

      * subject, sender and sender display name are IDENTICAL. Not "similar":
        the two halves are the same correspondent about the same thread, which
        is the real shape #520 was filed from — a company the owner had cold
        emailed AND applied to separately.
      * the courtesy phrase, which is the rule this family exists to judge,
        sits in the SHARED prefix, so it is demonstrably not what the pair
        varies.
      * the opening sentence is character-identical and neither side gains a
        sentence.
      * the one differing span names an application on the twin's side and
        never on the refusal's.
    """

    assert len(family) == PAIRS
    for refusal, twin in family:
        assert refusal.expected_category == "other"
        assert twin.expected_category == "applied"
        assert refusal.identity is None and refusal.employer is None
        assert twin.identity is not None and twin.employer is not None

        assert refusal.subject == twin.subject
        assert refusal.sender == twin.sender
        assert refusal.sender_name == twin.sender_name

        prefix, refusal_span, twin_span, _suffix = _one_slot(refusal.body, twin.body)
        assert _COURTESY.search(prefix), (
            "the courtesy phrase is not in the part the pair holds constant, so "
            f"the pair varies the rule under test: {prefix!r}"
        )
        assert refusal.body.split(".")[0] == twin.body.split(".")[0]
        assert refusal.body.count(".") == twin.body.count("."), (
            "the twin gained or lost a sentence, which is a second variable"
        )
        assert "applicat" not in refusal_span.lower(), (
            f"the refusal names an application: {refusal_span!r}"
        )
        assert "applicat" in twin_span.lower(), (
            f"the twin does not name an application: {twin_span!r}"
        )


def test_every_genuine_twin_reaches_at_least_the_review_floor(rules, family):
    """WITHOUT THIS THE FAMILY GRADES NOTHING, and that is measured, not feared.

    A twin already sitting under ``REVIEW_FLOOR`` cannot show a genre negative
    dropping it: it was dropped before the negative existed, so it is a case
    with a number on it and nothing to say. An earlier draft of this family had
    ten such twins. The weak rule
    ``application.{0,20}(for|to).{0,40}(position|role|job)`` has a 40-character
    window, so "your application for the <long job title> position" falls out
    of it, and three shapes scored 0.60 whenever the drawn role was long
    enough. The wordings were rebuilt to say "your application for the position
    of <role>", which is role-length independent.

    So this is the assertion that the family can grade a regression at all, and
    it is checked on every one of the 80 rather than on a sample.
    """

    low = []
    for _refusal, twin in family:
        result = rules.classify(twin.subject, twin.body, twin.sender)
        if (
            result.confidence < REVIEW_FLOOR
            or result.category is not EmailCategory.APPLIED
        ):
            low.append((twin.message_id, result.category.value, result.confidence))
    assert not low, (
        f"{len(low)} genuine confirmations do not reach the review floor as "
        f"`applied`, so a negative cannot be shown to drop them: {low[:5]}"
    )


def _classifier_with(monkeypatch, in_noise_negatives: bool):
    """The classifier as it WOULD be with the contact-form negative shipped.

    Both module globals, and the second one is the half a first probe missed.
    ``_SEMANTIC_REFUTATIONS`` is derived at import from ``patterns.negative``
    MINUS ``_NOISE_NEGATIVES``, so an arm that only recompiles the pattern
    tables measures the scoring change and not the ``own_text_refutes`` change
    that rides along with it. The fixtures here are short and never reach that
    path, which is exactly why it is rebuilt here rather than assumed away.
    """

    applied = rules_module.PATTERNS[EmailCategory.APPLIED]
    monkeypatch.setattr(
        applied, "negative", [*applied.negative, CONTACT_FORM_NEGATIVE], raising=False
    )
    noise = set(rules_module._NOISE_NEGATIVES)
    if in_noise_negatives:
        noise.add(CONTACT_FORM_NEGATIVE)
    monkeypatch.setattr(rules_module, "_NOISE_NEGATIVES", frozenset(noise))
    monkeypatch.setattr(
        rules_module,
        "_SEMANTIC_REFUTATIONS",
        {
            category.value: tuple(
                re.compile(p, re.IGNORECASE)
                for p in patterns.negative
                if p not in rules_module._NOISE_NEGATIVES
            )
            for category, patterns in rules_module.PATTERNS.items()
        },
    )
    built = rules_module.RulesClassifier()
    # PROVE THE ARM IS LIVE. A monkeypatch that silently failed to apply would
    # make every assertion below read as "the negative is harmless".
    assert any(
        p.pattern == CONTACT_FORM_NEGATIVE
        for p in built._compiled_patterns[EmailCategory.APPLIED]["negative"]
    ), "the arm did not compile the negative it is supposed to be measuring"
    return built


def _split(classifier, family):
    """(autoresponders still scored as applications, genuine twins now dropped)."""

    unfixed, dropped = 0, 0
    for refusal, twin in family:
        if (
            classifier.classify(refusal.subject, refusal.body, refusal.sender).confidence
            >= REVIEW_FLOOR
        ):
            unfixed += 1
        if (
            classifier.classify(twin.subject, twin.body, twin.sender).confidence
            < REVIEW_FLOOR
        ):
            dropped += 1
    return unfixed, dropped


def test_the_contact_form_negative_is_inert_inside_the_noise_set(monkeypatch, family):
    """ARM (b), and it is a regression with no upside at all.

    Membership in ``_NOISE_NEGATIVES`` is exactly what lets a strong BODY match
    outrank a genre filter — and all 40 autoresponders the rule was written for
    carry one ("reviewing applications", "reviewing candidates", "confirming
    receipt", "be in touch shortly"). So ``has_strong_body`` is True for
    ``applied`` on precisely the mail the filter exists for, and not one of
    them moves. Meanwhile 40 genuine confirmations, which have no strong body
    match to be exempted by, fall under the floor and are destroyed silently.

    Nothing that should move, and forty that must not.
    """

    before = _split(get_rules_classifier(), family)
    after = _split(_classifier_with(monkeypatch, in_noise_negatives=True), family)

    assert before == (40, 0), f"the shipped baseline moved: {before}"
    assert after == (40, 40), f"arm (b) measured {after}"


def test_the_contact_form_negative_costs_more_than_it_fixes_outside_it(
    monkeypatch, family
):
    """ARM (c), and it is the arm that WORKS — at a price nothing pays back.

    Every one of the 40 autoresponders is fixed. Fifty-five genuine
    confirmations go under ``REVIEW_FLOOR``, which is no card, no queue entry
    and nothing the user can correct: the worst failure this pipeline has, and
    the reason a genre filter cannot be bought on the strength of the mail it
    silences. Over the whole corpus that is `correct` 17250 -> 17235.

    The last assertion is the COMPARISON rather than the two counts on their
    own. If a later change makes the rule safe this reds — and it should,
    because that is when the decision recorded in ``rules.py`` deserves to be
    re-opened rather than this number re-recorded.
    """

    unfixed, dropped = _split(
        _classifier_with(monkeypatch, in_noise_negatives=False), family
    )

    assert unfixed == 0, f"arm (c) left {unfixed} autoresponders scored as applications"
    assert dropped == 55, f"arm (c) dropped {dropped} genuine confirmations"
    assert dropped > 40 - unfixed, (
        "the rule would now silence fewer genuine confirmations than the "
        "autoresponders it fixes. Re-open the decision in rules.py rather than "
        "re-recording this number."
    )
