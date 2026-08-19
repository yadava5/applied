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
