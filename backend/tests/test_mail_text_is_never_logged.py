"""Mail text does not go into a log record. Checked structurally, not promised.

Why this file exists
--------------------

``test_body_is_never_persisted.py`` already proves the message BODY never
reaches a log record, by driving the scan with a sentinel in the body and
sweeping every captured record. That sentinel cannot see the other half of the
problem: a subject, a sender address or a company name lifted out of a subject
is mail-derived text too, and CodeQL found one of those in production —
``py/clear-text-logging-sensitive-data``, alert 178, on a company token printed
beside ``user_id`` at WARNING in ``_warn_if_capped``.

The rule's own reason for firing was wrong (it saw a variable called ``token``
and read it as a credential; it is a company name). The finding was right
anyway. A company name beside a user id, in an aggregated log, is a statement
about where that person applied — which is the fact ``/privacy`` promises to
keep, and the reason the log claim is worth testing at all.

A sentinel cannot cover this the way it covers the body, because the offending
records are on error paths a normal scan never takes. So this file checks the
SOURCE: no ``logger.*`` call in ``jobtracker/cloud/`` may pass an expression
that is message content. The check is deliberately about content and not about
"anything personal" — ``user_id``, ``message_id``, ``application_id`` and
counts all stay, because a warning nobody can act on is worse than no warning.

Both halves are controlled. The sweep asserts it found a realistic number of
logger calls, and the checker is run against known-bad snippets — including an
f-string, which is where the next regression would most plausibly hide — to
prove it still says no.

Stated limit: the checker only recognises a receiver literally named
``logger``. That is every logging call in ``cloud/`` today, and the sweep's
count is what would notice a file starting to do something else.
"""

import ast
import logging
import pathlib
import uuid

import pytest

from jobtracker.cloud import applications

CLOUD = pathlib.Path(applications.__file__).parent

#: Attribute names that hold text taken from a message. ``.email`` is
#: deliberately absent: the connected account's own address is account
#: metadata, not message content, and this gate is about the latter.
MAIL_TEXT_ATTRS = frozenset(
    {
        "subject",
        "sender",
        "sender_email",
        "sender_name",
        "snippet",
        "body",
        "body_text",
        "body_html",
        "body_snippet",
        "company",
        "company_display",
        "role",
    }
)

#: The same values as bare locals — ``token`` is here because that is the exact
#: variable alert 178 was raised on.
MAIL_TEXT_NAMES = frozenset(
    {
        "subject",
        "sender_email",
        "sender_name",
        "snippet",
        "body",
        "company",
        "company_display",
        "token",
        "display",
    }
)

LOG_LEVELS = frozenset(
    {"debug", "info", "warning", "warn", "error", "exception", "critical"}
)


def _offending_args(source: str, filename: str) -> list[str]:
    """Every ``logger.<level>`` argument that evaluates to message text.

    ``len(x)`` is allowed through: a length is a shape, not the content, and it
    is what keeps the surviving warnings diagnosable.
    """

    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in LOG_LEVELS:
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "logger"):
            continue
        # ``args[0]`` is included, not skipped. A plain format string holds no
        # Name/Attribute nodes so it costs nothing, and an f-string — which is
        # how this codebase's older logging is written — puts the whole
        # offending expression THERE and nowhere else.
        for arg in node.args + [k.value for k in node.keywords]:
            for sub in ast.walk(arg):
                # A length or a count is fine, and so is anything derived from
                # one, so do not walk into it.
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id in {"len", "bool", "type"}
                ):
                    continue
                bad = (
                    isinstance(sub, ast.Attribute) and sub.attr in MAIL_TEXT_ATTRS
                ) or (isinstance(sub, ast.Name) and sub.id in MAIL_TEXT_NAMES)
                if bad and not _under_len(arg, sub):
                    found.append(f"{filename}:{node.lineno}: {ast.unparse(arg)}")
                    break
    return found


def _under_len(root: ast.AST, target: ast.AST) -> bool:
    """True when ``target`` sits inside a ``len()``/``bool()``/``type()`` call."""

    for node in ast.walk(root):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"len", "bool", "type"}
            and any(sub is target for sub in ast.walk(node))
        ):
            return True
    return False


