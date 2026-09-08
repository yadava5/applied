"""A preheader the reader never sees decides an auto-filed verdict — issue #766.

Marketing HTML opens with a preheader: a block styled out of the rendered page
whose only job is to fill the inbox preview line. Nothing in the extraction path
reads ``style``, ``class``, ``hidden`` or ``aria-hidden`` — ``_SCRIPT_OR_STYLE``
removes ``<script>``/``<style>`` bodies and ``_TAG`` removes every remaining tag
— so that block survives as text and, being first in the document, lands FIRST
in the string the classifier is handed.

Measured here, through production's own entry point, on an HTML-only message
whose invisible preheader contradicts its visible invitation:

    preheader hidden + visible invitation  ->  rejection  0.95
    the visible invitation alone           ->  interview  0.70

0.95 is above ``pipeline.AUTO_FILE_GATE`` (0.85) and 0.70 is below it, so the
hidden text does not merely change the category — it raises the confidence past
the point where anybody is asked. An interview invitation is written onto the
board as a terminal rejection, stated to the reader as fact.

THE ENTRY POINT, NAMED. Every assertion below drives
``jobtracker.cloud.gmail_client.extract_body_text`` — the request path, not a
private helper and not the desktop twin. Production reaches it at
``gmail_client.py:1465`` inside ``_batch_fetch_metadata``; the string it returns
becomes ``bodies[message_id]``, and ``gmail_oauth.py:2173`` classifies
``bodies.get(msg.message_id) or msg.snippet``. ``email_clients/html_text.py``
carries the same rule for the desktop paths and is NOT what a synced Gmail
message crosses; a family that graded it would grade the copy nobody runs.

SCOPE, SO IT IS NEITHER OVER- NOR UNDER-READ. ``extract_body_text`` prefers
``text/plain`` and only falls through to HTML when no plain part exists, so the
live blast radius is HTML-only mail.
:func:`test_a_plain_part_alongside_the_html_is_untouched` is that claim as an
executed arm rather than a read one.

WHAT THIS FILE IS AND IS NOT
----------------------------
It is the gate. It is not the fix, and the difference is deliberate.

#766 records four adjudicated rounds of a regex hidden-element stripper, each
found to DELETE TEXT THE READER CAN SEE, abandoned on a decision written down
before the last result. This file is the reason a fifth round cannot be assessed
on the leak alone: the population below is split into the half a remedy MUST
move and the half it must NOT, and both halves are asserted.

THE POPULATION, ENUMERATED AND CLASSIFIED BEFORE ANY REMEDY
-----------------------------------------------------------
Ten mechanisms, one case each, split by what a browser renders:

    mechanism                        reader sees it   a remedy must
    ------------------------------   --------------   -----------------
    display:none                     no               MOVE it
    visibility:hidden                no               MOVE it
    opacity:0                        no               MOVE it
    max-height:0 + overflow:hidden   no               MOVE it
    hidden attribute                 no               MOVE it
    max-height:0 alone               YES              LEAVE it
    font-size:0, child sets its own  YES              LEAVE it
    aria-hidden="true"               YES              LEAVE it
    display:nonesuch                 YES              LEAVE it
    display:none;display:block       YES              LEAVE it

The right-hand column is CSS, not preference. ``max-height`` with the default
``overflow:visible`` overflows and paints; ``font-size:0`` is the old-Outlook
gap hack applied to containers whose children set their own size;
``aria-hidden`` hides from assistive technology and from nobody else, so by this
issue's own principle — "text the reader never saw" — that text is message text;
``nonesuch`` is not a valid ``display`` value so the declaration is dropped; and
``display:none;display:block`` is CSS last-wins, which makes the element
VISIBLE. The last two are the shapes that ended #766's regex rounds, and
:func:`test_the_substring_stripper_deletes_text_the_reader_can_see` runs that
abandoned approach against this population and shows it losing them.

NOT ADJUDICATED AGAINST A BROWSER HERE. #766's rounds were settled by parsing
each shape in Chromium with html5lib as a second opinion. No browser and no
``html5lib`` is reachable from this suite, so the ten shapes above are ordinary,
well-formed, single-attribute elements whose rendering is settled by the CSS
cascade rather than by tokenizer edge cases. A remedy that claims more than
these ten — nested, malformed, duplicate-attribute, foreign-content or
raw-text-element shapes — needs the browser adjudication this file cannot give
it, and #766 records what happens without one.

Every subject, sender and body here is invented. No real mailbox content, per
#593.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass

import pytest

from jobtracker.classifier.rules import RulesClassifier
from jobtracker.cloud.gmail_client import extract_body_text
from jobtracker.cloud.pipeline import AUTO_FILE_GATE, REVIEW_FLOOR

# Instantiated directly rather than through ``get_rules_classifier()``: the
# module singleton would make this file's behaviour depend on what ran before
# it. Same reasoning as ``test_a_verification_refusal_is_not_a_rejection_522``.
CLASSIFIER = RulesClassifier()

SUBJECT = "Update on your application"
#: A relay-shaped sender that is NOT a known ATS domain, so no +0.05 bonus is
#: quietly doing part of the work these numbers are attributed to.
SENDER = "noreply@careers.example"

#: The block that opens the document. In half the shapes below the reader never
#: sees it; in the other half it is ordinary message text.
PREHEADER = "Unfortunately we will not be moving forward with your application."

#: The block a reader of every shape below DOES see.
BODY = (
    "Great news! We would like to invite you to interview for the "
    "Backend Engineer role."
)


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _html_only(markup: str) -> dict:
    """A ``format="full"`` payload with no ``text/plain`` part anywhere."""

    return {"mimeType": "text/html", "body": {"data": _b64(markup)}}


def _plain_and_html(plain: str, markup: str) -> dict:
    """The shape ``extract_body_text`` prefers the plain half of."""

    return {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64(plain)}},
            {"mimeType": "text/html", "body": {"data": _b64(markup)}},
        ],
    }


@dataclass(frozen=True)
class Shape:
    """One hiding mechanism, and the ground truth about who can read it."""

    id: str
    #: The opening element, with ``{}`` where the preheader text goes.
    element: str
    #: A literal that MUST appear in this shape's markup and in no other's.
    #: Asserted rather than assumed — see
    #: :func:`test_every_shape_carries_its_own_mechanism`. Ten arms that all
    #: assert the same thing look identical to ten arms built from one markup,
    #: and only one of those is a test.
    mechanism: str
    #: Does a sighted reader of the rendered message see the preheader?
    reader_sees: bool
    #: Why, in CSS terms.
    why: str

    @property
    def markup(self) -> str:
        return (
            "<html><body>"
            + self.element.format(PREHEADER)
            + f"<p>{BODY}</p>"
            + "</body></html>"
        )


SHAPES: tuple[Shape, ...] = (
    Shape(
        id="display-none",
        element='<div style="display:none">{}</div>',
        # The closing quote is load-bearing: bare ``display:none`` is a
        # substring of ``display:none;display:block``, and the uniqueness check
        # below caught exactly that.
        mechanism='style="display:none"',
        reader_sees=False,
        why="generates no box at all",
    ),
    Shape(
        id="visibility-hidden",
        element='<div style="visibility:hidden">{}</div>',
        mechanism="visibility:hidden",
        reader_sees=False,
        why="the box is laid out and not painted",
    ),
    Shape(
        id="opacity-0",
        element='<div style="opacity:0">{}</div>',
        mechanism="opacity:0",
        reader_sees=False,
        why="fully transparent",
    ),
    Shape(
        id="max-height-0-overflow-hidden",
        element='<div style="max-height:0;overflow:hidden">{}</div>',
        mechanism="max-height:0;overflow:hidden",
        reader_sees=False,
        why="clipped to a zero-height box; the overflow half is what hides it",
    ),
    Shape(
        id="hidden-attribute",
        element="<div hidden>{}</div>",
        mechanism="<div hidden>",
        reader_sees=False,
        why="the UA stylesheet gives [hidden] display:none",
    ),
    Shape(
        id="max-height-0-alone",
        element='<div style="max-height:0">{}</div>',
        mechanism='style="max-height:0"',
        reader_sees=True,
        why="overflow defaults to visible, so the text overflows and paints",
    ),
    Shape(
        id="font-size-0-child-sized",
        element=(
            '<div style="font-size:0">'
            '<span style="font-size:14px">{}</span>'
            "</div>"
        ),
        mechanism='font-size:0"><span style="font-size:14px"',
        reader_sees=True,
        why="the old-Outlook gap hack; the child sets its own size and renders",
    ),
    Shape(
        id="aria-hidden",
        element='<div aria-hidden="true">{}</div>',
        mechanism='aria-hidden="true"',
        reader_sees=True,
        why="hidden from assistive technology only; a sighted reader sees it",
    ),
    Shape(
        id="display-nonesuch",
        element='<div style="display:nonesuch">{}</div>',
        mechanism="display:nonesuch",
        reader_sees=True,
        why="not a valid display value, so the declaration is dropped",
    ),
    Shape(
        id="display-none-then-block",
        element='<div style="display:none;display:block">{}</div>',
        mechanism="display:none;display:block",
        reader_sees=True,
        why="CSS last-wins: the element is displayed",
    ),
)

HIDDEN_FROM_THE_READER = [s for s in SHAPES if not s.reader_sees]
VISIBLE_TO_THE_READER = [s for s in SHAPES if s.reader_sees]


def _delivered(shape: Shape) -> str:
    """What production hands ``classify()`` for this shape's message."""

    return extract_body_text(_html_only(shape.markup))


