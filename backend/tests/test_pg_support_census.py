"""The Postgres-module split in ``pg_support``'s docstring, as a gate (#695).

That docstring said "the two modules added here" share the container and "all
four Postgres modules" point at one database. Six modules imported the file and
four of them shared the container. Nobody had written a wrong thing: the counts
were right when they were written and every suite added since moved them, which
is what prose counts do.

So they are read out of the tree here instead. The point is not the numbers —
it is that adding a seventh Postgres module reds this test and the person adding
it updates one sentence, rather than the docstring quietly describing a
repository that no longer exists.

NO DOCKER, NO DATABASE. This reads files. It runs in the ordinary ``test`` job
alongside everything else, which matters: a gate that only fires inside the
Postgres jobs would be skipped in exactly the runs where somebody is adding a
module without one.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SUPPORT = TESTS / "pg_support.py"

#: A module that calls this SHARES the memoised container.
SHARES = "resolve_admin_url"
#: A module that calls this STARTED its own and is only registering it for
#: cleanup. It is not sharing anything.
OWNS = "register_owned_container"


def _importers(name: str) -> set[str]:
    """Modules whose ``from tests.pg_support import ...`` names ``name``.

    Anchored on the import statement rather than on any mention of the symbol,
    so a module that merely discusses ``resolve_admin_url`` in a comment — this
    repository's modules discuss things at length — is not counted as a caller.
    """

    pattern = re.compile(
        r"^from tests\.pg_support import (?P<names>.+)$", re.MULTILINE
    )
    found = set()
    for path in sorted(TESTS.glob("test_*.py")):
        for match in pattern.finditer(path.read_text()):
            if name in {n.strip() for n in match.group("names").split(",")}:
                found.add(path.name)
    return found


def test_the_split_is_what_the_docstring_says() -> None:
    """Four share, two own, six in total — and the docstring says so.

    Asserted as three separate numbers because they are three separate claims:
    a module could move from owning to sharing and leave the total unchanged,
    which is the drift that is hardest to notice and the one that changes how
    many containers a laptop starts.

    MUTATION: change any one of the three counts in ``pg_support``'s docstring
    and this reds; add a Postgres module that shares the container and it reds
    on ``shares`` and ``total`` together.
    """

    shares = _importers(SHARES)
    owns = _importers(OWNS)
    doc = SUPPORT.read_text()

    assert len(shares) == 4, f"modules sharing the container: {sorted(shares)}"
    assert len(owns) == 2, f"modules owning their own container: {sorted(owns)}"
    assert shares & owns == set(), (
        f"a module both shares and owns a container: {sorted(shares & owns)}"
    )
    assert len(shares | owns) == 6, f"Postgres modules: {sorted(shares | owns)}"

    assert "four modules SHARE the memoised container" in doc
    assert "two own theirs" in doc
    assert "six Postgres modules, three simultaneous containers" in doc


def test_the_census_can_see_a_module_it_should_not() -> None:
    """The control: the reader is not matching every file in the directory.

    Without this, ``_importers`` returning the whole ``test_*.py`` glob would
    satisfy nothing above by luck alone but would satisfy a future looser
    version of it — and a census that counts everything is the same defect as a
    count maintained by hand, only harder to see.
    """

    assert _importers(SHARES) != set(p.name for p in TESTS.glob("test_*.py"))
    assert _importers("a_symbol_pg_support_does_not_export") == set()