def _cloud_sources() -> list[tuple[str, str]]:
    return [
        (f.name, f.read_text(encoding="utf-8"))
        for f in sorted(CLOUD.glob("*.py"))
        if f.name != "__init__.py"
    ]


def test_the_sweep_actually_sees_the_logging() -> None:
    """POSITIVE CONTROL on the instrument, not on the code under test."""

    total = 0
    for name, source in _cloud_sources():
        for node in ast.walk(ast.parse(source, name)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in LOG_LEVELS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logger"
            ):
                total += 1
    assert total > 40, f"only {total} logger calls found in {CLOUD}; sweep is broken"


def test_the_checker_still_rejects_a_known_bad_record() -> None:
    """And a control on the checker itself — this is the line alert 178 flagged."""

    bad = (
        "logger.warning('Company lookup hit its cap for user_id=%s token=%r',"
        " user_id, token)"
    )
    assert _offending_args(bad, "<synthetic>"), "the checker no longer says no"

    also_bad = "logger.warning('needs an employer: %s', email.subject)"
    assert _offending_args(also_bad, "<synthetic>")

    # The shape a %-args-only checker cannot see, and the one this repo is most
    # likely to write next: `test_body_is_never_persisted.py` names f-string
    # logging as a case it guards, and `email_clients/gmail.py` still uses it.
    fstring_bad = 'logger.warning(f"needs an employer: {email.subject}")'
    assert _offending_args(fstring_bad, "<synthetic>"), "f-string logging slips past"

    good = "logger.warning('needs an employer: %s', len(email.subject or ''))"
    assert _offending_args(good, "<synthetic>") == []


def test_no_cloud_log_record_carries_message_text() -> None:
    offenders: list[str] = []
    for name, source in _cloud_sources():
        offenders.extend(_offending_args(source, name))
    assert offenders == [], "message text in a log record:\n" + "\n".join(offenders)


@pytest.mark.asyncio
async def test_the_capped_company_lookup_warns_without_naming_the_company(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The record alert 178 was raised on: still audible, no longer a disclosure.

    A truncated lookup is a WRONG answer, not a slow one, so the warning has to
    stay loud. What it may not do is print the employer beside the user id.
    """

    monkeypatch.setattr(applications, "_COMPANY_ROWS_CAP", 2)
    user_id = uuid.uuid4()
    rows = [
        applications.Application(
            id=n, user_id=user_id, company="Northwind Traders", position="SWE"
        )
        for n in (41, 42)
    ]

    with caplog.at_level(logging.WARNING, logger="jobtracker.cloud.applications"):
        applications._warn_if_capped(rows, user_id, "northwind traders", "exact")

    records = [r for r in caplog.records if r.name == "jobtracker.cloud.applications"]
    assert len(records) == 1, f"expected exactly one cap warning, got {records}"
    message = records[0].getMessage()

    # Still actionable: who, which half, what bound, and a row to go look at.
    assert str(user_id) in message
    assert "exact" in message
    assert "_COMPANY_ROWS_CAP" in message
    assert "41" in message, "no application_id to trace the truncated set by"
    assert "token length 17" in message, "the shape fact that replaced the name"

    # And not a disclosure. `record.args` as well as the rendered message,
    # because a lazy logging argument is still on the record.
    haystack = f"{message} {records[0].args!r}"
    assert "northwind" not in haystack.lower(), haystack
    assert "traders" not in haystack.lower(), haystack


@pytest.mark.asyncio
async def test_an_uncapped_lookup_stays_silent(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate has to be able to NOT fire, or the test above proves nothing."""

    monkeypatch.setattr(applications, "_COMPANY_ROWS_CAP", 2)
    user_id = uuid.uuid4()
    rows = [applications.Application(id=1, user_id=user_id, company="A", position="B")]

    with caplog.at_level(logging.WARNING, logger="jobtracker.cloud.applications"):
        applications._warn_if_capped(rows, user_id, "a", "prefix")

    assert [r for r in caplog.records if r.name == "jobtracker.cloud.applications"] == []
