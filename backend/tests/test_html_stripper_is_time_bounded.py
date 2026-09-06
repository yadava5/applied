"""Every HTML stripper is bounded in TIME, not only in output size.

WHAT WAS WRONG. Each stripper is a chain of non-greedy patterns matched against
a terminator that may not exist. `SCRIPT_OR_STYLE`'s `.*?</script>` is the
clearest: on an unterminated `<script>` — a shape `html_text.py`'s docstring
already records as deliberately unfixed — it scans to end of input and fails,
once per occurrence. That is quadratic, and nothing bounded the input.

Measured on `origin/main` at `3f32e0f3`, before any cap existed, through the
real functions:

    234 KB of repeated unterminated `<script>`      16.0 s
    215 KB of repeated unterminated `<style>`       14.7 s
    246 KB of ordinary marketing markup             0.007 s

It is the SHAPE and not the size, which is why a cap is the fix: nothing about
the content can be tested cheaply, but the cost is bounded by the length.

WHY IT MATTERS. Bodies are attacker-controlled — anyone who can send the reader
mail decides what arrives — `format="full"` fetches all of it, and the cloud
path runs this once per message inside a serverless budget the module's own
comments put at 60 seconds. One message is enough.

WHAT THIS FILE ASSERTS, and the two halves are different claims:

1. the bound is APPLIED — the strippers do not read past `MAX_HTML_CHARS`;
2. the bound is EFFECTIVE — adversarial input at the cap stays under a wall
   clock ceiling, with a size-matched benign control proving the ceiling is not
   just "this machine is fast".

The second is a timing assertion, so it is deliberately loose: a 4-second
ceiling against a measured ~0.3 s leaves an order of magnitude of headroom for a
slow or loaded runner while still failing outright if the cap is removed (16 s
on 234 KB, and the payload here is larger).

AND THE CAP IS A CORRECTNESS QUESTION TOO, which is why a third test asks it.
The obvious sizing argument — "the largest `text/html` part in the corpus is 682
characters, so anything is generous" — is wrong, because the corpus holds no
realistic ESP template. Real marketing mail is table markup with an inline style
on every cell and runs about **32:1** markup to text. Measured on a template of
that shape: a 16 KB cap yields **3,792** characters, SHORT of the 4,000 the
classifier is given; 32 KB yields 7,416. The first version of this change
capped at 16 KB and would have truncated real mail below the window the product
reads, silently, with every test green.
"""

from __future__ import annotations

import time

import pytest

from jobtracker.cloud.gmail_client import _MAX_HTML_CHARS
from jobtracker.cloud.gmail_client import _html_to_text as cloud_html_to_text
from jobtracker.email_clients.gmail import GmailClient
from jobtracker.email_clients.html_text import MAX_HTML_CHARS
from jobtracker.email_clients.icloud import ICloudClient
from jobtracker.email_clients.parser import EmailParser

STRIPPERS = {
    "email_clients.parser._html_to_text": EmailParser()._html_to_text,
    "email_clients.gmail._strip_html": GmailClient()._strip_html,
    "email_clients.icloud._strip_html": ICloudClient()._strip_html,
    "cloud.gmail_client._html_to_text": cloud_html_to_text,
}

#: Well past the cap, so the cap is what decides the cost.
ADVERSARIAL = "<script foo>" * 40000

#: The same length in markup a real sender emits. Without this the ceiling
#: below would pass on a machine that is merely fast, and prove nothing about
#: the shape.
BENIGN = ("<p>Hello Alex, thank you for applying.</p>" * 12000)[: len(ADVERSARIAL)]

#: Loose on purpose — see the module docstring. Removing the cap takes the
#: adversarial payload to tens of seconds, so this fails by a wide margin
#: rather than flickering.
CEILING_SECONDS = 4.0


def test_the_two_copies_agree_on_the_bound() -> None:
    """`cloud/` does not import from `email_clients/`, so the number is spelled
    twice. Two ceilings on one path is the drift a shared constant exists to
    prevent, and here it cannot be shared."""

    assert _MAX_HTML_CHARS == MAX_HTML_CHARS


