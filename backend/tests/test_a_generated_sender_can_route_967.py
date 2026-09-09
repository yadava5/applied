"""Every generated sender is an address a mail system could deliver (#967).

Two corpus families built an in-house sender by interpolating the employer TOKEN
straight into a domain, and roughly two thirds of the invented pool carries a
suffix ("Copperthwaitegate Labs"), so the token has a SPACE in it:

    careers@copperthwaitegate labs.example
    talent@quarrykeep dynamics.example

281 of 19,420 cases carried one — `update-from-another-domain` 171 and
`outreach-autoresponder` 110. No mail system could deliver any of them, and the
first of those two families exists to grade the DOMAIN reader: its whole subject
is an update arriving from somewhere other than the relay that opened the card,
so 171 of its 300 cases were exercising that reader with input production cannot
receive.

THE OBVIOUS REPAIR IS THE ONE THAT BREAKS IT, which is why this file asserts a
SHAPE and never a spelling. `pipeline._domain_brand` splits on dots, so the space
survives into the brand and the brand happens to equal the ground-truth token —
the cases resolved correctly BECAUSE the address was malformed. Deleting the
space yields a valid address whose brand `matches_company_token` REJECTS:

    careers@copperthwaitegate labs.example -> 'copperthwaitegate labs'  matches
    careers@copperthwaitegatelabs.example  -> 'copperthwaitegatelabs'   REJECTED
    careers@copperthwaitegate-labs.example -> 'copperthwaitegate-labs'  matches
    careers@copperthwaitegate.example      -> 'copperthwaitegate'       matches

so a naive fix would make 281 cases report a wrong company that is not a product
defect. The generator uses the LEADING WORD, which `matches_company_token`
accepts by the product's own rule — the same grouping `roll_up_applications`
applies when it collapses a company's mail under one token.

WHY NOTHING ELSE CAUGHT IT. `scripts/check_test_data.py` reads addresses, and an
interpolated one was invisible to it until #619 taught it templates — these are
built with an f-string at generate time and appear in no file as a literal.
Downstream, every reader lowercases and splits on `@` without ever rejecting
whitespace: `rules.is_ats_sender`, `pipeline.company_key`, `_domain_brand`. The
input is simply not one the product can receive, and nothing in the stack is
positioned to say so.
"""

from __future__ import annotations

import re

import pytest

from jobtracker.cloud.pipeline import company_key, matches_company_token

from tests.corpus_independent.generate import generate

#: Deliberately loose. The question is "could this route at all", not "is this
#: RFC 5322 valid" — a space, a comma or an empty domain is what this catches,
#: and tightening it toward real validation would start rejecting addresses the
#: product handles.
ROUTABLE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?")


@pytest.fixture(scope="module")
def cases():
    return generate()


def test_every_generated_sender_is_an_address_that_could_route(cases) -> None:
    """The gate. It reds on 281 cases before #967 and on none after."""

    malformed = [
        (c.family, c.message_id, c.sender)
        for c in cases
        if not ROUTABLE.fullmatch(c.sender or "")
    ]
    assert not malformed, (
        f"{len(malformed)} generated senders are not addresses any mail system "
        f"could deliver:\n  "
        + "\n  ".join(f"{f} {m} {s!r}" for f, m, s in malformed[:8])
    )


def test_the_gate_can_actually_fail(cases) -> None:
    """THE CONTROL, because a regex that matched everything would pass silently.

    The exact string the generator used to produce is asserted to be REFUSED,
    and a well-formed neighbour to be accepted. Without this, widening
    ``ROUTABLE`` by one character class would empty the gate above and nothing
    would say so.
    """

    assert not ROUTABLE.fullmatch("careers@copperthwaitegate labs.example")
    assert ROUTABLE.fullmatch("careers@copperthwaitegate.example")
    assert not ROUTABLE.fullmatch("careers@")
    assert not ROUTABLE.fullmatch("no-at-sign.example")


def test_the_leading_word_still_resolves_the_employer(cases) -> None:
    """The half a shape check cannot see: the fix must not cost resolution.

    `matches_company_token` accepts a match on the leading word, so a domain
    built from it identifies "Copperthwaitegate Labs" exactly as the whole token
    did. Asserted against the product's own function over every case in the two
    families the fix touches, rather than argued in the docstring.
    """

    touched = [
        c
        for c in cases
        if c.employer
        and c.family in {"outreach-autoresponder", "update-from-another-domain"}
    ]
    assert len(touched) > 600, (
        f"{len(touched)} cases in the two families carry an employer; this test "
        "is worth its population and the population moved"
    )
    unresolved = [
        (c.family, c.message_id, c.sender, c.employer)
        for c in touched
        if not matches_company_token(
            company_key(c.sender, c.subject, c.sender_name), c.employer
        )
    ]
    assert not unresolved, (
        f"{len(unresolved)} of {len(touched)} no longer resolve the employer "
        f"their ground truth names: {unresolved[:5]}"
    )
