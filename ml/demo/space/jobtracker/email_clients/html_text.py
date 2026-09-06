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
#: ``text/html`` part in the mail corpus is 682 characters, which would argue
#: for almost any cap — and it argues wrongly, because the corpus contains no
#: realistic ESP template. Real marketing mail is table markup with an inline
#: style on every cell, and its markup-to-text ratio is roughly **32:1**.
#:
#: Measured on a table-heavy template of that shape, asking the only question
#: that matters — does the cap still yield the 4,000 characters the classifier
#: is given?
#:
#:     cap 16 KB  ->  3,792 characters of text   <- SHORT of the window
#:     cap 32 KB  ->  7,416
#:     cap 64 KB  -> 14,670
#:
#: So 16 KB would have silently truncated real mail below the window the
#: product reads, and the corpus could not have said so. 32 KB clears it with
#: 1.8x of margin and costs 0.30 s on the adversarial shape.
MAX_HTML_CHARS = 32 * 1024

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
TAG = re.compile(r"<[^>]+>")

WHITESPACE = re.compile(r"\s+")
