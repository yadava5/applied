"""The company-name regexes must not be quadratic in the length of a name.

Why this file exists
--------------------

Three module-level patterns in ``cloud/pipeline.py`` were polynomial under
``re.sub``/``re.search``, which retry at every start position:

* ``_VIA_TAIL`` — CodeQL ``py/polynomial-redos``, alert 80. A leading ``\\s*``
  re-scanned a whitespace run from every offset inside it, and a trailing
  ``.*$`` re-scanned a line from every offset whenever ``$`` was out of reach.
* ``_EMPLOYER_AT_SIGN`` — ``\\s*[!?.]*\\s*$`` split a trailing whitespace run
  between two quantifiers every way it could.
* ``_NAME_IS_ADDRESS`` — ``^\\S+@\\S+\\.\\S+$``, three greedy runs separated by
  characters those runs can themselves match.

All three read attacker-supplied text. A mail subject is written by whoever
sends the mail, and ``ReviewClassifyRequest.company`` is a JSON string field
with no length bound at all, so "a very long company name" is a request anyone
with an account can make.

The two halves of the fix each need proving, and they pull in opposite
directions — a pattern is easy to make fast by making it wrong:

``test_*_is_linear`` measures. It compares the OLD pattern with the new one in
the same process, so the fast assertion is never alone: if the harness is
broken, the slow assertion fails too and says so. That is the negative control.

``test_*_equivalent*`` measures nothing and proves the rewrite kept the
meaning — exhaustively over short strings, and over the test tree's own string
literals for long ones.

The one deliberate behaviour change is stated in
:func:`test_the_only_divergence_is_whitespace_the_callers_now_canonicalise`.
"""

import ast
import itertools
import pathlib
import re
import time

import pytest

from jobtracker.cloud import pipeline as p

# The patterns exactly as they stood before this file was written. Recompiled
# rather than imported, because the point is to compare against something that
# no longer exists in the module.
OLD_VIA_TAIL = re.compile(r"\s*(?:\bvia\b|\bthrough\b|\bon\b|[(\[]).*$", re.IGNORECASE)
OLD_EMPLOYER_AT_SIGN = re.compile(r"@\s*(" + p._COMPANY_CAPTURE + r")\s*[!?.]*\s*$")
OLD_NAME_IS_ADDRESS = re.compile(r"^\S+@\S+\.\S+$")

#: Long enough that the quadratic term dominates, short enough that the slow
#: half of each test stays well under a second.
BLOWUP_N = 5_000

#: What the NEW pattern must come in under. This is the guarantee the file
#: exists to make, and it is an absolute number on purpose: a request pays wall
#: time, not a ratio. A loaded runner only ever makes this assertion harder,
#: which is the safe direction.
BUDGET_MS = 50.0

#: What the CONTROL must see between the old pattern and the new one.
#:
#: THIS USED TO BE ``old_ms > BUDGET_MS`` AND THAT WAS MACHINE-DEPENDENT. The
#: note here claimed "three orders of magnitude of headroom ... a loaded runner
#: only ever makes the SLOW assertion safer". Both halves were wrong. The
#: headroom is three orders of magnitude for the ``_VIA_TAIL`` cases and was
#: generalised to all of them; measured, the old timings at ``BLOWUP_N`` are:
#:
#:     clean: whitespace run             414 ms
#:     clean: name then whitespace       417 ms
#:     name is address                   184 ms
#:     employer at-sign                   87 ms   <-- 1.7x the budget
#:     clean: open parens non-final       63 ms   <-- 1.3x the budget
#:
#: And it is a FAST runner, not a loaded one, that breaks a "this must be slow"
#: assertion. On 2026-08-21 a GitHub runner ran the last two in 43.80 ms and
#: 37.64 ms and both controls failed, on a PR that touches neither pattern.
#:
#: A RATIO cannot have that failure mode: both halves are timed on the same
#: machine in the same run, so machine speed divides out. The ratios at
#: ``BLOWUP_N`` are 1,112x (the smallest) to 30,898x, so 50x leaves more than
#: twenty times the margin while still failing loudly — a restored quadratic
#: brings the ratio to roughly 1.
MIN_SLOWDOWN = 50.0

