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
on every cell and runs about **4.46:1** markup to text (measured, not asserted). Measured on a template of
that shape: a 16 KB cap yields **3,833** characters, SHORT of the 4,000 the
classifier is given; 32 KB yields 7,457. The first version of this change
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
#:
#: BARE `<` AND NOT `<script foo>`, and the reason is a trap this file walked
#: into. `<script foo>` repeated WAS the worst shape, and `cap_html` now cuts
#: everything after the first unterminated `<script` — so that payload costs
#: 0.000 s here and this test would have passed while measuring nothing. The
#: densest shape against the surviving patterns is a bare `<`, which maximises
#: `TAG`'s `<[^>]+>` start positions and survives the cut-back untouched
#: (there is no raw-text element to cut back to). Measured: 0.44 s, against
#: 0.000 s for the old payload and 28 s for either with the cap removed.
ADVERSARIAL = "<" * 262144

#: The same length in markup a real sender emits. Without this the ceiling
#: below would pass on a machine that is merely fast, and prove nothing about
#: the shape.
BENIGN = ("<p>Hello Alex, thank you for applying.</p>" * 8000)[: len(ADVERSARIAL)]
assert len(BENIGN) == len(ADVERSARIAL), "the control is not size-matched"

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
#: cell. Measured on this very block: 119,641 characters of markup to 26,797
#: of text, **4.46:1** — not the "roughly 32:1" an earlier draft asserted from
#: impression, which would have meant a quarter of the window at this cap.
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
    change was sized that way and chose 16 KB, which yields 3,833 characters on
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
    assert "Thank you for applying" in text, (
        "the window is full but it is not the message. Counting characters is "
        "not the assertion — see the stylesheet test below, where 4,000 "
        "characters of CSS satisfied a length check."
    )


def test_a_truncated_stylesheet_does_not_reach_the_classifier_as_prose() -> None:
    """The hazard the cap ITSELF introduced, and the reason a length check is
    not a correctness check.

    If the cut lands inside a `<style>` block, that block is no longer
    terminated, `SCRIPT_OR_STYLE` stops matching it, `TAG` strips the opening
    tag, and the stylesheet survives into the classifier's window as prose.
    Measured on the payload below before `cap_html` existed:
    `extract_body_text` returned **4,000 characters, every one of them CSS**,
    and the rejection sentence was gone — while
    `test_the_cap_still_yields_the_window_the_classifier_reads` PASSED, because
    4,000 characters is 4,000 characters.

    `cap_html` cuts back to the opening tag instead. The body then extracts to
    nothing, which is the safe answer and not a lossy one: production reads
    `bodies.get(id) or msg.snippet`, so the message is classified from Gmail's
    own snippet of the VISIBLE text.

    MUTATION: replace `cap_html(html)` with `html[:MAX_HTML_CHARS]` in any
    stripper -> that row reds with CSS in the output.
    """

    import base64

    from jobtracker.cloud.gmail_client import extract_body_text

    css = "@media only screen and (max-width:620px){.mcnTextContent{padding:9px 18px}} " * 700
    doc = (
        "<html><head><style>" + css + "</style></head><body>"
        "<p>Hi Ayush,</p><p>Unfortunately, we have decided not to move forward "
        "with your application at this time.</p></body></html>"
    )
    assert doc.index("</style>") > MAX_HTML_CHARS, (
        "the stylesheet no longer straddles the cap, so this proves nothing"
    )

    for where, strip in STRIPPERS.items():
        assert "@media" not in strip(doc), (
            f"{where} let a truncated stylesheet through as prose"
        )

    payload = {
        "mimeType": "text/html",
        "body": {"data": base64.urlsafe_b64encode(doc.encode()).decode()},
    }
    assert "@media" not in extract_body_text(payload), (
        "the production entry hands the classifier CSS"
    )


# ── what truncation must never do ────────────────────────────────────────────
#
# Three rounds of this function shipped three different wrong answers, and every
# one was found by adjudicating against a real browser rather than against these
# payloads. The rules that survived:
#
#   below the cap        change nothing at all
#   above it, unsure     return "" and let `msg.snippet` speak
#   "is it terminated"   ask SCRIPT_OR_STYLE, never a second opinion
#
# The third is the one that closes the class. Two earlier versions carried their
# own close-tag pattern — first any `</script|style>`, then a name-matched
# `</style\b` — and each disagreed with the stripper somewhere. `</style-x>`
# satisfies `\b` and is not an appropriate end tag to a browser or to
# SCRIPT_OR_STYLE, so the block read as closed and 4,000 characters of CSS went
# to the classifier.

#: Sub-cap markup that an earlier version truncated anyway. Each holds a token
#: that LOOKS like a raw-text open and is not one a browser would honour here.
SUB_CAP = {
    "comment holding a style tag": "<p>Hi</p><!-- <style> --><p>REJECTEDWORD.</p>",
    "script token inside an href": '<p>Hi</p><a href="/x?t=<script">l</a><p>REJECTEDWORD.</p>',
    "style inside noscript": "<p>Hi</p><noscript><style>a{}</noscript><p>REJECTEDWORD.</p>",
    "an entity, not a tag": "<p>A literal &lt;style&gt; is discussed.</p><p>REJECTEDWORD.</p>",
}

