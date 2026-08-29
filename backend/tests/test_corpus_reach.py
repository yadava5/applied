"""What the corpus can REACH, as a gate — #530.

``tests/corpus_independent/reach.py`` is the instrument and explains the three
metrics; this pins them. Every number below was MEASURED on 2026-08-29 over the
17,260-case corpus at the default seed, and every one of them carries a
DIRECTION and a reason, because a bare value is a transcription that gets
re-baselined the first time somebody breaks it.

WHAT THIS GATE IS FOR. ``test_independent_corpus.py`` asks how well the product
does on this corpus. This asks how much of the product the corpus is able to say
anything about at all, and the answer today is:

    positive engine patterns                              159
      exercised by at least one of 17,260 messages         48   (30.2%)
      never fired by anything                             111   (69.8%)

    never fired, by category:  interview 26 of 31 · rejection 20 of 36
      offer 17 of 20 · assessment 15 of 23 · pending_application 14 of 15
      applied 11 of 25 · follow_up 8 of 9

    17,260 messages · 104 distinct wordings corpus-wide

So 111 rules ship to users with nothing in the largest body of evidence this
product has exercising them, and the two worst categories are the two stages a
user cares most about. This gate does NOT close that gap — closing it is #531,
it needs human judgement over real mail, and inventing interview and offer
wordings would rebuild the closed loop ``observed.py`` exists to break. The job
here is to MEASURE the gap so it cannot widen quietly and cannot be narrowed by
editing the corpus.

THE DEFECTS ARE PINNED AS DEFECTS, at their measured size, the way the rest of
this corpus's numbers are. ``RECORDED_NEVER_FIRED`` is a ledger of missing
evidence, not a target; when #531 fires some of those patterns the counts fall,
which this gate allows, and the record has to be updated to say so.

IT RUNS IN SECONDS. Generating the corpus is 0.1s and scanning 17,260 messages
against 159 compiled patterns is 7s; the module is ~22s because the two control
tests each re-scan a modified copy. There is no board replay here, which is
where ``test_independent_corpus.py``'s fourteen minutes go — pattern reach does
not need one, and a gate nobody can afford to run is a gate nobody runs.
"""

from __future__ import annotations

import re

import pytest

from tests.corpus_independent import observed, reach
from tests.corpus_independent.generate import generate

#: The engine's shape when the record below was taken. Not asserted as an
#: equality — a pattern that is ADDED and exercised is a good change and must
#: not red — but the two directional checks below bound it from both sides: a
#: new pattern nothing fires raises ``never_fired`` and reds, and a pattern that
#: is deleted or edited drops out of ``RECORDED_FIRED`` and reds.
RECORDED_POSITIVE_PATTERNS = 159

#: The categories whose ``strong``/``weak`` lists ARGUE FOR a verdict.
#: ``EmailCategory.OTHER`` is excluded — its lists are vetoes, so counting them
#: would put patterns in the denominator that a lifecycle message is not
#: supposed to fire. Asserted, so that a seventh lifecycle category cannot
#: arrive with a full list of unexercised patterns that no counter here sees.
POSITIVE_CATEGORIES = frozenset(
    {
        "applied",
        "assessment",
        "follow_up",
        "interview",
        "offer",
        "pending_application",
        "rejection",
    }
)

