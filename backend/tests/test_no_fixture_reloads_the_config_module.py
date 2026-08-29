"""No test module may ``importlib.reload`` the config module.

WHY THIS FILE EXISTS
--------------------
``jobtracker.config.settings`` is a singleton that every other module binds BY
REFERENCE at import time — ``jobtracker.auth.supabase_jwt``,
``jobtracker.database.connection`` and ``jobtracker.credentials.cloud`` all do
``from jobtracker.config import settings``. ``importlib.reload`` on that module
rebuilds the ``Settings`` class, constructs a NEW instance and rebinds
``jobtracker.config.settings`` to it. Every other holder keeps the old one.

From then on the process has two settings objects and no way to tell which one
any given reader will consult. The failure that follows is loud, remote and
attributed to the wrong commit: a module that patches
``jobtracker.config.settings.supabase_jwt_secret`` sets the test JWT secret on
an object the verifier never reads, and every request it makes comes back
``401 Invalid signature`` — green when the module runs alone, red in a full run.

That is what #582 was. Six tests in ``test_application_delete_children.py``
failed for no reason other than the alphabetical position of
``test_status_vocabulary.py``, and the fix for one of them is not a fix: the
survey found 25 of the suite's modules doing it. Reloading is the mechanism, so
this file forbids the mechanism.

WHAT THIS IS NOT
----------------
It is not a ledger of known offenders. There are none left, and the assertion
is that the count is ZERO — a module added tomorrow with the old fixture shape
turns this red on its first CI run rather than turning somebody else's module
red three merges later.

Reloading OTHER modules is still allowed and still done (``test_main_cloud``
rebuilds ``jobtracker.main_cloud`` to re-run its import-time CORS wiring). Those
do not mint a second ``Settings``. ``test_a_reload_of_a_different_module_is_not
_flagged`` is the control that keeps this file honest about the difference.

THE REPLACEMENT, for whoever this test just stopped
---------------------------------------------------
Patch the attributes instead of rebuilding the object, on every instance the
request path holds, de-duplicated by identity::

    import jobtracker.auth.supabase_jwt as auth_module
    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    holders = {
        id(module.settings): module.settings
        for module in (config_module, auth_module, connection_module)
    }
    for instance in holders.values():
        monkeypatch.setattr(instance, "environment", "test")
        monkeypatch.setattr(instance, "supabase_jwt_secret", JWT_SECRET)

``database_url`` is a property derived from ``environment``, so the in-memory
URL follows from the same patch, and ``monkeypatch`` undoes each write exactly
— which the old teardown never did, because a second reload minted a THIRD
instance rather than restoring the first.
"""

from __future__ import annotations

import ast
from pathlib import Path

# The module whose reload splits the singleton. Written as a dotted path and
# compared against a RESOLVED path, never against the spelling of a local
# alias: ``import jobtracker.config as c`` is the same defect as
# ``import jobtracker.config as config_module`` and has to be caught the same.
FORBIDDEN = "jobtracker.config"

# The suite is 100+ modules. A source scan that silently matched nothing would
# pass this file vacuously, which is the exact shape of check this repo keeps
# having to fix, so the corpus size is asserted rather than assumed.
MODULE_FLOOR = 100

TESTS_DIR = Path(__file__).resolve().parent


def _test_sources() -> dict[str, str]:
    """Every module pytest can collect from ``backend/tests``, read as text.

    ``conftest.py`` is included: it is not named ``test_*`` but it runs in the
    same process and a reload there would leak to every module in the session.
    """

    paths = sorted(TESTS_DIR.glob("test_*.py")) + sorted(TESTS_DIR.glob("conftest.py"))
    return {p.name: p.read_text(encoding="utf-8") for p in paths}


def _dotted_path(node: ast.expr, aliases: dict[str, str]) -> str | None:
    """Resolve an expression to the module path it names, if it names one.

    Handles the three ways a test file gets hold of the config module::

        import jobtracker.config as config_module   ->  config_module
        import jobtracker.config                    ->  jobtracker.config
        from jobtracker import config               ->  config

    and the attribute form, so ``importlib.reload(jobtracker.config)`` resolves
    even when only ``import jobtracker.config`` was written.
    """

    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        head = _dotted_path(node.value, aliases)
        return None if head is None else f"{head}.{node.attr}"
    return None


