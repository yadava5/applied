r"""``</script >`` is a script end tag, and every stripper here missed it.

CodeQL ``py/bad-tag-filter``, alerts 52 / 53 / 56 (and the vendored mirrors 51 /
54 / 55 under ``ml/demo/space/``). HTML5 leaves the script-data-end-tag-name
state on whitespace, ``/`` or ``>``, so ``</script >``, ``</style\n>`` and
``</script/>`` all close the element in a browser. A regex spelling the end tag
as the literal ``</script>`` matches none of them, the non-greedy body then runs
past the real end of the element (or fails to match at all), and the element's
contents survive into the extracted text.

WHAT THAT TEXT IS. Every caller of these functions is text extraction, not
rendering: snippets and classifier input. ``EmailParser._clean_html`` is the
rendering path and is untouched by any of this. So the ceiling is
attacker-influenced text reaching the keyword counts in ``classifier.rules`` and
``classifier.hybrid`` — a ``<style>`` block stuffed with lifecycle vocabulary
scoring as prose. Misclassification, not injection.

FIVE COPIES, one bug. The three CodeQL flagged, plus ``cloud.gmail_client``
(the deployed path, which spells the same regex with a backreference and was
not flagged) and the mirror in ``tests/corpus/mail.py``. Parametrising over all
five is the point: a fix that lands on three of them leaves the production
ingest path carrying the defect.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud.gmail_client import _html_to_text as cloud_html_to_text
from jobtracker.email_clients.gmail import GmailClient
from jobtracker.email_clients.icloud import ICloudClient
from jobtracker.email_clients.parser import EmailParser
from tests.corpus.mail import html_to_text as corpus_html_to_text

STRIPPERS = {
    "email_clients.parser._html_to_text": EmailParser()._html_to_text,
    "email_clients.gmail._strip_html": GmailClient()._strip_html,
    "email_clients.icloud._strip_html": ICloudClient()._strip_html,
    "cloud.gmail_client._html_to_text": cloud_html_to_text,
    "tests.corpus.mail.html_to_text": corpus_html_to_text,
}

# Each payload closes its element the way a browser would, and each hides a
# lifecycle phrase the rules layer scores. ``SECRETWORD`` is the marker: if it
# comes out, the element body reached the classifier.
BYPASSES = {
    "space before gt": "<p>Hello</p><script >var SECRETWORD = 1;</script >",
    "newline before gt": "<p>Hello</p><style\n>.a { content: 'SECRETWORD' }</style\n>",
    "self closing end tag": "<p>Hello</p><script>var SECRETWORD = 1;</script/>",
    "attribute on end tag": "<p>Hello</p><script>var SECRETWORD = 1;</script foo>",
    "tab before gt": "<p>Hello</p><script\t>var SECRETWORD = 1;</script\t>",
    "uppercase and space": "<p>Hello</p><SCRIPT >var SECRETWORD = 1;</SCRIPT >",
}


@pytest.mark.parametrize("where", sorted(STRIPPERS))
@pytest.mark.parametrize("shape", sorted(BYPASSES))
def test_element_body_never_survives_a_whitespace_end_tag(where: str, shape: str) -> None:
    """The element's contents must not reach the extracted text."""

    text = STRIPPERS[where](BYPASSES[shape])

    assert "SECRETWORD" not in text, (
        f"{where} let a <script>/<style> body through on `{shape}`: {text!r}"
    )
    assert "Hello" in text, f"{where} dropped the surrounding prose on `{shape}`"


# THE ONE PROBE WHOSE ANSWER IS NOT SHARED — #430.
#
# ``cloud.gmail_client._html_to_text`` turns block-level markup into a newline
# BEFORE tags are stripped, because the classifier's quote detection is
# line-oriented and an HTML-only message spells its lines in tags; the desktop
# strippers feed rendering and snippets and still flatten. The corpus entry is
# the cloud function itself (``tests/corpus/mail.py`` re-exports it), so it
# answers the same. The interior space is the one ``_TAG`` leaves where the
# second ``<div>`` opened.
#
# WRITTEN AS A PER-STRIPPER VALUE, not as a comparison with the newlines
# normalised away. Erasing the difference to make one assertion serve five
# would stop this guard pinning any of them — see
# ``tests/test_the_quote_survives_the_html_body.py`` for what the cloud copy
# now has to do.
BLOCK_BOUNDARY = {
    "email_clients.parser._html_to_text": "a b",
    "email_clients.gmail._strip_html": "a b",
    "email_clients.icloud._strip_html": "a b",
    "cloud.gmail_client._html_to_text": "a\n\n b",
    "tests.corpus.mail.html_to_text": "a\n\n b",
}


@pytest.mark.parametrize("where", sorted(STRIPPERS))
def test_ordinary_markup_is_unchanged(where: str) -> None:
    """Equivalence guard: the shapes real mail actually uses still behave.

    A fix for the bypass above that also rewrote entity handling or ate a bare
    ``<`` would be a behaviour change on legitimate mail, which is the thing
    these paths cannot afford — they decide how applications are filed.
    """

    strip = STRIPPERS[where]

    assert strip("<style>p { color: red }</style><p>body</p>") == "body"
    assert strip("<script>evil()</script><p>Offer</p>") == "Offer"
    assert strip("<p>Interview</p>") == "Interview"
    assert strip("<div>a</div>\n<div>b</div>") == BLOCK_BOUNDARY[where]
    # A tag name that merely STARTS with "script" is not a script element.
    assert "keep" in strip("<scripture>keep</scripture>")
