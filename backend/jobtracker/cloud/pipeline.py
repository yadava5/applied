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
        # Applicant tracking systems / recruiting relays (front many employers).
        "lever",
        "greenhouse",
        "greenhouse-mail",
        "greenhousemail",
        "hire",
        "myworkday",
        "myworkdayjobs",
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
        "taleo",
        "successfactors",
        "brassring",
        "oraclecloud",
        "eightfold",
        "avature",
        "phenom",
        "paradox",
        "pageuppeople",
        "pageup",
        "jobs",
        "jobapp",
        "myjobs",
        "onboarding",
        "online-onboarding",
        # Job boards / aggregators / campus recruiting.
        "linkedin",
        "indeed",
        "ziprecruiter",
        "glassdoor",
        "wellfound",
        "angel",
        "monster",
        "dice",
        "handshake",
        "joinhandshake",
        "hire-education",
        "builtin",
        "lensa",
        "simplyhired",
        # Consumer webmail (never identify an employer).
        "gmail",
        "googlemail",
        "outlook",
        "hotmail",
        "live",
        "yahoo",
        "ymail",
        "aol",
        "icloud",
        "me",
        "proton",
        "protonmail",
        "zoho",
        # Generic mail-relay / ESP brands that front many senders.
        "sendgrid",
        "mailgun",
        "amazonses",
        "mailchimp",
        "mandrillapp",
        "sparkpostmail",
        "notifications",
        "email",
        "mail",
        "notification",
        "message",
        "messaging",
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
    """One classified message reduced to what the analytics need.

    ``confidence`` is the classifier's confidence for ``category`` (0.0-1.0).
    It is what the Phase-2 rollup gates on: only a *high-confidence* lifecycle
    verdict may assert a hard application status, so a low-confidence guess can
    no longer manufacture a fake ``interviewing``/``offered`` row. Absent (the
    default 0.0) it is treated as "no confidence" — the safe end of the gate.
    ``thread_id`` lets a persisted row deep-link back to the Gmail conversation.
    """

    message_id: str
    category: str
    sender_email: str
    subject: str
    sender_name: str | None = None
    received_at: datetime | None = None
    confidence: float = 0.0
    thread_id: str | None = None
    snippet: str = ""


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


def to_naive_utc(value: datetime | None) -> datetime | None:
    """Coerce a datetime to NAIVE UTC for persistence, or pass through None.

    The DB columns are ``TIMESTAMP WITHOUT TIME ZONE`` and the codebase writes
    naive ``datetime.utcnow()``-style values. But ``received_at`` comes from
    ``email.utils.parsedate_to_datetime``, which returns a timezone-AWARE
    datetime — and asyncpg refuses to encode an aware datetime into a naive
    column (``DataError``), which 500'd the whole sync in production. Every
    datetime that flows into a persisted column MUST pass through here so the DB
    never sees a mix of naive and aware values. (SQLite silently tolerates the
    mismatch, which is why the unit suite missed it.)
    """

    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


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
#
# PRECISION GATE (issue: "far too eager, low precision")
# ------------------------------------------------------
# A message may only assert a *hard* application status when BOTH:
#   1. its classifier confidence is at or above the auto-file gate (0.85), and
#   2. a real employer can be identified from the mail (never the sender domain
#      of a shared ATS relay, never a bare subject fragment, never a person).
# A lifecycle verdict in the 0.70-0.85 band, or one that clears the gate but
# whose employer cannot be named, is routed to a *review* bucket rather than
# fabricating an ``interviewing``/``offered``/``rejected`` row. Anything below
# the review floor is dropped. Net effect: a handful of real rows, not 21 fake
# ones parsed out of job-alert/newsletter/onboarding noise.

# Confidence gates — kept in lock-step with classifier/hybrid.py (CONFIDENCE_AUTO
# / CONFIDENCE_MIN_CLASSIFICATION) and the web's lib/dashboard/model.ts.
AUTO_FILE_GATE = 0.85  # >= → may assert a hard status
REVIEW_FLOOR = 0.70  # [floor, gate) → needs human review; below → dropped