def _alias_map(tree: ast.AST) -> dict[str, str]:
    """Local name -> the module it actually refers to.

    Collected over the WHOLE tree rather than per scope, deliberately: these
    imports live inside fixture bodies as often as at module level, and a gate
    that over-approximates refuses a defect it cannot prove is absent.
    """

    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = (
                    a.name if a.asname else a.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for a in node.names:
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"
    return aliases


def config_reload_lines(source: str) -> list[int]:
    """Line numbers at which ``source`` reloads :data:`FORBIDDEN`.

    Takes text rather than a path so the controls below can hand it a module
    that does not exist on disk. A gate with no red case is not a gate.
    """

    tree = ast.parse(source)
    aliases = _alias_map(tree)

    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        callee = _dotted_path(node.func, aliases)
        # ``from importlib import reload`` resolves through the alias map to
        # ``importlib.reload``; a bare, unresolvable ``reload`` is kept too
        # rather than assumed innocent.
        if callee not in ("importlib.reload", "reload"):
            continue
        if _dotted_path(node.args[0], aliases) == FORBIDDEN:
            hits.append(node.lineno)
    return hits


# =============================================================================
# The gate
# =============================================================================


def test_no_test_module_reloads_the_config_module() -> None:
    """ZERO, not "no more than before"."""

    offenders = {
        name: lines
        for name, source in _test_sources().items()
        if (lines := config_reload_lines(source))
    }

    assert offenders == {}, (
        "importlib.reload(jobtracker.config) mints a second Settings instance "
        "and orphans every module that imported the first (#582). Patch the "
        "attributes on each live instance instead -- see this file's docstring "
        f"for the replacement. Offenders: {offenders}"
    )


def test_the_scan_read_the_whole_suite() -> None:
    """The floor. A scan that matched nothing must not be able to pass."""

    sources = _test_sources()

    assert len(sources) >= MODULE_FLOOR, (
        f"only {len(sources)} modules were read from {TESTS_DIR}; the gate above "
        "cannot mean anything if the corpus is empty or truncated"
    )
    # Positive control on the corpus itself: a named module that certainly
    # exists must be in it, so a glob that silently stopped matching is caught
    # as well as one that matched too few.
    assert "test_status_vocabulary.py" in sources
    assert "conftest.py" in sources
    assert all(sources.values()), "a module was read as empty text"


# =============================================================================
# The controls -- this file has to be able to go red
# =============================================================================

_RELOADING_MODULE = """
import importlib

import jobtracker.config as config_module


def fixture():
    importlib.reload(config_module)
"""


def test_a_module_that_reloads_the_config_is_flagged() -> None:
    """The red case. Without it the gate above proves only that it ran."""

    assert config_reload_lines(_RELOADING_MODULE) == [8]


def test_a_reload_of_a_different_module_is_not_flagged() -> None:
    """The operand swap: same shape, one name changed, and it must go quiet.

    Deleting the reload would only show the assertion exists. Swapping the
    module for another of the same kind shows the gate reads WHICH module is
    being reloaded -- otherwise it would forbid ``importlib.reload`` outright
    and take ``test_main_cloud`` with it.
    """

    swapped = _RELOADING_MODULE.replace("jobtracker.config", "jobtracker.database")
    assert config_reload_lines(swapped) == []


def test_the_alias_does_not_have_to_be_spelled_like_the_module() -> None:
    """``as c`` is the same defect as ``as config_module``.

    A gate that looked for the substring ``config`` in the argument would pass
    this file and miss the next one.
    """

    disguised = _RELOADING_MODULE.replace("config_module", "c")
    assert config_reload_lines(disguised) == [8]


def test_the_from_import_form_is_flagged() -> None:
    """``from jobtracker import config`` binds the same module by a bare name."""

    source = """
import importlib

from jobtracker import config

importlib.reload(config)
"""
    assert config_reload_lines(source) == [6]


def test_the_unaliased_attribute_form_is_flagged() -> None:
    """``import jobtracker.config`` then ``reload(jobtracker.config)``."""

    source = """
import importlib
import jobtracker.config

importlib.reload(jobtracker.config)
"""
    assert config_reload_lines(source) == [5]


def test_a_bare_reload_imported_from_importlib_is_flagged() -> None:
    """``from importlib import reload`` is the same call by another name."""

    source = """
from importlib import reload

import jobtracker.config as cfg

reload(cfg)
"""
    assert config_reload_lines(source) == [6]
