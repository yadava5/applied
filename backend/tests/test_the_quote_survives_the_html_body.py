"""#430, the HTML half — THE QUOTE BOUNDARY HAS TO SURVIVE MARKUP TOO.

``test_the_quote_survives_the_body_extractor.py`` closed the ``text/plain``
half: ``extract_body_text`` stopped collapsing the newlines a plain part
already carries, so ``rules._QUOTE_BOUNDARY`` — ``^``-anchored under
``re.MULTILINE`` — could find the line a reply stops speaking on. That file
builds ``text/plain`` payloads and only those; the string "html" does not
appear in it.

AN HTML-ONLY MESSAGE CARRIES NO NEWLINES TO KEEP. Its line structure is
spelled ``<br>`` and ``</div>``, and ``_html_to_text`` replaced every tag with
a space before the newline-preserving normalisation ever ran. So the fixed
extractor returned a single line for exactly the messages that have no plain
part — which is the case that motivated reading bodies at all, and the case
Gmail gives the poorest snippet for.

WHY NOTHING SAW IT. Of the 404-case corpus only ten cases are HTML-only and
none of them carries a quote boundary, so the instrument could not answer this
in either direction, and the plain-text file above could not either.

WHAT IS ASSERTED HERE, and it is deliberately not a confidence number: that
the boundary is FOUND and that ``own_text_span`` returns the reader's own
words. Those are the property. The verdict that follows from them is moved by
every change to the rules layer, and a test pinned to it would report other
people's work as this defect coming back.

WHAT THIS DOES NOT FIX, measured rather than assumed. A reply whose only quote
marker is ``<blockquote>`` and ``&gt;``, with no attribution line, still has NO
boundary after this change: ``_html_to_text`` never calls ``html.unescape``, so
``_QUOTE_BOUNDARY``'s ``[ \\t]*>`` alternative cannot fire on HTML-derived
text, and ``<blockquote>`` is erased by ``_TAG`` without leaving a trace of
itself. Its ``text/plain`` twin matches at offset 42. That needs entity
decoding or a blockquote-to-``>`` mapping and a measurement of its own; it is
described here rather than pinned, because a test asserting today's ``None``
would go red the day somebody fixes it.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Callable
from typing import Any

import pytest

from jobtracker.classifier.rules import (
    _QUOTE_BOUNDARY,
    asserted_text,
    own_text_span,
    reflow_paragraphs,
)
from jobtracker.cloud import gmail_client
from jobtracker.cloud.gmail_client import extract_body_text
from jobtracker.cloud.pipeline import role_from_message

from .corpus.mail import CANDIDATE

#: A reserved domain (RFC 2606), per ``docs/TEST_DATA_POLICY.md``. Nothing in
#: this file may name an address that could route, and no real mail is quoted:
#: every string below is invented.
SENDER = "no-reply@us.greenhouse-mail.example"
EMPLOYER = "Cedarhollow Systems"
ROLE = "Backend Engineer"
SUBJECT = f"Re: Thank you for applying to {EMPLOYER}"

#: The four lines every shape below draws, in order. The reply's own words
#: first, then the attribution, then the acknowledgement it quotes — the #441
#: family, in the one MIME shape no test has ever handed the extractor.
OWN_WORDS = (
    f"Hi {CANDIDATE}, Following up on the below — we would love to set up a "
    "conversation with you next week. Are you free Thursday?"
)
ATTRIBUTION = f"On Tuesday, {EMPLOYER} Recruiting wrote:"
QUOTED_FIRST = f"Hi {CANDIDATE}, Thank you for applying to the {ROLE} position at"
QUOTED_SECOND = f"{EMPLOYER}. Your application has been received."
LINES = [OWN_WORDS, ATTRIBUTION, QUOTED_FIRST, QUOTED_SECOND]

#: EVERY SHAPE IS ONE SOURCE LINE, and that is the instrument, not formatting.
#:
#: A newline in the HTML SOURCE is preserved by the horizontal-only collapse
#: all by itself, so a pretty-printed fixture would find its boundary with half
#: this fix in place and the control below would pass against a mutant. Here
#: the line structure is carried by markup and by nothing else, which is the
#: only shape that can tell the two halves apart. See
#: ``test_a_source_line_break_is_kept_too`` for the pretty-printed case and why
#: it is deliberately outside the control set.
MARKUP = {
    "blockquote": (
        f"<html><body><div>{OWN_WORDS}</div><br><div>{ATTRIBUTION}</div>"
        f"<blockquote><div>{QUOTED_FIRST}</div><div>{QUOTED_SECOND}</div>"
        "</blockquote></body></html>"
    ),
    "divs": (
        f"<div>{OWN_WORDS}</div><div>{ATTRIBUTION}</div>"
        f"<div>{QUOTED_FIRST}</div><div>{QUOTED_SECOND}</div>"
    ),
    "paragraphs": (
        f"<p>{OWN_WORDS}</p><p>{ATTRIBUTION}</p>"
        f"<blockquote><p>{QUOTED_FIRST}</p><p>{QUOTED_SECOND}</p></blockquote>"
    ),
    # ``<br clear="all">`` is what Gmail and Outlook actually emit, and it is
    # here because ``<br\s*/?>`` — the obvious spelling — does not match it.
    "line breaks": (
        f'{OWN_WORDS}<br clear="all"><br />{ATTRIBUTION}<br>{QUOTED_FIRST}<br>{QUOTED_SECOND}'
    ),
    # Horizontal noise a real mailer adds: runs of spaces, tabs, indentation
    # inside the tags. The extractor must be doing visible WORK in these tests
    # and not merely handing back what it was given.
    "untidy": (
        f"<div  style='margin:0'>  {OWN_WORDS.replace(', ', ',   ', 1)}\t</div>"
        f"<br>  <div>\t{ATTRIBUTION}  </div>"
        f"<blockquote><div>  {QUOTED_FIRST}</div><div>{QUOTED_SECOND}  </div>"
        "</blockquote>"
    ),
}

#: The same four lines as ``text/plain``. A CONTROL, not decoration: it is the
#: path #430's first half fixed, it crosses the same ``extract_body_text``, and
#: it reds if that half is ever undone.
PLAIN_TWIN = "\n\n".join([OWN_WORDS, ATTRIBUTION]) + "\n" + "\n".join([QUOTED_FIRST, QUOTED_SECOND])


def _part(mime: str, content: str) -> dict[str, Any]:
    return {
        "mimeType": mime,
        "body": {"data": base64.urlsafe_b64encode(content.encode("utf-8")).decode()},
    }


def _html_only(markup: str) -> dict[str, Any]:
    """A ``format=full`` payload whose ONLY leaf part is ``text/html``."""

    return {"mimeType": "multipart/alternative", "parts": [_part("text/html", markup)]}


def _plain_only(text: str) -> dict[str, Any]:
    return {"mimeType": "multipart/alternative", "parts": [_part("text/plain", text)]}


def _stripper(*, block: bool, collapse: re.Pattern[str]) -> Callable[[str], str]:
    """One arm of the fix, composed from production's OWN patterns.

    Built out of ``gmail_client``'s compiled patterns rather than out of
    transcribed regexes, so an arm cannot quietly stop being the thing it is a
    control for. Only two things vary: whether block-level markup becomes a
    newline before ``_TAG`` runs, and which collapse finishes the job.
    """

    def strip(markup: str) -> str:
        markup = gmail_client._SCRIPT_OR_STYLE.sub(" ", markup)
        if block:
            markup = gmail_client._BLOCK_LEVEL.sub("\n", markup)
        return collapse.sub(" ", gmail_client._TAG.sub(" ", markup)).strip()

    return strip


#: THE DIRECTIONAL CONTROL. Each of these is the shipped extractor with ONE
#: half taken away, and each must fail to find the boundary — which is what
#: makes a mutant that reverts either half on its own go red rather than only
#: one that reverts both.
BROKEN_ARMS = {
    "neither half: the collapse that caused #430": _stripper(
        block=False, collapse=gmail_client._WHITESPACE
    ),
    "(a) alone: horizontal-only collapse, no block newlines": _stripper(
        block=False, collapse=gmail_client._HORIZONTAL_WHITESPACE
    ),
    "(b) alone: block newlines, then the old collapse erases them": _stripper(
        block=True, collapse=gmail_client._WHITESPACE
    ),
}


# ── the instrument itself ────────────────────────────────────────────────────


@pytest.mark.parametrize("shape", sorted(MARKUP))
def test_the_payload_really_is_html_only(shape: str) -> None:
    """``extract_body_text`` PREFERS ``text/plain``.

    A payload that grew a plain sibling would take the path the first half of
    #430 already fixed, every assertion in this file would pass, and none of
    them would have crossed the HTML extractor at all.
    """

    parts = _html_only(MARKUP[shape])["parts"]
    assert [p["mimeType"] for p in parts] == ["text/html"]


# ── the property ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("shape", sorted(MARKUP))
def test_an_html_only_body_still_carries_a_quote_boundary(shape: str) -> None:
    delivered = extract_body_text(_html_only(MARKUP[shape]))

    assert "\n" in delivered, (
        f"the extractor returned one line for {shape}: {delivered!r}. Every "
        "marker _QUOTE_BOUNDARY knows is anchored to the start of a line."
    )
    marker = _QUOTE_BOUNDARY.search(delivered)
    assert marker is not None, (
        f"no quote boundary in the delivered body for {shape}: {delivered!r}. "
        "The reply's history will be scored as words this sender wrote."
    )
    assert marker.start() > 0, (
        "the boundary matched at offset 0, which is what a single-line string "
        "does — the reply's own words came back as the empty span."
    )


@pytest.mark.parametrize("shape", sorted(MARKUP))
def test_the_delivered_lines_are_the_lines_the_markup_drew(shape: str) -> None:
    """Exact content, not "there is a newline somewhere".

    Interior lines begin with the space ``_TAG`` leaves where an opening
    ``<div>`` was, so the comparison strips each line — every
    ``_QUOTE_BOUNDARY`` alternative already tolerates leading ``[ \\t]``, and
    removing that space in the extractor would be a third variable nothing has
    measured.
    """

    delivered = extract_body_text(_html_only(MARKUP[shape]))
    assert [line.strip() for line in delivered.split("\n") if line.strip()] == LINES
    assert "  " not in delivered, f"a double space survived: {delivered!r}"
    assert " \n" not in delivered, f"a trailing space survived: {delivered!r}"
    assert "\t" not in delivered
    assert "\n\n\n" not in delivered


@pytest.mark.parametrize("shape", sorted(MARKUP))
def test_the_quote_does_not_reach_the_span_that_gets_scored(shape: str) -> None:
    """Stated on the TEXT and not on the verdict, so it cannot pass by luck."""

    delivered = extract_body_text(_html_only(MARKUP[shape]))

    own = own_text_span(delivered)
    assert own is not None, f"no own-text span for {shape}: {delivered!r}"
    assert "Thank you for applying" not in own, (
        f"the quoted acknowledgement survived into the own-text span: {own!r}"
    )
    assert "Thank you for applying" not in asserted_text(delivered)
    # Read through the reflow for the same reason the plain-text file does:
    # ``own_text_span`` is taken before ``reflow_paragraphs`` because the
    # boundary needs the newlines, and ``classify`` reflows the span before
    # anything reads it.
    assert "set up a conversation" in reflow_paragraphs(own)


# ── the control: each half alone is not enough ───────────────────────────────


@pytest.mark.parametrize("arm", sorted(BROKEN_ARMS))
@pytest.mark.parametrize("shape", sorted(MARKUP))
def test_neither_half_of_the_fix_finds_the_boundary_alone(
    arm: str, shape: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Measured one variable at a time, through the real ``extract_body_text``.

    ============================================  ========  =============
    arm                                           newlines  boundary
    ============================================  ========  =============
    neither half (the ``\\s+`` collapse)           0         NO MATCH
    horizontal-only collapse alone                0         NO MATCH
    block-level newlines alone                    0         NO MATCH
    both — what ships                             4         @120
    ============================================  ========  =============

    The two halves fail for different reasons, which is why one of them alone
    reads like progress and is not: without the substitution there is no
    newline to keep, and with the old collapse the newline it inserts is
    erased two calls later.
    """

    monkeypatch.setattr(gmail_client, "_html_to_text", BROKEN_ARMS[arm])
    delivered = extract_body_text(_html_only(MARKUP[shape]))

    assert "\n" not in delivered, (
        f"{arm} kept a newline on {shape}: {delivered!r}. Then this arm is not "
        "the broken shape and it is controlling for nothing."
    )
    assert _QUOTE_BOUNDARY.search(delivered) is None
    assert own_text_span(delivered) is None