#: Over-cap markup carrying an unterminated raw-text element. The answer must be
#: EMPTY — never a short non-empty stub, which is what defeats the snippet
#: fallback and turned a rejection into `other`.
_PAD = "<p>Filler paragraph number one.</p>" * 1200
OVER_CAP_UNTERMINATED = {
    "comment holding a style tag": "<!-- <style> -->",
    "script token inside an href": '<a href="/x?t=<script">l</a>',
    "style inside noscript": "<noscript><style>a{}</noscript>",
    "style inside svg": "<svg><style>a{}</svg>",
    "a CDATA section": "<![CDATA[ <style> ]]>",
    "an ESP build comment": "<!-- start: hero module <style> -->",
}

#: A close tag of the right NAME and the wrong SHAPE. `</style\b` accepts every
#: one of these; a browser and `SCRIPT_OR_STYLE` accept none, so the stylesheet
#: is still open and its body must not reach the classifier.
WRONG_SHAPE_CLOSE = ("</style-x>", "</style:1>", "</style.y>", '</style"y>', "</style!y>")


@pytest.mark.parametrize("where", sorted(STRIPPERS))
@pytest.mark.parametrize("shape", sorted(SUB_CAP))
def test_a_message_below_the_cap_is_left_completely_alone(where: str, shape: str) -> None:
    """MUTATION: drop the `len(html) <= MAX_HTML_CHARS` guard -> every row reds.

    An earlier version cut back on any unpaired token at any size, so a
    fifty-byte message lost its verdict — and the result was short but NOT
    empty, so `if text:` stored it and `bodies.get(id) or msg.snippet` never
    fired. A real rejection scored `other`.
    """

    markup = SUB_CAP[shape]
    assert len(markup) < MAX_HTML_CHARS, "this payload is not sub-cap"
    assert "REJECTEDWORD" in STRIPPERS[where](markup)


@pytest.mark.parametrize("where", sorted(STRIPPERS))
@pytest.mark.parametrize("shape", sorted(OVER_CAP_UNTERMINATED))
def test_an_over_cap_body_it_cannot_read_becomes_empty_and_not_a_stub(
    where: str, shape: str
) -> None:
    """Empty, or the whole message — never a stub.

    A short non-empty body is the worst of the three outcomes: production stores
    it and never reaches `msg.snippet`, so the reader's mail is classified from
    a fragment. `""` hands the message to Gmail's own summary of the VISIBLE
    text instead.

    MUTATION: cut back to the opening tag instead of returning "" -> every row
    reds with a stub.
    """

    doc = (
        "<html><body><p>Hi Ayush,</p>"
        + OVER_CAP_UNTERMINATED[shape]
        + "<p>You were REJECTEDWORD.</p>"
        + _PAD
        + "</body></html>"
    )
    assert len(doc) > MAX_HTML_CHARS, "this payload does not exceed the cap"

    text = STRIPPERS[where](doc)
    assert text == "" or "REJECTEDWORD" in text, (
        f"{where} returned a {len(text)}-character stub with the verdict gone: "
        f"{text[:80]!r}. A stub defeats the snippet fallback."
    )


@pytest.mark.parametrize("where", sorted(STRIPPERS))
@pytest.mark.parametrize("close", WRONG_SHAPE_CLOSE)
def test_a_close_tag_of_the_wrong_shape_does_not_count_as_terminated(
    where: str, close: str
) -> None:
    """MUTATION: give `cap_html` its own `</script|style\b` close pattern
    instead of asking `SCRIPT_OR_STYLE` -> every row reds with the poison out.

    This is the whole reason the check delegates: any second opinion about what
    "terminated" means is a place the two can disagree, and every disagreement
    is a bug.
    """

    # THE FAKE CLOSE MUST SIT INSIDE THE WINDOW, and the first version of this
    # payload put it past the cap — where BOTH the right answer and the wrong
    # one return "", so the row could not tell them apart. A control that
    # cannot return positive is this repository's signature defect and it very
    # nearly shipped inside the test written to catch one.
    doc = (
        "<html><body><p>REJECTEDWORD</p><style>@media{a{}} POISONWORD"
        + close
        + _PAD
        + "</body></html>"
    )
    assert len(doc) > MAX_HTML_CHARS, "this payload does not exceed the cap"
    assert doc.index(close) < MAX_HTML_CHARS, (
        "the fake close is past the cap, where every implementation returns "
        "empty and this row grades nothing"
    )

    assert "POISONWORD" not in STRIPPERS[where](doc)


def test_the_vendored_mirror_carries_the_same_stripper() -> None:
    """The `ml/demo/space` copy is a fifth stripper and is not in `STRIPPERS`.

    It cannot be imported here — it is a vendored package, not a dependency —
    so the property asserted is the one that makes its absence safe: the file is
    byte-identical to the one these tests do exercise.
    """

    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    shipped = root / "backend/jobtracker/email_clients/html_text.py"
    mirror = root / "ml/demo/space/jobtracker/email_clients/html_text.py"
    assert mirror.exists(), "the vendored mirror is gone; drop this test with it"
    assert mirror.read_bytes() == shipped.read_bytes(), (
        "the vendored stripper has drifted from the one under test, so nothing "
        "in this file says anything about it"
    )
