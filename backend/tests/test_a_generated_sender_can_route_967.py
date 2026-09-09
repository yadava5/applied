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
so 171 of its 300 cases were exercising that reader with an address no
legitimate sender emits.

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
whitespace: `rules.is_ats_sender`, `pipeline.company_key`, `_domain_brand`.

AND "PRODUCTION CANNOT RECEIVE IT" WOULD BE TOO STRONG, which is worth stating
because the weaker claim is the true one. Routing is the SMTP envelope's job and
the `From` HEADER is sender-controlled prose, so mail whose header carries a
spaced domain does arrive — what no legitimate corporate sender emits is this
shape, and these two families simulate exactly that genre. Adversarial `From`
values are a `hostile-*` family's subject, not this one's.
"""

from __future__ import annotations

import re

import pytest

from jobtracker.cloud.pipeline import company_key, matches_company_token

from tests.corpus_independent.generate import generate

#: Deliberately loose. The question is "could this route at all", not "is this
#: RFC 5322 valid" — a space, a comma, an empty label or a domain with no dot at
#: all is what this catches, and tightening it toward real validation would start
#: rejecting addresses the product handles.
#:
#: THE DOT IS PART OF THE SHAPE, and an earlier draft left it out. Without the
#: repeated group `talent@quarrykeep` — the generator with `.example` dropped
#: from either f-string — full-matches, and so does `acme..example`, whose empty
#: label no resolver can look up. Both are mutations one keystroke away from the
#: two lines this file exists to gate, and neither is an address a mail system
#: could deliver. Nothing in the corpus is dotless, so requiring one costs
#: nothing today and closes the hole.
ROUTABLE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")


def routable(sender: str | None) -> bool:
    """Is this an address a mail system could deliver?

    ONE FUNCTION, TWO READERS, and that is the point rather than a convenience.
    The sweep below and the control beside it both ask this question, and while
    they each called ``ROUTABLE`` themselves they shared the pattern and not the
    METHOD: turning the sweep's ``fullmatch`` into ``match`` or ``search`` — an
    ordinary refactor slip, and exactly what a port to another engine does —
    would let `careers@copperthwaitegate labs.example` through on its prefix
    while the control, calling ``fullmatch`` on its own, stayed green. A gate
    and its control that share a constant but not the call are two readers of
    one number, which this repository has already paid for twice.
    """

    return ROUTABLE.fullmatch(sender or "") is not None


@pytest.fixture(scope="module")
def cases():
    return generate()


def test_every_generated_sender_is_an_address_that_could_route(cases) -> None:
    """The gate. It reds on 281 cases before #967 and on none after."""

    malformed = [
        (c.family, c.message_id, c.sender)
        for c in cases
        if not routable(c.sender)
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

    assert not routable("careers@copperthwaitegate labs.example")
    assert routable("careers@copperthwaitegate.example")
    assert not routable("careers@")
    assert not routable("no-at-sign.example")
    # The two mutations the first draft of ``ROUTABLE`` accepted: a domain with
    # no dot, which is what dropping `.example` from either f-string produces,
    # and an empty label. Both are one keystroke from the lines this file gates.
    assert not routable("talent@quarrykeep")
    assert not routable("talent@quarrykeep..example")
    # And the leading-word address the fix actually emits, so a tightening that
    # went one step further would red here rather than in the sweep.
    assert routable("talent@quarrykeep.example")


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


def test_the_unresolved_counter_moves_when_an_employer_stops_resolving(cases) -> None:
    """THE DIRECTION CONTROL for `RECORDED_EMPLOYER_SPELLINGS["unresolved"]`.

    That pin exists to separate a token MERGE from a token LOSS, because the
    three counters beside it cannot: a token that merges into its neighbour and
    a token whose cases stop resolving at all both remove exactly one token and
    one display from the sums. Only the count of cases resolving NO employer
    says which happened.

    A recorded equality that never moves is the thing this repository keeps
    finding, so the counter is shown moving here. The mutation is the smallest
    honest one — one case arrives from a free-mail
    provider with nothing else to read — and it
    must raise the count by exactly one.

    The other half of the pair is a mutation of the GENERATOR rather than of a
    case, and it was run rather than argued: replacing this issue's
    ``token.split()[0]`` with the naive ``token.replace(" ", "")`` reds
    ``tokens`` at 9819 while ``unresolved`` holds at 403 — the address becomes
    routable and resolves to the WRONG token, which is a re-key and not a loss.
    Two assertions, two causes, and neither one alone can tell them apart.
    """

    import dataclasses

    from jobtracker.cloud import pipeline

    def unresolved(cs) -> int:
        return sum(
            1
            for c in cs
            if pipeline.resolve_employer(c.sender, c.subject, c.sender_name) is None
        )

    before = unresolved(cases)
    victim = next(
        c
        for c in cases
        if pipeline.resolve_employer(c.sender, c.subject, c.sender_name) is not None
    )
    # THE REFUSAL IS SOURCED FROM THE PRODUCT'S OWN SET, not spelled here. A
    # hard-coded free-mail domain would be a new published address the test-data
    # gate has to be told about, and worse, it would keep passing if
    # `CONSUMER_WEBMAIL_DOMAINS` ever stopped containing it — the mutation would
    # silently stop being a blinding and this control would go green on nothing.
    # The `.example` TLD keeps the address inside the reserved band; the brand is
    # what `resolve_employer` refuses on.
    webmail = sorted(pipeline.CONSUMER_WEBMAIL_DOMAINS)[0]
    blinded = dataclasses.replace(
        victim,
        sender=f"someone@{webmail}.example",
        subject="hello",
        sender_name=None,
    )
    after = unresolved([blinded if c is victim else c for c in cases])
    assert after == before + 1, (
        f"blinding one case's employer moved `unresolved` {before} -> {after}, "
        "expected exactly one. The counter that separates a merge from a loss "
        "is not responding to a loss."
    )
