"""What this corpus can REACH — the three numbers that bound what it can find.

``harness.py`` measures how well the product does on the corpus. This measures
how much of the product the corpus is capable of saying anything about, which is
a different question and the one #530 asks. A headline accuracy over a body of
mail that only ever exercises a third of the rules is a statement about the
third.

Three metrics, per family, each with the direction that matters. The gate is
``tests/test_corpus_reach.py``; this file only measures.

**1. PATTERN COVERAGE.** Of the positive ``strong``/``weak`` patterns in
``rules.PATTERNS`` — every category except ``OTHER``, whose entries are vetoes
rather than evidence — how many are matched by at least one message. Measured
2026-08-29: **48 of 159 (30.2%)**, so 111 rules ship with nothing in the largest
body of evidence this product has exercising them. Any of them could carry a bad
bound, a wrong alternation or a ReDoS and nothing here would say so. Worst by
category are ``interview`` (26 of 31 never fired) and ``offer`` (17 of 20) —
the two stages a user cares most about.

**2. DISTINCT WORDINGS.** A family's statistical weight is its wording count,
not its message count. ``repeat-anonymous`` is 600 messages of ONE wording and
``interview`` is 700 of two; multiplying a sentence by 600 buys 600 rows in a
table and no new evidence. Only the message count was reported before this file.

A "wording" is the mail with its PARAMETERS masked out — employer, role,
requisition id, digits — because those are drawn from a pool and vary by
construction. Masked from ``employers.POOL`` rather than from ``Case.employer``:
the noise families carry ``employer=None`` by design, so a per-case mask is a
no-op on exactly the four families whose text varies most, and it reported 80
wordings for ``observed-not-application``'s single template. The arithmetic that
says the mask works is asserted, not assumed —
``test_an_observed_family_has_exactly_its_templates_wordings``.

**3. DISCOVERY RATE.** The share of a family's messages matching NO strong
pattern anywhere in the engine. It is the only place a corpus can find something
the classifier does not already know, and every invented lifecycle family sits
at **0.0%** by construction: they were written by the author of ``rules.py``, so
their language is the language the engine was taught. All of the discovery power
in 17,260 messages lives in the ``observed-*`` families — 1,600 messages from
36 transcribed templates. The four that carry an UPDATE run 17.3–50.8%;
``observed-confirmation`` is 1.3% because an acknowledgement is the shape the
engine knows best, and ``observed-not-application`` is 100% because it is not
job mail at all.

WHAT THIS IS NOT. A raw case-insensitive regex scan over ``subject`` +
``delivered``, which is NOT what the classifier does: the real path strips
quoted history, cuts to asserted text, weights a subject match double and scores
against a floor. Pattern reach is deliberately the looser measure — a pattern
this cannot find is one no classifier configuration could have used, and a
family this scores as discovering nothing has nothing to discover regardless of
how the scoring is tuned. Read ``no_strong`` as "the engine has never been shown
this sentence", not as "the classifier got it wrong".
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from jobtracker.classifier.rules import PATTERNS
from jobtracker.database.models import EmailCategory

from .employers import POOL
from .generate import ROLES, Case

__all__ = [
    "Reach",
    "PatternId",
    "measure",
    "measure_texts",
    "positive_patterns",
    "scan_text",
    "wording",
    "texts_of",
]


@dataclass(frozen=True, order=True)
class PatternId:
    """One positive rule, named the way a failure message has to name it."""

    category: str
    tier: str
    pattern: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.category}:{self.tier}:{self.pattern}"


def positive_patterns() -> tuple[tuple[PatternId, re.Pattern[str]], ...]:
    """Every ``strong``/``weak`` pattern that can ARGUE FOR a category.

    ``EmailCategory.OTHER`` is excluded: its lists are the noise vetoes, they
    argue against every category rather than for one, and counting them would
    put patterns in the denominator that a lifecycle message is not supposed to
    fire. 159 of them as of 2026-08-29.
    """

    out: list[tuple[PatternId, re.Pattern[str]]] = []
    for category, patterns in PATTERNS.items():
        if category is EmailCategory.OTHER:
            continue
        for tier in ("strong", "weak"):
            for pattern in getattr(patterns, tier):
                out.append(
                    (
                        PatternId(category.value, tier, pattern),
                        re.compile(pattern, re.IGNORECASE),
                    )
                )
    return tuple(out)


def positive_categories() -> frozenset[str]:
    return frozenset(c.value for c in PATTERNS if c is not EmailCategory.OTHER)


# ── masking the parameters out of a wording ──────────────────────────────────
#
# Employers are minted so that no two share a LEADING word (see employers.py),
# which is what makes a lead-word set a safe mask: "Alderbourne" cannot collide
# with an English word in a template. The suffixes can — "Systems", "Works" and
# "Analytics" are ordinary words, and "Systems Engineer" is a real entry in
# ROLES — so a suffix is only swallowed when it directly follows a lead word.

_EMPLOYER_LEADS = frozenset(display.split()[0].lower() for display, _ in POOL)
_EMPLOYER_SUFFIXES = frozenset(
    word.lower() for display, _ in POOL for word in display.split()[1:]
)
_WORD = re.compile(r"[^\W\d_]+")
_ROLE = re.compile(
    "|".join(re.escape(r) for r in sorted(ROLES, key=len, reverse=True)),
    re.IGNORECASE,
)
_DIGITS = re.compile(r"\d+")


def _mask_employers(text: str) -> str:
    out: list[str] = []
    cursor = 0
    swallow_suffix_from = -1
    for match in _WORD.finditer(text):
        word = match.group(0).lower()
        if word in _EMPLOYER_LEADS:
            out.append(text[cursor : match.start()])
            out.append("{e}")
            cursor = match.end()
            swallow_suffix_from = match.end()
        elif match.start() == swallow_suffix_from + 1 and word in _EMPLOYER_SUFFIXES:
            # "Alderbourne Labs" is ONE name. Only reachable directly after a
            # lead word, so a template that says "systems" on its own is left
            # alone.
            cursor = match.end()
            swallow_suffix_from = match.end()
    out.append(text[cursor:])
    return "".join(out)


def wording(subject: str, body: str) -> str:
    """The mail with everything the builder varies masked out.

    Over the BODY and not ``delivered``. ``delivered`` is a snippet for the
    truncation families, and a snippet is cut at a fixed character count — so
    the same sentence truncated after two different employer names is two
    strings, and counting those as two wordings would credit the corpus with
    variety that is an artefact of the cut. It reported 105 wordings for
    ``observed-rejection``'s 29.
    """

    text = _mask_employers(f"{subject}\n{body}")
    text = _ROLE.sub("{r}", text)
    text = _DIGITS.sub("0", text)
    return " ".join(text.split()).lower()


def scan_text(subject: str, delivered: str) -> str:
    """What a pattern is searched in: the subject and what production delivers.

    ``delivered`` and not ``body`` here, and for the opposite reason: a rule
    that only matches text the product never receives has not been exercised by
    this corpus in any sense a user would recognise.
    """

    return f"{subject}\n{delivered}"


def texts_of(case: Case) -> tuple[str, str, str]:
    """``(family, scan text, wording)`` for one case."""

    return case.family, scan_text(case.subject, case.delivered), wording(
        case.subject, case.body
    )


@dataclass(frozen=True)
class FamilyReach:
    messages: int
    wordings: int
    #: Messages matching no ``strong`` pattern in any category.
    no_strong: int

    @property
    def discovery_rate(self) -> float:
        return self.no_strong / self.messages if self.messages else 0.0


@dataclass(frozen=True)
class Reach:
    fired: frozenset[PatternId]
    total_patterns: int
    families: dict[str, FamilyReach] = field(default_factory=dict)

    @property
    def never_fired(self) -> tuple[PatternId, ...]:
        every = {pid for pid, _ in positive_patterns()}
        return tuple(sorted(every - self.fired))

    @property
    def never_fired_by_category(self) -> dict[str, int]:
        return dict(Counter(p.category for p in self.never_fired))

    @property
    def coverage(self) -> float:
        return len(self.fired) / self.total_patterns if self.total_patterns else 0.0


def measure_texts(items: Iterable[tuple[str, str, str]]) -> Reach:
    """The three metrics over ``(family, scan text, wording)`` triples.

    Takes triples rather than cases so a mutation can be applied to the TEXT
    without rebuilding a ``Case`` — ``Case.__post_init__`` derives ground truth
    and refuses several combinations, so ``dataclasses.replace`` is not a safe
    way to ask "what if this wording said something else".
    """

    patterns = positive_patterns()
    fired: set[PatternId] = set()
    messages: Counter[str] = Counter()
    no_strong: Counter[str] = Counter()
    wordings: dict[str, set[str]] = {}

    for family, text, said in items:
        messages[family] += 1
        wordings.setdefault(family, set()).add(said)
        hit_strong = False
        for pid, rx in patterns:
            if rx.search(text):
                fired.add(pid)
                # NOT short-circuited on the first strong hit. A pattern that
                # only ever appears alongside an earlier one would then never
                # be recorded as fired, and coverage would depend on the order
                # PATTERNS happens to be written in.
                if pid.tier == "strong":
                    hit_strong = True
        if not hit_strong:
            no_strong[family] += 1

    return Reach(
        fired=frozenset(fired),
        total_patterns=len(patterns),
        families={
            family: FamilyReach(
                messages=count,
                wordings=len(wordings[family]),
                no_strong=no_strong[family],
            )
            for family, count in sorted(messages.items())
        },
    )


def measure(cases: list[Case]) -> Reach:
    return measure_texts(texts_of(case) for case in cases)