# Sort sentinel for undated mail (kept aware so mixed aware/naive never raises).
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

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

# Words that are never, on their own, a company or a role — so an extraction
# that yields only these is rejected (this is what stops rows like "The",
# "Software", "Team", "Careers" from ever being created).
_COMPANY_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "your", "our", "my", "this", "that", "these", "those",
        "new", "re", "fw", "fwd", "hi", "hello", "hey", "thanks", "thank",
        "software", "engineer", "developer", "engineering", "intern",
        "internship", "role", "roles", "position", "positions", "opening",
        "openings", "application", "applications", "interview", "interviews",
        "offer", "offers", "update", "updates", "team", "teams", "careers",
        "career", "job", "jobs", "hiring", "talent", "recruiting", "recruiter",
        "recruitment", "hr", "people", "services", "service", "mail", "email",
        "notification", "notifications", "message", "opportunity",
        "opportunities", "candidate", "candidacy", "status", "confirmation",
        "onboarding", "welcome", "us", "you", "we", "here", "now", "today",
    }
)

# Corporate suffixes / recruiting tails stripped from a display name so that
# "Globex Corp", "Globex Inc." and "Globex" all collapse to the same token.
_CORP_TAIL = re.compile(
    r"\b(?:inc|inc\.|llc|l\.l\.c\.|ltd|ltd\.|corp|corp\.|corporation|co|co\.|"
    r"gmbh|plc|group|holdings|technologies|technology|labs|systems|solutions|"
    r"careers?|recruiting|recruitment|talent|hiring|team|hr|people)\b\.?",
    re.IGNORECASE,
)

# "Acme via Lever" / "Acme (Greenhouse)" tails that name the relay, not the co.
_VIA_TAIL = re.compile(r"\s*(?:\bvia\b|\bthrough\b|\bon\b|[(\[]).*$", re.IGNORECASE)

# A capitalized proper-noun-ish company token (leading capital, up to 3 words).
_COMPANY_CAPTURE = r"[A-Z][A-Za-z0-9&.\-']*(?:\s+[A-Z0-9][A-Za-z0-9&.\-']*){0,3}"

# The employer named explicitly in a subject, anchored to lifecycle language so
# a random "to Monday" is not mistaken for a company. The anchor/connective is
# case-insensitive (subjects are Capitalized) but the company capture stays
# case-sensitive so it only ever grabs a Capitalized proper noun. First match
# wins.
_EMPLOYER_ANCHORED = re.compile(
    r"(?i:(?:application|applying|apply|interview(?:ing)?|role|position|"
    r"opportunity|opening|offer|assessment|candidacy|"
    r"thank you for your interest in)\b[^\n]{0,40}?\b"
    r"(?:at|with|to|for|from|join)\s+)"
    r"(" + _COMPANY_CAPTURE + r")"
)
_EMPLOYER_ON_BEHALF = re.compile(
    r"(?i:on behalf of\s+)(" + _COMPANY_CAPTURE + r")"
)
_EMPLOYER_BARE_AT = re.compile(r"(?i:\bat\s+)(" + _COMPANY_CAPTURE + r")")

# Pure filler that is never itself a role title (kept SEPARATE from the company
# stopwords, which reject legitimate title words like "Software"/"Engineer").
_ROLE_FILLER: frozenset[str] = frozenset(
    {"the", "a", "an", "your", "our", "my", "this", "that", "new", "re",
     "fw", "fwd", "update", "status", "position", "role", "opening"}
)

