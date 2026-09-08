"""A recorded baseline must say which tree and which stack produced it.

#446 item 7: the v3 baselines carried `dataset`, `dataset_sha256`,
`generated_at`, `mode` and `sample_count`, which answers "what was measured"
and leaves "by what" unanswered. The investigation that opened that issue spent
its time on exactly the two questions the artifact could not answer -- what code
was this, and what was installed -- so both are now stamped into `meta`.

WHAT THESE TESTS ARE AND ARE NOT. `test_a_recorded_run_stamps...` is a PRESENCE
test, and a presence test compares the writer against itself unless it can be
shown to go red. It was shown to: deleting the two `report["meta"][...] = ...`
lines from `run_evaluation` fails it, and the failure names the missing key.
The other tests are behavioural -- they drive `_code_rev` and
`_package_versions` into states this machine is not in (no git, a dirty tree, a
missing package) and assert what gets recorded, which is the half a presence
test cannot reach.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from jobtracker.scripts import evaluate_classifier as ec

_SHA1 = re.compile(r"^[0-9a-f]{40}$")


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    """Two examples the rules layer can answer without a model or a database."""
    path = tmp_path / "eval.jsonl"
    path.write_text(
        '{"subject":"Application received","body":"Thanks for applying.",'
        '"label":"applied"}\n'
        '{"subject":"Newsletter","body":"This week in tech.","label":"other"}\n',
        encoding="utf-8",
    )
    return path


async def _run(dataset: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """`run_evaluation` in rules mode, with the database stood down.

    The rules layer is regex only -- `predict_labels` never touches a session --
    so `init_db` is the single reason this would need one. Stubbing it keeps the
    test hermetic while still running the real `run_evaluation`, which is the
    function that stamps the provenance and therefore the one worth exercising.
    """

    async def _no_db() -> None:
        return None

    monkeypatch.setattr(ec, "init_db", _no_db)
    return await ec.run_evaluation(dataset, "rules", hybrid_profile="full")


async def test_a_recorded_run_stamps_the_code_rev_and_the_environment(
    dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two blocks #446 item 7 asks for, with the shape a reader depends on."""
    report = await _run(dataset, monkeypatch)
    meta = report["meta"]

    assert "code_rev" in meta, "a baseline that cannot name its tree is not provenance"
    assert set(meta["code_rev"]) == {"commit", "dirty"}
    # Run from a checkout, so this arm is the real answer rather than the
    # None-tolerant fallback. `_code_rev` is separately tested for the
    # not-a-checkout case below.
    assert _SHA1.match(meta["code_rev"]["commit"] or "")
    assert isinstance(meta["code_rev"]["dirty"], bool)

    assert "environment" in meta, "a score is a statement about a stack"
    assert set(meta["environment"]) == {"python", "platform", "packages"}
    assert meta["environment"]["python"].count(".") == 2
    assert "-" in meta["environment"]["platform"]

    # Every declared package has a key whatever this machine has installed --
    # the null-for-absent rule is what makes that true, and it is what lets a
    # rules baseline and a cascade baseline be compared field by field.
    assert set(meta["environment"]["packages"]) == set(ec.PROVENANCE_PACKAGES)
    # scikit-learn specifically: it is the version difference #446's amendment
    # is about (a head pickled under 1.8.0, unpickled under 1.9.0), so a stanza
    # that failed to carry it would not answer the question it was added for.
    assert "scikit-learn" in meta["environment"]["packages"]