def _verdict(text: str):
    return CLASSIFIER.classify(subject=SUBJECT, body=text, sender_email=SENDER)


# ---------------------------------------------------------------------------
# Prove the control ran
# ---------------------------------------------------------------------------


def test_every_shape_carries_its_own_mechanism() -> None:
    """Ten arms that assert the same thing must not BE the same arm.

    The extractor reads no styles, so every arm below is expected to behave
    identically — which is exactly the result a builder that emitted one markup
    ten times would also print. This is the difference between the two.
    """

    assert len(SHAPES) == 10
    assert len({s.id for s in SHAPES}) == 10
    assert len({s.markup for s in SHAPES}) == 10, "two shapes are the same message"
    assert len(HIDDEN_FROM_THE_READER) == 5
    assert len(VISIBLE_TO_THE_READER) == 5

    for shape in SHAPES:
        assert shape.mechanism in shape.markup, (
            f"{shape.id} does not contain {shape.mechanism!r}; it is not the "
            "mechanism it is named for"
        )
        others = [s.markup for s in SHAPES if s.id != shape.id]
        assert not any(shape.mechanism in m for m in others), (
            f"{shape.id}'s mechanism also appears in another shape, so the two "
            "arms are not independent"
        )
        assert PREHEADER in shape.markup and BODY in shape.markup