#: METRIC 1 — PATTERN COVERAGE. The 48 patterns at least one message fires.
#:
#: DIRECTION: this set may only GROW. Pinned as a SET and not as the count 48,
#: because ``>= 48`` is satisfied by a DIFFERENT 48 — a rewritten pattern that
#: stops matching while a new one starts would leave the number still reading
#: 48 and the rule silently unexercised.
RECORDED_FIRED: tuple[tuple[str, str, str], ...] = (
    # applied — 14 of 25
    ('applied', 'strong', 'application.{0,20}(for|to).{0,40}(position|role|job)'),
    ('applied', 'strong', 'application.{0,20}received'),
    ('applied', 'strong', 'application.{0,30}has been (received|submitted)'),
    ('applied', 'strong', 'be in touch (soon|shortly|if)'),
    ('applied', 'strong', 'reviewing (applications|candidates)'),
    ('applied', 'strong', 'thank(s| you) for (taking the time to )?submit(ting)? your application'),
    ('applied', 'strong', 'thank(s| you) for applying'),
    ('applied', 'strong', "we (have |'ve )received your application"),
    ('applied', 'strong', 'we received your (job )?application'),
    ('applied', 'weak', 'review your (application|resume|qualifications)'),
    ('applied', 'weak', 'thank you for your interest'),
    ('applied', 'weak', 'thank(s| you) for your application'),
    ('applied', 'weak', 'your application for\\s+.+\\s+at\\s+[A-Z]'),
    ('applied', 'weak', 'your application to\\s+.+\\s+at\\s+[A-Z]'),
    # assessment — 8 of 23
    ('assessment', 'strong', '(technical|coding|take.?home).{0,20}(assessment|challenge|test|exercise)'),
    ('assessment', 'strong', '\\btake-home\\b(?!\\s+(pay|message|gift|dose|salary))'),
    ('assessment', 'strong', 'assessments?\\s+(invitation|invite)\\b'),
    ('assessment', 'strong', 'coding (exercise|test|challenge)'),
    ('assessment', 'strong', 'complete.{0,30}(assessment|challenge|test)'),
    ('assessment', 'strong', 'online (assessment|test)'),
    ('assessment', 'strong', 'take.?home (assignment|project|exercise|task|round)'),
    ('assessment', 'weak', 'next step.{0,30}(assessment|test)'),
    # follow_up — 1 of 9
    ('follow_up', 'weak', 'follow-?up'),
    # interview — 5 of 31
    ('interview', 'strong', "(would |'d |)like to (schedule|set up|arrange|book).{0,25}(call|meeting|interview|chat|conversation)"),
    ('interview', 'strong', '\\b(book|pick|choose|select|schedule|reserve|grab)\\s+(a|your|another)\\s+(time|slot)\\b'),
    ('interview', 'strong', 'invite you (to|for).{0,20}interview'),
    ('interview', 'strong', 'schedule.{0,20}interview'),
    ('interview', 'weak', 'learn more about (you|your background|your experience)'),
    # offer — 3 of 20
    ('offer', 'strong', 'congratulations.{0,30}(job )?offer'),
    ('offer', 'strong', 'extend.{0,20}(job |employment )?offer'),
    ('offer', 'weak', 'joining.{0,20}(our |the )team'),
    # pending_application — 1 of 15
    ('pending_application', 'strong', 'action required.{0,60}(application|submit)'),
    # rejection — 16 of 36
    ('rejection', 'strong', '(decided|chosen|elected|will be|are)\\b.{0,20}(move|moving) forward with (a |an |the )?(other|another|different) (candidate|applicant)'),
    ('rejection', 'strong', '(move|moved|moving) forward with (a |an |the )?(other|another|different) (candidate|applicant)'),
    ('rejection', 'strong', "(won't|will not|not) (be )?(proceeding|continuing) with"),
    ('rejection', 'strong', "(won't|will not|not) (be )?(proceeding|continuing) with.{0,30}(application|candidacy)"),
    ('rejection', 'strong', '\\byou (have|were)\\b.{0,10}not (been )?selected\\b'),
    ('rejection', 'strong', 'after careful (consideration|review).{0,30}(not|decided|unfortunately)'),
    ('rejection', 'strong', 'not (be )?(moving|proceeding) forward'),
    ('rejection', 'strong', 'not (been )?selected.{0,30}(position|role|interview)'),
    ('rejection', 'strong', 'not to (move|proceed|go) forward'),
    ('rejection', 'strong', 'not to (move|proceed|go) forward.{0,30}(application|candidacy)'),
    ('rejection', 'strong', 'not.{0,20}moving forward.{0,20}(application|your candidacy)'),
    ('rejection', 'strong', 'regret to inform'),
    ('rejection', 'strong', "unfortunately.{0,50}(not|won't|will not|unable)"),
    ('rejection', 'strong', 'will not be moving forward.{0,30}(application|candidacy)'),
    ('rejection', 'strong', 'wish you (all |only |nothing but )?(the (very )?best|well|success|luck) in your'),
    ('rejection', 'weak', 'many qualified (candidates|applicants)'),
)