#: ``_NAME_IS_ADDRESS`` has the mildest of the three quadratics and needs a
#: longer string before the difference is unambiguous (45 ms at 5,000, 180 ms
#: at 10,000). Sized so the control fails loudly if the pattern is ever quietly
#: restored.
ADDR_N = 10_000


def _assert_control(label: str, old_ms: float, new_ms: float) -> None:
    """The control: this comparison can still tell fast from slow.

    Expressed as a RATIO because both halves are timed on the same machine in
    the same run, so machine speed divides out — see :data:`MIN_SLOWDOWN` for
    the flake this replaced.
    """

    ratio = old_ms / new_ms if new_ms > 0 else float("inf")
    assert ratio > MIN_SLOWDOWN, (
        f"{label}: the old pattern was only {ratio:.0f}x the new one "
        f"({old_ms:.2f} ms vs {new_ms:.3f} ms). Below {MIN_SLOWDOWN:.0f}x this "
        "comparison can no longer tell a quadratic from a linear one, so the "
        "assertion below would pass whether or not the fix is still in place."
    )


def _elapsed_ms(fn, *args) -> float:
    start = time.perf_counter()
    fn(*args)
    return (time.perf_counter() - start) * 1000


def _old_clean_company_display(raw: str) -> str:
    """``_clean_company_display`` as it stood before the whitespace step moved."""

    text = OLD_VIA_TAIL.sub("", raw or "").strip()
    text = p._CORP_TAIL.sub("", text).strip(" ,.-&")
    return re.sub(r"\s+", " ", text)


def _old_employer_from_text(raw: str) -> tuple[str, str] | None:
    """``employer_from_text`` over the old cleaner — the TOKEN, not just the
    display, because the token is what rows are matched on."""

    display = _old_clean_company_display(raw or "")
    if not display:
        return None
    token = p._normalize_token(display.split(" ")[0])
    if not p._valid_company_token(token):
        return None
    return token, display


def _old_clean_sender_display_name(raw: str) -> str:
    """``_clean_sender_display_name`` as it stood before the same move."""

    text = OLD_VIA_TAIL.sub("", raw or "").strip()
    for _ in range(4):
        stripped = p._NAME_ROLE_TAIL.sub("", text).strip(" ,.-&|")
        if stripped == text:
            break
        text = stripped
    return re.sub(r"\s+", " ", text).strip(" ,.-&|")


# --------------------------------------------------------------------------- #
# Linearity                                                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("whitespace run", " " * BLOWUP_N),
        ("open parens on a non-final line", "(" * BLOWUP_N + "\nx"),
        ("a real name then a whitespace run", "Acme " + " " * BLOWUP_N),
    ],
)
def test_clean_company_display_is_linear(label: str, payload: str) -> None:
    """The whole cleaner, not just the pattern — this is what a request pays."""

    old_ms = _elapsed_ms(_old_clean_company_display, payload)
    new_ms = _elapsed_ms(p._clean_company_display, payload)

    _assert_control(label, old_ms, new_ms)
    assert new_ms < BUDGET_MS, f"{label}: {new_ms:.2f} ms, budget {BUDGET_MS} ms"


def test_employer_at_sign_is_linear() -> None:
    """A subject ending in a long whitespace run, which is free to send."""

    payload = "@A" + " " * BLOWUP_N + "x"

    old_ms = _elapsed_ms(OLD_EMPLOYER_AT_SIGN.search, payload)
    new_ms = _elapsed_ms(p._EMPLOYER_AT_SIGN.search, payload)

    _assert_control("employer at-sign", old_ms, new_ms)
    assert new_ms < BUDGET_MS, f"{new_ms:.2f} ms, budget {BUDGET_MS} ms"


def test_leading_run_is_linear() -> None:
    """The bare leading-run capture (#512 gap 2), on a long whitespace run.

    It carries no trailing alternation for the engine to backtrack into — the
    delimiter search moved out of the pattern and into ``_SEGMENT_DELIMITER``
    precisely so this one could stay a single anchored capture — but it is the
    newest ``_COMPANY_CAPTURE`` consumer and the family has a ReDoS scar, so it
    is measured rather than argued.
    """

    payload = "A" + " " * BLOWUP_N + "x"

    new_ms = _elapsed_ms(p._LEADING_RUN.match, payload)

    assert new_ms < BUDGET_MS, f"leading run: {new_ms:.2f} ms, budget {BUDGET_MS} ms"