# ---------------------------------------------------------------------------
# The population, both halves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shape", HIDDEN_FROM_THE_READER, ids=lambda s: s.id)
def test_a_preheader_the_reader_cannot_see_still_reaches_the_classifier(
    shape: Shape,
) -> None:
    """THE DEFECT, PINNED AT ITS SIZE. Five mechanisms, five leaks.

    Not "this is correct" — this is #766 recorded as the shape it currently
    has, in the ``quoted-history`` idiom this repository already uses for a bug
    it has chosen to measure rather than exclude. When a remedy lands, every
    assertion in this function goes RED and has to be rewritten to say the
    preheader is gone. That is the gate: today a fix would land against nothing.

    Both halves are asserted because they are different claims. "The hidden
    text is in the string" is the leak; "the string STARTS with it" is why it
    decides a first-match verdict.
    """

    delivered = _delivered(shape)
    assert PREHEADER in delivered, (
        f"{shape.id}: the preheader no longer reaches the classifier. If that "
        "is a remedy landing, move this shape to the other half of the "
        "population and re-record #766's numbers; if it is not, extraction "
        "silently changed."
    )
    assert delivered.startswith(PREHEADER), (
        f"{shape.id}: the preheader no longer lands FIRST. First-match "
        "precedence over a string built in DOM order is the whole mechanism."
    )
    assert BODY in delivered, f"{shape.id}: the visible body was lost"


@pytest.mark.parametrize("shape", VISIBLE_TO_THE_READER, ids=lambda s: s.id)
def test_a_preheader_the_reader_can_see_must_keep_reaching_the_classifier(
    shape: Shape,
) -> None:
    """PERMANENT, AND THE HALF #766'S FOUR ROUNDS KEPT FAILING.

    These five render. Their first block is not a preheader in any meaningful
    sense — it is message text that happens to carry a style attribute, and a
    reader sees it. Deleting it is a worse failure than the leak, because the
    leak mis-scores a contradicting message while this loses the evidence out of
    an ordinary one: a partial deletion leaves the body non-empty, so
    ``bodies.get(id) or msg.snippet`` never falls back and the message is
    classified on what is left.

    No remedy may move a single assertion here.
    """

    delivered = _delivered(shape)
    assert PREHEADER in delivered, (
        f"{shape.id}: text a reader CAN see was deleted from the classifier's "
        f"input. {shape.why}. This is the failure #766's regex rounds were "
        "abandoned over, not a stricter extractor."
    )
    assert BODY in delivered, f"{shape.id}: the visible body was lost"