@pytest.mark.parametrize("where", sorted(STRIPPERS))
def test_no_stripper_reads_past_the_bound(where: str) -> None:
    """The bound is APPLIED.

    Marker text placed just past the cap must not come out. This reds if a
    stripper is added without the cap, which is how three of the four came to
    be unbounded in the first place.

    MUTATION: delete the `html[:MAX_HTML_CHARS]` line from any stripper -> that
    stripper's row reds.
    """

    marker = "PASTTHECAP"
    payload = "<p>a</p>" * (MAX_HTML_CHARS // 8 + 100) + f"<p>{marker}</p>"
    assert len(payload) > MAX_HTML_CHARS, "the payload does not reach the cap"

    assert marker not in STRIPPERS[where](payload)


@pytest.mark.parametrize("where", sorted(STRIPPERS))
def test_adversarial_markup_stays_under_the_ceiling(where: str) -> None:
    """The bound is EFFECTIVE.

    MUTATION: delete the cap -> this reds by a factor of tens, not by a hair.
    """

    strip = STRIPPERS[where]
    start = time.perf_counter()
    strip(ADVERSARIAL)
    adversarial = time.perf_counter() - start

    assert adversarial < CEILING_SECONDS, (
        f"{where} took {adversarial:.2f}s on {len(ADVERSARIAL) // 1024} KB of "
        f"unterminated markup. The cap is {MAX_HTML_CHARS // 1024} KB; either "
        "it is not applied here or a pattern has become more expensive."
    )


@pytest.mark.parametrize("where", sorted(STRIPPERS))
def test_the_ceiling_is_about_the_shape_and_not_the_machine(where: str) -> None:
    """The control on the test above.

    A ceiling that ordinary markup also brushes would pass for the wrong
    reason. Same byte count, ordinary shape: it must be far cheaper, which is
    what makes the adversarial number a statement about backtracking rather
    than about this laptop.
    """

    strip = STRIPPERS[where]
    start = time.perf_counter()
    strip(BENIGN)
    benign = time.perf_counter() - start

    assert benign < CEILING_SECONDS / 4, (
        f"{where} took {benign:.2f}s on ORDINARY markup of the same length. "
        "The adversarial ceiling in this module is then meaningless."
    )


# ── the other half of choosing a number ─────────────────────────────────────

#: A table-heavy block in the shape a real ESP emits: an inline style on every
#: cell, which is what makes marketing markup roughly 32:1 against its own text.
_ESP_CELL = (
    '<tr><td align="center" valign="top" style="padding:12px 24px;font-family:'
    "'Helvetica Neue',Helvetica,Arial,sans-serif;font-size:14px;line-height:22px;"
    'color:#333333;border-bottom:1px solid #eeeeee;mso-line-height-rule:exactly">'
    "Thank you for applying to the role. We will be in touch shortly.</td></tr>"
)

#: What the cloud path hands the classifier. Imported rather than retyped: two
#: ceilings on one pipeline is the drift these constants exist to prevent.
from jobtracker.cloud.gmail_client import _MAX_BODY_CHARS  # noqa: E402


def test_the_cap_still_yields_the_window_the_classifier_reads() -> None:
    """The cap must not truncate real mail below `_MAX_BODY_CHARS`.

    THE CORPUS CANNOT ANSWER THIS. Its largest `text/html` part is 682
    characters, so it would bless any cap at all — and the first version of this
    change was sized that way and chose 16 KB, which yields 3,792 characters on
    the template below. Every test was green; the loss would have been silent
    and would have landed on exactly the long, heavily-styled mail whose verdict
    sits furthest down.

    MUTATION: set the cap to 16 KB -> this reds while every timing test above
    still passes, which is the direction that names the trade.
    """

    doc = "<html><body><table>" + _ESP_CELL * 400 + "</table></body></html>"
    assert len(doc) > 2 * MAX_HTML_CHARS, "the template no longer exceeds the cap"

    text = cloud_html_to_text(doc)

    assert len(text) >= _MAX_BODY_CHARS, (
        f"{MAX_HTML_CHARS // 1024} KB of ESP-shaped markup yields {len(text)} "
        f"characters, short of the {_MAX_BODY_CHARS} the classifier is given. "
        "The cap is now truncating real mail below the product's own window."
    )