def test_the_segment_delimiter_split_is_linear() -> None:
    """Splitting a subject on its first delimiter, over a pathological input."""

    payload = ("-" + " " * 40) * 400

    new_ms = _elapsed_ms(lambda s: p._SEGMENT_DELIMITER.split(s, 1), payload)

    assert new_ms < BUDGET_MS, f"segment split: {new_ms:.2f} ms, budget {BUDGET_MS} ms"


def test_name_is_address_is_linear() -> None:
    """A sender display name made entirely of at-signs."""

    payload = "@" * ADDR_N

    old_ms = _elapsed_ms(OLD_NAME_IS_ADDRESS.match, payload)
    new_ms = _elapsed_ms(p._NAME_IS_ADDRESS.match, payload)

    _assert_control("name is address", old_ms, new_ms)
    assert new_ms < BUDGET_MS, f"{new_ms:.2f} ms, budget {BUDGET_MS} ms"


# --------------------------------------------------------------------------- #
# Equivalence                                                                  #
# --------------------------------------------------------------------------- #


def _short_strings(alphabet: str, up_to: int) -> list[str]:
    return [
        "".join(t)
        for n in range(up_to + 1)
        for t in itertools.product(alphabet, repeat=n)
    ]


def test_name_is_address_accepts_exactly_the_same_strings() -> None:
    """Exhaustive over every string of length <= 6 in the alphabet that matters.

    The rewrite pins each run to the FIRST delimiter after it instead of letting
    three greedy runs negotiate. That is only sound because the earliest ``@``
    past index 0 leaves the longest tail for the ``.`` to sit in — an argument,
    and arguments about backtracking are how this class of bug gets written in
    the first place. So it is checked rather than reasoned about.
    """

    for s in _short_strings("a@. \n", 6):
        assert bool(p._NAME_IS_ADDRESS.match(s)) == bool(
            OLD_NAME_IS_ADDRESS.match(s)
        ), f"disagreement on {s!r}"


def test_employer_at_sign_captures_exactly_the_same_company() -> None:
    """Exhaustive again, over the characters this pattern can distinguish."""

    for s in _short_strings("@A !.\n", 5):
        old = OLD_EMPLOYER_AT_SIGN.search(s)
        new = p._EMPLOYER_AT_SIGN.search(s)
        assert (old.group(1) if old else None) == (
            new.group(1) if new else None
        ), f"disagreement on {s!r}"


def _corpus() -> list[str]:
    """Every string literal in the test tree — thousands of real subjects,
    sender display names, company names and, deliberately, long prose."""

    out: set[str] = set()
    for f in pathlib.Path(__file__).parent.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and 0 < len(node.value) <= 400
            ):
                out.add(node.value)
    return sorted(out)


def test_the_corpus_is_big_enough_to_mean_something() -> None:
    """A sweep over an empty corpus proves nothing; say so out loud."""

    corpus = _corpus()
    assert len(corpus) > 2_000, f"only {len(corpus)} strings harvested"
    assert any("\n" in s for s in corpus), "no multi-line strings to diverge on"


#: Growth factor a LINEAR routine may show when its input doubles. Timing on a
#: shared runner is noisy at the millisecond scale, so this is generous: a
#: quadratic doubles to ~4x and a linear one to ~2x, and 3.0 sits between them
#: with room for a scheduler hiccup on either side.
MAX_DOUBLING_GROWTH = 3.0


def _growth(fn, make, n: int) -> tuple[float, float, float]:
    """Time `fn` on `make(n)` and `make(2n)`; return both and the ratio.

    Warmed once at each size first: Python's regex engine caches nothing that
    matters here, but the first call into a function pays import-time costs that
    would land entirely on the smaller measurement and manufacture growth.
    """

    small, large = make(n), make(2 * n)
    fn(small)
    fn(large)
    a = min(_elapsed_ms(fn, small) for _ in range(3))
    b = min(_elapsed_ms(fn, large) for _ in range(3))
    return a, b, (b / a if a > 0 else float("inf"))


