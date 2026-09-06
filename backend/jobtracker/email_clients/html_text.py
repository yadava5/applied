r"""One definition of "a script or style element", shared by every stripper here.

WHY THIS MODULE EXISTS. ``parser.py``, ``gmail.py`` and ``icloud.py`` each
carried their own copy of the same two substitutions, and CodeQL
``py/bad-tag-filter`` opened one alert per copy (52 / 53 / 56, plus the vendored
mirrors 51 / 54 / 55). A regex that decides what counts as an element is exactly
the kind of thing that must exist once: the fourth copy, in
``cloud/gmail_client.py``, spells the same rule with a backreference and was
never flagged at all, so three of four got fixed by the alerts and the deployed
one would not have.

WHAT THE ALERT WAS. The end tag was written as the literal ``</script>``. HTML5
leaves the script-data-end-tag-name state on whitespace, ``/`` or ``>``, so a
browser closes the element on ``</script >``, ``</style\n>``, ``</script/>`` and
``</script foo>`` — none of which that literal matches. The non-greedy body then
ran past the real end of the element, or the substitution did not fire at all,
and the element's contents survived into the extracted text. See
``tests/test_html_end_tag_whitespace.py`` for each shape.

WHY REGEX AND NOT ``html.parser``. ``html.parser.HTMLParser`` cannot be fooled
by tag shape, and it was weighed. It loses on the constraint that matters more
here: it converts character references (``&nbsp;`` → ``\xa0``, ``&amp;`` → ``&``)
on EVERY legitimate HTML mail, which is a broad, guaranteed change to the text
that classification and snippets are built from, bought to fix a shape that
appears in no legitimate mail. ``cloud/gmail_client.py`` also already carries a
recorded decision to keep this function regex-based for its serverless time
budget. The alert is a wrong pattern, not a wrong instrument.

WHAT IS DELIBERATELY NOT FIXED. An UNTERMINATED ``<script>`` — one with no end
tag anywhere after it — still survives, as it did before. Matching it would mean
a ``<script[^>]*>.*`` fallback to end of message, and a stray ``<script`` in
prose would then eat the rest of the mail. That is a worse failure on real
input than the one it prevents.
"""

import re

#: How much markup a stripper is allowed to look at.
#:
#: NOT A CORRECTNESS BOUND. The cloud path caps the TEXT it produces at
#: ``_MAX_BODY_CHARS`` (4,000) immediately afterwards, and 64 KB of markup
#: yields far more than 4,000 characters of text on anything a person wrote.
#: This is a TIME bound.
#:
#: EVERY PATTERN IN THIS MODULE IS NON-GREEDY AGAINST A TERMINATOR THAT MAY NOT
#: EXIST, which is what makes it quadratic. An unterminated ``<script>`` — the
#: shape the module docstring above already records as deliberately unfixed —
#: costs a full scan to end of input per occurrence. Measured on
#: ``origin/main`` at ``3f32e0f3``, before any cap existed, through the real
#: functions:
#:
#:     234 KB of repeated unterminated ``<script>``      16.0 s
#:     215 KB of repeated unterminated ``<style>``       14.7 s
#:     246 KB of ordinary marketing markup               0.007 s
#:
#: So it is the SHAPE and not the size. At the cap the same input costs 0.08 s,
#: and the doubling curve is 0.08 / 0.30 / 1.2 / 4.8 s at 16 / 32 / 64 / 128 KB
#: for both the cloud and the desktop strippers.
#:
#: WHY THIS IS NOT THEORETICAL. Bodies are attacker-controlled — anyone who can
#: send the reader mail decides what arrives here — ``format="full"`` fetches
#: all of it, and the cloud path runs this once per message inside a serverless
#: budget the module's own comments put at 60 s. One message is enough.
#:
#: 32 KB, AND THE CORPUS IS THE WRONG INSTRUMENT FOR CHOOSING IT. The largest
#: ``text/html`` part in the mail corpus is 682 characters — 2% of this — so it
#: would bless any cap at all, because it contains no realistic ESP template.
#:
#: THE NUMBER THAT DECIDES THIS IS A RATIO, and it has to be measured rather
#: than asserted: an earlier draft of this note said "roughly 32:1" from
#: impression, and a genuinely 32:1 template at a 32 KB cap would yield 1,024
#: characters — a quarter of the window — so the claim refuted the number it was
#: printed next to. Measured on a table-heavy template with an inline style on
#: every cell, which is the shape real marketing mail has:
#:
#:     119,641 characters of markup  ->  26,797 of text   =  4.46 : 1
#:
#: Break-even for a full 4,000-character window at 32 KB is **8.19:1**, so that
#: template has 1.8x of headroom. Asking the question the cap is actually about:
#:
#:     cap 16 KB  ->  3,833 characters of text   <- SHORT of the window
#:     cap 32 KB  ->  7,457
#:     cap 64 KB  -> 14,704
#:
#: So 16 KB would have silently truncated real mail below the window the
#: product reads, and the corpus could not have said so. A template denser than
#: 8.19:1 still loses text, and that is a disclosed limit rather than a solved
#: one; the cap trades it for a bound on a 16-second worst case.
MAX_HTML_CHARS = 32 * 1024

