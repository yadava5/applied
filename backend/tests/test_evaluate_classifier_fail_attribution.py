"""
The FAIL block must say WHICH layer was wrong (#841).

`learning-gate.yml` runs `cascade_gate.sh`, and it is the only check standing
between a silent ML degradation and `main` -- the backend suite cannot see the
ML layers at all, because the tests touching `embeddings.py` monkeypatch or
inject fakes and pass with the stack uninstalled. So when that gate reds, the
verdict text IS the diagnosis.

Two causes with opposite responses produced the same verdict text:

    a rules pattern got broader   -> narrow the pattern
    a learned layer degraded      -> leave the patterns alone, go to the
                                     checkpoint

Picking wrong is how a red gate gets "fixed" by editing the thing that was not
broken.

**On the issue's premise, corrected.** #841 says both discriminators are
"computed on every run and thrown away". They are not thrown away: `print_summary`
is called unconditionally before all three FAIL paths, so a red run's log already
carries `answered by:` and a per-item `by=`. The defect is *adjacency* -- a
reader who greps `FAIL:` or reads a job summary of the failing lines does not have
them. That is why the fix moves text into the verdict rather than computing
anything new, and why `test_the_arms_are_identical_where_they_should_be` below
pins that the two arms are byte-identical everywhere except attribution: if they
differed in their metrics too, the pair would prove nothing about attribution.

These tests construct report dicts directly. They deliberately do NOT run the
classifier: the arms differ only in the *reporting* path, and the local venv is a
major version behind `requirements.txt`'s floors for transformers, so a run here
would measure a different cascade than CI gates on (#698).
"""

from __future__ import annotations

import ast
from pathlib import Path

from jobtracker.scripts.evaluate_classifier import (
    compare_against_baseline,
    fail_diagnosis,
)

SOURCE = Path(__file__).resolve().parents[1] / "jobtracker/scripts/evaluate_classifier.py"

# What a healthy cascade recorded: SetFit answered 18 of 96.
BASELINE = {
    "meta": {"mode": "hybrid", "hybrid_profile": "full"},
    "overall": {"accuracy": 0.9688, "macro_f1": 0.9688, "weighted_f1": 0.9688},
    "per_label": {
        "assessment": {"support": 12, "precision": 1.0, "recall": 1.0, "f1": 1.0},
        "follow_up": {"support": 12, "precision": 1.0, "recall": 1.0, "f1": 1.0},
    },
    "layers": {"content_filter": 5, "fallback": 12, "rules": 61, "setfit": 18},
    "artifacts": {"setfit": {"checkpoint": "setfit_model_20260306_175404"}},
}

# The identical regression, reached two ways. Same accuracy, same macro_f1, same
# two per-label f1 values -- so `compare_against_baseline` cannot separate them.
_REGRESSED_METRICS = {
    "overall": {"accuracy": 0.9583, "macro_f1": 0.9583, "weighted_f1": 0.9583},
    "per_label": {
        "assessment": {"support": 12, "precision": 0.96, "recall": 0.96, "f1": 0.96},
        "follow_up": {"support": 12, "precision": 0.9565, "recall": 0.9565, "f1": 0.9565},
    },
}


def _arm(layers: dict[str, int], mismatch_methods: list[str]) -> dict:
    return {
        "meta": {"mode": "hybrid", "hybrid_profile": "full"},
        **_REGRESSED_METRICS,
        "layers": layers,
        "mismatches": [
            {"expected": "assessment", "predicted": "other", "method": method}
            for method in mismatch_methods
        ],
    }


# A rules pattern got broader. SetFit still answers its usual 18; the wrong
# verdicts came off the deterministic path.
ARM_BROADENED_RULE = _arm(
    {"content_filter": 5, "fallback": 12, "rules": 61, "setfit": 18},
    ["rules", "rules", "rules", "rules"],
)

# Arm D of #841: the model is loaded and answering, just far less often and
# confidently wrong. Same metrics as above, by construction.
ARM_DEGRADED_MODEL = _arm(
    {"content_filter": 5, "fallback": 28, "rules": 61, "setfit": 2},
    ["setfit", "setfit", "rules", "rules"],
)


def test_the_arms_are_identical_where_they_should_be() -> None:
    """
    A two-variable pair proves neither variable. If these arms differed in their
    metrics as well as their attribution, a difference in the FAIL text would not
    be evidence that *attribution* is what separated them.
    """
    assert ARM_BROADENED_RULE["overall"] == ARM_DEGRADED_MODEL["overall"]
    assert ARM_BROADENED_RULE["per_label"] == ARM_DEGRADED_MODEL["per_label"]
    assert len(ARM_BROADENED_RULE["mismatches"]) == len(ARM_DEGRADED_MODEL["mismatches"])