#: The other half of metric 1 — the 111 rules with NO evidence behind them.
#:
#: DIRECTION: these may only FALL. A category that gains an unexercised pattern
#: reds, which is the pressure this gate exists to apply: a rule shipped with
#: nothing firing it is a rule whose bound, alternation or backtracking nobody
#: has checked. Falling is #531's job and needs the record updated to say so.
RECORDED_NEVER_FIRED: dict[str, int] = {
    "interview": 26,          # of 31 — and interview is a stage users care about
    "rejection": 20,          # of 36
    "offer": 17,              # of 20 — the other one
    "assessment": 15,         # of 23
    "pending_application": 14,  # of 15
    "applied": 11,            # of 25
    "follow_up": 8,           # of 9
}

#: METRICS 2 and 3, per family — ``(messages, distinct wordings, no-strong)``.
#:
#: The middle column is the one that did not exist before #530. A family's
#: statistical weight is its WORDING count: ``repeat-anonymous`` is 600 messages
#: of one sentence and ``interview`` is 700 of two, so multiplying either buys
#: rows in a table and not evidence.
#:
#: The third column is the discovery rate's numerator — messages matching no
#: strong pattern anywhere in the engine, which is the only place a corpus can
#: find something the classifier does not already know.
#:
#: DIRECTIONS, all three:
#:   * ``messages`` may only grow. It is here as the denominator, so that a
#:     rate cannot be improved by deleting the mail it is computed over.
#:   * ``wordings`` may only grow. A wording removed is evidence removed.
#:   * ``no_strong`` is a FLOOR ON THE COUNT where it is non-zero, and an
#:     EQUALITY where it is zero. Two different claims, two tests — and a floor
#:     on the COUNT rather than on the rate, so that transcribing more wordings
#:     that agree with the engine dilutes the rate without reading as
#:     contamination. See ``_discovery_shortfalls``.
RECORDED_FAMILIES: dict[str, tuple[int, int, int]] = {
    # ── the invented lifecycle. Written by the author of ``rules.py``, so its
    # discovery rate is 0.0% BY CONSTRUCTION: there is no sentence here the
    # engine was not already taught. This column is the measurement that says
    # so, and it is the reason the accuracy figure over this corpus has to be
    # read with the corpus.
    "ambiguous-update": (450, 2, 0),
    "assessment": (660, 2, 0),
    "bare-relay": (200, 1, 0),
    "conditional-explainer": (400, 2, 0),
    "confirmation": (1100, 4, 0),
    "double-acknowledgement": (120, 2, 0),
    "employer-spelling": (450, 1, 0),
    "hostile-bidi-sender": (100, 1, 0),
    "hostile-preheader": (100, 1, 0),
    "interview": (700, 2, 0),
    "offer": (440, 2, 0),
    "one-thread-many-roles": (240, 1, 0),
    "one-thread-many-roles-in-the-queue": (240, 1, 0),
    "quoted-history": (400, 2, 0),
    "rejection-plain": (1100, 4, 0),
    "reopen-after-rejection": (750, 2, 0),
    "repeat-anonymous": (600, 1, 0),
    "req-id-same-title": (400, 1, 0),
    "requisition-inside-the-bound": (120, 2, 0),
    "rescinded-offer": (520, 4, 0),
    "update-before-confirmation": (600, 5, 0),
    "update-from-another-domain": (600, 5, 0),
    "update-in-thread": (600, 2, 0),
    "update-joins-one-application": (1200, 5, 0),
    "update-outside-the-thread": (600, 5, 0),
    "update-picks-between-two": (750, 5, 0),
    "verdict-past-the-body-cap": (320, 2, 0),
    # ── invented, and non-zero for a reason that is NOT discovery. These are
    # noise and truncation families: their mail either is not about a job at
    # all, or is cut off before the verdict. A fall here is a finding of a
    # different kind — lifecycle patterns starting to match mail that must
    # never become an application.
    "ats-relay-noise": (400, 5, 400),
    "hostile-zero-width": (100, 1, 28),
    "not-job-mail": (700, 6, 700),
    "rejection-past-the-snippet": (700, 3, 350),
    # ── TRANSCRIBED. All of the corpus's discovery power, in 1,600 of 17,260
    # messages and 36 templates. These wordings were written by recruiting teams
    # with no knowledge of this repository, so a message here matching no strong
    # pattern is real ATS mail the engine has never been shown.
    #
    # THE FOUR THAT CARRY AN UPDATE run 17.3-50.8%, which is the range #530
    # quotes. The other two are not counter-examples and are not averaged in:
    # observed-confirmation is 1.3% because an acknowledgement is the shape the
    # engine knows best, and observed-not-application is 100% because it is not
    # job mail at all and no lifecycle pattern should touch it.
    "observed-assessment": (300, 26, 54),
    "observed-closure": (240, 24, 122),
    "observed-confirmation": (300, 23, 4),
    "observed-not-application": (80, 1, 80),
    "observed-pending": (240, 25, 71),
    "observed-rejection": (440, 29, 76),
}