async def test_the_stamp_does_not_disturb_what_was_already_recorded(
    dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provenance is additive. The metrics and the older meta keys are untouched."""
    report = await _run(dataset, monkeypatch)

    assert report["meta"]["mode"] == "rules"
    assert report["meta"]["sample_count"] == 2
    assert len(report["meta"]["dataset_sha256"]) == 64
    assert report["overall"]["misclassified"] == 0


def test_an_absent_package_is_recorded_as_null_rather_than_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rules run must not depend on the ML stack being installed.

    The `--mode rules` gate in `backend-ci.yml` needs no torch, and a stanza
    that raised or silently omitted the key would either break that gate or
    make "torch was not here" indistinguishable from "nobody recorded torch".
    """
    real = ec.importlib.import_module

    def _no_torch(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "torch":
            raise ModuleNotFoundError("No module named 'torch'")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(ec.importlib, "import_module", _no_torch)
    versions = ec._package_versions()

    assert "torch" in versions
    assert versions["torch"] is None
    # The rest still resolve, so this is a control for one package and not a
    # test that happens to pass because everything returned null.
    assert versions["numpy"] is not None


def test_a_package_that_raises_on_import_does_not_fail_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A half-installed package raises OSError, not ImportError. Neither may escape."""
    real = ec.importlib.import_module

    def _broken_sklearn(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sklearn":
            raise OSError("dlopen failed: incompatible architecture")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(ec.importlib, "import_module", _broken_sklearn)

    assert ec._package_versions()["scikit-learn"] is None


def test_a_present_but_unversioned_package_is_not_reported_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three states, not two: absent (null), unversioned ("unknown"), or a version."""
    real = ec.importlib.import_module

    class _Unversioned:
        pass

    def _blank(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "setfit":
            return _Unversioned()
        return real(name, *args, **kwargs)

    monkeypatch.setattr(ec.importlib, "import_module", _blank)
    versions = ec._package_versions()

    assert versions["setfit"] == "unknown"
    assert versions["setfit"] is not None


def test_a_dirty_tree_is_recorded_as_dirty(monkeypatch: pytest.MonkeyPatch) -> None:
    """The flag that stops a sha from over-promising.

    Driven both ways from the same stub so the two arms differ in exactly one
    thing -- the porcelain output -- and a stub that always returned the same
    value could not pass both.
    """
    head = "a" * 40

    def _git(*args: str, porcelain: str) -> str | None:
        if args[:1] == ("rev-parse",):
            return head + "\n"
        return porcelain

    monkeypatch.setattr(ec, "_git", lambda *a: _git(*a, porcelain=" M backend/x.py\n"))
    assert ec._code_rev() == {"commit": head, "dirty": True}

    monkeypatch.setattr(ec, "_git", lambda *a: _git(*a, porcelain="\n"))
    assert ec._code_rev() == {"commit": head, "dirty": False}


def test_untracked_files_make_the_tree_dirty(monkeypatch: pytest.MonkeyPatch) -> None:
    """`git status --porcelain` lists untracked paths and that default is kept.

    An uncommitted file can change what a run answers, so it must not read as a
    tree the recorded commit reproduces.
    """
    monkeypatch.setattr(
        ec,
        "_git",
        lambda *a: ("b" * 40 + "\n") if a[:1] == ("rev-parse",) else "?? backend/stray.py\n",
    )

    assert ec._code_rev()["dirty"] is True


def test_outside_a_checkout_the_rev_is_null_and_dirtiness_is_not_claimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ml/demo/space/jobtracker` is a copy, not a checkout.

    `dirty` is null rather than False: "git could not tell us" and "nothing
    differs" are different facts, and recording the second for the first is the
    over-claim the flag exists to prevent.
    """
    monkeypatch.setattr(ec, "_git", lambda *a: None)

    assert ec._code_rev() == {"commit": None, "dirty": None}


def test_an_unreadable_git_status_does_not_forge_a_clean_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HEAD resolves, status does not. The commit is recorded; cleanliness is not."""
    monkeypatch.setattr(
        ec, "_git", lambda *a: ("c" * 40 + "\n") if a[:1] == ("rev-parse",) else None
    )

    assert ec._code_rev() == {"commit": "c" * 40, "dirty": None}


def test_git_failing_outright_is_not_an_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_git` swallows the failure itself, so no caller has to.

    Provenance describes a run; it must never be the reason a run fails.
    """

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("git")

    monkeypatch.setattr(ec.subprocess, "run", _explode)

    assert ec._git("rev-parse", "HEAD") is None