def test_the_verdict_alone_still_cannot_tell_them_apart() -> None:
    """
    The defect #841 reported, pinned so the control cannot quietly stop being a
    control. If a future change makes `compare_against_baseline` itself
    attribute, this reds and the fix below becomes redundant -- which is a result
    worth being told about, not a failure to route around.
    """
    broadened = compare_against_baseline(ARM_BROADENED_RULE, BASELINE, tolerance=0.001)
    degraded = compare_against_baseline(ARM_DEGRADED_MODEL, BASELINE, tolerance=0.001)

    assert broadened, "both arms must actually fail, or the pair grades nothing"
    assert degraded
    assert broadened == degraded, (
        "the two causes are byte-identical in the verdict lines -- this is the "
        "defect the diagnosis below exists to answer"
    )


def test_the_fail_diagnosis_separates_the_two_causes() -> None:
    """Item 2 of #841: not that both fail, but that the two FAIL texts DIFFER."""
    broadened = fail_diagnosis(ARM_BROADENED_RULE, BASELINE)
    degraded = fail_diagnosis(ARM_DEGRADED_MODEL, BASELINE)

    assert broadened != degraded, (
        "a degraded model and a broadened rule must not produce the same FAIL text"
    )


def test_the_diagnosis_names_the_layer_that_answered_wrong() -> None:
    """
    Differing is necessary and not sufficient: the reader has to be able to act
    on it. Pinned with equality rather than a substring, because a substring
    assertion survives a widened line (`wrong answers by: rules=4, setfit=1`
    contains `rules=4`).
    """
    broadened = fail_diagnosis(ARM_BROADENED_RULE, BASELINE)
    degraded = fail_diagnosis(ARM_DEGRADED_MODEL, BASELINE)

    assert "wrong answers by: rules=4" in broadened
    assert "wrong answers by: rules=2, setfit=2" in degraded

    # And the census that says the model went quiet, against what healthy recorded.
    assert "answered by: content_filter=5, fallback=12, rules=61, setfit=18" in broadened
    assert "answered by: content_filter=5, fallback=28, rules=61, setfit=2" in degraded
    baseline_line = "baseline answered by: content_filter=5, fallback=12, rules=61, setfit=18"
    assert baseline_line in broadened
    assert baseline_line in degraded


def test_a_report_with_no_baseline_still_gets_its_own_attribution() -> None:
    """`--baseline` may point at a path that does not exist yet."""
    lines = fail_diagnosis(ARM_DEGRADED_MODEL, None)
    assert "wrong answers by: rules=2, setfit=2" in lines
    assert not any(line.startswith("baseline answered by:") for line in lines)


def test_unattributed_mismatches_say_so_rather_than_vanish() -> None:
    """
    Every report written before the `method` field existed. An absent line reads
    as "nothing was wrong", which is the opposite of true.
    """
    legacy = {
        "meta": {"mode": "rules"},
        "layers": {"rules": 96},
        "mismatches": [{"expected": "offer", "predicted": "other"}] * 3,
    }
    assert "wrong answers by: not recorded (3 mismatches)" in fail_diagnosis(legacy)


def test_partially_attributed_mismatches_report_the_remainder() -> None:
    partial = {
        "meta": {"mode": "hybrid"},
        "layers": {"rules": 96},
        "mismatches": [
            {"expected": "offer", "predicted": "other", "method": "rules"},
            {"expected": "offer", "predicted": "other"},
        ],
    }
    assert "wrong answers by: rules=1 (1 not recorded)" in fail_diagnosis(partial)