#: Which of ``observed.py``'s template tuples each transcribed family draws
#: from, per the builders in ``generate.py``. Every observed family opens with a
#: real acknowledgement before the update it is about, so all but two of them
#: draw ``OBSERVED_CONFIRMATIONS`` as well.
#:
#: This is the POSITIVE CONTROL on metric 2 and it is what makes the wording
#: counts above interpretable rather than transcribed: the number measured off
#: the corpus must equal the number of templates in the source. Before the mask
#: read from ``employers.POOL`` it read from ``Case.employer``, which the noise
#: families leave as ``None`` — so the employer name survived masking and
#: ``observed-not-application``'s ONE template measured as 80 wordings. A
#: weakened normaliser inflates every count in the table and every "must not
#: fall" direction above passes happily while it does.
OBSERVED_TEMPLATES: dict[str, tuple[tuple, ...]] = {
    "observed-confirmation": (observed.OBSERVED_CONFIRMATIONS,),
    "observed-rejection": (observed.OBSERVED_CONFIRMATIONS, observed.OBSERVED_REJECTIONS),
    "observed-assessment": (observed.OBSERVED_CONFIRMATIONS, observed.OBSERVED_ASSESSMENTS),
    "observed-closure": (observed.OBSERVED_CONFIRMATIONS, observed.OBSERVED_CLOSURES),
    "observed-pending": (observed.OBSERVED_CONFIRMATIONS, observed.OBSERVED_PENDING),
    "observed-not-application": (observed.OBSERVED_NOT_APPLICATIONS,),
}

OBSERVED_FAMILIES = tuple(sorted(OBSERVED_TEMPLATES))


@pytest.fixture(scope="module")
def cases():
    return generate()


@pytest.fixture(scope="module")
def measured(cases):
    return reach.measure(cases)


# ── the record's own arithmetic ──────────────────────────────────────────────


def test_the_record_is_arithmetically_whole() -> None:
    """48 fired plus 111 never fired is 159, or the ledger is mistyped.

    Cheap, and it is the check the two directional tests cannot do for
    themselves: they compare MEASURED against RECORDED, so a transcription error
    in RECORDED moves the bar rather than failing.
    """

    assert len(RECORDED_FIRED) == len(set(RECORDED_FIRED)), "a duplicate entry"
    assert set(RECORDED_NEVER_FIRED) <= POSITIVE_CATEGORIES
    assert (
        len(RECORDED_FIRED) + sum(RECORDED_NEVER_FIRED.values())
        == RECORDED_POSITIVE_PATTERNS
    ), (
        f"{len(RECORDED_FIRED)} fired + {sum(RECORDED_NEVER_FIRED.values())} never "
        f"fired != {RECORDED_POSITIVE_PATTERNS} positive patterns"
    )
    assert len(RECORDED_FIRED) / RECORDED_POSITIVE_PATTERNS == pytest.approx(
        0.302, abs=0.0005
    ), "the 30.2% this gate's docstring publishes"


def test_the_positive_pattern_set_is_the_one_that_was_measured() -> None:
    """A seventh lifecycle category cannot arrive unmeasured.

    ``RECORDED_NEVER_FIRED`` is keyed by category, so a new category with a full
    list of unexercised patterns would simply be absent from it and every
    ``<=`` below would pass over nothing.
    """

    assert reach.positive_categories() == POSITIVE_CATEGORIES