@pytest.mark.parametrize("shape", sorted(MARKUP))
def test_what_ships_is_exactly_those_two_substitutions(shape: str) -> None:
    """Pins the arms to the real function.

    Without this, ``_html_to_text`` could be rewritten into something the arms
    above are no longer one variable away from, and the control would go on
    passing while measuring a composition nobody ships.
    """

    markup = MARKUP[shape]
    shipped = _stripper(block=True, collapse=gmail_client._HORIZONTAL_WHITESPACE)
    assert gmail_client._html_to_text(markup) == shipped(markup)
    for arm, broken in BROKEN_ARMS.items():
        assert gmail_client._html_to_text(markup) != broken(markup), (
            f"{arm} produces what the shipped extractor produces, so it is not a mutant of it."
        )


# ── the plain-text twin, and what must not break ─────────────────────────────


def test_the_plain_text_twin_of_the_same_content_still_works() -> None:
    """The other half of #430, on the same four lines.

    HERE SO THAT A CHANGE BREAKING THE PLAIN PATH ALSO REDS. Everything above
    would stay green if ``normalise_body_text`` went back to collapsing
    newlines and only ``_html_to_text`` kept them, which is a repair that
    breaks the majority of real mail.
    """

    delivered = extract_body_text(_plain_only(PLAIN_TWIN))

    marker = _QUOTE_BOUNDARY.search(delivered)
    assert marker is not None and marker.start() > 0
    own = own_text_span(delivered)
    assert own is not None
    assert "Thank you for applying" not in own
    assert "set up a conversation" in reflow_paragraphs(own)


