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

IDENTIFYING WHAT LEAKED
-----------------------
Every testcontainers container carries ``org.testcontainers.session-id``, one
value per interpreter. Diffing the set of session ids before and after the
subprocess attributes containers to *that run* rather than counting, so a
container someone else left behind cannot red this. It does assume no second
pytest process is starting containers in the same window, which holds in CI
and on a desktop running one suite.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent

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


def _session_ids() -> set[str]:
    """Every ``org.testcontainers.session-id`` present, running or exited."""

    out = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            "label=org.testcontainers=true",
            "--format",
            '{{.Label "org.testcontainers.session-id"}}',
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def _remove(session_ids: set[str]) -> None:
    """Take out containers this test's own control deliberately leaked."""

    for session_id in session_ids:
        ids = subprocess.run(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                f"label=org.testcontainers.session-id={session_id}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout.split()
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


@requires_docker
def test_the_measurement_can_see_a_container_that_is_never_registered() -> None:
    """Directional control: an unregistered container DOES show up as leaked."""

    pytest.importorskip("testcontainers.community.postgres")

    before = _session_ids()
    run = subprocess.run(
        [sys.executable, "-c", LEAKY_SNIPPET],
        cwd=BACKEND_DIR,
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=600,
    )
    leaked = _session_ids() - before
    try:
        assert run.returncode == 0, run.stderr[-2000:]
        assert len(leaked) == 1, (
            "the control was supposed to leak exactly one session, "
            f"saw {sorted(leaked)}"
        )
    finally:
        _remove(leaked)


@requires_docker
@pytest.mark.parametrize("module", DRIVEN_MODULES)
def test_importing_a_postgres_module_leaves_no_container(module: str) -> None:
    """``--collect-only`` imports the module, starts a container, and exits."""

    before = _session_ids()
    run = subprocess.run(
        [sys.executable, "-m", "pytest", module, "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=BACKEND_DIR,
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=900,
    )
    leaked = _session_ids() - before
    try:
        assert run.returncode == 0, (
            f"collection of {module} failed, so it may never have started a "
            f"container and this assertion would prove nothing:\n"
            f"{run.stdout[-2000:]}\n{run.stderr[-2000:]}"
        )
        assert leaked == set(), (
            f"{module} left {len(leaked)} testcontainers session(s) behind "
            f"after --collect-only: {sorted(leaked)}"
        )
    finally:
        _remove(leaked)


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