# ── metric 1: pattern coverage ───────────────────────────────────────────────


def test_every_pattern_this_corpus_has_ever_fired_still_fires(measured) -> None:
    """DIRECTION: coverage may not fall.

    A pattern leaving this set means one of two things and both need saying out
    loud: the rule was edited so that real mail no longer matches it, or the
    corpus wording that used to reach it was changed. Either way 17,260 messages
    stopped exercising a rule that ships to users.
    """

    recorded = {reach.PatternId(*entry) for entry in RECORDED_FIRED}
    lost = sorted(recorded - measured.fired)
    assert not lost, (
        f"{len(lost)} pattern(s) that 17,260 messages used to exercise now "
        f"match nothing:\n  " + "\n  ".join(str(p) for p in lost)
    )


def test_no_category_gains_a_pattern_that_nothing_exercises(measured) -> None:
    """DIRECTION: the ledger of missing evidence may only fall.

    This is what bounds the coverage SHARE without pinning the percentage. A
    percentage re-baselines every time the denominator moves; these two
    directions together do not — a pattern added and exercised raises the
    numerator, and a pattern added and NOT exercised raises this counter and
    reds. Adding a rule with nothing behind it has to be argued for.
    """

    measured_never = measured.never_fired_by_category
    worse = {
        category: (count, RECORDED_NEVER_FIRED.get(category, 0))
        for category, count in measured_never.items()
        if count > RECORDED_NEVER_FIRED.get(category, 0)
    }
    assert not worse, (
        "patterns with no evidence behind them, by category (now, recorded): "
        f"{worse}. A new rule needs a message that fires it — in "
        "`observed.py` if it is a real ATS wording, which is #531."
    )


# ── metric 2: distinct wordings ──────────────────────────────────────────────


def test_no_family_loses_a_wording_or_a_message(measured) -> None:
    """DIRECTION: both may only grow.

    ``messages`` is here as the DENOMINATOR of metric 3, so that a discovery
    rate cannot be improved by deleting the mail it is computed over.
    """

    missing = sorted(set(RECORDED_FAMILIES) - set(measured.families))
    assert not missing, f"families that no longer exist: {missing}"
    # AND THE OTHER DIRECTION, which is the one that matters here. Every check
    # in this file iterates RECORDED_FAMILIES, so a family that is ADDED and not
    # recorded gets no wording pin, no discovery pin and no share of the growth
    # trap below — it is simply invisible. The families #531 will add are
    # `observed-interview` and `observed-offer`, which is to say the gate built
    # to measure the interview and offer gap would have had nothing to say about
    # the evidence that closes it.
    unrecorded = sorted(set(measured.families) - set(RECORDED_FAMILIES))
    assert not unrecorded, (
        f"families with no recorded reach: {unrecorded}. Record "
        f"(messages, wordings, no_strong) for each — until you do, nothing in "
        f"this file measures them."
    )
    shrunk = []
    for family, (messages, wordings, _) in sorted(RECORDED_FAMILIES.items()):
        now = measured.families[family]
        if now.messages < messages:
            shrunk.append(f"{family}: {messages} messages -> {now.messages}")
        if now.wordings < wordings:
            shrunk.append(f"{family}: {wordings} wordings -> {now.wordings}")
    assert not shrunk, "evidence removed:\n  " + "\n  ".join(shrunk)


@pytest.mark.parametrize("family", OBSERVED_FAMILIES)
def test_an_observed_family_has_exactly_its_templates_wordings(
    measured, family: str
) -> None:
    """THE CONTROL ON THE MASK, derived from source rather than recorded.

    A wording is the mail with its parameters masked out, and a mask that stops
    working does not fail — it silently reports more wordings than exist, which
    every "must not fall" direction in this file then passes. So the count is
    checked against the number of templates ``observed.py`` actually holds.

    Equality in both directions. Too many means the mask leaked a parameter;
    too few means a template was added and the family draws too few messages
    to ever pick it, which is a template that gates nothing.
    """

    expected = sum(len(source) for source in OBSERVED_TEMPLATES[family])
    assert measured.families[family].wordings == expected, (
        f"{family} measures {measured.families[family].wordings} distinct "
        f"wordings from {expected} templates in observed.py"
    )