#: Inputs shaped like the things that made the other three patterns quadratic:
#: a whitespace run, a whitespace run after a word, and a repetition of the
#: literal the pattern is looking for.
DISPLAY_TAIL_PROBES = (
    ("whitespace run", lambda n: " " * n),
    ("name then whitespace", lambda n: "Acme" + " " * n),
    ("whitespace then a tail word", lambda n: " " * n + "Team"),
    ("the tail word, repeated", lambda n: "Team " * (n // 5)),
)


def test_the_display_tail_loop_is_linear() -> None:
    """#532 put a new substitution in front of an unbounded caller.

    ``_clean_company_display`` reads ``ReviewClassifyRequest.company``, a JSON
    string field with no length bound — the same reachability that made the
    other three patterns in this file worth fixing. ``_DISPLAY_TAIL`` runs up to
    four times per call, so a quadratic here would be paid four times over.

    There is no old-versus-new ratio to use as a control, because this pattern
    has no slow predecessor. Growth under doubling is the measurement instead,
    and :func:`test_the_doubling_measurement_can_see_a_quadratic` is what says
    the measurement can fail.
    """

    for label, make in DISPLAY_TAIL_PROBES:
        small, large, ratio = _growth(p._clean_company_display, make, 16_000)
        assert ratio < MAX_DOUBLING_GROWTH, (
            f"{label}: doubling the input multiplied the time by {ratio:.1f}x "
            f"({small:.3f} ms -> {large:.3f} ms). A linear routine doubles; this "
            "is the shape of a quadratic, and _clean_company_display is reached "
            "from an unbounded request field."
        )
        assert large < BUDGET_MS, f"{label}: {large:.2f} ms exceeds the budget"


def test_the_doubling_measurement_can_see_a_quadratic() -> None:
    """The control. Without it the test above passes on a broken timer.

    ``OLD_VIA_TAIL`` is the pattern CodeQL flagged, kept in this file precisely
    so there is something known-quadratic to point an instrument at. If this
    stops showing growth, the assertion above has stopped measuring.
    """

    def quadratic(s: str) -> str:
        return OLD_VIA_TAIL.sub("", s)

    _, _, ratio = _growth(quadratic, lambda n: " " * n, 4_000)
    assert ratio > MAX_DOUBLING_GROWTH, (
        f"the known-quadratic control grew only {ratio:.1f}x under doubling, so "
        "this measurement can no longer distinguish a quadratic from a linear "
        "one and the assertion above proves nothing."
    )


def test_the_sender_cleaner_is_unchanged_on_every_canonical_string() -> None:
    """"Canonical" = one line, single spaces — which is what a name IS.

    Every capture class that feeds these functions from mail excludes newlines,
    so this covers the whole extraction path by construction. The user-typed
    path is the exception and gets its own test below.

    ``_clean_sender_display_name`` is untouched by #532 and still has to be
    byte-identical to the pre-rewrite implementation. ``_clean_company_display``
    does NOT, and the two tests below say exactly how far it may move.
    """

    for raw in _corpus():
        if raw != re.sub(r"\s+", " ", raw):
            continue
        cleaned = p._clean_sender_display_name(raw)
        was = _old_clean_sender_display_name(raw)
        if cleaned == "" and was != "":
            # #581 gave both cleaners a length refusal, and it is the ONLY way
            # the new implementation can empty a name the old one kept. The
            # refusal reads the CLEANED length, so a raw string well over the
            # bound can still clean down under it — which is why the condition
            # below is on the raw and asserted rather than assumed. An
            # over-stripping bug that emptied a short name fails here.
            assert len(raw) > p._MAX_COMPANY_LEN, (
                "the sender cleaner emptied a name the pre-rewrite implementation "
                f"kept, and the input is only {len(raw)} characters, so #581's "
                f"length refusal at {p._MAX_COMPANY_LEN} cannot be the reason:\n"
                f"  input {raw!r}\n  old   {was!r}"
            )
            continue
        assert cleaned == was, raw


def test_the_company_cleaner_only_ever_keeps_MORE_than_it_used_to() -> None:
    """#532's behaviour change, bounded rather than re-baselined.

    ``_CORP_TAIL`` was an unanchored substitution, so it removed its words from
    anywhere in a string — "People Data Labs" came out as "Data". The display
    path now strips an anchored, smaller set, which means every disagreement
    with the old implementation has to be in ONE direction: the new answer
    keeps at least as much of the input as the old one did.

    That is the whole safety argument for the change, so it is asserted over
    the corpus rather than argued in a comment. Re-recording the 240 differing
    answers would prove nothing — a new bug that deleted a different word would
    have been recorded along with the fix.
    """

    diverged = 0
    for raw in _corpus():
        if raw != re.sub(r"\s+", " ", raw):
            continue
        new = p._clean_company_display(raw)
        old = _old_clean_company_display(raw)
        if new == "" and old != "":
            # See the sender-cleaner test above. #532's ratchet asks whether the
            # new cleaner strips more WORDS than the old one; #581's refusal is
            # not a word-stripping decision, and a 364-character sentence is not
            # a name whose words could be over-stripped. Asserted, not skipped,
            # so the exemption cannot become a hiding place.
            assert len(raw) > p._MAX_COMPANY_LEN, (
                "the display cleaner emptied a name the pre-rewrite implementation "
                f"kept, and the input is only {len(raw)} characters, so #581's "
                f"length refusal at {p._MAX_COMPANY_LEN} cannot be the reason:\n"
                f"  input {raw!r}\n  old   {old!r}"
            )
            continue
        if new == old:
            continue
        diverged += 1
        assert len(new) >= len(old), (
            "the display cleaner removed MORE than the implementation it "
            f"replaced, which is the one direction #532 forbids:\n"
            f"  input {raw!r}\n  old   {old!r}\n  new   {new!r}"
        )

    # A vacuous pass is the failure mode here: if the two implementations agreed
    # everywhere, the assertion above would hold and say nothing. The count is a
    # floor, not a target — it moves whenever the test tree gains strings.
    assert diverged >= 100, (
        f"only {diverged} strings distinguish the two cleaners. The old and new "
        "implementations have converged, so the assertion above is no longer "
        "measuring anything."
    )


#: The names #532 is about, and the ones that must keep being trimmed. Written
#: out because the corpus sweep above bounds the DIRECTION of the change and
#: this pins the ANSWER — a cleaner that returned its input unchanged would
#: satisfy "never shorter" perfectly.
COMPANY_DISPLAY_CASES = (
    # A descriptive second word is part of the name and is kept (#532).
    ("Arcgrove Systems", "Arcgrove Systems"),
    ("Northwind Labs", "Northwind Labs"),
    ("Bright Horizons Technologies", "Bright Horizons Technologies"),
    ("Health Solutions Group", "Health Solutions Group"),
    # The words are no longer removed from the MIDDLE or the FRONT either, which
    # is the half that produced a wrong name rather than a short one.
    ("People Data Labs", "People Data Labs"),
    ("Team Liquid", "Team Liquid"),
    ("Systems Research", "Systems Research"),
    # Legal entity forms are still not part of the display name.
    ("Globex Inc.", "Globex"),
    ("Globex Corp", "Globex"),
    ("Cloudflare, Inc.", "Cloudflare"),
    ("Acme Co.", "Acme"),
    ("Acme GmbH", "Acme"),
    # Nor is the recruiting desk, and the loop is what makes two of them go.
    ("Acme Careers", "Acme"),
    ("Crusoe Hiring Team", "Crusoe"),
    # A name that is ONLY a tail word cleans to nothing, so it cannot become a
    # company. `_valid_company_token` refuses it downstream as well, but this is
    # the first of the two gates and it should not be the one that stops.
    ("Careers", ""),
    ("Team", ""),
)


def test_the_company_cleaner_keeps_names_and_trims_suffixes() -> None:
    for raw, want in COMPANY_DISPLAY_CASES:
        assert p._clean_company_display(raw) == want, raw


def test_a_kept_second_word_does_not_split_the_employer() -> None:
    """The reason the trimming existed at all, checked rather than assumed.

    ``_CORP_TAIL``'s comment said it was there so "Globex Corp" and "Globex"
    collapse to one token. For the words #532 restores that was never true:
    :func:`matches_company_token` groups on the LEADING word, so a longer
    display and a bare token were always the same employer. If this ever fails,
    the fix has started filing duplicate cards and must be reverted.
    """

    for display, token in (
        ("Arcgrove Systems", "arcgrove"),
        ("Northwind Labs", "northwind"),
        ("People Data Labs", "people"),
        ("Globex", "globex"),
    ):
        assert p.matches_company_token(display, token), (display, token)


def test_a_newline_bearing_name_is_reachable_from_mail_not_only_from_the_user() -> None:
    """Which callers can deliver the divergent input — measured, not assumed.

    ``_COMPANY_CAPTURE``'s inter-word ``\\s+`` matches a newline, so an employer
    captured out of a SUBJECT can arrive multi-line; seven of the eight employer
    patterns are built on it. That decides how much of the behaviour change
    below is user-typed input and how much is live mail, and the first answer
    written here — "only the user-typed field can do this" — was wrong.
    """

    probes = {
        p._EMPLOYER_ANCHORED: "Your application at Acme\nCorp",
        p._EMPLOYER_ON_BEHALF: "on behalf of Acme\nCorp",
        p._EMPLOYER_BARE_AT: "role at Acme\nCorp",
        p._EMPLOYER_AT_SIGN: "SWE @ Acme\nCorp",
        p._EMPLOYER_LEAD_SEGMENT: "Acme\nCorp | Application Received",
        # #512 gap 2: the leading run is taken on its own now, so the segment's
        # employer can be cut out in front of a lifecycle word.
        p._LEADING_RUN: "Acme\nCorp Follow-Up for A Role",
        p._SUBJECT_NAMES_EMPLOYER: "Thanks for applying to Acme\nCorp",
    }
    for pattern, subject in probes.items():
        match = pattern.search(subject)
        assert match is not None and "\n" in match.group(1), pattern.pattern

    # The one exception, and the reason this is a list and not a rule.
    spaces_only = p._SUBJECT_COMPANY.search("application to Acme\nCorp")
    assert spaces_only is not None and "\n" not in spaces_only.group(1)


def test_the_only_divergence_is_whitespace_the_callers_now_canonicalise() -> None:
    """The one deliberate behaviour change, pinned rather than described.

    A name arriving with a newline, tab or non-breaking space in it is now read
    as the single line it was always assumed to be. Before, a tail marker on a
    non-final line could not match (``.*`` cannot cross ``\\n`` and ``$`` was out
    of reach), so "Acme\\nvia Lever\\nCorp" kept its relay tail and could keep a
    stray newline in the returned display name.

    Over the corpus this is 741 display-only changes and 251 where the TOKEN
    moves as well, so it is not merely cosmetic — and where the token moves, the
    new answer is the one the module was already trying to give. Every one of
    them needs whitespace other than a plain space; on canonical input the two
    implementations agree everywhere, which is the test above.
    """

    raw = "Acme\nvia Lever\nCorp"

    # Note the trailing space the old cleaner leaves behind: it strips ",.-&"
    # after ``_CORP_TAIL`` eats "Corp" but the newline it left is not in that
    # set, and the final whitespace collapse then turns it into a space. That
    # stray space is a second thing the reorder fixes.
    assert _old_clean_company_display(raw) == "Acme via Lever "
    assert p._clean_company_display(raw) == "Acme"

    # Display moves, token does not: a tab inside the first word.
    assert _old_employer_from_text("Acme\tInc") == ("acme", "Acme ")
    assert p.employer_from_text("Acme\tInc") == ("acme", "Acme")

    # And a case where the TOKEN moves. The old cleaner could not match the
    # parenthetical across the newline, so the relay's own name survived as the
    # first word and became the employer — the exact mistake ``_VIA_TAIL``
    # exists to prevent. Nothing nameable is left once it is stripped, and
    # falling through to the resolver's later steps is what should happen.
    assert _old_employer_from_text("(Greenhouse)\nAcme") == (
        "greenhouse",
        "(Greenhouse) Acme",
    )
    assert p.employer_from_text("(Greenhouse)\nAcme") is None


def test_a_via_tail_still_names_the_relay_not_the_company() -> None:
    """The behaviour the pattern exists for, spelled out so a rewrite cannot
    quietly trade correctness for speed."""

    assert p._clean_company_display("Acme via Lever") == "Acme"
    assert p._clean_company_display("Acme through Greenhouse") == "Acme"
    assert p._clean_company_display("Acme (Greenhouse)") == "Acme"
    assert p._clean_company_display("Acme [Ashby]") == "Acme"
    assert p._clean_company_display("Globex Inc.") == "Globex"
    assert p._clean_sender_display_name("Crusoe Hiring Team") == "Crusoe"
