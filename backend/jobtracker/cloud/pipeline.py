"""Pure pipeline analytics over classified cloud mail (issue C7).

The high-volume inbox mine (``GET /gmail/inbox``) is server-paginated: the
web client loops pages and accumulates one verdict per message. This module
holds the *pure, Gmail-free* analytics that run over that accumulated set:

- :func:`company_key` — collapse a sender + subject to a stable company token
  so mail from one employer groups together even when it is relayed through a
  shared ATS domain (Lever, Greenhouse, Workday, …) that fronts many
  companies.
- :func:`summarize` — counts per category for a fetched set.
- :func:`flag_follow_ups` — the ghosting differentiator: ``applied`` mail with
  no later interview/assessment/offer/rejection from the same company within
  ``stale_days`` is surfaced as "No response — consider following up."

Everything here is a pure function over plain data (:class:`PipelineItem`),
which is what lets it be unit-tested without a Gmail token and re-used by the
Phase 2 dashboard-persistence path. No network, no I/O, no side effects.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

# The full category vocabulary the cloud rules classifier can emit. Kept in one
# place so a summary always reports every bucket (a category with zero hits is
# an explicit 0, never a missing key the UI has to guard).
CANONICAL_CATEGORIES: tuple[str, ...] = (
    "applied",
    "pending_application",
    "interview",
    "assessment",
    "offer",
    "rejection",
    "follow_up",
    "needs_review",
    "other",
)

# Categories that are part of a real job-search lifecycle (everything the
# tracker cares about) — i.e. NOT the "other" noise nor the "needs_review"
# holding pen. Phase 2 persists exactly these to the applications table.
JOB_LIFECYCLE_CATEGORIES: frozenset[str] = frozenset(
    {
        "applied",
        "pending_application",
        "interview",
        "assessment",
        "offer",
        "rejection",
        "follow_up",
    }
)

# A later message in one of these categories counts as the company having
# "responded" to an application, so the application is NOT ghosted.
RESPONSE_CATEGORIES: frozenset[str] = frozenset(
    {"interview", "assessment", "offer", "rejection"}
)

# Domains that relay mail on behalf of MANY employers (applicant tracking
# systems, job boards, generic mailbox providers). Grouping by these would
# wrongly merge unrelated companies, so for a sender on one of these we derive
# the company from the subject / sender display-name instead of the domain.
RELAY_DOMAINS: frozenset[str] = frozenset(
    {
        "lever",
        "greenhouse",
        "greenhouse-mail",
        "hire",
        "myworkday",
        "workday",
        "icims",
        "ashbyhq",
        "smartrecruiters",
        "jobvite",
        "workable",
        "recruitee",
        "bamboohr",
        "breezy",
        "teamtailor",
        "gem",
        "goodtime",
        "modernloop",
        "linkedin",
        "indeed",
        "ziprecruiter",
        "glassdoor",
        "wellfound",
        "angel",
        "monster",
        "dice",
        "handshake",
        "gmail",
        "googlemail",
        "outlook",
        "hotmail",
        "yahoo",
        "icloud",
        "proton",
        "protonmail",
    }
)

# Corporate/recruiting noise words stripped from a sender display-name before
# it is used as a company token ("Acme Recruiting" / "Acme via Lever" → "acme").
_NAME_NOISE = re.compile(
    r"\b(?:recruit(?:ing|er|ment)?|talent|careers?|jobs?|hiring|hr|"
    r"people|team|no[-\s]?reply|noreply|notifications?|via|the)\b",
    re.IGNORECASE,
)

# Subject patterns that name the company directly. First match wins.
_SUBJECT_COMPANY = re.compile(
    r"(?:application|interview|role|position|opportunity|offer)\s+"
    r"(?:to|at|for|with|from)\s+([A-Z][\w&.\- ]{1,40}?)"
    r"(?=[\s,.!?:;)]|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PipelineItem:
    """One classified message reduced to what the analytics need."""

    message_id: str
    category: str
    sender_email: str
    subject: str
    sender_name: str | None = None
    received_at: datetime | None = None


@dataclass(frozen=True)
class FollowUp:
    """An `applied` message flagged as ghosted (no later response)."""

    message_id: str
    company: str
    subject: str
    days_since: int
    applied_at: datetime | None = None


def _normalize_token(value: str) -> str:
    """Lowercase, collapse to ``[a-z0-9]`` words, join with single spaces."""

    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def _domain_brand(domain: str) -> str:
    """Return the registrable brand label of a host (``jobs.acme.co.uk`` → acme).

    A tiny public-suffix heuristic: if the last two labels look like a country
    second-level domain (``co.uk``, ``com.au``, …) the brand is the third-from-
    last label; otherwise it is the second-from-last. Good enough to group a
    company's own mail without shipping a full PSL.
    """

    labels = [p for p in domain.lower().split(".") if p]
    if len(labels) < 2:
        return labels[0] if labels else ""
    cc_slds = {"co", "com", "org", "net", "ac", "gov", "edu"}
    if len(labels) >= 3 and labels[-2] in cc_slds and len(labels[-1]) == 2:
        return labels[-3]
    return labels[-2]


def _company_from_subject(subject: str) -> str:
    match = _SUBJECT_COMPANY.search(subject or "")
    if not match:
        return ""
    return _normalize_token(match.group(1))


def _company_from_name(sender_name: str | None) -> str:
    if not sender_name:
        return ""
    stripped = _NAME_NOISE.sub(" ", sender_name)
    return _normalize_token(stripped)


def company_key(
    sender_email: str,
    subject: str = "",
    sender_name: str | None = None,
) -> str:
    """Collapse a message to a stable company token used for grouping.

    Strategy, in order:

    1. Take the sender-domain brand (``jobs.acme.com`` → ``acme``).
    2. If that brand is a shared relay (ATS / job board / consumer webmail)
       it does NOT identify the employer, so derive the company from the
       subject ("application to <Company>") and then from the cleaned sender
       display-name, falling back to the relay brand only if neither yields
       anything.

    Always returns a non-empty token (``"unknown"`` as the last resort) so
    callers can group without None-guards.
    """

    domain = ""
    if "@" in sender_email:
        domain = sender_email.rsplit("@", 1)[1].strip().lower()
    brand = _domain_brand(domain)

    if brand and brand not in RELAY_DOMAINS:
        return brand

    from_subject = _company_from_subject(subject)
    if from_subject:
        return from_subject

    from_name = _company_from_name(sender_name)
    if from_name:
        return from_name

    return brand or "unknown"


def summarize(items: Iterable[PipelineItem]) -> dict[str, int]:
    """Count messages per canonical category (every bucket present, 0-filled)."""

    counts = dict.fromkeys(CANONICAL_CATEGORIES, 0)
    for item in items:
        if item.category in counts:
            counts[item.category] += 1
        else:  # a category outside the known set still gets tallied honestly
            counts[item.category] = counts.get(item.category, 0) + 1
    return counts


def _as_utc(value: datetime) -> datetime:
    """Coerce a datetime to timezone-aware UTC (naive → assumed UTC)."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def flag_follow_ups(
    items: Iterable[PipelineItem],
    *,
    now: datetime | None = None,
    stale_days: int = 21,
) -> list[FollowUp]:
    """Flag `applied` mail that a company never responded to.

    An application is "ghosted" when, grouped by :func:`company_key`, there is
    no later message from the same company in :data:`RESPONSE_CATEGORIES`
    (interview / assessment / offer / rejection) and the application is at
    least ``stale_days`` old.

    De-duplicated to at most one flag per company — the oldest un-answered
    application, which is the most overdue nudge — so a company you emailed
    five times does not produce five identical "follow up" cards.

    Returns the flags sorted by ``days_since`` descending (most overdue first).
    """

    reference = _as_utc(now) if now is not None else datetime.now(UTC)
    materialized = list(items)

    # Group every message by company so we can ask "did THIS company respond?".
    by_company: dict[str, list[PipelineItem]] = defaultdict(list)
    for item in materialized:
        key = company_key(item.sender_email, item.subject, item.sender_name)
        by_company[key].append(item)

    best_per_company: dict[str, FollowUp] = {}
    for item in materialized:
        if item.category != "applied" or item.received_at is None:
            continue
        applied_at = _as_utc(item.received_at)
        key = company_key(item.sender_email, item.subject, item.sender_name)

        responded = any(
            other.category in RESPONSE_CATEGORIES
            and other.received_at is not None
            and _as_utc(other.received_at) >= applied_at
            for other in by_company[key]
        )
        if responded:
            continue

        days_since = (reference - applied_at).days
        if days_since < stale_days:
            continue

        candidate = FollowUp(
            message_id=item.message_id,
            company=key,
            subject=item.subject,
            days_since=days_since,
            applied_at=applied_at,
        )
        current = best_per_company.get(key)
        if current is None or candidate.days_since > current.days_since:
            best_per_company[key] = candidate

    return sorted(
        best_per_company.values(), key=lambda f: f.days_since, reverse=True
    )