def _copies_without_evidence(measured) -> list[str]:
    """Observed families that grew their messages and not their wordings."""

    out = []
    for family in OBSERVED_FAMILIES:
        messages, wordings, _ = RECORDED_FAMILIES[family]
        now = measured.families[family]
        if now.messages > messages and now.wordings <= wordings:
            out.append(
                f"{family}: {messages} -> {now.messages} messages, still "
                f"{now.wordings} wordings"
            )
    return out


def test_an_observed_family_cannot_grow_messages_without_growing_wordings(
    measured,
) -> None:
    """THE 10,000-MESSAGES-36-WORDINGS TRAP, named in #530's close.

    Repeating a transcription is free and repeating it raises every count in
    ``test_independent_corpus.py``'s headline. It adds no evidence: the same
    sentence at a second employer is the same sentence. So the observed families
    — the only non-circular evidence the product has — may not grow their
    message count while their wording count stands still.
    """

    trapped = _copies_without_evidence(measured)
    assert not trapped, (
        "more copies of the same letter is more rows and no more evidence:\n  "
        + "\n  ".join(trapped)
        + "\n\nTranscribe a new wording (#531) or leave the count alone."
    )


def test_the_copies_without_evidence_trap_can_actually_spring(measured) -> None:
    """THE CONTROL ON IT, because on this tree the check above is DORMANT.

    Nothing has grown, so its predicate is false for every family and it cannot
    fail today — which is this estate's recurring defect, a check that passes
    because it never evaluates anything. So the predicate is fed the shape it
    exists to catch: an observed family's messages multiplied while its wordings
    stand still, which is exactly what shipping 10,000 messages of 36 templates
    looks like.

    Directional in both halves. Growing the messages AND the wordings must NOT
    trip it, or the check would forbid the good change as well as the bad one.
    """

    family = "observed-rejection"
    messages, wordings, no_strong = RECORDED_FAMILIES[family]

    def _as(msgs: int, words: int):
        families = dict(measured.families)
        families[family] = reach.FamilyReach(msgs, words, no_strong)
        return reach.Reach(measured.fired, measured.total_patterns, families)

    assert not _copies_without_evidence(measured), "the tree is clean"
    sprung = _copies_without_evidence(_as(messages * 10, wordings))
    assert len(sprung) == 1 and sprung[0].startswith(family), (
        f"440 -> 4400 messages on the same 29 wordings and the trap said "
        f"{sprung}"
    )
    assert not _copies_without_evidence(_as(messages * 10, wordings + 1)), (
        "one new transcription with the growth is the change this is FOR; "
        "forbidding it would make the check an obstacle rather than a gate"
    )


# ── metric 3: discovery rate ─────────────────────────────────────────────────


def _discovery_shortfalls(measured) -> list[str]:
    """Families that have LOST discovery power against what was recorded.

    THE FLOOR IS ON THE COUNT AND THE REPORT IS IN RATES, and those are not the
    same claim. A rate floor reds on a third thing that is neither of the two
    cases below: transcribe more wordings that AGREE with the engine and the
    denominator grows while the numerator does not, so the rate falls. That is
    not contamination — a randomly chosen real ATS wording matches a strong
    pattern about 83% of the time in this very corpus (``observed-rejection``,
    364 of 440), so ordinary honest growth lands there more often than not, and
    a rate floor would meet it with an accusation the ``observed.py`` docstring
    says is wrong. The COUNT only falls when a message that used to reach
    nothing now reaches something, which is the two cases the failure names.

    A function rather than an inline assert because the mutation test below has
    to be able to ask "would this have failed", which is the only way to prove a
    gate can fail without waiting for the day it does.
    """

    out = []
    for family, (messages, _, no_strong) in sorted(RECORDED_FAMILIES.items()):
        if not no_strong:
            continue
        now = measured.families[family]
        if now.no_strong < no_strong:
            out.append(
                f"{family}: {no_strong / messages:.1%} ({no_strong}/{messages}) -> "
                f"{now.discovery_rate:.1%} ({now.no_strong}/{now.messages})"
            )
    return out