#: A raw-text element left open by the truncation above.
#:
#: TRUNCATION CAN REPLACE THE MESSAGE WITH ITS OWN STYLESHEET, which is worse
#: than the timeout the cap exists to prevent and was found only by asking what
#: the cap does to CONTENT. If the cut lands inside a `<style>` block,
#: `SCRIPT_OR_STYLE` no longer matches — its end tag is past the cut — so `TAG`
#: strips the `<style>` opening and the stylesheet survives into the
#: classifier's window as prose. Measured on a 52 KB ESP template whose head
#: block straddles the cap: `extract_body_text` returned 4,000 characters, all
#: of them CSS, and the rejection sentence was gone.
#:
#: Cutting back to the opening tag is the fix, and it is the safe direction:
#: text before an unterminated stylesheet is real message text; text after it,
#: at this point, is unreachable anyway.
RAW_TEXT_OPEN = re.compile(r"<(script|style)\b", re.IGNORECASE)

# ``<script foo>…</script >``, ``<style>…</style/>``, either case, spanning
# newlines. ``\b`` after the name so ``<scripture>`` is not a script element;
# ``[\s/]`` in the end tag because whitespace and ``/`` are what actually
# terminate the tag name in a browser.
SCRIPT_OR_STYLE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1(?:[\s/][^>]*)?>",
    re.DOTALL | re.IGNORECASE,
)

# Every remaining tag. Left as it was on purpose: it has the same family of
# weaknesses (a bare ``<`` in prose, a ``>`` inside an attribute value), but its
# failure mode is text QUALITY — a few characters more or fewer in a snippet —
# not an element body surviving into the classifier's input. CodeQL did not
# flag it and widening it here would change legitimate mail.
def cap_html(html: str) -> str:
    """Truncate to :data:`MAX_HTML_CHARS` without leaving a stylesheet open.

    BELOW THE CAP, CHANGE NOTHING. An earlier version had no such guard and cut
    back on any unpaired token at any size, so a fifty-byte message lost its
    verdict — and the result was short but NOT empty, so `if text:` stored it
    and `bodies.get(id) or msg.snippet` never fell back. A real rejection
    scored `other`.

    ABOVE IT, THE QUESTION IS ASKED WITH ``SCRIPT_OR_STYLE`` ITSELF, and that is
    the whole design. Two earlier versions asked their own version of "is this
    element terminated" — first any `</script|style>` at all, then a
    name-matched `</style\\b` — and each disagreed with the stripper somewhere:
    ``</style-x>`` satisfies `\\b` and is NOT an appropriate end tag to a
    browser or to ``SCRIPT_OR_STYLE``, so the block read as closed and its CSS
    reached the classifier. Every such mismatch is a bug, and the only way to
    have none is to stop having a second opinion: remove what the stripper
    removes, and if a raw-text open SURVIVES that, it is unterminated by the
    only definition that matters here.

    AND THE ANSWER IS "" RATHER THAN A CUT-BACK. Cutting back to the opening tag
    keeps the text before it, which is real message text — but it also produces
    a short non-empty body, and that is precisely the shape that defeats the
    snippet fallback and turns a rejection into `other`. Returning nothing hands
    the message to ``msg.snippet``, which is Gmail's own summary of the VISIBLE
    text, so the reader's mail is still classified. Losing the head of an
    over-cap body is the smaller harm, and it is disclosed rather than implied:
    on the desktop paths there is no snippet to fall back to.
    """

    if len(html) <= MAX_HTML_CHARS:
        return html

    html = html[:MAX_HTML_CHARS]
    if RAW_TEXT_OPEN.search(SCRIPT_OR_STYLE.sub(" ", html)):
        return ""
    return html


TAG = re.compile(r"<[^>]+>")

WHITESPACE = re.compile(r"\s+")