# =============================================================================
# Rollup → Application rows (Phase 2: dashboard persistence)
# =============================================================================
#
# The classified pipeline is grouped into ONE application per company (role
# where detectable), with the status set to the furthest lifecycle stage that
# company's mail reached. These plain-string statuses match ApplicationStatus
# values; sync.py maps them to the enum + upserts. pipeline.py stays DB-free.

# EmailCategory → lifecycle stage rank. Higher = further along.
_STAGE_RANK: dict[str, int] = {
    "applied": 1,
    "pending_application": 1,
    "follow_up": 1,
    "assessment": 2,
    "interview": 3,
    "offer": 4,
}

# Application lifecycle status (ApplicationStatus values) by ascending progress.
# Used to roll a stage rank up to a status and to advance monotonically.
_STATUS_RANK: dict[str, int] = {
    "applied": 1,
    "interviewing": 2,
    "offered": 3,
    "accepted": 4,
}

# A stored status the mail signal must never silently override (a manual/terminal
# decision the user or a prior signal already settled).
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"rejected", "accepted", "withdrawn", "ghosted"}
)

# Subject patterns that name the role. First match wins; best-effort only.
_SUBJECT_ROLE = re.compile(
    r"(?:for the|for a|the|as a|as an|regarding(?: the)?)\s+"
    r"([A-Z][\w/&.\-]*(?:\s+[A-Z0-9][\w/&.\-]*){0,4}?)\s+"
    r"(?:role|position|opening|opportunity|internship|intern)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RolledApplication:
    """One company's applications rolled into a single tracker row."""

    company_token: str  # normalized match key (e.g. "acme")
    company_display: str  # human display (e.g. "Acme")
    role: str | None  # detected role, or None
    status: str  # ApplicationStatus value
    applied_at: datetime | None  # earliest application date
    last_activity: datetime | None  # most recent relevant date


def _rank_to_status(rank: int) -> str:
    if rank >= 4:
        return "offered"
    if rank >= 2:
        return "interviewing"
    return "applied"


def _role_from_subject(subject: str) -> str | None:
    match = _SUBJECT_ROLE.search(subject or "")
    if not match:
        return None
    role = re.sub(r"\s+", " ", match.group(1)).strip(" .-")
    return role or None


def advance_application_status(current: str, incoming: str) -> str:
    """Return the status a stored row should hold given an incoming signal.

    Monotonic and safe: a mail signal only moves an *in-flight* application
    forward (applied → interviewing → offered) or, on a rejection, to the
    terminal ``rejected``. It never downgrades a row and never overrides a
    status the user already settled (rejected/accepted/withdrawn/ghosted), so
    re-syncing cannot clobber a manual decision.
    """

    if current in _TERMINAL_STATUSES:
        return current
    if incoming == "rejected":
        return "rejected"
    if _STATUS_RANK.get(incoming, 0) > _STATUS_RANK.get(current, 0):
        return incoming
    return current


def roll_up_applications(items: Iterable[PipelineItem]) -> list[RolledApplication]:
    """Group classified mail into one :class:`RolledApplication` per company.

    Only job-lifecycle mail counts (``other``/``needs_review`` are ignored). A
    company's status is the furthest stage its mail reached (applied <
    assessment < interview < offer), with any rejection as a terminal override.
    A company seen only via a weak ``follow_up`` with no real lifecycle mail is
    skipped so the board is not polluted with phantom rows.

    Deterministic and DB-free — the same input always yields the same rows,
    which is what makes the downstream upsert idempotent.
    """

    grouped: dict[str, list[PipelineItem]] = defaultdict(list)
    for item in items:
        if item.category not in JOB_LIFECYCLE_CATEGORIES:
            continue
        key = company_key(item.sender_email, item.subject, item.sender_name)
        grouped[key].append(item)

    rolled: list[RolledApplication] = []
    for token, msgs in grouped.items():
        categories = {m.category for m in msgs}
        has_real_stage = any(c in _STAGE_RANK and c != "follow_up" for c in categories)
        has_rejection = "rejection" in categories
        if not has_real_stage and not has_rejection:
            # Only a weak follow-up nudge — not enough to assert an application.
            continue

        max_rank = max((_STAGE_RANK.get(c, 0) for c in categories), default=1)
        status = "rejected" if has_rejection else _rank_to_status(max_rank)

        dated = [m.received_at for m in msgs if m.received_at is not None]
        applied_dates = [
            m.received_at
            for m in msgs
            if m.category in ("applied", "pending_application") and m.received_at
        ]
        applied_at = min(applied_dates) if applied_dates else (min(dated) if dated else None)
        last_activity = max(dated) if dated else None

        role = next((_role_from_subject(m.subject) for m in msgs if _role_from_subject(m.subject)), None)

        rolled.append(
            RolledApplication(
                company_token=token,
                company_display=token.title(),
                role=role,
                status=status,
                applied_at=applied_at,
                last_activity=last_activity,
            )
        )

    return sorted(rolled, key=lambda r: r.company_token)