def test_the_corpus_keeps_the_discovery_power_it_has(measured) -> None:
    """DIRECTION: the messages that reach nothing are a FLOOR.

    Exactly two things can lower that count, they call for opposite responses,
    and the failure has to say which — so it reports whether the fired set grew:

    * **The corpus drifted toward the engine.** Somebody edited a transcribed
      wording until it matched a rule. ``observed.py`` forbids it in terms and
      #530 explains why the obvious repair is the wrong one — real ATS mail says
      "thank you for applying" and the engine has that pattern BECAUSE real mail
      says it, so a verbatim match is agreement, not contamination. Near-zero
      here would mean the transcriptions had stopped describing how ATS mail is
      written. This is the case where the fired set is unchanged.
    * **The engine learned something real.** A new rule covers a wording that
      previously matched nothing — a genuine gap closed, and the honest outcome
      of reading this table. This is the case where the fired set GREW, and it
      is a legitimate reason to re-record.

    A third thing that lowers the RATE is deliberately not a failure; see
    ``_discovery_shortfalls`` for why the floor is on the count.

    For the noise families (``ats-relay-noise``, ``not-job-mail``) a fall means
    neither: it means lifecycle patterns have started matching mail that must
    never become an application.
    """

    shortfalls = _discovery_shortfalls(measured)
    recorded = {reach.PatternId(*entry) for entry in RECORDED_FIRED}
    gained = sorted(measured.fired - recorded)
    assert not shortfalls, (
        "discovery rate fell:\n  "
        + "\n  ".join(shortfalls)
        + f"\n\nthe engine gained {len(gained)} newly-exercised pattern(s): "
        + (", ".join(str(p) for p in gained) if gained else "NONE")
        + "\n\nNONE means the corpus moved toward the engine, which observed.py "
        "forbids. A non-empty list means a real gap closed — re-record, and say "
        "which pattern closed it."
    )


def test_the_invented_families_still_discover_nothing(measured) -> None:
    """DIRECTION: a recorded ZERO is an EQUALITY, not a floor.

    27 families, 13,760 messages, and not one sentence in them that the
    classifier was not already taught — they were written by the author of
    ``rules.py``. That is the finding #530 is about, and it is pinned as a
    defect at its measured size rather than excluded, the way the rest of this
    corpus's known defects are.

    If one of these goes non-zero, something invented a wording the engine has
    never seen. That is a real change in what the corpus can find and it must be
    recorded and argued for, not absorbed. It is also the direction #531
    explicitly forbids for interview and offer: inventing wordings and filing
    them as evidence rebuilds the closed loop one layer up.
    """

    zeros = {f for f, (_, _, n) in RECORDED_FAMILIES.items() if n == 0}
    assert len(zeros) == 27, "the recorded set of circular families"
    moved = {
        family: measured.families[family].no_strong
        for family in sorted(zeros)
        if measured.families[family].no_strong
    }
    assert not moved, (
        f"families recorded as discovering nothing now do: {moved}. If this is "
        f"a new wording the engine was never taught, say so and re-record."
    )


#: A sentence no ``strong`` pattern in the engine matches — asserted below
#: rather than assumed, because a control built out of language the engine
#: already knows proves nothing.
_UNTAUGHT_SUBJECT = "A note from the team"
_UNTAUGHT_BODY = (
    "Ayush, the panel liked what they saw and the team will circle back once "
    "the req is signed off upstairs."
)


