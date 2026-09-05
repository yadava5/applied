"""#430 — THE QUOTE BOUNDARY HAS TO SURVIVE THE BODY EXTRACTOR.

``strip_quoted_history``, ``own_text_span`` and the refutation cap all hang off
one LINE-ORIENTED marker: ``rules._QUOTE_BOUNDARY`` is ``^``-anchored under
``re.MULTILINE``, and its Outlook alternative spells a literal newline.
``cloud/gmail_client.extract_body_text`` used to finish with
``_WHITESPACE.sub(" ", text)``, so the string the request path actually handed
the classifier had no newlines in it at all: the anchor could only ever match
at offset 0, the Outlook alternative could not match at any offset, and all
three of those functions were dead code in production.

WHY NOTHING CAUGHT IT, which is why this file is separate from
``test_a_reply_speaks_for_itself.py`` rather than a section inside it. Every
fixture there is a Python literal with real ``\\n`` in it, handed straight to
``strip_quoted_history``. Those tests fail if the strip is deleted and pass for
every input production is capable of producing — the wrong half of the space.
So nothing here starts from a string. Each case starts from a Gmail
``format=full`` payload and crosses ``extract_body_text``, because the shape
the wire delivers is the only shape worth pinning.

WHAT THIS DOES NOT FIX: the reply below is STILL classified wrongly. Its own
words ("we would love to set up a conversation") match no interview pattern,
and its demoted ``Re:`` subject still contributes to ``applied``. This change
moves it from wrong-and-auto-filed to wrong-and-held-for-review, which is worth
having and is not a correct answer. The assertions below say "not auto-filed"
and never "read as an interview", so this file cannot rot into claiming the
second.
"""

from __future__ import annotations

import base64

import pytest

from jobtracker.classifier.rules import (
    _QUOTE_BOUNDARY,
    asserted_text,
    get_rules_classifier,
    own_text_span,
    reflow_paragraphs,
)
from jobtracker.cloud.gmail_client import (
    _MAX_BODY_CHARS,
    _WHITESPACE,
    extract_body_text,
)
from jobtracker.cloud.pipeline import AUTO_FILE_GATE, role_from_message

from .corpus.mail import CANDIDATE, hard_wrap

#: A reserved domain (RFC 2606), per ``docs/TEST_DATA_POLICY.md``: nothing here
#: may name an address that could actually route.
#:
#: IT COSTS THE ATS PATH, and that was checked rather than assumed. No reserved
#: address can satisfy ``is_ats_sender`` — ``ATS_DOMAINS`` is a closed list of
#: real relays — so this sender forgoes the +0.05 bonus and every confidence in
#: this file reads 0.05 lower than it would from ``greenhouse.io``. Measured on
#: ``QUOTED_INVITE``: 0.90 -> 0.70 here against 0.95 -> 0.75 there. The gate is
#: 0.85, so the one assertion that reads a confidence still separates the
#: broken shape from the fixed one by the same margin, and none of the claims
#: in this file are about ATS handling. If one ever is, it needs the bonus and
#: cannot get it from a reserved domain — say so rather than reaching for a
#: routable address.
ATS = "no-reply@us.greenhouse-mail.example"
SUBJECT = "Re: Thank you for applying to Cedarhollow Systems"

#: A recruiter replying to their own acknowledgement — the #441 family, in the
#: shape Gmail hands it over rather than the shape a test would write it in.
QUOTED_INVITE = (
    f"Hi {CANDIDATE}, Following up on the below — we would love to set up a "
    "conversation with you next week. Are you free Thursday?\n\n"
    "On Tuesday, Cedarhollow Systems Recruiting wrote:\n"
    f"> Hi {CANDIDATE}, Thank you for applying to the Backend Engineer position at\n"
    "> Cedarhollow Systems. Your application has been received.\n"
)

#: The same message as a mailer that indents, pads and double-spaces would send
#: it: tabs, trailing spaces, and four blank lines where two belong. It exists
#: so the extractor is doing visible WORK in these tests and not merely handing
#: back what it was given.
UNTIDY_INVITE = (
    f"Hi {CANDIDATE},   Following   up on the below — we would love to set up a  \n"
    "conversation with you next week.\tAre you free Thursday?   \n\n\n\n"
    "On Tuesday, Cedarhollow Systems Recruiting wrote:\n"
    f"  > Hi {CANDIDATE}, Thank you for applying to the Backend Engineer position at\n"
    "  > Cedarhollow Systems. Your application has been received.\n"
)


