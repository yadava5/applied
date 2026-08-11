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
import urllib.parse
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
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

# Domains that relay mail on behalf of MANY EMPLOYERS: applicant tracking
# systems, job boards and the generic ESPs that front them. The domain does not
# identify the employer, but the *message* still comes from one — so the sender
# display-name and the subject are legitimate places to look for the company.
ATS_RELAY_DOMAINS: frozenset[str] = frozenset(
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

# Consumer webmail. Also a relay in the sense that the domain never identifies
# an employer — but unlike an ATS relay there is no employer behind it at all:
# a display-name here is a PERSON ("Julee Johnson"), which is exactly how the
# board once grew a "Julee Johnson → OFFERED" row. Kept as its own set so the
# display-name/subject fallbacks in :func:`resolve_employer` can be applied to
# ATS mail WITHOUT ever being applied to a human's personal mail.
CONSUMER_WEBMAIL_DOMAINS: frozenset[str] = frozenset(
    {
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
    }
)

# Every domain whose brand must NOT be used as the employer. Composed from the
# two sets above so membership can never drift between them.
RELAY_DOMAINS: frozenset[str] = ATS_RELAY_DOMAINS | CONSUMER_WEBMAIL_DOMAINS

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


def normalize_company_name(value: str) -> str:
    """Public form of the internal token normalizer.

    Lowercase, collapse to ``[a-z0-9]`` words, single-space joined. Exposed so
    the persistence layer can normalize a STORED company name with exactly the
    same rules the tokens were minted under, instead of inventing a fifth
    spelling of "the same company" (``lower(company)``, which is what filed a
    second "Together AI" row on every sync).
    """

    return _normalize_token(value or "")


def matches_company_token(company_name: str, token: str) -> bool:
    """Does a stored row's company NAME identify the employer ``token`` names?

    The two sides are minted differently and cannot simply be compared:

    - a row stores the human DISPLAY name (``"Together AI"``, ``"Y Combinator"``);
    - a rollup carries the match TOKEN, which is either the sender's domain
      brand (``"tcs"``, ``"y-combinator"``) or the normalized FIRST WORD of a
      display name (``"together"``).

    So ``lower("Together AI") == "together"`` is false and the upsert filed a
    duplicate — twice on the owner's board (applications 64 and 65), with the
    only linked email re-pointed to the newer row and the older one stranded.

    Matching normalizes both sides and accepts either a full match or a match on
    the leading word, which is the same grouping :func:`roll_up_applications`
    already applies when it collapses a company's mail under one token. Two
    employers sharing a first word therefore merge — but they would have shared
    a rolled row anyway, whereas the alternative is the duplicate above.
    """

    left = _normalize_token(company_name or "")
    right = _normalize_token(token or "")
    if not left or not right:
        return False
    if left == right:
        return True
    return left.split(" ")[0] == right.split(" ")[0]


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

    An application is "ghosted" when there is no later message answering it in
    :data:`RESPONSE_CATEGORIES` (interview / assessment / offer / rejection) and
    it is at least ``stale_days`` old.

    "Answering it" is judged per APPLICATION, not per company: since one employer
    can hold several applications, a rejection for one role must not silence the
    nudge for a different role that really has gone quiet. A response that names
    a role answers only that role; a response that names none — "Update on your
    application" is the common shape — cannot be attributed, so it counts as
    contact for the whole company. That direction is deliberate: suppressing a
    nudge is a small annoyance, while asserting a company has ignored you when it
    has already written back is the kind of wrong that makes a user distrust the
    product.

    De-duplicated to at most one flag per application — the oldest un-answered
    one — so re-sending the same application does not produce two identical
    "follow up" cards.

    Returns the flags sorted by ``days_since`` descending (most overdue first).
    """

    reference = _as_utc(now) if now is not None else datetime.now(UTC)
    materialized = list(items)

    def sub_key(item: PipelineItem) -> str | None:
        return extract_req_id(item.subject, item.snippet) or normalize_role_token(
            role_from_message(item.subject, item.snippet)
        )

    # Group every message by company so we can ask "did THIS company respond?",
    # then narrow to the specific application inside the loop.
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
        mine = sub_key(item)

        responded = any(
            other.category in RESPONSE_CATEGORIES
            and other.received_at is not None
            and _as_utc(other.received_at) >= applied_at
            # None on either side means "not attributable to one role" and so
            # counts company-wide; two named roles must match to answer.
            and (mine is None or (theirs := sub_key(other)) is None or theirs == mine)
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

# The employer named by the LEADING segment of an ATS subject, before a "|" or a
# spaced dash: "Crusoe | Application Received", "Acme — Interview scheduled".
# Anchored to the start so a separator later in the line cannot invent a company,
# and the capture stays case-sensitive so only a Capitalized proper noun is taken.
_EMPLOYER_LEAD_SEGMENT = re.compile(
    r"^\s*(" + _COMPANY_CAPTURE + r")\s*(?:\||\s[-–—]\s)"
)

# Role-ish tails an ATS sender's display name carries AFTER the company name:
# "Crusoe Hiring Team", "Supabase Recruiting", "Acme Talent Acquisition".
# Anchored to the END (and applied repeatedly) so a company whose own name
# contains one of these words — "People Data Labs", "Team Liquid" — is not
# shredded from the middle out the way a global substitution would do it.
_NAME_ROLE_TAIL = re.compile(
    r"(?:\s|^)(?:hiring|recruit(?:ing|ment|er|ers)?|talent|careers?|jobs?|hr|"
    r"people|team|notifications?|no[-\s]?reply|noreply|support|"
    r"acquisition|ops|operations)"
    r"\s*$",
    re.IGNORECASE,
)

# A display name that is really an email address ("no-reply@ashbyhq.com"), which
# names the relay, never the employer.
_NAME_IS_ADDRESS = re.compile(r"^\S+@\S+\.\S+$")

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

# Role named in the BODY. Real ATS confirmations put the company in the subject
# and the role in the first sentence, which is why every one of the owner's four
# Amazon confirmations shares the subject "Thank you for Applying to Amazon!" and
# differs only here. Measured against the live corpus: these three patterns name
# the role for Amazon, Roblox, DoorDash, SimpliSafe, Crusoe, Baseten, Cursor,
# MotherDuck and Anthropic; Supabase, Twitch, Together AI and IXL genuinely name
# no role anywhere in the mail, and must degrade to None rather than to a guess.
#
# Ordered most-specific first. Each capture is bounded to one clause (no ``.``,
# ``!``, ``?`` or newline) so a runaway match cannot swallow the next sentence.
_ROLE_BODY_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Ashby: "Thank you for applying to our role: Software Engineer I, Storage."
    re.compile(r"\brole:\s*(?P<role>[^.!?\n]{3,90}?)\s*(?=[.!?\n]|$)", re.IGNORECASE),
    # "...application for the <ROLE> position", "...interest in the <ROLE> position",
    # "...applying to our <ROLE> role", "...application for the <ROLE> role"
    re.compile(
        r"\b(?:for|in|to)\s+(?:the|our|your|a|an)\s+"
        r"(?P<role>[^.!?\n]{3,90}?)\s+"
        r"(?:position|role|opening|opportunity|req)\b",
        re.IGNORECASE,
    ),
    # DoorDash-shaped: "...applying to DoorDash's <ROLE> position!" — the employer
    # sits between the verb and the title, so no article anchors the capture.
    re.compile(
        r"\b(?:applying|applied|application)\b[^.!?\n]{0,40}?"
        r"(?P<role>[A-Z][^.!?\n]{3,90}?)\s+(?:position|role)\b",
    ),
)

# A requisition id, when the employer prints one. DELIBERATELY conservative: a
# false shared id merges two genuinely different applications, which is strictly
# worse than having no id at all and falling back to the role token. So every
# pattern requires an explicit label or a recognised ATS shape, and a bare number
# (a year, a salary, "2026") never qualifies.
_REQ_ID_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Amazon: "(ID: 3177934)". Also "Job ID 12345", "Requisition ID: R-4821".
    re.compile(
        r"\b(?:job\s*|requisition\s*|req\s*|posting\s*)?id[:\s#]+(?P<id>[A-Z]{0,3}-?\d{4,12})\b",
        re.IGNORECASE,
    ),
    # Workday/Greenhouse style standalone requisition codes: "R-4821", "JR0093214".
    re.compile(r"\b(?P<id>(?:R|JR|REQ)-?\d{4,10})\b"),
)

# Words a role token drops before comparison, so "Software Engineer I, Storage"
# and "Software Engineer I - Storage" are the same application and not two.
_ROLE_TOKEN_STRIP = re.compile(r"[^a-z0-9]+")


def _unescape_basic_entities(text: str) -> str:
    """Undo the handful of HTML entities Gmail snippets arrive carrying.

    Snippets come back pre-escaped (``We&#39;ve received your application``), and
    an escaped apostrophe inside a captured role would make two spellings of one
    title compare unequal.
    """

    if "&" not in text:
        return text
    return (
        text.replace("&#39;", "'")
        .replace("&quot;", '"')
        .replace("&amp;", "&")
        .replace("&nbsp;", " ")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


def extract_req_id(subject: str, snippet: str = "") -> str | None:
    """Return the employer's own requisition id for this application, or None.

    This is the strongest identity signal available: two Amazon confirmations
    with different ids are two applications no matter how similar their titles
    read, and two messages carrying the same id are one application no matter
    how differently they word it.
    """

    for text in (subject or "", _unescape_basic_entities(snippet or "")):
        for pattern in _REQ_ID_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group("id").upper()
    return None


def _clean_role(raw: str) -> str | None:
    """Normalize a captured role, or None if the capture is not a real title."""

    role = re.sub(r"\s+", " ", raw).strip(" .,;:-–—")
    # The requisition id is identity, not part of the human-readable title.
    role = re.sub(r"\s*\(\s*(?:job\s*|requisition\s*|req\s*)?id[:\s#][^)]*\)", "", role, flags=re.IGNORECASE)
    # "applying to DoorDash's Software Engineer I" — the employer's possessive
    # rides in ahead of the title because no article separates them.
    role = re.sub(r"^\w+['’]s\s+", "", role)
    # A regex matches leftmost-first, so a sentence with two preposition+article
    # pairs hands back the prose between them: "Thank you for your interest in
    # the Software Engineer, C# position" captured on "for your …" and yielded
    # "interest in the Software Engineer, C#", which shipped to the live board.
    # Cutting at the LAST such pair keeps the innermost, which is the title.
    # Deliberately narrow — it only fires when the capture itself still contains
    # a preposition + article, which a real job title does not.
    role = re.sub(r"^.*\b(?:in|for|to|at|with)\s+(?:the|our|your|a|an)\s+", "", role, flags=re.IGNORECASE)
    role = role.strip(" .,;:-–—")
    words = role.split()
    if not words or len(role) < 3:
        return None
    if all(_normalize_token(w) in _ROLE_FILLER for w in words):
        return None
    # A real job title in an ATS template is Title Case — "Software Engineer I,
    # Storage", "TPU Kernel Engineer". An all-lowercase capture is prose that
    # happened to sit between the anchors, and prose must never become an
    # identity: Supabase's "Thanks for your interest in a role with Supabase"
    # yielded the role "interest in a", which would have keyed an application.
    if not any(w[:1].isupper() for w in words):
        return None
    return role


def role_from_message(subject: str, snippet: str = "") -> str | None:
    """Extract the job title this message is about, or None. Never a guess.

    Subject first (it is the cleaner signal when present), then the body. The
    body half is what makes per-application tracking possible at all: ATS
    templates repeat one subject across every role a candidate applies to.
    """

    from_subject = _role_from_subject(subject)
    if from_subject is not None:
        return from_subject

    body = _unescape_basic_entities(snippet or "")
    for pattern in _ROLE_BODY_PATTERNS:
        match = pattern.search(body)
        if not match:
            continue
        role = _clean_role(match.group("role"))
        if role is not None:
            return role
    return None


def normalize_role_token(role: str | None) -> str | None:
    """Collapse a role title to a comparison key, or None.

    Punctuation and spacing vary between an employer's confirmation and its own
    later interview mail ("Software Engineer I, Storage" vs "Software Engineer I
    - Storage"); the token has to survive that or one application becomes two.
    """

    if not role:
        return None
    token = _ROLE_TOKEN_STRIP.sub(" ", role.lower()).strip()
    return token or None


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
    """ONE application — an employer plus the specific role applied for.

    Not "one company's applications rolled into a single row", which is what
    this used to be and what made four different Amazon requisitions render as
    one card. ``company_token`` alone is no longer an identity; the identity is
    ``(company_token, req_id or role_token)``.
    """

    company_token: str  # normalized match key (e.g. "acme")
    company_display: str  # human display (e.g. "Acme")
    role: str | None  # detected role, or None
    status: str  # ApplicationStatus value
    applied_at: datetime | None  # earliest application date
    last_activity: datetime | None  # most recent relevant date
    messages: tuple[MessageRef, ...] = ()  # contributing mail, newest-first
    # Identity within the employer. ``req_id`` is the employer's own requisition
    # number when it prints one; ``role_token`` is the normalized title. Both are
    # None for an employer that names no role anywhere in its mail (Supabase,
    # Twitch, Together AI in the live corpus) — that degrades to one row, which
    # is the honest floor when the mail genuinely does not distinguish.
    req_id: str | None = None
    role_token: str | None = None


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
    # Carried so the persisted Email keeps its snippet. It used to be dropped
    # here and hard-coded to "" at the two persist sites, and because the persist
    # path assigns `body_snippet` unconditionally, a message that came back
    # through review had its stored snippet ERASED — taking the role with it,
    # which is the one field per-application identity depends on.
    snippet: str = ""


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


def _clean_sender_display_name(raw: str) -> str:
    """Trim an ATS sender display-name down to the employer it fronts.

    Drops a "via Lever" / "(Greenhouse)" relay tail, then strips trailing
    role-ish words repeatedly ("Crusoe Hiring Team" → "Crusoe Hiring" →
    "Crusoe"). Only the TAIL is touched, so a company whose name legitimately
    contains one of those words keeps it.
    """

    text = _VIA_TAIL.sub("", raw or "").strip()
    for _ in range(4):  # bounded: "Acme Talent Acquisition" needs two passes
        stripped = _NAME_ROLE_TAIL.sub("", text).strip(" ,.-&|")
        if stripped == text:
            break
        text = stripped
    return re.sub(r"\s+", " ", text).strip(" ,.-&|")


def _names_the_relay(token: str, relay_brand: str) -> bool:
    """True when a candidate names the RELAY itself, not the employer behind it.

    "Handshake", "Greenhouse", "Ashby" are the courier, not the company — a row
    built from one of those is exactly the garbage the precision gate exists to
    prevent. Matched both against the known relay vocabulary and against the
    actual sending brand (so "Ashby" is rejected for ``ashbyhq.com``).
    """

    first = token.split(" ")[0] if token else ""
    if not first:
        return True
    if first in RELAY_DOMAINS:
        return True
    return bool(
        relay_brand
        and (relay_brand.startswith(first) or first.startswith(relay_brand))
    )


def _employer_from_sender_name(
    sender_name: str | None, relay_brand: str
) -> tuple[str, str] | None:
    """Employer named by an ATS sender's DISPLAY NAME, or None.

    Handles the two shapes ATS mail actually uses:
      - ``"Crusoe Hiring Team"`` → ``Crusoe`` (role-ish tail stripped)
      - ``"Team Talent @ MotherDuck"`` → ``MotherDuck`` (company after the ``@``)
    """

    raw = (sender_name or "").strip().strip('"')
    if not raw or _NAME_IS_ADDRESS.match(raw):
        return None

    candidates: list[str] = []
    if "@" in raw:
        tail = raw.rsplit("@", 1)[1].strip()
        # A dot in the tail means it is a hostname ("…@ashbyhq.com"), not a name.
        if tail and "." not in tail:
            candidates.append(tail)
    candidates.append(raw)

    for candidate in candidates:
        display = _clean_sender_display_name(candidate)
        if not display:
            continue
        token = _normalize_token(display.split(" ")[0])
        if not _valid_company_token(token) or _names_the_relay(token, relay_brand):
            continue
        return token, display
    return None


def _employer_from_subject_segment(
    subject: str, relay_brand: str
) -> tuple[str, str] | None:
    """Employer named by the leading segment of an ATS subject, or None.

    ``"Crusoe | Application Received"`` → ``Crusoe``. This is the shape that has
    no ``at``/``with``/``to`` connective for :data:`_EMPLOYER_ANCHORED` to hang
    off, which is why a real production classification silently created nothing.
    """

    match = _EMPLOYER_LEAD_SEGMENT.match(subject or "")
    if not match:
        return None
    display = _clean_company_display(match.group(1))
    if not display:
        return None
    token = _normalize_token(display.split(" ")[0])
    if not _valid_company_token(token) or _names_the_relay(token, relay_brand):
        return None
    return token, display


def employer_from_text(raw: str | None) -> tuple[str, str] | None:
    """Resolve a caller-supplied company string to ``(token, display)`` or None.

    Used when the pipeline cannot name the employer itself and the USER supplies
    it (``POST /applications/review/{id}/classify`` with a ``company``). Cleaned
    and validated with exactly the same rules as an extracted name, so a blank
    or stopword-only string still cannot manufacture a row.
    """

    display = _clean_company_display(raw or "")
    if not display:
        return None
    token = _normalize_token(display.split(" ")[0])
    if not _valid_company_token(token):
        return None
    return token, display


def _brand_display(brand: str, sender_name: str | None) -> str:
    """Human display for an employer identified by its own mail domain."""

    if sender_name:
        cleaned = _clean_company_display(sender_name)
        if cleaned and _normalize_token(cleaned).startswith(brand):
            return cleaned
    return brand.replace("-", " ").title()


# "Thanks for applying to Twitch", "Thank you for applying to DoorDash" — the
# employer, spelled by the employer, in its own subject line.
_SUBJECT_NAMES_EMPLOYER = re.compile(
    r"\bapply(?:ing)?\s+(?:to|with|for)\s+(?:the\s+)?(?P<name>[A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,2})",
)


def _corporate_identity(
    brand: str, subject: str, sender_name: str | None
) -> tuple[str, str]:
    """``(token, display)`` for an employer that mailed from its own domain.

    The domain is the right thing to TRUST but the wrong thing to PRINT. Two
    live rows show why: ``no-reply@twitchjobs.tv`` rendered the company as
    "Twitchjobs" while its own subject said "Thank you for applying to Twitch",
    and ``no-reply@doordash.com`` rendered "Doordash" because title-casing a
    lowercase domain label cannot know where the intercap goes.

    So when the subject names a company and the domain agrees with it — the
    domain brand starts with, or is started by, the normalized subject name —
    the subject's spelling wins. The agreement test is what keeps this from
    picking up a company merely *mentioned* in a subject: "Your application to
    Acme via Workday" mailed from workday.com resolves nothing here, and falls
    through to the relay branches as before.

    The TOKEN moves with the display, deliberately. Returning "Twitch" for
    display while keeping "twitchjobs" as the match key would make the row
    unfindable by its own token on the next sync — `matches_company_token`
    compares leading words, and "twitch" is not "twitchjobs" — so the sync would
    file a duplicate. Keeping them consistent means the old mis-named row is
    simply left without mail and dismissed as an auto row, which is recoverable
    and self-healing.
    """

    match = _SUBJECT_NAMES_EMPLOYER.search(subject or "")
    if match:
        named = _clean_company_display(match.group("name"))
        token = _normalize_token(named).replace(" ", "")
        if token and (brand.startswith(token) or token.startswith(brand)):
            return token, named
    return brand, _brand_display(brand, sender_name)


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
      3. (ATS relays only) the sender DISPLAY NAME — "Crusoe Hiring Team" →
         Crusoe, "Team Talent @ MotherDuck" → MotherDuck.
      4. (ATS relays only) the subject's leading segment before a ``|`` or a
         spaced dash — "Crusoe | Application Received" → Crusoe.

    Steps 3 and 4 are deliberately LAST and deliberately restricted to ATS /
    job-board / ESP relays: an ATS message really is sent on behalf of one
    employer, so its display name and subject lead are honest signals. Consumer
    webmail is excluded because a display name there is a person, and a ``.edu``
    (or any other host that already failed step 1) is excluded because it never
    reaches these branches at all. Without 3 and 4 a real production
    classification of "Crusoe | Application Received" resolved to None and the
    endpoint created nothing while reporting success.
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
        return _corporate_identity(brand, subject, sender_name)

    from_subject = _employer_from_subject(subject)
    if from_subject:
        token = _normalize_token(from_subject.split(" ")[0])
        if _valid_company_token(token):
            return token, from_subject

    if brand in ATS_RELAY_DOMAINS:
        from_name = _employer_from_sender_name(sender_name, brand)
        if from_name is not None:
            return from_name
        from_segment = _employer_from_subject_segment(subject, brand)
        if from_segment is not None:
            return from_segment

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


@dataclass(frozen=True)
class _Cluster:
    """One application's worth of gated mail, before it becomes a row."""

    company_token: str
    company_display: str
    req_id: str | None
    role_token: str | None
    role: str | None
    items: list[PipelineItem]


def partition_applications(
    items: Iterable[PipelineItem],
) -> tuple[list[_Cluster], list[PipelineItem]]:
    """Split gated mail into per-application clusters, plus what it cannot place.

    This is the identity resolution the whole product rests on, and it is pure so
    it can be reasoned about and tested without a database.

    Within one employer, a message is placed by the first rule that fires:

    1. its requisition id matches a cluster (the strongest signal — two Amazon
       confirmations with different ids are two applications however similar
       their titles read);
    2. its normalized role token matches a cluster;
    3. it names no role at all, and the employer has exactly ONE cluster — so it
       joins that one. This is what keeps Roblox's separate email-verification
       message (different sender, no shared role text, no shared thread) on the
       same application as its confirmation, and it means behaviour changes only
       for employers with several applications.

    A role-less message at an employer with SEVERAL applications is returned in
    the second element instead of being guessed at. Guessing here is not a cosmetic
    error: attributing a rejection to the wrong one of four Amazon rows settles a
    live application terminally and, because ``advance_application_status`` treats
    terminal states as final, freezes it against every later interview or offer.
    Those messages go to the review queue for the user to assign.

    A role-less message at an employer with NO other cluster mints its own
    ``(company, None)`` cluster — which is exactly the old behaviour, so an
    employer that genuinely never names a role (Supabase, Twitch, Together AI in
    the live corpus) still gets one honest row.
    """

    by_company: dict[str, list[tuple[PipelineItem, str, str | None, str | None, str | None]]] = {}
    for item in items:
        resolved = _qualifies_for_hard_row(item)
        if resolved is None:
            continue
        token, display = resolved
        role = role_from_message(item.subject, item.snippet)
        by_company.setdefault(token, []).append(
            (item, display, extract_req_id(item.subject, item.snippet), normalize_role_token(role), role)
        )

    clusters: list[_Cluster] = []
    unplaced: list[PipelineItem] = []

    for token, entries in by_company.items():
        display = entries[0][1]
        keyed: list[_Cluster] = []
        # Two passes, so placement never depends on arrival order: every message
        # that carries its own identity mints or joins first, and only then do the
        # anonymous ones look for a home.
        #
        # Scanning the clusters rather than keying a dict on ``req_id or
        # role_token`` is deliberate. Those are two namespaces that would
        # otherwise never meet: a confirmation carries the requisition id, the
        # interview invite that follows carries only the title, and a dict keyed
        # on "whichever we have" would file one application under two keys.
        for item, _display, req_id, role_token, role in entries:
            if req_id is None and role_token is None:
                continue
            match = next(
                (
                    c
                    for c in keyed
                    if (req_id is not None and c.req_id == req_id)
                    or (role_token is not None and c.role_token == role_token)
                ),
                None,
            )
            if match is None:
                keyed.append(
                    _Cluster(
                        company_token=token,
                        company_display=_display,
                        req_id=req_id,
                        role_token=role_token,
                        role=role,
                        items=[item],
                    )
                )
                continue
            match.items.append(item)
            # Each message may carry the half of the identity the other lacked.
            keyed[keyed.index(match)] = replace(
                match,
                req_id=match.req_id or req_id,
                role_token=match.role_token or role_token,
                role=match.role or role,
                items=match.items,
            )

        anonymous = [e[0] for e in entries if e[2] is None and e[3] is None]
        if anonymous:
            if not keyed:
                keyed.append(
                    _Cluster(
                        company_token=token,
                        company_display=display,
                        req_id=None,
                        role_token=None,
                        role=None,
                        items=list(anonymous),
                    )
                )
            elif len(keyed) == 1:
                keyed[0].items.extend(anonymous)
            else:
                unplaced.extend(anonymous)

        clusters.extend(keyed)

    return clusters, unplaced


def unplaceable_message_ids(items: Iterable[PipelineItem]) -> set[str]:
    """Message ids that name no role at an employer holding several applications.

    :func:`collect_review_items` promotes these into the queue so the user can
    say which application they belong to, rather than the pipeline picking one.
    """

    _clusters, unplaced = partition_applications(items)
    return {item.message_id for item in unplaced}


def roll_up_applications(items: Iterable[PipelineItem]) -> list[RolledApplication]:
    """Group high-confidence lifecycle mail into one row per real APPLICATION.

    Only messages that clear the precision gate (:func:`_qualifies_for_hard_row`)
    contribute: at/above the 0.85 auto-file confidence, a real lifecycle
    category, and a nameable employer. Identity within an employer comes from
    :func:`partition_applications`. An application's status is the furthest stage
    *its own* gated mail reached (applied < assessment < interview < offer), with
    a gated rejection as a terminal override — per application, so one
    requisition's rejection can no longer settle three live ones beside it.
    Uncertain mail never lands here — it goes to :func:`collect_review_items`
    instead — so the board shows real rows, not noise parsed out of job alerts.

    Deterministic and DB-free — the same input always yields the same rows,
    which is what makes the downstream upsert idempotent.
    """

    clusters, _unplaced = partition_applications(items)

    rolled: list[RolledApplication] = []
    for cluster in clusters:
        token, display, msgs = cluster.company_token, cluster.company_display, cluster.items
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

        role = cluster.role

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
                req_id=cluster.req_id,
                role_token=cluster.role_token,
            )
        )

    # Sorted by the full identity, not just the company: several applications at
    # one employer must come back in a stable order across syncs or the upsert
    # stops being idempotent.
    return sorted(rolled, key=lambda r: (r.company_token, r.req_id or "", r.role_token or ""))


def collect_review_items(items: Iterable[PipelineItem]) -> list[ReviewItem]:
    """Return the uncertain lifecycle verdicts that need a human decision.

    An item is review-worthy when it is NOT a hard-row contributor and either:
      - the classifier explicitly emitted ``needs_review``, or
      - it is a lifecycle verdict (not follow-up) at/above the review floor
        (0.70) — including one that clears the gate but whose employer could not
        be named (skipping is better than inventing a company).

    Anything below the review floor, or plain ``other`` noise, is omitted.

    Deduplicated by THREAD (newest message wins), falling back to ``message_id``
    for mail with no thread id. One Gmail conversation is one decision: the
    owner's queue asked them to classify "Crusoe | Application Received" twice
    (emails 58 and 73 — two messages, one thread ``19fed7e0706ee704``), while
    the filing path had grouped the same shape correctly for months. Newest-
    first overall.
    """

    items = list(items)
    # Gated mail that names no role at an employer holding several applications.
    # It clears the precision gate, so the loop below would skip it as "already a
    # real application row" — but there is no single row it belongs to, and
    # picking one would settle the wrong application (see
    # :func:`partition_applications`). Asking is the only honest move.
    unplaceable = unplaceable_message_ids(items)

    best: dict[str, ReviewItem] = {}
    for item in items:
        if item.message_id not in unplaceable and _qualifies_for_hard_row(item) is not None:
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
            snippet=item.snippet,
        )
        key = item.thread_id or item.message_id
        current = best.get(key)
        if current is None or _review_sort_key(candidate) >= _review_sort_key(current):
            best[key] = candidate

    return sorted(best.values(), key=_review_sort_key, reverse=True)


