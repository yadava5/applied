"""A large pool of wholly invented employers, minted deterministically.

WHY NOT REUSE ``tests/corpus/generator._POOL``. That one holds 74 hand-written
names, which is right for a 200-case corpus and nowhere near enough for ten
thousand messages spread over twenty-odd families that must not share an
employer by accident. Sharing is not a cosmetic problem: application identity is
``(employer, req_id or role_token)``, so two families that happen to reuse one
employer AND one job title describe a single application by the product's own
rule, and the harness would report a MERGE for behaviour that is correct.

THE HARD RULE, inherited unchanged: every employer here is fictional. The owner's
mailbox holds genuine applications to real companies and this repository is
public. What is borrowed from reality is the SHAPE — ATS relay domains, subject
conventions, the phrasings that break the extractor. Real-world shapes,
invented companies.

Minted from two disjoint syllable lists so the names read as companies rather
than as identifiers, and so the pool can grow without anyone hand-writing four
hundred more. The product is deterministic and the order is fixed, so a corpus
built from it is byte-identical between runs.
"""

from __future__ import annotations

_HEADS: tuple[str, ...] = (
    "Alder", "Amber", "Arc", "Ash", "Basalt", "Beacon", "Bell", "Birch",
    "Bram", "Briar", "Cairn", "Cedar", "Cinder", "Clove", "Cobalt", "Copper",
    "Coral", "Crag", "Dovetail", "Drift", "Dusk", "Elm", "Ember", "Fern",
    "Flint", "Frost", "Gale", "Glass", "Gorse", "Granite", "Harrow", "Hazel",
    "Hearth", "Heron", "Hollow", "Ivory", "Juniper", "Kestrel", "Lark", "Larch",
    "Lantern", "Loam", "Marsh", "Meadow", "Mica", "Moss", "Nettle", "Onyx",
    "Orchard", "Otter", "Pike", "Pine", "Quarry", "Quill", "Rowan", "Rush",
    "Sable", "Sedge", "Slate", "Sorrel", "Spindle", "Spruce", "Stone", "Tamarisk",
    "Thistle", "Thorn", "Tide", "Umber", "Vale", "Verdigris", "Wick", "Willow",
    "Wren", "Yarrow",
)

_TAILS: tuple[str, ...] = (
    "bourne", "brook", "cross", "dale", "fall", "ford", "gate", "grove",
    "haven", "hollow", "keep", "landing", "mere", "moor", "point", "reach",
    "ridge", "row", "shore", "stead", "vale", "watch", "well", "wood",
)

#: A middle particle, so the pool is big enough without anyone hand-writing
#: thousands of names. It has to widen the FIRST WORD and not add a second one:
#: ``matches_company_token`` accepts a match on the leading word, so
#: "Alderbourne" and "Alderbourne Labs" are the same employer to the product and
#: a pool built by adding suffixes would be full of accidental collisions.
_MIDS: tuple[str, ...] = ("", "field", "mont", "wick", "bury", "holt")

#: Suffixes that make a NAME rather than a token — the resolver's leading-word
#: rule means "Cobalt Ridge" arrives as ``cobalt``, so a corpus of single-word
#: names would never exercise it. Roughly a third of the pool carries one.
_SUFFIXES: tuple[str | None, ...] = (
    None, None, None, None,
    "Labs", "Systems", "Robotics", "Analytics", "Dynamics", "Works",
)


def _mint() -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    n = 0
    for m, mid in enumerate(_MIDS):
        for i, head in enumerate(_HEADS):
            for j, tail in enumerate(_TAILS):
                suffix = _SUFFIXES[n % len(_SUFFIXES)]
                n += 1
                lead = f"{head}{mid}{tail}"
                display = lead + (f" {suffix}" if suffix else "")
                # Keyed on the LEADING WORD, which is the token the resolver
                # actually produces. Two names sharing it are one employer.
                if lead.lower() in seen:
                    continue
                seen.add(lead.lower())
                out.append((display, display.lower()))
    return tuple(out)


#: Ten thousand-odd invented employers, in a fixed order, no two of which share
#: a leading word.
POOL: tuple[tuple[str, str], ...] = _mint()


class EmployerPool:
    """Hands out employers no other caller has taken.

    Disjointness is the whole contract; running out is an error rather than a
    wrap-around, because a silent wrap would start reporting merges that are
    the harness's own fault and nobody would know which.
    """

    def __init__(self) -> None:
        self._taken = 0

    def take(self) -> tuple[str, str]:
        if self._taken >= len(POOL):
            raise RuntimeError(
                f"invented-employer pool exhausted at {len(POOL)}; widen "
                "_HEADS or _TAILS rather than reusing a name"
            )
        pair = POOL[self._taken]
        self._taken += 1
        return pair

    @property
    def used(self) -> int:
        return self._taken