# Role named in the subject. Tried in order; the capture is validated against
# ``_ROLE_FILLER`` so "the role" alone never survives. Best-effort — a missing
# role renders as nothing, never the literal "Unknown role".
_ROLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:for the|for a|for an|as a|as an|regarding the|to the|to a|to an)\s+"
        r"([A-Za-z][\w/&.\-]*(?:\s+[\w/&.\-]+){0,4}?)\s+"
        r"(?:role|position|opening|opportunity|internship|intern)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?i:\bapplication for)(?i:\s+the)?\s+"
        r"([A-Z][\w/&.\-]*(?:\s+[A-Z0-9][\w/&.\-]*){0,4})",
    ),
    re.compile(
        r"^\s*(?i:new\s+)?"
        r"([A-Z][\w/&.\-]*(?:\s+[A-Z0-9][\w/&.\-]*){0,4}?)\s+"
        r"(?i:role|position|opening|internship)\b",
    ),
    re.compile(
        r"^\s*(?i:new\s+)?"
        r"([A-Z][\w/&.\-]*(?:\s+[A-Z0-9][\w/&.\-]*){0,4}?)\s+(?:at|@|[-–—])\s+[A-Z]",
    ),
)


@dataclass(frozen=True)
class MessageRef:
    """A metadata-only reference to one underlying email (for click-through)."""

    message_id: str
    thread_id: str | None
    subject: str
    sender_email: str
    sender_name: str | None
    received_at: datetime | None
    category: str
    confidence: float
    snippet: str = ""


@dataclass(frozen=True)
class RolledApplication:
    """One company's applications rolled into a single tracker row."""

    company_token: str  # normalized match key (e.g. "acme")
    company_display: str  # human display (e.g. "Acme")
    role: str | None  # detected role, or None
    status: str  # ApplicationStatus value
    applied_at: datetime | None  # earliest application date
    last_activity: datetime | None  # most recent relevant date
    messages: tuple[MessageRef, ...] = ()  # contributing mail, newest-first


@dataclass(frozen=True)
class ReviewItem:
    """A lifecycle-ish verdict that is too uncertain to auto-file.

    These populate the dashboard's "needs classification" queue: the user can
    confirm a category (which then persists as an application *and* trains the
    model) or dismiss it. Never rendered on the pipeline board as a hard row.
    """

    message_id: str
    thread_id: str | None
    subject: str
    sender_email: str
    sender_name: str | None
    received_at: datetime | None
    category: str  # the tentative lifecycle category
    confidence: float
    company_display: str | None  # best-effort; may be None (unknown employer)


def _rank_to_status(rank: int) -> str:
    if rank >= 4:
        return "offered"
    if rank >= 2:
        return "interviewing"
    return "applied"


def _valid_company_token(token: str) -> bool:
    """A token is a usable company only if it is not a stopword or a bare number."""

    if not token or len(token) < 2:
        return False
    words = token.split()
    if all(w in _COMPANY_STOPWORDS for w in words):
        return False
    if words[0] in _COMPANY_STOPWORDS:
        return False
    return re.fullmatch(r"[0-9]+", token) is None


def _clean_company_display(raw: str) -> str:
    """Trim a captured company string to a clean human display name."""

    text = _VIA_TAIL.sub("", raw or "").strip()
    text = _CORP_TAIL.sub("", text).strip(" ,.-&")
    text = re.sub(r"\s+", " ", text)
    return text


def _employer_from_subject(subject: str) -> str | None:
    """Return the employer explicitly named in a subject, or None.

    Only trusts language that unambiguously names an employer (application/
    interview/offer "... at/with/to <Company>", "on behalf of <Company>", or a
    trailing "at <Company>"). The capture is cleaned and validated so a
    fragment like "The" or "Software" can never survive.
    """

    for pattern in (_EMPLOYER_ANCHORED, _EMPLOYER_ON_BEHALF, _EMPLOYER_BARE_AT):
        match = pattern.search(subject or "")
        if not match:
            continue
        display = _clean_company_display(match.group(1))
        token = _normalize_token(display.split(" ")[0]) if display else ""
        if _valid_company_token(token):
            return display
    return None


def _brand_display(brand: str, sender_name: str | None) -> str:
    """Human display for an employer identified by its own mail domain."""

    if sender_name:
        cleaned = _clean_company_display(sender_name)
        if cleaned and _normalize_token(cleaned).startswith(brand):
            return cleaned
    return brand.replace("-", " ").title()