def _payload(body: str) -> dict:
    """A ``text/plain`` ``format=full`` payload carrying ``body``."""

    return {
        "mimeType": "text/plain",
        "body": {"data": base64.urlsafe_b64encode(body.encode("utf-8")).decode()},
    }


def _delivered(body: str, wrap: bool = False) -> str:
    """The string production hands ``classify()``. The whole point of the file."""

    return extract_body_text(_payload(hard_wrap(body) if wrap else body))


@pytest.fixture(params=[False, True], ids=["as-authored", "wrap72"])
def shape(request) -> bool:
    """EVERY CLAIM BELOW IS MADE TWICE.

    Once on the body as the fixture author typed it, and once on the same body
    hard-wrapped at 72 columns, which is how an ATS actually sends
    ``text/plain``. The first shape is the one a test file reaches for and the
    second is the one production receives; #430 is the story of a defect that
    lived entirely in the gap between them, so a file written to catch it that
    only ever measured the first would be repeating the mistake.
    """

    return request.param


@pytest.fixture()
def rules():
    return get_rules_classifier()


# ── the marker is still findable in what the wire delivers ───────────────────


@pytest.mark.parametrize(
    "body",
    [
        QUOTED_INVITE,
        UNTIDY_INVITE,
        # No attribution line: some clients write only the ``>``.
        "We would like to invite you to interview next week.\n"
        "> Thank you for applying to the Backend Engineer position.\n",
        "We would like to invite you to interview next week.\n\n"
        "-----Original Message-----\n"
        "Thank you for applying to the Backend Engineer position.\n",
        "We would like to invite you to interview next week.\n\n"
        "Begin forwarded message:\n"
        "Thank you for applying to the Backend Engineer position.\n",
    ],
)
def test_the_delivered_body_still_carries_a_quote_boundary(body: str, shape: bool) -> None:
    delivered = _delivered(body, shape)
    assert "\n" in delivered, (
        f"the extractor returned one line: {delivered!r}. Every marker "
        "_QUOTE_BOUNDARY knows is anchored to the start of a line."
    )
    marker = _QUOTE_BOUNDARY.search(delivered)
    assert marker is not None, (
        f"no quote boundary in the delivered body: {delivered!r}. The reply's "
        "history will be scored as words this sender wrote."
    )
    assert marker.start() > 0, (
        "the boundary matched at offset 0, which is what a single-line string "
        "does — the reply's own words came back as the empty span."
    )


def test_the_quote_does_not_reach_the_span_that_gets_scored(shape: bool) -> None:
    """Stated on the TEXT and not on the verdict, so it cannot pass by luck."""

    delivered = _delivered(QUOTED_INVITE, shape)
    own = own_text_span(delivered)
    assert own is not None
    assert "Thank you for applying" not in own, (
        f"the quoted acknowledgement survived into the own-text span: {own!r}"
    )
    assert "Thank you for applying" not in asserted_text(delivered)

    # READ THROUGH THE REFLOW, and the wrap72 run is why. ``own_text_span``
    # answers "which words did the sender write" and is deliberately taken
    # BEFORE ``reflow_paragraphs`` -- the quote boundary needs the newlines and
    # the ``_MIN_ASSERTED_CHARS`` floors are counted on that same unreflowed
    # span. So a phrase split across a 72-column wrap point is genuinely absent
    # from it, and asserting on the raw span would be asserting on a string no
    # pattern ever sees. ``classify`` reflows it before ``own_text_refutes``;
    # this asserts what that reader gets.
    assert "set up a conversation" in reflow_paragraphs(own)