def test_the_html_body_delivers_what_its_plain_twin_delivers() -> None:
    """Same content, two MIME shapes, one string — modulo the leading space."""

    from_html = extract_body_text(_html_only(MARKUP["blockquote"]))
    from_plain = extract_body_text(_plain_only(PLAIN_TWIN))
    assert [line.lstrip(" ") for line in from_html.split("\n")] == from_plain.split("\n")


@pytest.mark.parametrize("shape", sorted(MARKUP))
def test_identity_still_reads_the_whole_delivered_body(shape: str) -> None:
    """The quote is the only place the role appears, and extraction keeps it.

    A fix that hid the history from the identity layer would repair
    classification by breaking the grouping that decides which card a message
    lands on. Only SCORING loses the quote.
    """

    delivered = extract_body_text(_html_only(MARKUP[shape]))
    assert role_from_message(SUBJECT, delivered) == ROLE


def test_html_prose_with_no_quote_is_delivered_as_one_line() -> None:
    """A one-paragraph message must not grow structure it never had."""

    delivered = extract_body_text(_html_only(f"<html><body><p>{OWN_WORDS}</p></body></html>"))
    assert delivered == OWN_WORDS
    assert own_text_span(delivered) is None


def test_a_source_line_break_is_kept_too() -> None:
    """Pretty-printed HTML: the source newlines survive, like a wrapped plain part.

    DELIBERATELY OUTSIDE ``BROKEN_ARMS``. The horizontal-only collapse keeps a
    source newline on its own, so this shape finds its boundary with half the
    fix in place — which makes it a fine thing to assert and a useless control.
    It is asserted because the consequence is real: HTML that a mailer indents
    now reaches the rules layer with line breaks inside sentences, exactly as a
    72-column ``text/plain`` part already does, and ``reflow_paragraphs`` is
    what handles both.
    """

    delivered = extract_body_text(
        _html_only(
            f"<div>\n  {OWN_WORDS}\n</div>\n<div>\n  {ATTRIBUTION}\n</div>\n"
            f"<blockquote>\n  <div>{QUOTED_FIRST} {QUOTED_SECOND}</div>\n</blockquote>"
        )
    )
    assert _QUOTE_BOUNDARY.search(delivered) is not None
    own = own_text_span(delivered)
    assert own is not None and "Thank you for applying" not in own