def resolve_employer(
    sender_email: str,
    subject: str = "",
    sender_name: str | None = None,
) -> tuple[str, str] | None:
    """Identify the real EMPLOYER for a message, or None when unsure.

    Returns ``(token, display)`` where ``token`` is the stable lowercase match
    key and ``display`` the human name. Unlike :func:`company_key` (which always
    returns *something* so follow-up grouping never None-guards), this refuses
    to guess: if the employer cannot be named with confidence it returns None,
    and the caller must NOT create an application row from that message.

    Order:
      1. The sender's own corporate domain (``careers@stripe.com`` → Stripe) —
         but NOT a shared ATS/job-board relay, consumer webmail, generic ESP,
         or a ``.edu`` host (a student's university is not an employer here).
      2. An employer named explicitly in the subject ("... at <Company>",
         "on behalf of <Company>"). This is the relay case (Lever/Greenhouse).
    """

    domain = ""
    if "@" in sender_email:
        domain = sender_email.rsplit("@", 1)[1].strip().lower()
    labels = [p for p in domain.split(".") if p]
    tld = labels[-1] if labels else ""
    brand = _domain_brand(domain)

    corporate = (
        brand
        and brand not in RELAY_DOMAINS
        and len(brand) >= 2
        and tld != "edu"
        and not brand.isdigit()
    )
    if corporate:
        return brand, _brand_display(brand, sender_name)

    from_subject = _employer_from_subject(subject)
    if from_subject:
        token = _normalize_token(from_subject.split(" ")[0])
        if _valid_company_token(token):
            return token, from_subject

    return None


def _role_from_subject(subject: str) -> str | None:
    """Extract a job role/title from a subject, or None. Never 'Unknown role'."""

    text = subject or ""
    for pattern in _ROLE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        role = re.sub(r"\s+", " ", match.group(1)).strip(" .-–—")
        words = role.split()
        if not words:
            continue
        # Reject a capture that is only filler (e.g. "the", "your update").
        if all(_normalize_token(w) in _ROLE_FILLER for w in words):
            continue
        if len(role) < 3:
            continue
        return role
    return None


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


def _message_ref(item: PipelineItem) -> MessageRef:
    return MessageRef(
        message_id=item.message_id,
        thread_id=item.thread_id,
        subject=item.subject,
        sender_email=item.sender_email,
        sender_name=item.sender_name,
        # Naive-UTC so the ref persists straight into the naive Email.received_at
        # column without asyncpg rejecting an aware datetime.
        received_at=to_naive_utc(item.received_at),
        category=item.category,
        confidence=item.confidence,
        snippet=item.snippet,
    )


def _qualifies_for_hard_row(item: PipelineItem) -> tuple[str, str] | None:
    """Return the (token, display) employer iff this item may assert a status.

    A hard-row contributor is a non-follow-up lifecycle verdict at/above the
    auto-file gate whose employer can be named. Everything else (low confidence,
    unknown employer, follow-up, other/needs_review) returns None.
    """

    if item.category not in JOB_LIFECYCLE_CATEGORIES or item.category == "follow_up":
        return None
    if item.confidence < AUTO_FILE_GATE:
        return None
    return resolve_employer(item.sender_email, item.subject, item.sender_name)