def test_a_zero_discovery_rate_is_a_finding_and_not_a_blind_spot(cases, measured) -> None:
    """THE CONTROL ON THE ZERO. It has to be provably able to be non-zero.

    27 families read 0.0% and the honest question about any recorded zero is
    whether the instrument could ever have reported anything else. So one
    ``interview`` message — a family recorded at 0 of 700 — is rewritten to a
    wording the engine was never taught, and the family's counter is required to
    move by EXACTLY one, with the denominator unchanged.

    Directional in both halves: the injected wording is first asserted to match
    no strong pattern, because a control that quietly fires a rule would show
    the counter NOT moving and read as a passing test.
    """

    injected = reach.scan_text(_UNTAUGHT_SUBJECT, _UNTAUGHT_BODY)
    matched = sorted(
        str(pid)
        for pid, rx in reach.positive_patterns()
        if pid.tier == "strong" and rx.search(injected)
    )
    assert not matched, f"the control is not inert; it fires {matched}"

    swapped = False
    items = []
    for case in cases:
        family, text, said = reach.texts_of(case)
        if family == "interview" and not swapped:
            text = injected
            said = reach.wording(_UNTAUGHT_SUBJECT, _UNTAUGHT_BODY)
            swapped = True
        items.append((family, text, said))
    assert swapped, "no `interview` case to rewrite"

    before = measured.families["interview"]
    after = reach.measure_texts(items).families["interview"]
    assert before.no_strong == 0, "the recorded zero"
    assert after.messages == before.messages == 700, "the denominator is untouched"
    assert after.no_strong == 1, (
        f"one untaught sentence in 700 and the counter reads {after.no_strong}; "
        f"the zero above is a property of the instrument, not of the corpus"
    )


# ── the mutation this gate was built against ─────────────────────────────────

#: An ``interview`` rule that 17,260 messages have never fired, copied VERBATIM.
#: A literal one on purpose: pasting a regex with alternations into a wording
#: would prove a string was inserted, not that the rule matches ATS prose.
_MUTATION = reach.PatternId("interview", "strong", "panel interview")


def _longest_literal(template: str) -> str:
    """The longest run of a template that is not a ``{placeholder}``."""

    return max(re.split(r"\{[a-z]+\}", template), key=len).strip()


def test_copying_an_engine_pattern_into_an_observed_wording_reds_this_gate(
    cases, measured
) -> None:
    """#530's own proof obligation: make the gate fail before shipping it.

    The mutation is the one the issue names — one engine pattern copied verbatim
    into one ``observed.py`` template — applied to the wording behind
    ``observed-closure``, the family with the most discovery power per message
    (50.8%). It is applied to the TEXT rather than to the file so the proof is
    permanent and runs in CI; the same edit made to ``observed.py`` on disk
    produces the same numbers and is quoted in the PR.

    Two of the three metrics move, in opposite directions, which is what makes
    them independent measurements rather than one number twice:

    * pattern coverage RISES, 48 -> 49, and ``interview``'s ledger of
      unexercised rules falls 26 -> 25. Coverage alone would call that an
      improvement, which is exactly why coverage alone is not the gate.
    * ``observed-closure``'s discovery rate COLLAPSES, 50.8% -> 0.8%, and
      ``_discovery_shortfalls`` names it. Real evidence was replaced by an echo
      of the rule list, and the number that says so is the discovery rate.
    """

    assert _MUTATION not in measured.fired, "the mutation must start unexercised"

    marker = _longest_literal(observed.OBSERVED_CLOSURES[0][1])
    touched = 0
    items = []
    for case in cases:
        family, text, said = reach.texts_of(case)
        if family == "observed-closure" and marker in case.body:
            body = f"{case.body} We would also book a {_MUTATION.pattern}."
            text = reach.scan_text(case.subject, body)
            said = reach.wording(case.subject, body)
            touched += 1
        items.append((family, text, said))
    assert touched == 120, (
        f"the mutation reached {touched} messages, not the 120 drawn from "
        f"OBSERVED_CLOSURES; it is measuring nothing"
    )

    mutated = reach.measure_texts(items)

    assert _MUTATION in mutated.fired
    assert mutated.fired == measured.fired | {_MUTATION}
    assert len(mutated.fired) == len(measured.fired) + 1 == 49
    assert mutated.never_fired_by_category["interview"] == 25

    closure = mutated.families["observed-closure"]
    assert closure.messages == 240, "the denominator is untouched"
    assert closure.no_strong == 2, f"122 -> {closure.no_strong}"
    assert closure.discovery_rate < 0.01

    shortfalls = _discovery_shortfalls(mutated)
    assert any(s.startswith("observed-closure:") for s in shortfalls), (
        f"the gate did not notice: {shortfalls}"
    )