def _main_function() -> ast.FunctionDef:
    tree = ast.parse(SOURCE.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("evaluate_classifier.main not found")


def _returns_one(block: list[ast.stmt]) -> bool:
    return any(
        isinstance(stmt, ast.Return)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value == 1
        for stmt in block
    )


def _calls_diagnosis(block: list[ast.stmt]) -> bool:
    return any(
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
        and stmt.value.func.id == "print_fail_diagnosis"
        for stmt in block
    )


def test_every_fail_path_in_main_carries_the_diagnosis() -> None:
    """
    The wiring pin, and the reason this file is not just the pure-function tests
    above. On #848 a `detail` was threaded all the way through and rendered
    nowhere: it typechecked, and it passed every unit test of the extractor,
    because no test asserted the caller called it. A `fail_diagnosis` nothing
    invokes is exactly that bug.

    One FAIL path is excluded by name: `--hybrid-profile is only valid when
    --mode hybrid` rejects the arguments before any evaluation runs, so there is
    no report to attribute. Excluding it explicitly -- rather than tolerating
    any number of bare exits -- is what makes a NEW unaccompanied FAIL path red
    this test.
    """
    blocks_returning_one = [
        block
        for node in ast.walk(_main_function())
        for block in (getattr(node, "body", []), getattr(node, "orelse", []))
        if isinstance(block, list) and _returns_one(block)
    ]

    assert len(blocks_returning_one) == 5, (
        f"expected 5 failure exits in main(), found {len(blocks_returning_one)}; "
        "a new one must either carry print_fail_diagnosis or be excluded here "
        "with a stated reason"
    )

    undiagnosed = [block for block in blocks_returning_one if not _calls_diagnosis(block)]
    assert len(undiagnosed) == 1, (
        f"{len(undiagnosed)} FAIL paths return 1 without printing the layer "
        "attribution; only the argument-validation exit may"
    )
    argument_validation = ast.dump(ast.Module(body=undiagnosed[0], type_ignores=[]))
    assert "--hybrid-profile is only valid when --mode hybrid" in argument_validation


def test_main_fails_only_by_returning_one() -> None:
    """
    The counter above finds `return 1`. It is blind to `sys.exit(1)`,
    `raise SystemExit(1)` and `os._exit(1)`, so a FAIL path written in any of
    those spellings would leave the count at 4 and never be asked whether it
    carries the diagnosis.

    Rather than teach the counter three more shapes, pin the idiom it counts.
    `main` is a `-> int` that `__main__` wraps in `SystemExit`; an exit written
    any other way is a bug on its own terms.
    """
    offenders: list[str] = []
    for node in ast.walk(_main_function()):
        if isinstance(node, ast.Raise) and "SystemExit" in ast.dump(node):
            offenders.append("raise SystemExit")
        if isinstance(node, ast.Call):
            target = ast.dump(node.func)
            if "'exit'" in target or "'_exit'" in target:
                offenders.append(ast.unparse(node))

    assert offenders == [], (
        f"main() exits by {offenders} as well as by `return 1`; the FAIL-path "
        "counter above only sees `return 1` and would not check these"
    )


# --- the printed FAIL block, from a real main() ------------------------------
#
# Everything above this line reads either a pure function or the source. That
# leaves the fix itself unfalsifiable in three ways, all of which stay green:
#
#   emptying `print_fail_diagnosis`'s body     -- `fail_diagnosis` is still
#                                                 tested, the call still exists
#   dropping its `baseline` argument           -- the AST pin is argument-blind
#   `baseline = None` at the hoist             -- and the compare branch then
#                                                 becomes unreachable, so both
#                                                 non-regression gates would
#                                                 print "no baseline found" and
#                                                 exit 0 FOREVER
#
# The last one is the estate's own recurring defect -- a check that cannot fail
# -- introduced by the very change meant to make failures legible. So this drives
# `main()` end to end with a stubbed evaluation, and reads the bytes it printed.


def _full_report(layers: dict[str, int], methods: list[str], f1: float) -> dict:
    """A report shaped as `compute_report` actually emits one."""
    return {
        "meta": {
            "dataset": "data/evaluation/classifier_eval_v3.jsonl",
            "mode": "hybrid",
            "hybrid_profile": "full",
            "sample_count": 96,
        },
        "overall": {
            "accuracy": f1,
            "macro_f1": f1,
            "weighted_f1": f1,
            "misclassified": len(methods),
        },
        # BOTH labels the baseline carries. A report missing one fails
        #  on "Missing current per-label metrics"
        # rather than on the metric, which is a different verdict than the one
        # these tests mean to produce.
        "per_label": {
            "assessment": {"support": 12, "precision": f1, "recall": f1, "f1": f1},
            "follow_up": {"support": 12, "precision": f1, "recall": f1, "f1": f1},
        },
        "layers": layers,
        "mismatches": [
            {
                "expected": "assessment",
                "predicted": "other",
                "subject": "a subject",
                "method": method,
            }
            for method in methods
        ],
    }


def _run_main(monkeypatch, tmp_path, report: dict, baseline: dict | str) -> tuple[int, str]:
    """`main()` with the evaluation stubbed out, returning (exit code, stdout)."""
    import io
    import json
    import sys
    from contextlib import redirect_stdout

    from jobtracker.scripts import evaluate_classifier as ec

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(baseline if isinstance(baseline, str) else json.dumps(baseline))

    async def _stub(*_args, **_kwargs) -> dict:
        return report

    monkeypatch.setattr(ec, "run_evaluation", _stub)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_classifier",
            "--mode",
            "hybrid",
            "--hybrid-profile",
            "full",
            "--baseline",
            str(baseline_path),
            "--tolerance",
            "0.001",
        ],
    )

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = ec.main()
    return code, buffer.getvalue()