def roll_up_applications(items: Iterable[PipelineItem]) -> list[RolledApplication]:
    """Group high-confidence lifecycle mail into one row per real employer.

    Only messages that clear the precision gate (:func:`_qualifies_for_hard_row`)
    contribute: at/above the 0.85 auto-file confidence, a real lifecycle
    category, and a nameable employer. A company's status is the furthest stage
    its *gated* mail reached (applied < assessment < interview < offer), with a
    gated rejection as a terminal override. Uncertain mail never lands here — it
    goes to :func:`collect_review_items` instead — so the board shows real rows,
    not noise parsed out of job alerts.

    Deterministic and DB-free — the same input always yields the same rows,
    which is what makes the downstream upsert idempotent.
    """

    grouped: dict[str, tuple[str, list[PipelineItem]]] = {}
    for item in items:
        resolved = _qualifies_for_hard_row(item)
        if resolved is None:
            continue
        token, display = resolved
        if token not in grouped:
            grouped[token] = (display, [])
        grouped[token][1].append(item)

    rolled: list[RolledApplication] = []
    for token, (display, msgs) in grouped.items():
        categories = {m.category for m in msgs}
        has_rejection = "rejection" in categories
        max_rank = max((_STAGE_RANK.get(c, 0) for c in categories), default=1)
        status = "rejected" if has_rejection else _rank_to_status(max_rank)

        # Normalize to naive UTC FIRST, so min()/max() never compares a mix of
        # aware and naive datetimes (which raises), and the result persists into
        # the naive TIMESTAMP columns without asyncpg's aware→naive encoder error.
        dated = [to_naive_utc(m.received_at) for m in msgs if m.received_at is not None]
        applied_dates = [
            to_naive_utc(m.received_at)
            for m in msgs
            if m.category in ("applied", "pending_application") and m.received_at
        ]
        applied_at = (
            min(applied_dates) if applied_dates else (min(dated) if dated else None)
        )
        last_activity = max(dated) if dated else None

        role = next(
            (
                _role_from_subject(m.subject)
                for m in msgs
                if _role_from_subject(m.subject)
            ),
            None,
        )

        refs = sorted(
            (_message_ref(m) for m in msgs),
            key=lambda r: _as_utc(r.received_at) if r.received_at else _EPOCH,
            reverse=True,
        )

        rolled.append(
            RolledApplication(
                company_token=token,
                company_display=display,
                role=role,
                status=status,
                applied_at=applied_at,
                last_activity=last_activity,
                messages=tuple(refs),
            )
        )

    return sorted(rolled, key=lambda r: r.company_token)


def collect_review_items(items: Iterable[PipelineItem]) -> list[ReviewItem]:
    """Return the uncertain lifecycle verdicts that need a human decision.

    An item is review-worthy when it is NOT a hard-row contributor and either:
      - the classifier explicitly emitted ``needs_review``, or
      - it is a lifecycle verdict (not follow-up) at/above the review floor
        (0.70) — including one that clears the gate but whose employer could not
        be named (skipping is better than inventing a company).

    Anything below the review floor, or plain ``other`` noise, is omitted.
    Deduplicated by ``message_id`` (newest wins), newest-first.
    """

    best: dict[str, ReviewItem] = {}
    for item in items:
        if _qualifies_for_hard_row(item) is not None:
            continue  # already a real application row

        is_needs_review = item.category == "needs_review"
        is_lifecycle = (
            item.category in JOB_LIFECYCLE_CATEGORIES and item.category != "follow_up"
        )
        if not is_needs_review and not (is_lifecycle and item.confidence >= REVIEW_FLOOR):
            continue

        employer = (
            resolve_employer(item.sender_email, item.subject, item.sender_name)
            if is_lifecycle
            else None
        )
        candidate = ReviewItem(
            message_id=item.message_id,
            thread_id=item.thread_id,
            subject=item.subject,
            sender_email=item.sender_email,
            sender_name=item.sender_name,
            # Naive-UTC — this persists straight into Email.received_at.
            received_at=to_naive_utc(item.received_at),
            category=item.category,
            confidence=item.confidence,
            company_display=employer[1] if employer else None,
        )
        best[item.message_id] = candidate

    return sorted(
        best.values(),
        key=lambda r: _as_utc(r.received_at) if r.received_at else _EPOCH,
        reverse=True,
    )


def gmail_deeplink(
    *, thread_id: str | None = None, message_id: str | None = None
) -> str | None:
    """Build a stable Gmail web deep link for a thread/message, or None.

    Prefers the conversation (``#all/<threadId>``) so the whole thread opens;
    falls back to the message id. Uses the ``#all/`` anchor so archived mail is
    still reachable. We only have Gmail API ids (never the RFC822 header), which
    the ``#all/`` fragment resolves directly.
    """

    ref = (thread_id or "").strip() or (message_id or "").strip()
    if not ref:
        return None
    return f"https://mail.google.com/mail/u/0/#all/{ref}"