def test_the_outlook_header_block_could_not_have_matched_a_collapsed_body(
    shape: bool,
) -> None:
    """The proof that the collapse DISABLED the marker rather than weakening it.

    ``_QUOTE_BOUNDARY``'s Outlook alternative is ``from:`` … ``\\n`` …
    ``sent:``. A literal newline inside a pattern applied to a string with no
    newlines in it cannot match at any offset and for any wording, so this is
    not a matter of degree: the old normalisation removed a branch of the
    grammar. Both halves are asserted here so the control travels with the
    claim.
    """

    body = (
        f"Hi {CANDIDATE}, We would love to set up a conversation with you next week. "
        "Please let me know what suits.\n\n"
        "From: Cedarhollow Systems Recruiting\n"
        "Sent: Tuesday, 12 August 2026 09:14\n"
        f"To: {CANDIDATE}\n"
        "Subject: Thank you for applying to the Backend Engineer position\n"
    )
    delivered = _delivered(body, shape)
    assert _QUOTE_BOUNDARY.search(delivered) is not None

    collapsed = _WHITESPACE.sub(" ", body)
    assert _QUOTE_BOUNDARY.search(collapsed) is None, (
        "the collapsed form matched after all — then the old shape was not the "
        "reason this branch never fired and this test is measuring nothing."
    )


def test_a_reply_in_its_own_confirmation_thread_is_not_auto_filed(rules, shape: bool) -> None:
    """The consequence, measured end to end from the payload.

    STATED AS "NOT AUTO-FILED", never as "read as an interview". The reply's
    own words name no interview vocabulary the rules have and its ``Re:``
    subject still argues for ``applied``, so it remains WRONG — it just stops
    being wrong silently. Measured on this body with this file's reserved
    sender: ``applied`` 0.90 auto-filed before, ``applied`` 0.70 held for
    review after. From an ATS relay both read 0.05 higher; see ``ATS``.
    """

    result = rules.classify(SUBJECT, _delivered(QUOTED_INVITE, shape), ATS)
    assert result.confidence < AUTO_FILE_GATE, (
        f"a follow-up in a confirmation thread was auto-filed as "
        f"{result.category.value} at {result.confidence}. It scored its own "
        "quoted acknowledgement, so nobody is ever asked about it."
    )


# ── what must not break ──────────────────────────────────────────────────────


def test_identity_still_reads_the_whole_delivered_body(shape: bool) -> None:
    """The quote is the only place the role appears; extraction keeps it.

    A fix that hid the history from the identity layer would repair
    classification by breaking the grouping that decides which card a message
    lands on. Only SCORING loses the quote.
    """

    assert role_from_message(SUBJECT, _delivered(QUOTED_INVITE, shape)) == "Backend Engineer"


def test_the_delivered_body_is_still_normalised(shape: bool) -> None:
    """Line structure is kept; whitespace noise is not.

    Without this the change reads as "stop normalising", which would hand the
    rules layer raw mailer output — runs of spaces inside a phrase, and the
    space every horizontal collapse strands in front of a newline.
    """

    delivered = _delivered(UNTIDY_INVITE, shape)
    assert "Following up on the below" in delivered, "horizontal runs must collapse"
    assert "Thursday?" in delivered
    assert "  " not in delivered, f"a double space survived: {delivered!r}"
    assert " \n" not in delivered, f"a trailing space survived: {delivered!r}"
    assert "\n\n\n" not in delivered, "four blank lines are not a paragraph break"
    assert "\n\n" in delivered, "the paragraph break itself must survive"
    assert "\t" not in delivered


def test_the_cap_is_still_applied_after_normalising(shape: bool) -> None:
    """Order matters: normalise, then cut. Cutting first would cap a string the
    classifier never sees."""

    body = "line of words here\n" * 1000
    delivered = _delivered(body, shape)
    assert len(delivered) == _MAX_BODY_CHARS


def test_a_body_with_no_quote_survives_intact(shape: bool) -> None:
    plain = f"Hi {CANDIDATE}, Unfortunately we will not be moving forward. Best of luck."
    assert _delivered(plain, shape) == plain
    assert own_text_span(_delivered(plain, shape)) is None


def test_windows_line_endings_do_not_leave_stray_spaces(shape: bool) -> None:
    """``[^\\S\\n]+`` matches ``\\r``, so CRLF becomes " \\n" before the trailing
    -space pass removes the space. Asserted because the intermediate state is
    the kind of thing a later simplification deletes."""

    delivered = _delivered(
        "We would love to set up a conversation with you next week.\r\n"
        "\r\n"
        "On Tuesday, Cedarhollow Systems Recruiting wrote:\r\n"
        "> Thank you for applying to the Backend Engineer position.\r\n",
        shape,
    )
    assert "\r" not in delivered
    assert " \n" not in delivered
    assert _QUOTE_BOUNDARY.search(delivered) is not None
