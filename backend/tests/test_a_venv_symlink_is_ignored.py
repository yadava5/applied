"""A virtualenv is ignored whether it is a DIRECTORY or a SYMLINK to one.

`.gitignore` carried `.venv/`, `.venv*/` and `venv/`, and every one of those has
a trailing slash. **A trailing slash matches directories only.** So a symlink
named `.venv311` — the obvious thing to create in a worktree that needs the
interpreter the real checkout already has — was not ignored by any of them, and
`git status` listed it as untracked all session.

What that costs is specific, and it is not "a stray entry in `git status`". Git
stores a symlink as a blob whose CONTENT IS THE TARGET PATH. So `git add -A` in
such a worktree publishes an absolute path from the author's filesystem into a
**public** repository. Found by an agent that hit it, and reproduced here before
the pattern was changed:

    $ ln -s /path/to/backend/.venv311 .venv311
    $ git check-ignore -v .venv311
    $ echo $?
    1                      # not ignored

The fix keeps BOTH forms of each pattern rather than replacing the slashed one:
the slashless pattern is what catches the link, and the slashed pattern stays
because it is the clearer statement of the ordinary case.

`git check-ignore` decides from the path STRING, not from what is on disk, so
these cases need no files created and no cleanup — verified by running it both
ways, against a real symlink and against a name with nothing behind it, and
getting the same answer.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _is_ignored(path: str) -> bool:
    """True when git would ignore ``path``. Never creates anything."""

    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", path],
        cwd=ROOT,
        capture_output=True,
    )
    # 0 = ignored, 1 = not ignored. Anything else is git failing to answer, and
    # must not be read as either verdict.
    assert result.returncode in (0, 1), (
        f"git check-ignore could not answer for {path!r}: "
        f"rc={result.returncode} stderr={result.stderr.decode()!r}"
    )
    return result.returncode == 0


@pytest.mark.parametrize(
    "name",
    [
        ".venv",  # the plain one, as a link rather than a directory
        ".venv311",  # the one that was actually created and actually leaked
        ".venv313",
        ".venv-migrate",
        "venv",
    ],
)
def test_a_venv_by_any_of_its_names_is_ignored(name: str) -> None:
    assert _is_ignored(name), (
        f"{name!r} is not ignored, so a SYMLINK by that name would be committed "
        "as a blob holding its target — an absolute path from somebody's "
        "filesystem, in a public repository"
    )


def test_the_instrument_can_return_not_ignored() -> None:
    """The control, without which every assertion above passes vacuously.

    If `_is_ignored` returned True unconditionally — a wrong `cwd`, a git that
    cannot read `.gitignore`, an `--` that swallowed the path — the parametrized
    test would be green for a `.gitignore` with the defect still in it. These are
    tracked files, so git must answer "not ignored" for them.
    """

    for tracked in ("README.md", ".gitignore", "backend/jobtracker/__init__.py"):
        assert not _is_ignored(tracked), (
            f"{tracked!r} reads as ignored, so this module's other assertions "
            "prove nothing about .gitignore"
        )


def test_the_slashless_forms_are_present_and_are_what_does_the_work() -> None:
    """Pinned as text, because the behaviour above has one cause.

    A future edit that tidies the "duplicate" patterns away would take the
    symlink case with it, and the parametrized test would go red without saying
    why. This one names the reason.
    """

    patterns = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    for slashless in (".venv", ".venv*", "venv"):
        assert slashless in patterns, (
            f"{slashless!r} is gone from .gitignore. The slashed form "
            f"{slashless + '/'!r} matches DIRECTORIES ONLY and does not cover a "
            "symlink of that name"
        )
