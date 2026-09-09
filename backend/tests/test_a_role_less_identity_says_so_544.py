"""An identity keyed on a job title no message names (#544).

``identity`` is ground truth for SPLIT and MERGE, not decoration on a card:
two cases sharing it MUST land on one card, two with different keys MUST NOT.
So the key is an assertion about the product's own rule,
``(employer, req_id or role_token)``.

#533 stopped grading 146 cards against a title their mail never spells, by
nulling ``role_truth`` and asserting a blank card instead. It deliberately left
the KEY alone, and the key went on naming the title:

    marshburyshore|Software Development Engineer I - AI/ML Network Infrastructure

for mail whose entire text is "your details have been added to our database".
81 of those identities hold two messages and **none of them is threaded**, so
what actually joined the pair was employer plus an EMPTY role token. The
assertion passed, and not for the reason it stated. The day the extractor
learned to read a role out of one of the two messages and not the other, the
pair would split — and the corpus would report that split correctly while the
key that was supposed to predict it had been describing something else all
along.

WHAT THIS FILE ASSERTS is that the two derivations agree: an identity whose role
no message spells carries the ``__norole__`` sentinel, and ``names_no_role`` is
read off that sub-key rather than set beside it. One definition, one place.

WHY THE COLLAPSE IS A RENAME AND NOT A MERGE, measured rather than assumed:
0 of the 260 identities the rule touches shares an employer token with any other
identity, touched or untouched, so no two applications collapse onto one key.
That is checked below at the current seed and refused outright in
``_settle_role_reachability`` for any future family that would create one.
"""

from __future__ import annotations

import collections

import pytest

from tests.corpus_independent import generate as G
from tests.corpus_independent.generate import _ROLE_SENTINEL, generate

#: What the settler moves at seed 20260822: 260 identities over 341 messages,
#: 81 of them pairs. Recorded so that a family which quietly stops naming its
#: role — or starts — is visible as a number rather than as silence.
RECORDED_NO_ROLE = {"identities": 260, "messages": 341, "pairs": 81}


@pytest.fixture(scope="module")
def cases():
    return generate()


def _unreachable_before_the_settler():
    """The identities the settler touches, rebuilt WITHOUT it.

    The families are run directly rather than through :func:`generate`, because
    ``generate`` is what applies the correction and the question here is what it
    was applied TO.
    """

    b = G._Builder(20260822)
    for _name, family, n in G._FAMILIES:
        family(b, n)
    by: dict[str, list] = {}
    for case in b.cases:
        if case.identity is not None and case.role_truth is not None:
            by.setdefault(case.identity, []).append(case)
    return {
        identity: group
        for identity, group in by.items()
        if not any(
            " ".join(group[0].role_truth.split()).lower() in G._readable_text(c)
            for c in group
        )
    }


def test_no_identity_is_keyed_on_a_role_its_mail_never_names(cases) -> None:
    """The defect, stated as the product's own rule.

    A key naming a role asserts that role_token is what joins the card's mail.
    For these cases nothing can read that token out of any message on the card,
    so the assertion is unfalsifiable by construction — which is the thing #540
    calls ground truth that rewards guessing.
    """

    offenders = [
        (c.family, c.message_id, c.identity)
        for c in cases
        if c.names_no_role
        and c.identity is not None
        and not _ROLE_SENTINEL.match(c.identity.partition("|")[2])
    ]
    assert not offenders, (
        f"{len(offenders)} cases assert a blank card while their identity key "
        f"names a job title:\n  "
        + "\n  ".join(f"{f} {m} {i!r}" for f, m, i in offenders[:8])
    )


def test_names_no_role_is_read_off_the_sub_key_and_nowhere_else(cases) -> None:
    """ONE DEFINITION. The sub-key decides, in the builder and in the settler.

    Before #544 the settler set ``names_no_role`` beside a key that still named
    a role, so the corpus held two answers to "does this mail name a job" and
    they disagreed on 341 messages. This asserts they cannot disagree again:
    every case's flag is exactly what its own sub-key says.
    """

    for case in cases:
        if case.identity is None:
            continue
        sub_key = case.identity.partition("|")[2]
        assert case.names_no_role == bool(_ROLE_SENTINEL.match(sub_key)), (
            f"{case.message_id} ({case.family}) has names_no_role="
            f"{case.names_no_role} and sub-key {sub_key!r}. The flag and the "
            "key are two readings of one fact and they must not diverge."
        )


def test_the_collapse_renames_and_never_merges(cases) -> None:
    """A key change moves ground truth about SPLIT and MERGE, so measure it.

    The collapse is safe only while no employer holds two identities the rule
    touches, and no touched identity shares an employer with an untouched one.
    Both are counted here at the current seed rather than trusted, because a
    family added later is exactly what would break it — and the settler itself
    raises rather than merging if it ever does.
    """

    touched = _unreachable_before_the_settler()
    got = {
        "identities": len(touched),
        "messages": sum(len(g) for g in touched.values()),
        "pairs": sum(1 for g in touched.values() if len(g) == 2),
    }
    assert got == RECORDED_NO_ROLE, (
        f"the population the settler moves is {got}, recorded "
        f"{RECORDED_NO_ROLE}. A family that stopped naming its role, or "
        "started, moves this; re-record it with the change that caused it."
    )

    per_employer = collections.Counter(i.partition("|")[0] for i in touched)
    assert not [t for t, n in per_employer.items() if n > 1], (
        "an employer holds two identities whose roles are unreadable, so "
        "collapsing them to one sentinel would MERGE two applications"
    )

    everything = {c.identity for c in cases if c.identity is not None}
    for identity in touched:
        token = identity.partition("|")[0]
        siblings = {
            i for i in everything if i.partition("|")[0] == token and i != f"{token}|__norole__"
        }
        assert not siblings, (
            f"{token} holds {sorted(siblings)} beside the collapsed key, so the "
            "rename put role-less mail onto a card that names a role"
        )


def test_the_settler_refuses_a_collapse_that_would_merge() -> None:
    """THE CONTROL. The guard above is only worth having if it can fire.

    Two identities at one employer, both keyed on a role neither message
    spells, is the shape the rename must never silently produce. It cannot
    arise at this seed, so it is constructed here — otherwise the raise is a
    branch nothing has ever executed.
    """

    b = G._Builder(20260822)
    for role in ("Machine Learning Engineer", "Platform Engineer"):
        b.add(
            family="confirmation",
            subject="Thanks for your interest",
            sender="careers@northwind.example",
            sender_name="Northwind Talent",
            body="Hi Ayush, your details have been added to our database.",
            expected_category="applied",
            identity=f"northwind|{role}",
            employer="northwind",
        )
    with pytest.raises(ValueError, match="would merge it with"):
        G._settle_role_reachability(b.cases)
