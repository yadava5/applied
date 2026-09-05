"""Every throwaway ``postgres:16`` this suite starts is gone when it exits.

WHAT THIS DEFENDS, AND WHY A UNIT TEST CANNOT
----------------------------------------------
Four modules resolve a Postgres at **import** time and start a container when
no ``JOBTRACKER_TEST_PG_ADMIN_URL`` is exported. Nothing outside this process
reaps them: Ryuk is enabled and does start, but ``Reaper.delete_instance`` is
registered with ``atexit`` and stops the Ryuk container before its 10 s
reconnection timeout can elapse, so on an orderly exit the reaper is dead
before it could act. ``tests/pg_support.py`` carries that measurement.

The consequence was 105 leaked containers on the dev machine holding 4.8 GB of
resident memory and 81 GB of volumes, and ten red tests that looked like
product failures (issue #492).

Asserting that ``register_owned_container`` registers an ``atexit`` handler
would be a check that cannot fail in the way that matters: it would stay green
if a module simply stopped calling it. So this drives a real interpreter,
through the one path where ``teardown_module`` is no help — ``--collect-only``,
which imports the module (starting the container) without executing a test.
Delete the ``register_owned_container`` call from any of the three call sites
and the matching case here goes red.

IDENTIFYING WHAT LEAKED: AN IDENTITY, NOT A WINDOW
--------------------------------------------------
Every testcontainers container carries ``org.testcontainers.session-id``, one
value per interpreter, generated as a ``uuid4`` at first import of
``testcontainers.core.labels``.

This file used to diff that set before and after the subprocess. A difference
excludes anything that existed *before*, which is why it stopped the incident
in #603 — two ryuk containers and a concurrent audit's throwaway, force-removed
out from under a live session. But a difference is a **timestamp**, and it
captures anything that appears inside the window regardless of who started it.
The ``--collect-only`` case below has a 900-second timeout; a second suite
starting anywhere in those fifteen minutes landed in ``leaked`` and was force
removed. Same harm as the original incident, through a narrower door.

So the child is given the session id **before it runs**. A tiny plugin on the
child's ``PYTHONPATH`` sets ``testcontainers.core.labels.SESSION_ID`` to a
value this process chose, and everything that child starts carries it. The
measurement then asks docker for exactly that label. A concurrent session holds
a different uuid and is invisible here — not merely unlikely to collide, but
unable to, which is what ``test_a_concurrent_session_is_neither_flagged_nor_removed``
pins.

One asymmetry is worth recording because it is load-bearing: ``create_labels``
returns early for the ryuk image and never stamps a session id on it
(``testcontainers/core/labels.py:31``). Ryuk containers therefore cannot be
selected by any session-id filter, so the containers named in #603 are outside
the reach of this file by construction now.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent

#: testcontainers stamps this on every container it starts EXCEPT ryuk's.
LABEL_SESSION_ID = "org.testcontainers.session-id"

#: Read by the plugin below, written by ``child_session``.
FORCED_SESSION_ENV = "JOBTRACKER_TEST_FORCED_SESSION_ID"

PLUGIN_MODULE = "_jt_forced_session"

#: Sets the child's testcontainers session id to a value the parent already
#: knows. ``testcontainers.core.container`` does ``from ...labels import
#: SESSION_ID``, which COPIES the value at import time, so this has to land
#: before that module is first imported. Both entry points below satisfy that:
#: ``PYTEST_PLUGINS`` is imported during pytest startup, ahead of collection —
#: and collection is when the driven modules start their containers — while the
#: ``python -c`` child imports it on its own first line.
#:
#: Deliberately NOT ``sitecustomize``: this interpreter already has one from
#: Homebrew, and a second on PYTHONPATH would shadow it rather than run beside
#: it.
FORCING_PLUGIN = f"""import os

_forced = os.environ.get("{FORCED_SESSION_ENV}")
if _forced:
    import testcontainers.core.labels as _labels

    _labels.SESSION_ID = _forced
