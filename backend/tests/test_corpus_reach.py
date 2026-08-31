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
        of those, fired ONLY by invented families          17
        fired by at least one ``observed-*`` family        31   (19.5%)
      never fired by anything                             111   (69.8%)

    never fired, by category:  interview 26 of 31 · rejection 20 of 36
      offer 17 of 20 · assessment 15 of 23 · pending_application 14 of 15
      applied 11 of 25 · follow_up 8 of 9

    17,260 messages · 104 distinct wordings corpus-wide

So 111 rules ship to users with nothing in the largest body of evidence this
product has exercising them, and the two worst categories are the two stages a
user cares most about.

AND 30.2% IS THE GENEROUS READING OF THE 48. For 17 of them "fired" means an
invented fixture quotes the pattern's own wording back at it — the author of
``rules.py`` wrote both — so the coverage that rests on mail nobody here wrote
is 31 of 159, **19.5%**. For interview it is 1 of 31 and for offer 1 of 20.
``reach.py`` carries the per-category derivation; quote the two figures
together, because the difference between them is the whole of #531. This gate does NOT close that gap — closing it is #531,
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

import dataclasses
import re

import pytest

from tests.corpus_independent import observed, reach
from tests.corpus_independent.generate import generate

#: The engine's shape when the record below was taken, asserted as a FLOOR on
#: what ``rules.py`` still holds — see ``test_the_record_is_arithmetically_whole``.
#: Not an equality: a pattern ADDED and exercised is a good change and must not
#: red.
#:
#: THAT FLOOR IS THE ASSERTION, AND IT WAS MISSING. This comment used to claim
#: the two directional checks below "bound it from both sides". They do not. A
#: pattern that NEVER FIRED can be deleted from ``rules.py`` outright and
#: neither of them moves: it is absent from ``RECORDED_FIRED``, so nothing goes
#: missing there, and deleting it LOWERS ``never_fired`` for its category, which
#: is the direction that passes. Proved by execution — 159 to 158 left all 17
#: tests green. The ``approx(0.302)`` check could not see it either; it divides
#: two constants declared in this file and measures nothing at all.
#:
#: AND THE FLOOR IS STILL NOT BOTH SIDES — said plainly rather than replacing
#: one overstated bound with another. A delete AND an add in the same commit
#: leaves the total at 159 and passes here; if the deleted pattern never fired
#: and the added one lands in a different category, the ledger below does not
#: see it either. What remains uncovered is a rule dropped in the same breath as
#: an unrelated rule arriving. That is narrower than the hole this closes, and
#: it is named here rather than papered over.
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
    ('applied', 'strong', 'application.{0,20}received'),
    ('applied', 'strong', 'application.{0,30}has been (received|submitted)'),
    ('applied', 'strong', 'be in touch (soon|shortly|if)'),
    ('applied', 'strong', 'reviewing (applications|candidates)'),
    ('applied', 'strong', 'thank(s| you) for (taking the time to )?submit(ting)? your application'),
    ('applied', 'strong', 'thank(s| you) for applying'),
    ('applied', 'strong', "we (have |'ve )received your application"),
    ('applied', 'strong', 'we received your (job )?application'),
    # DEMOTED, not lost. #451 moved this one from `applied`'s `strong` list to
    # its `weak` list: it names WHICH application a message is about and says
    # nothing about what happened to it, so at +3 it tied every offer and
    # rejection that named its own thread and enum order broke the tie. Same
    # regex, same category, same 17,260 messages firing it — only the tier
    # moved, so the entry moves with it rather than leaving this ledger. The
    # count is still 14 of 25 and `RECORDED_POSITIVE_PATTERNS` is still 159.
    ('applied', 'weak', 'application.{0,20}(for|to).{0,40}(position|role|job)'),
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
#:
#: SIX ``no_strong`` FIGURES ROSE WITH #451 and are re-recorded here rather than
#: re-baselined. That PR demotes ``application.{0,20}(for|to).{0,40}(position|
#: role|job)`` from ``applied``'s ``strong`` list to its ``weak`` list, and
#: ``no_strong`` counts messages matching no STRONG pattern anywhere — so
#: removing one from the strong set can only ever raise it. Up is the only
#: direction the demotion can produce; that is a proof from the mechanism, not a
#: direction check, so the moves are attributed message by message as well.
#:
#: Measured on the pre-#451 tree: the messages whose ONLY strong match was the
#: demoted pattern number exactly 72 · 4 · 4 · 16 · 5 · 13 in
#: ``hostile-zero-width``, ``observed-assessment``, ``observed-closure``,
#: ``observed-confirmation``, ``observed-pending`` and ``observed-rejection``
#: — and ZERO in every one of the other 31 families. Those six counts are
#: exactly the six deltas below (28+72, 54+4, 122+4, 4+16, 71+5, 76+13), so
#: every message that moved is accounted for and no family that did not move
#: could have. Nothing else in this file changes: ``total_patterns`` is still
#: 159, the fired set is still 48 (the entry moved tier, it did not leave),
#: every ``never_fired`` count is unchanged, and no ``messages`` or ``wordings``
#: figure moves at all.
#:
#: ``hostile-zero-width`` 28 -> 100 is the largest and reads as a finding rather
#: than a loss: that family's mail is a zero-width-obfuscated acknowledgement,
#: and the ONE strong pattern 72 of its 100 messages could reach was the
#: demoted reference. It now reaches none, which is #451's argument — naming a
#: thread is not reporting on it — applied to the most adversarial mail here.
#:
#: EVERY NUMBER IN THIS TABLE IS A NUMBER AT THE DEFAULT SEED (20260822), and
#: unlike metric 1 these two do not survive a re-seed. Metric 1's fired SET is
#: identical at seeds 20260822, 12345 and 20260829 — the same 48 patterns, not
#: merely the same count. Metrics 2 and 3 are draws from a template pool, so
#: they move: at seed 12345 ``observed-pending`` measures 24 wordings against
#: the 25 recorded here and ``no_strong`` 65 against 76; at seed 20260829, 24
#: and 69. Both would red the directions above, and the source-derived control
#: below fails at both. That is a property of a seeded draw and not a broken
#: mask — but it means the per-family half of this gate is pinned at ONE SEED
#: rather than universally, and a re-seed is a re-recording of this table.
RECORDED_FAMILIES: dict[str, tuple[int, int, int]] = {
    # ── the invented lifecycle. Written by the author of ``rules.py``, so its
    # discovery rate is 0.0% BY CONSTRUCTION: there is no sentence here the
    # engine was not already taught. This column is the measurement that says
    # so, and it is the reason the accuracy figure over this corpus has to be
    # read with the corpus.
    "ambiguous-update": (450, 2, 0),
    # #641. Both wordings are lifted from families already here — the
    # role-naming confirmation and `repeat-anonymous`'s acknowledgement —
    # so it discovers nothing, by construction and not by luck. It exists
    # for the IDENTITY composition, which this metric cannot see.
    "anonymous-third-application": (180, 2, 0),
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
    # #626, and it is invented in the same sense as everything above it: the
    # BODIES are the author's, so its discovery rate is 0.0% by construction and
    # it belongs in this block. What is real about it is the half this metric
    # does not measure — its subjects carry job titles and locations copied from
    # public Greenhouse board APIs, and the thing it grades is the identity
    # reader rather than the classifier.
    #
    # 148 WORDINGS OFF 760 MESSAGES, which is out of scale with every family
    # here and is not a leak in the mask. The mask blanks the corpus's own
    # parameters — the invented employers and the `ROLES` pool — and a real
    # board title is in neither, so each (title x location x boilerplate)
    # combination survives as its own wording. The number is therefore
    # combinatorial, and the "may only grow" direction on it is a pin on the
    # family's shape rather than on its evidence.
    #
    # The corpus is 18,200 messages from this family on; the figures in this
    # file's module docstring describe the 17,260-message corpus measured
    # 2026-08-29 and are left as the dated measurements they are.
    "concatenated-post-name": (760, 148, 0),
    # ── invented, and non-zero for a reason that is NOT discovery. These are
    # noise and truncation families: their mail either is not about a job at
    # all, or is cut off before the verdict. A fall here is a finding of a
    # different kind — lifecycle patterns starting to match mail that must
    # never become an application.
    "ats-relay-noise": (400, 5, 400),
    "hostile-zero-width": (100, 1, 100),  # 28 before #451 — see above
    "not-job-mail": (700, 6, 700),
    "rejection-past-the-snippet": (700, 3, 350),
    # ── TRANSCRIBED. All of the corpus's discovery power, in 1,600 of 17,260
    # messages and 36 templates. These wordings were written by recruiting teams
    # with no knowledge of this repository, so a message here matching no strong
    # pattern is real ATS mail the engine has never been shown.
    #
    # THE FOUR THAT CARRY AN UPDATE run 19.3-52.5%, which is the range #530
    # quotes -- 17.3-50.8% before #451 raised all four, and rejection rather
    # than assessment used to be the floor. The other two are not
    # counter-examples and are not averaged in: observed-confirmation is 6.7%
    # (1.3% before #451) because an acknowledgement is the shape the engine
    # knows best, and observed-not-application is 100% because it is not job
    # mail at all and no lifecycle pattern should touch it.
    "observed-assessment": (300, 26, 58),  # 54 before #451
    "observed-closure": (240, 24, 126),  # 122 before #451
    "observed-confirmation": (300, 23, 20),  # 4 before #451
    "observed-not-application": (80, 1, 80),
    "observed-pending": (240, 25, 76),  # 71 before #451
    "observed-rejection": (440, 29, 89),  # 76 before #451
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


def _engine_shortfall(measured) -> str | None:
    """The complaint for a ``rules.py`` holding FEWER positive patterns than recorded.

    A FUNCTION and not an inline assert, for the same reason
    ``_discovery_shortfalls`` is one: this is the only line in the file that
    reads the engine rather than comparing two of this file's own constants, so
    it is the only one whose ability to fail has to be demonstrated rather than
    assumed. ``test_the_pattern_floor_reads_the_engine_and_not_the_ledger``
    below is that demonstration.
    """

    if measured.total_patterns >= RECORDED_POSITIVE_PATTERNS:
        return None
    return (
        f"`rules.py` holds {measured.total_patterns} positive patterns and "
        f"{RECORDED_POSITIVE_PATTERNS} were recorded, so a rule was deleted or "
        f"moved under EmailCategory.OTHER. Nothing else in this file notices: a "
        f"never-fired pattern is absent from RECORDED_FIRED, and removing it "
        f"LOWERS never_fired for its category, which is the passing direction. "
        f"If the removal is deliberate, re-record — and say which rule went and "
        f"why the mail it was there for no longer needs it."
    )


def _every_pattern_in(table) -> int:
    """Every regex in ``PATTERNS``, positive and negative alike.

    The NAIVE counter — the same int, one attribute wider — and it exists here
    only so the swap below can show it standing still while the real one moves.
    """

    return sum(
        len(getattr(entry, tier))
        for entry in table.values()
        for tier in ("strong", "weak", "negative", "veto")
    )


def test_the_record_is_arithmetically_whole(measured) -> None:
    """48 fired plus 111 never fired is 159, AND the engine still holds 159.

    Two separate claims, and only the second one touches the engine.

    The arithmetic is the check the two directional tests cannot do for
    themselves: they compare MEASURED against RECORDED, so a transcription error
    in RECORDED moves the bar rather than failing.

    THE FLOOR ON ``total_patterns`` IS THE ONE THAT CATCHES A DELETED RULE, and
    it is the only line in this file that does. Everything else here compares
    constants to constants — including the ``approx(0.302)`` below, which reads
    a percentage off two literals and would go on publishing it over an engine
    that had lost a pattern. Without this assertion, deleting a never-fired rule
    from ``rules.py`` outright is green in all 17 tests. The comment on
    ``RECORDED_POSITIVE_PATTERNS`` explains why, and says what this still does
    not bound.
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
    shortfall = _engine_shortfall(measured)
    assert shortfall is None, shortfall
    assert len(RECORDED_FIRED) / RECORDED_POSITIVE_PATTERNS == pytest.approx(
        0.302, abs=0.0005
    ), (
        "the 30.2% this gate's docstring publishes. Two constants divided: this "
        "catches a mistyped ledger, never a moved engine."
    )


def test_the_pattern_floor_reads_the_engine_and_not_the_ledger(
    monkeypatch: pytest.MonkeyPatch, measured
) -> None:
    """THE CONTROL ON THE ONE LINE HERE THAT TOUCHES ``rules.py``.

    The floor's failure message claims to catch a rule "deleted or moved under
    EmailCategory.OTHER". A deletion was proved by hand — 159 to 158 left all 17
    tests green before the floor existed — and that proof lived in a commit
    message. It runs here now, and it is only half of what is owed: DELETION
    PROVES AN ASSERTION IS PRESENT, A SAME-TYPED OPERAND SWAP PROVES IT READS
    THE RIGHT VALUE.

    The swap is the MOVE, and it is a swap in the precise sense: one pattern
    taken out of ``applied``'s ``strong`` list and put into
    ``EmailCategory.OTHER``'s. ``rules.py`` still holds exactly as many regexes
    as before — same type, same total, one dict key different — so a floor that
    counted the whole of ``PATTERNS`` reads 220 both times and stays silent. Only
    a floor reading ``positive_patterns()``, which skips ``OTHER`` because its
    entries are vetoes rather than evidence, sees 158. Deleting a rule moves BOTH
    counters and therefore cannot tell them apart; this is the mutation that can.

    ``positive_patterns()`` resolves ``PATTERNS`` at call time, so the move is
    made on the module attribute and undone by ``monkeypatch``. No corpus is
    scanned: ``measure_texts(())`` reports ``total_patterns`` off an empty
    stream, which is the only field under test.

    THE COMPOSITION AND ITS EDGE. The two halves say "the floor reds one below
    the record" and "the move takes the engine one below where it is". Today the
    engine sits exactly on the record, so together they say the move reds. If a
    rule is legitimately ADDED tomorrow the engine sits at 160, the move leaves
    159, and that is NOT a red — correctly, because the floor is a ``>=`` and
    the "a delete and an add in one commit" hole is already named on
    ``RECORDED_POSITIVE_PATTERNS``. The control degrades to a weaker true claim
    rather than to a false one; it is not written as an ``if``, which would make
    it a check that stops evaluating.
    """

    def _with_total(total: int):
        return reach.Reach(measured.fired, total, measured.families)

    # ── half one: the deletion, in CI rather than quoted from a session ──
    assert _engine_shortfall(measured) is None, "the tree is clean"
    assert _engine_shortfall(_with_total(RECORDED_POSITIVE_PATTERNS - 1)), (
        "one rule fewer than the record and the floor said nothing"
    )
    assert _engine_shortfall(_with_total(RECORDED_POSITIVE_PATTERNS + 1)) is None, (
        "a rule ADDED and exercised is a good change; the floor must not red on it"
    )

    # ── half two: the operand swap — a MOVE, which keeps the file's size ──
    live = reach.PATTERNS
    before_total = reach.measure_texts(()).total_patterns
    assert before_total == measured.total_patterns, "the same engine, unscanned"

    donor = reach.EmailCategory.APPLIED
    other = reach.EmailCategory.OTHER
    moved = live[donor].strong[0]

    swapped = dict(live)
    swapped[donor] = dataclasses.replace(
        live[donor], strong=[p for p in live[donor].strong if p != moved]
    )
    # ``EmailCategory.OTHER`` HAS NO ENTRY IN ``PATTERNS`` TODAY — the skip in
    # ``positive_patterns()`` is defensive rather than load-bearing, which is
    # itself worth knowing, because it means "moved under OTHER" is an ADDED key
    # and not an edited one. The naive count is still unchanged: one regex left
    # ``applied`` and one arrived under ``other``.
    existing_other = live.get(other)
    swapped[other] = (
        dataclasses.replace(existing_other, strong=[*existing_other.strong, moved])
        if existing_other is not None
        else type(live[donor])(strong=[moved])
    )

    assert _every_pattern_in(swapped) == _every_pattern_in(live), (
        "the swap has to leave the file the same size, or it is a deletion "
        "wearing a different hat and proves nothing a deletion did not"
    )

    monkeypatch.setattr(reach, "PATTERNS", swapped)
    after_total = reach.measure_texts(()).total_patterns
    assert after_total == before_total - 1, (
        f"a rule moved under EmailCategory.OTHER and the positive count read "
        f"{after_total} against {before_total}; the floor is counting the whole "
        f"of PATTERNS and cannot see a move at all"
    )


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

    IT HOLDS AT THE DEFAULT SEED, NOT UNIVERSALLY. Derived from source rather
    than recorded is the strong half of the claim and it is true; seed-invariant
    is NOT part of it. Which templates a family draws is itself a seeded choice,
    so a family with little headroom between its message count and its template
    count can simply miss one. Measured: at seeds 12345 and 20260829
    ``observed-pending`` draws 24 of its 25 templates and this test fails. That
    is the "too few" arm firing on a re-seed rather than on an unreachable
    template — a real limit on what the control certifies, and not a flake to be
    widened away. Re-seeding the corpus means re-recording ``RECORDED_FAMILIES``
    and re-reading this.
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
    pattern about 80% of the time in this very corpus (``observed-rejection``,
    351 of 440), so ordinary honest growth lands there more often than not, and
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
    # 27 -> 28 (#626). The 28th is `concatenated-post-name`, whose bodies are
    # invented like every other family in this set — its evidence is in the
    # SUBJECT and is about the identity reader, which this metric does not see.
    # Recorded rather than absorbed, which is what the docstring above asks for.
    # 28 -> 29 (#641). The 29th is `anonymous-third-application`, whose two
    # wordings are copies of families already in this set; its evidence is in
    # the ORDER and the DAYS of its three messages, which this metric does not
    # see either.
    assert len(zeros) == 29, "the recorded set of circular families"
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
    (52.5%). It is applied to the TEXT rather than to the file so the proof is
    permanent and runs in CI; the same edit made to ``observed.py`` on disk
    produces the same numbers and is quoted in the PR.

    Two of the three metrics move, in opposite directions, which is what makes
    them independent measurements rather than one number twice:

    * pattern coverage RISES, 48 -> 49, and ``interview``'s ledger of
      unexercised rules falls 26 -> 25. Coverage alone would call that an
      improvement, which is exactly why coverage alone is not the gate.
    * ``observed-closure``'s discovery rate COLLAPSES, 52.5% -> 2.5%, and
      ``_discovery_shortfalls`` names it. Real evidence was replaced by an echo
      of the rule list, and the number that says so is the discovery rate.

    WHAT THE 120 DOES AND DOES NOT PROVE. ``observed-closure`` is named above as
    the family with the most discovery power per message, and 52.5% is the
    highest of the four that carry an update — but ``OBSERVED_CLOSURES`` holds
    exactly ONE template. The family's 24 wordings are that one closure plus the
    23 acknowledgements every observed family opens with. So ``touched == 120``
    is 100% of this family's non-acknowledgement wording, and what reds below is
    TOTAL replacement of a single-template family's only closure sentence.
    That proves the gate can fail, which is the obligation. It does NOT show the
    gate catching PARTIAL drift across a multi-wording family: one of
    ``observed-rejection``'s six closures edited would move ``no_strong`` by a
    fraction of 89, and the floor might well still hold. The smallest edit this
    gate can notice is not measured anywhere, and #531 — which adds wordings to
    exactly these families — is when that starts to matter.
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
    # SIX, NOT TWO. 126 of these 240 messages reach no strong pattern; the
    # mutation gives 120 of them one, and the 6 left over are the messages the
    # #451 demotion freed -- four of the family's own, plus the two that always
    # sat outside the 120 the marker reaches. Re-recorded with the row above
    # rather than widened: the equality is the point.
    assert closure.no_strong == 6, (
        f"{RECORDED_FAMILIES['observed-closure'][2]} -> {closure.no_strong}"
    )
    # THE CLAIM IS A COLLAPSE, and it is stated as one instead of as a literal
    # threshold. `< 0.01` was true at 0.8% and false at 2.5%, and the repair
    # that widens a constant until the number fits is the re-baseline this file
    # exists to refuse. An order of magnitude off the RECORDED rate says the
    # same thing and cannot be met by nudging a digit.
    recorded_rate = RECORDED_FAMILIES["observed-closure"][2] / closure.messages
    assert closure.discovery_rate < recorded_rate / 10, (
        f"{recorded_rate:.1%} -> {closure.discovery_rate:.1%} is a fall, and "
        f"what this asserts is a collapse"
    )

    shortfalls = _discovery_shortfalls(mutated)
    assert any(s.startswith("observed-closure:") for s in shortfalls), (
        f"the gate did not notice: {shortfalls}"
    )
