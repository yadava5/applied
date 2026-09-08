"""The two `rules.json` tables must BE `rules.py`'s patterns — #955.

There are three implementations of one rule set and only one of them holds the
patterns as code. The other two load a JSON table, and the two tables are
hand-maintained copies with no generator and, until this file, nothing checking
them.

WHAT THAT COST, found while closing #955 and not by any gate: #928 deleted the
`|if` arm of `be in touch (soon|shortly|if)` from `rules.py` because the
conditional mask makes it unreachable, and **both** tables kept the three-arm
form. So the engine that ships and the two ports it is copied into were running
different pattern sets, in the one place the repository asserts they are the
same. `scripts/cross_engine_differential.py` could not see it: it compares
VERDICTS, and the arm is dead under a mask, so the drift was invisible to the
only cross-engine instrument there is.

WHY BYTE-EQUALITY OF THE TWO TABLES IS NOT THIS CHECK. They were byte-identical
to each other the whole time, and the differential's prose said so. Two copies
that agree with each other and not with the engine is exactly the state this
found, and a hash comparison between them reports it as healthy.

DIRECTION AND SHAPE. The assertion is equality of the whole table, per category
and per tier, not containment: containment in either direction passes for a
table that has quietly gained a pattern the engine does not have, which is the
same defect facing the other way.

ORDER IS NOT ASSERTED, and a first draft did assert it and was wrong. Nothing
in any of the three engines reads these lists positionally — the scoring walk
SUMS over each tier, the ATS check is an `any`, and `_SEMANTIC_REFUTATIONS` is
a filter that preserves whatever order it is given and is then also searched
with `any`. So a re-sorted table is the same classifier, and a test that reds
on it reds on nothing. Compared as SORTED lists rather than as sets, because
multiplicity is not free: a duplicated `negative` subtracts five twice.

The draft was caught by the tables themselves — the JSON `ats_domains` list is
alphabetised and `ATS_DOMAINS` is not, so the order assertion failed on the
committed tree, on a difference that changes no verdict.

The copy this gate exists beside is argued in DEC-011.

WHAT THIS DOES NOT CHECK, stated so the file is not mistaken for parity: that
the ports SCORE the way the engine does. Identical tables do not make identical
classifiers — that was #955's whole subject, and the cross-engine differential
is what grades it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobtracker.classifier.rules import ATS_DOMAINS, PATTERNS

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every tracked copy of the pattern table, by the port that loads it.
TABLES = {
    "typescript": REPO_ROOT / "apps" / "web" / "lib" / "demo" / "rules.json",
    "browser": REPO_ROOT / "ml" / "browser" / "site" / "rules.json",
}

TIERS = ("strong", "weak", "negative", "veto")


@pytest.fixture(scope="module", params=sorted(TABLES), ids=sorted(TABLES))
def table(request) -> tuple[str, dict]:
    path = TABLES[request.param]
    assert path.exists(), f"{request.param}'s table is not at {path}"
    return request.param, json.loads(path.read_text(encoding="utf-8"))


def test_the_table_carries_exactly_the_engines_categories(table) -> None:
    port, data = table
    engine = {c.value for c in PATTERNS}
    shipped = set(data["categories"])
    assert engine == shipped, (
        f"{port}'s table and the engine disagree about which categories exist.\n"
        f"  only in rules.py:   {sorted(engine - shipped)}\n"
        f"  only in the table:  {sorted(shipped - engine)}"
    )


def test_every_tier_holds_the_engines_patterns(table) -> None:
    """The one that would have caught the `|if` drift.

    Reported per tier rather than as one big inequality, because "these two
    tables differ" is not actionable and "applied.strong differs by one entry,
    and here it is" is.
    """
    port, data = table
    problems: list[str] = []
    for category, group in PATTERNS.items():
        shipped = data["categories"][category.value]
        for tier in TIERS:
            engine_list = sorted(getattr(group, tier, []) or [])
            table_list = sorted(shipped.get(tier, []) or [])
            if engine_list == table_list:
                continue
            only_engine = [p for p in engine_list if p not in table_list]
            only_table = [p for p in table_list if p not in engine_list]
            problems.append(
                f"  {category.value}.{tier}: rules.py has {len(engine_list)}, "
                f"{port}'s table has {len(table_list)}\n"
                + "".join(f"      only in rules.py:  {p}\n" for p in only_engine)
                + "".join(f"      only in the table: {p}\n" for p in only_table)
                + (
                    "      the same entries at different MULTIPLICITY\n"
                    if not only_engine and not only_table
                    else ""
                )
            )
    assert not problems, (
        f"{port}'s pattern table has drifted from the engine it copies:\n"
        + "\n".join(problems)
        + "\nEdit the table to match rules.py. Do not edit rules.py to match the "
        "table: the engine is what ships."
    )


def test_the_ats_domain_list_is_the_engines(table) -> None:
    port, data = table
    assert sorted(data["ats_domains"]) == sorted(ATS_DOMAINS), (
        f"{port}'s ATS domain list has drifted from `ATS_DOMAINS`. The relay "
        "bonus is worth 0.05 of confidence and rides entirely on this list."
    )


def test_the_two_tables_are_the_same_file(table) -> None:
    """...and they are, but this is NOT what the tests above assert.

    Kept because the two ports genuinely must load the same bytes, and dropped
    into this file rather than left implicit so the distinction is on the page:
    the tables agreed with EACH OTHER for the whole time they disagreed with
    the engine, so this check alone reports a drifted pair as healthy.
    """
    contents = {port: path.read_bytes() for port, path in TABLES.items()}
    first, *rest = contents.items()
    for port, blob in rest:
        assert blob == first[1], (
            f"{port}'s table is not byte-identical to {first[0]}'s. Both ports "
            "are supposed to load one table; two of them is two engines."
        )


def test_the_comparison_can_fail(table) -> None:
    """A control: the equality above must be able to report a difference.

    Without it, a `PATTERNS` that imported as empty and a table that parsed as
    empty would agree perfectly and this file would be furniture.
    """
    port, data = table
    populated = [
        (c.value, tier)
        for c, g in PATTERNS.items()
        for tier in TIERS
        if getattr(g, tier, None)
    ]
    assert len(populated) >= 8, (
        f"the engine offered only {len(populated)} populated tiers; it did not "
        "load, so the equality assertions above compared nothing"
    )
    category, tier = populated[0]
    mutated = sorted([*data["categories"][category][tier], "never-a-real-pattern"])
    engine = next(sorted(getattr(g, tier)) for c, g in PATTERNS.items() if c.value == category)
    assert mutated != engine, (
        "adding a pattern to the table did not make it differ from the engine, "
        "so the equality assertions above cannot report a drift"
    )