"""

# The three distinct places a container is started and must be registered.
# ``test_cascade_delete_postgres`` stands for the three modules that share
# ``pg_support.resolve_admin_url``'s memoised container; the other two hold
# their own, against their own schema lifecycle.
DRIVEN_MODULES = [
    "tests/test_cascade_delete_postgres.py",  # -> pg_support.resolve_admin_url
    "tests/test_migrations_postgres.py",
    "tests/test_rls_postgres.py",
]

# Starts a container exactly the way ``pg_support`` does and exits WITHOUT
# registering it. This is the directional control: it proves the measurement
# below can actually see a leak, so a green result means "nothing leaked" and
# not "nothing was started".
LEAKY_SNIPPET = (
    # ``python -c`` gets no PYTEST_PLUGINS, so it adopts the forced session id
    # by importing the plugin itself. This has to come FIRST: the assignment
    # only reaches ``container.py`` while that module is still unimported.
    f"import {PLUGIN_MODULE}\n"
    "from testcontainers.community.postgres import PostgresContainer\n"
    "c = PostgresContainer('postgres:16')\n"
    "c.start()\n"
)


def _docker_is_usable() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return probe.returncode == 0


requires_docker = pytest.mark.skipif(
    not _docker_is_usable(),
    reason=(
        "No Docker daemon, so no module here starts a container and there is "
        "nothing to leak. This leaves the reaping of throwaway postgres:16 "
        "containers UNVERIFIED on this run."
    ),
)


def containers_in(session_id: str) -> list[str]:
    """Container ids carrying exactly this session id.

    THE WHOLE POINT OF THIS FUNCTION is that it names what it wants instead of
    subtracting what it did not expect. It is the measurement the two tests
    below assert on, and swapping it back for a before/after difference reds
    ``test_a_concurrent_session_is_neither_flagged_nor_removed``.

    ``-a`` because a container that has exited still holds its volumes, which
    is most of what #492 measured as leaked. ``--no-trunc`` because ``docker
    create`` hands back a 64-character id while ``ps -q`` truncates to 12, and
    comparing the two forms is a silent mismatch rather than an error.
    """

    out = subprocess.run(
        [
            "docker",
            "ps",
            "-aq",
            "--no-trunc",
            "--filter",
            f"label={LABEL_SESSION_ID}={session_id}",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.split()


def _remove(session_id: str) -> None:
    """Take out the containers of one session this file itself created.

    Destructive, so it is never handed anything but an id minted by
    ``child_session`` a few lines earlier. That is the entire safety argument,
    and it is why the id is chosen rather than discovered.
    """

    ids = containers_in(session_id)
    if ids:
        subprocess.run(
            ["docker", "rm", "--force", "--volumes", *ids],
            capture_output=True,
            timeout=300,
        )


def _child_env() -> dict[str, str]:
    """CI's own recipe, minus any pointer at an already-running Postgres.

    If ``JOBTRACKER_TEST_PG_ADMIN_URL`` leaked in from the parent the driven
    module would resolve to that URL, start nothing, and this file would assert
    that nothing leaked from a run that never had anything to leak.
    """

    env = dict(os.environ)
    env.pop("JOBTRACKER_TEST_PG_ADMIN_URL", None)
    env["JOBTRACKER_ENVIRONMENT"] = "test"
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    return env


@dataclass(frozen=True)
class ChildSession:
    """A session id minted here, plus the env that makes a child adopt it."""

    id: str
    env: dict[str, str]


@pytest.fixture
def child_session(tmp_path: Path) -> Iterator[ChildSession]:
    """Mint a session id, hand it to the child, and reap only that id."""

    session_id = f"jt-reap-{uuid4()}"
    plugin_dir = tmp_path / "forced_session"
    plugin_dir.mkdir()
    (plugin_dir / f"{PLUGIN_MODULE}.py").write_text(FORCING_PLUGIN)

    env = _child_env()
    env[FORCED_SESSION_ENV] = session_id
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (env.get("PYTHONPATH", ""), str(plugin_dir)) if part
    )
    # Reaches `-m pytest` children; the `python -c` child imports it by hand.
    env["PYTEST_PLUGINS"] = PLUGIN_MODULE

    try:
        yield ChildSession(id=session_id, env=env)
    finally:
        _remove(session_id)


@requires_docker
def test_the_measurement_can_see_a_container_that_is_never_registered(
    child_session: ChildSession,
) -> None:
    """Directional control: an unregistered container DOES show up as leaked."""

    pytest.importorskip("testcontainers.community.postgres")

    run = subprocess.run(
        [sys.executable, "-c", LEAKY_SNIPPET],
        cwd=BACKEND_DIR,
        env=child_session.env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    assert containers_in(child_session.id), (
        "the control was supposed to leak a container carrying "
        f"{child_session.id}, and the measurement found none — so a green "
        "result from the cases below would mean 'nothing was seen', not "
        "'nothing leaked'"
    )


@requires_docker
def test_a_concurrent_session_is_neither_flagged_nor_removed(
    child_session: ChildSession,
) -> None:
    """The race #603 stayed open on, pinned.

    A second suite starting DURING the child's run used to land in ``leaked``
    and be force-removed, because the old measurement subtracted a snapshot
    taken before the child began. This creates a container carrying somebody
    else's session id after that snapshot would have been taken, and asserts
    the measurement neither reports nor destroys it.

    ``docker create`` rather than a started container: the label is the whole
    subject here, and a created container appears in ``docker ps -a`` exactly
    like a running one, without waiting for postgres to come up.
    """

    bystander_id = f"jt-bystander-{uuid4()}"
    made = subprocess.run(
        [
            "docker",
            "create",
            "--label",
            "org.testcontainers=true",
            "--label",
            f"{LABEL_SESSION_ID}={bystander_id}",
            "postgres:16",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert made.returncode == 0, made.stderr
    bystander = made.stdout.strip()

    try:
        # The child's own leak, so this run has something real to confuse.
        run = subprocess.run(
            [sys.executable, "-c", LEAKY_SNIPPET],
            cwd=BACKEND_DIR,
            env=child_session.env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert run.returncode == 0, run.stderr[-2000:]

        ours = containers_in(child_session.id)
        theirs = containers_in(bystander_id)

        assert ours, "the child leaked nothing, so this proves nothing"
        assert bystander not in ours, (
            "the measurement claimed a container belonging to another session: "
            f"{bystander} is labelled {bystander_id}, not {child_session.id}"
        )
        assert theirs == [bystander], (
            f"expected the bystander to be intact and alone under its own id, saw {theirs}"
        )

        # And the destructive half: reaping ours must leave theirs standing.
        _remove(child_session.id)
        assert containers_in(bystander_id) == [bystander], (
            "reaping this session's containers removed another session's"
        )
    finally:
        subprocess.run(
            ["docker", "rm", "--force", "--volumes", bystander],
            capture_output=True,
            timeout=300,
        )


@requires_docker
@pytest.mark.parametrize("module", DRIVEN_MODULES)
def test_importing_a_postgres_module_leaves_no_container(
    module: str, child_session: ChildSession
) -> None:
    """``--collect-only`` imports the module, starts a container, and exits."""

    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            module,
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=BACKEND_DIR,
        env=child_session.env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    leaked = containers_in(child_session.id)
    assert run.returncode == 0, (
        f"collection of {module} failed, so it may never have started a "
        f"container and this assertion would prove nothing:\n"
        f"{run.stdout[-2000:]}\n{run.stderr[-2000:]}"
    )
    assert leaked == [], (
        f"{module} left {len(leaked)} container(s) behind after --collect-only: {leaked}"
    )


def _modules_that_can_start_a_container() -> tuple[set[str], set[str]]:
    """``(starts one directly, resolves the shared one)``, by AST, not by grep.

    A comment saying "remember to add new modules to DRIVEN_MODULES" is not a
    check. This reads the tree.
    """

    direct: set[str] = set()
    shared: set[str] = set()
    for path in sorted((BACKEND_DIR / "tests").glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == "PostgresContainer":
                direct.add(f"tests/{path.name}")
            elif node.func.id == "resolve_admin_url":
                shared.add(f"tests/{path.name}")
    return direct, shared


def test_every_module_that_starts_a_container_is_driven_above() -> None:
    """A module added later must be added to ``DRIVEN_MODULES`` or this reds.

    Without this the parametrised list silently stops covering the codebase:
    a fifth Postgres module could leak on every run while every case above
    stayed green. ``pg_support`` itself is not driven directly — it has no
    tests — so it is covered through whichever module resolves its shared
    container.
    """

    direct, shared = _modules_that_can_start_a_container()
    driven = set(DRIVEN_MODULES)

    # pg_support is a helper, not a test module; it is reached through its users.
    direct.discard("tests/pg_support.py")
    shared.discard("tests/pg_support.py")

    assert direct <= driven, (
        "these modules construct a PostgresContainer of their own but are not "
        f"driven by this file: {sorted(direct - driven)}"
    )
    assert shared, "nothing resolves pg_support's shared container any more"
    assert shared & driven, (
        "no module that shares pg_support's container is driven here, so "
        f"pg_support's own registration is untested: {sorted(shared)}"
    )