# ---------------------------------------------------------------------------
# What it costs, and the controls that keep the diagnosis honest
# ---------------------------------------------------------------------------


def test_the_invisible_preheader_decides_an_auto_filed_verdict() -> None:
    """One variable — the ``display:none`` element — and it crosses the gate.

    The pair is the same subject, the same sender and the same visible body,
    differing only in whether the contradicting block is there at all.
    """

    shape = next(s for s in SHAPES if s.id == "display-none")

    with_preheader = _verdict(_delivered(shape))
    assert with_preheader.category.value == "rejection"
    assert with_preheader.confidence >= AUTO_FILE_GATE, (
        f"{with_preheader.confidence} is below the auto-file gate, so this "
        "message would be queued for a person rather than filed. That is a "
        "materially smaller defect than #766 records and the issue should say "
        "so."
    )

    body_only = _verdict(extract_body_text(_html_only(f"<html><body><p>{BODY}</p></body></html>")))
    assert body_only.category.value == "interview", (
        "the control message is not an interview invitation on its own, so the "
        "pair above is measuring two variables"
    )
    assert REVIEW_FLOOR <= body_only.confidence < AUTO_FILE_GATE, (
        f"the invitation alone scores {body_only.confidence}. The finding is "
        "that the hidden text raises confidence THROUGH the gate; if the "
        "invitation already sat above it, it would not."
    )


def test_both_blocks_visible_still_reads_the_first_one() -> None:
    """THE DIRECTIONAL CONTROL, and it rules out the obvious wrong remedy.

    The same two blocks, neither hidden. The verdict is still ``rejection``, so
    the classifier is not treating hidden text specially — it is first-match
    precedence over a string the extractor built in DOM order. Ordinary mail
    looks like this.

    Without this arm, "ignore the leading block" would pass as a fix for #766.
    It is a different and worse bug, and this is the assertion it reds.
    """

    markup = f"<html><body><div>{PREHEADER}</div><p>{BODY}</p></body></html>"
    delivered = extract_body_text(_html_only(markup))
    assert delivered.startswith(PREHEADER)

    verdict = _verdict(delivered)
    assert verdict.category.value == "rejection"
    assert verdict.confidence >= AUTO_FILE_GATE


def test_a_plain_part_alongside_the_html_is_untouched() -> None:
    """SCOPE. ``extract_body_text`` prefers ``text/plain``, so this is not the
    blast radius — asserted rather than read off the docstring.

    A remedy must not change this message at all: the HTML half carrying the
    hidden preheader is never consulted.
    """

    shape = next(s for s in SHAPES if s.id == "display-none")
    delivered = extract_body_text(_plain_and_html(BODY, shape.markup))

    assert delivered == BODY
    assert PREHEADER not in delivered, (
        "the HTML part was read even though a text/plain part exists, which "
        "would widen #766's blast radius from HTML-only mail to all of it"
    )
    assert _verdict(delivered).category.value == "interview"


# ---------------------------------------------------------------------------
# The abandoned remedy, run against the population that ended it
# ---------------------------------------------------------------------------