def _review_sort_key(item: ReviewItem) -> datetime:
    """Newest-first ordering key that never compares aware to naive."""

    return _as_utc(item.received_at) if item.received_at else _EPOCH


def gmail_deeplink(
    *,
    thread_id: str | None = None,
    message_id: str | None = None,
    account_email: str | None = None,
) -> str | None:
    """Build a stable Gmail web deep link for a thread/message, or None.

    Prefers the conversation (``#all/<threadId>``) so the whole thread opens;
    falls back to the message id. Uses the ``#all/`` anchor so archived mail is
    still reachable. We only have Gmail API ids (never the RFC822 header), which
    the ``#all/`` fragment resolves directly.

    ``account_email`` — the CONNECTED Gmail account. When known we select it with
    ``?authuser=<email>`` rather than the positional ``/u/0/`` slot. ``/u/0/`` is
    the FIRST account in the browser's session, which is almost never the linked
    mailbox for a user signed into several Google accounts — the reported bug
    where "Open in Gmail" dumped the user into the wrong inbox. ``authuser`` with
    the exact address is Google's robust multi-account selector; the ``/u/0/``
    form is kept only as the fallback when the account is unknown.
    """

    ref = (thread_id or "").strip() or (message_id or "").strip()
    if not ref:
        return None
    email = (account_email or "").strip()
    if email:
        return (
            f"https://mail.google.com/mail/?authuser={urllib.parse.quote(email)}"
            f"#all/{ref}"
        )
    return f"https://mail.google.com/mail/u/0/#all/{ref}"


def retarget_gmail_deeplink(url: str | None, account_email: str | None) -> str | None:
    """Point an existing stored Gmail deep link at the connected account.

    A persisted ``Application.url`` was minted with the positional ``/u/0/``
    account (or an older connection). Rewriting the account selector to
    ``?authuser=<connected-email>`` at READ time makes an "Open in Gmail" click
    always land in the mailbox the user has linked *now* — healing rows written
    before this fix without needing a re-sync, and following a reconnection to a
    different account. The message/thread fragment is preserved verbatim, so the
    same conversation still opens. Non-Gmail or fragment-less urls pass through
    unchanged; when no account is known the url is returned as-is.
    """

    if not url or not account_email or "mail.google.com" not in url:
        return url
    marker = url.find("#")
    if marker == -1:
        return url
    email = account_email.strip()
    if not email:
        return url
    fragment = url[marker:]  # keep '#all/<ref>' (or '#search/…') exactly
    return (
        f"https://mail.google.com/mail/?authuser={urllib.parse.quote(email)}{fragment}"
    )