HEALTHY_LAYERS = {"content_filter": 5, "fallback": 12, "rules": 61, "setfit": 18}
DEGRADED_LAYERS = {"content_filter": 5, "fallback": 28, "rules": 61, "setfit": 2}


def test_the_attribution_is_printed_inside_the_fail_block(monkeypatch, tmp_path) -> None:
    """
    ADJACENCY IS THE WHOLE ISSUE, and this is the only test that measures it.

    #841's defect was never that the discriminators were uncomputed -- they are
    printed above the verdict on every run. It is that a reader who greps
    `FAIL:` does not have them. So the assertion is positional: the three lines
    must appear AFTER the FAIL header, not merely somewhere in the output, which
    was already true before the change.
    """
    code, out = _run_main(
        monkeypatch,
        tmp_path,
        _full_report(DEGRADED_LAYERS, ["setfit", "setfit", "rules", "rules"], 0.96),
        BASELINE,
    )

    assert code == 1
    header = out.index("FAIL: non-regression checks failed")

    for line in (
        "answered by: content_filter=5, fallback=28, rules=61, setfit=2",
        "wrong answers by: rules=2, setfit=2",
        "baseline answered by: content_filter=5, fallback=12, rules=61, setfit=18",
    ):
        assert line in out, f"the FAIL block never printed {line!r}"
        assert out.index(line, header) > header, f"{line!r} appears only above the verdict"


def test_a_passing_run_prints_no_failure_attribution(monkeypatch, tmp_path) -> None:
    """
    The other side of adjacency, and the pin that makes the branch REACHABLE.

    `baseline = None` at the hoist keeps every other test in this file green
    while making the comparison unreachable -- both backend-ci non-regression
    gates would print "No baseline found ... skipping" and exit 0 forever. This
    is the assertion that reds on it.

    `answered by:` is NOT asserted absent: `print_summary` prints it on every
    run, which is the fact that made the issue's premise wrong. `wrong answers
    by:` is emitted only by `fail_diagnosis`, so it is the discriminating one.
    """
    code, out = _run_main(
        monkeypatch,
        tmp_path,
        _full_report(HEALTHY_LAYERS, [], 1.0),
        BASELINE,
    )

    assert code == 0
    assert "PASS: non-regression checks passed" in out
    assert "No baseline found" not in out, "the baseline was not read at all"
    assert "wrong answers by:" not in out, "a passing run printed a failure diagnosis"


def test_an_unreadable_baseline_fails_rather_than_skipping(monkeypatch, tmp_path) -> None:
    """
    W2. Hoisting the baseline read above the verdicts made an unparseable
    baseline crash before anything printed, and -- worse -- the obvious repair
    was to fall through to the "no baseline found" branch, which exits 0.

    A conflict-marked committed JSON is the realistic instance. Absent and
    unparseable are different states; only the first may be green.
    """
    code, out = _run_main(
        monkeypatch,
        tmp_path,
        _full_report(HEALTHY_LAYERS, ["rules"], 1.0),
        "<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> main\n",
    )

    assert code == 1
    assert "FAIL: the baseline at" in out
    assert "could not be read" in out
    assert "--update-baseline" in out, "the note does not name the remedy"
    assert "skipping regression checks" not in out, "an unreadable baseline read as absent"
    # The summary still ran: the reader keeps the run they paid for.
    assert "=== Classifier Evaluation ===" in out


def test_update_baseline_survives_a_baseline_it_cannot_parse(monkeypatch, tmp_path) -> None:
    """
    `compare_against_baseline` and `cascade_gate.sh --help` both advertise
    `--update-baseline` as the remedy for a bad baseline. Before W2's fix the
    hoisted read stack-traced on the way to it, so the documented repair for a
    corrupt file was itself broken by it.
    """
    import io
    import json
    import sys
    from contextlib import redirect_stdout

    from jobtracker.scripts import evaluate_classifier as ec

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{not json at all")
    report = _full_report(HEALTHY_LAYERS, [], 1.0)

    async def _stub(*_args, **_kwargs) -> dict:
        return report

    monkeypatch.setattr(ec, "run_evaluation", _stub)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_classifier",
            "--mode",
            "hybrid",
            "--hybrid-profile",
            "full",
            "--baseline",
            str(baseline_path),
            "--update-baseline",
        ],
    )

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = ec.main()

    assert code == 0, buffer.getvalue()
    assert "Updated baseline" in buffer.getvalue()
    assert json.loads(baseline_path.read_text())["overall"]["macro_f1"] == 1.0