#: The shape #766 tried four times: a non-greedy element match keyed on a
#: SUBSTRING of the style attribute. Written out here rather than described, so
#: the claim "a substring test cannot do this" is executable.
_SUBSTRING_STRIPPER = re.compile(
    r"<(div|span|p|td)\b[^>]*style=\"[^\"]*display\s*:\s*none[^\"]*\"[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)


def test_the_substring_stripper_deletes_text_the_reader_can_see() -> None:
    """Why #766 is not closed by a pattern, kept as a test rather than a note.

    The stripper WORKS on the shape it was written for — that is the trap. It
    also eats two shapes a browser renders, both of them well-formed single
    attributes that any sender can emit and one of them by accident. A remedy
    reaching for this shape reds here before it reaches the population above.
    """

    hit = next(s for s in SHAPES if s.id == "display-none")
    stripped = _SUBSTRING_STRIPPER.sub(" ", hit.markup)
    assert PREHEADER not in stripped, (
        "the stripper did not fire on display:none, so nothing below is a "
        "statement about it — the control did not run"
    )
    assert BODY in stripped

    casualties = []
    for shape in VISIBLE_TO_THE_READER:
        if PREHEADER not in _SUBSTRING_STRIPPER.sub(" ", shape.markup):
            casualties.append(shape.id)

    assert casualties == ["display-nonesuch", "display-none-then-block"], (
        f"the substring stripper deletes {casualties} from the rendered half of "
        "the population. If this list changed, the population changed; the "
        "assertion is that it deletes rendered text AT ALL, and which shapes "
        "is the evidence."
    )


# ---------------------------------------------------------------------------
# The corpus that already crosses this path
# ---------------------------------------------------------------------------


def test_the_mail_corpus_carries_both_polarities_and_one_of_them_auto_files() -> None:
    """The two committed cases, scored through ``mail_report``.

    ``mail_report.derive`` is ``extract_body_text(payload) or snippet`` —
    production's own expression — so these two are the only cases in either
    corpus that reach #766 at all. ``test_mail_corpus_instrument`` asserts the
    defect class is COVERED and may not assert accuracy; the verdicts are
    pinned here instead.

    AND THE SECOND ONE IS CORRECT BY ACCIDENT, which is the part that would be
    misread as coverage. Its hidden preheader claims an interview and its
    visible text is a rejection, so first-match precedence happens to agree with
    the ground truth. Its verdict is identical with the preheader deleted, so it
    grades nothing about hiding. Only ``interview`` polarity can fail, and it
    does.

    Both halves of that are ASSERTED below, one variable at a time, on the
    derived string rather than on the markup: delete the leading line and
    re-classify. c0050 moves ``rejection`` -> ``interview``; c0051 does not move
    at all. Measured, not reasoned — the aggregate cannot see any of this, and
    that is not a guess either: neutering ``_SCRIPT_OR_STYLE`` and then ``_TAG``
    outright (extraction stripping strictly LESS, then nothing) leaves this
    corpus at 344 correct / 26 wrong / 34 abstained / 5 wrongly auto-filed in
    both cases, because 7 of its 391 decoded body parts are HTML at all. An
    aggregate pin here would be a check that cannot fail.
    """

    from tests.corpus.mail import generate
    from tests.corpus.mail_report import derive, score_one

    cases = [
        c
        for c in generate()
        if "html:hidden-preheader-contradicts" in c.defects
    ]
    assert len(cases) == 2, (
        f"{len(cases)} cases carry the hidden-preheader defect, not 2. A "
        "family that shrank reads as a defect that was fixed."
    )

    # The one-variable control, per case: the SAME derived string with its
    # leading line removed. Nothing else about the message changes.
    moved = {}
    for case in cases:
        text = derive(case)
        head, _, rest = text.partition("\n")
        assert rest.strip(), f"{case.case_id}: nothing after the leading line"
        with_head = CLASSIFIER.classify(case.subject, text, case.sender)
        without = CLASSIFIER.classify(case.subject, rest.strip(), case.sender)
        moved[case.expected] = (with_head.category.value, without.category.value)

    assert moved["interview"] == ("rejection", "interview"), (
        f"the interview-polarity case reads {moved['interview']} with and "
        "without its leading line. The claim is that the hidden line is the "
        "WHOLE cause of the wrong verdict; if the pair stopped differing, it "
        "is wrong for some other reason and this file is describing the wrong "
        "defect."
    )
    assert moved["rejection"][0] == moved["rejection"][1], (
        f"the rejection-polarity case now reads {moved['rejection']}. It used "
        "to be identical with and without its preheader — correct by accident "
        "— which is why it cannot be cited as coverage of #766."
    )

    outcomes = {c.expected: score_one(c, CLASSIFIER) for c in cases}
    assert set(outcomes) == {"interview", "rejection"}, (
        "both polarities are required; one alone is green for a remedy that "
        "deletes the leading block"
    )

    wrong = outcomes["interview"]
    assert wrong.actual == "rejection", (
        "the interview-polarity case no longer reads as a rejection. If a "
        "remedy landed, re-record it here and in #766."
    )
    assert wrong.bucket == "wrong"
    assert wrong.auto_filed is True, (
        "this case is one of the mail corpus's confidently-wrong auto-files. "
        "Losing that is the whole cost of #766 and it must not go quiet."
    )
    assert wrong.confidence == 0.9

    accidental = outcomes["rejection"]
    assert accidental.actual == "rejection"
    assert accidental.bucket == "correct"
