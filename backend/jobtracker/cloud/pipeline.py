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
Phase 2 dashboard-persistence path. No network, no I/O, no side effects — with
ONE deliberate exception: :func:`collect_review_items` emits a log line for a
confident verdict it drops. That drop is the module's only outcome that leaves
no trace anywhere else (no application row, no queue row, no counter), and its
invisibility is what let a whole class of persistence bug ship unnoticed. A log
record is not a side effect the callers can observe, so purity as the tests use
it — same input, same return value — still holds.
"""

from __future__ import annotations

import html
import logging
import re
import urllib.parse
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

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
        # Rippling fronts other employers' careers mail from ats.rippling.com.
        # Observed live: "Thank You for Applying to Supernova Technology" sent by
        # no-reply@ats.rippling.com filed an application at *Rippling*, which is
        # not a company the owner applied to. The sender display name already
        # said "Supernova Technology"; the domain overrode it.
        "rippling",
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
    # WHICH APPLICATION THIS MESSAGE NAMES, derived by the reader from the
    # message BODY rather than re-derived here from ``snippet``.
    #
    # ``snippet`` is Gmail's own ~200 characters and is all this dataclass used
    # to carry, so a title printed past character 200 was invisible to every
    # identity decision while the classifier — which IS handed the body — read
    # it correctly. Torc's card carried no position for that reason alone.
    #
    # NULL/None means "not derived", not "names nothing": the client relay path
    # carries a snippet and no body, so its items leave these unset and
    # :func:`item_identity` falls back to reading ``snippet``, which is exactly
    # what it did before. An empty string means "derived, and it names nothing".
    identity_role: str | None = None
    identity_req_id: str | None = None
    # WHICH LAYER PRODUCED ``category``, straight off the classifier that ran.
    #
    # This used to be thrown away, and the persist layer wrote the literal
    # ``"rules"`` for every row it stored (#496). ``get_classifier`` is
    # ``get_hybrid_classifier``, so the layer that actually answered may equally
    # have been embeddings, setfit, the content filter or the fallback — the
    # column read like provenance and was a constant, which is no evidence at
    # all. It already cost one wrong diagnosis: while tracing #493 the stored
    # rows claimed ``rules`` while the rules layer disagreed with them, and the
    # contradiction was read as "some other layer labelled this". It had not.
    #
    # ``None`` means NOT DERIVED HERE and is the honest answer for the two
    # client-relay paths, where the caller classified the mail and the server
    # never saw a classifier run. It is written through as NULL rather than
    # backfilled with a guess: the column is ``Optional[str]`` and nullable rows
    # already exist, and "we do not know" is a different fact from "rules".
    method: str | None = None


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
        return item_identity(item)

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

# Confidence gates — lock-stepped with classifier/hybrid.py (CONFIDENCE_AUTO /
# CONFIDENCE_MIN_CLASSIFICATION) and with every copy on the web side. Both
# halves of that are now held by something that can fail, which is why this
# comment names the checks rather than asking you to remember:
#
#   backend  tests/test_confidence_gate_lockstep.py — the four Python copies
#            (here, hybrid.py, and classification.py's constant AND its
#            seed_training_data default).
#   web      scripts/readme_facts.py — an invariant that reads CONFIDENCE_AUTO
#            out of hybrid.py and each TypeScript gate constant out of apps/web
#            and fails when they disagree, plus a census so a new hand-written
#            copy has to be registered. It runs in readme-facts.yml, the one
#            workflow with no path filter, because backend-ci and frontend-ci
#            are each filtered to a single side and neither can see this drift.
#
# This comment used to name only `lib/dashboard/model.ts`, which the dashboard
# largely did not read — ReviewQueue and ApplicationDetail imported a second
# copy from components/viz/GateMeter.tsx, so the invariant claimed here could
# hold while the number a user actually sees drifted (#229). The second copy is
# gone; the pointer is a check now, not a promise.
AUTO_FILE_GATE = 0.85  # >= → may assert a hard status
REVIEW_FLOOR = 0.70  # [floor, gate) → needs human review; below → dropped

# Sort sentinel for undated mail (kept aware so mixed aware/naive never raises).
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# The same instant without a zone. ``to_naive_utc`` returns naive datetimes, and
# comparing one against ``_EPOCH`` raises, so a sort that falls back for undated
# mail needs this one rather than the aware constant above.
_NAIVE_EPOCH = datetime(1970, 1, 1)

# EmailCategory → lifecycle stage rank. Higher = further along.
#
# ``follow_up`` is deliberately absent. :func:`_qualifies_for_hard_row` drops
# follow-ups before any rank is consulted, so the entry that used to sit here
# was unreachable — and it read as if a nudge asserted ``applied``, which is a
# claim the pipeline does not make. (Behaviourally inert either way: the lookup
# defaults to 0 and :func:`_rank_to_status` bottoms out at ``applied``.)
_STAGE_RANK: dict[str, int] = {
    "applied": 1,
    "pending_application": 1,
    "assessment": 2,
    "interview": 3,
    "offer": 4,
}

# The categories that ASSERT a new application rather than report on an existing
# one. A confirmation is the only mail that says "I applied"; everything else
# (assessment, interview, offer, rejection) is a later message ABOUT an
# application that already exists. :func:`partition_applications` leans on that
# asymmetry to tell a second application from a second message.
#
# ``pending_application`` USED TO BE IN HERE, and the sentence above is why it
# no longer is — it enumerated one member while the set held two, and the code
# followed the set. A "please verify your email before we can review your
# application" is an outstanding STEP in an application that already exists; it
# reports, it does not assert. Leaving it in meant an employer's confirmation
# and its own verification mail read as two anonymous confirmations and minted
# two cards. Issue #459.
#
# It does NOT stop such mail getting a card. An employer whose only message is a
# pending_application still mints one through the "no other cluster" branch of
# :func:`partition_applications`, and ``EmailCategory.PENDING_APPLICATION`` still
# maps to ``ApplicationStatus.APPLIED``. What changes is narrower and is the
# whole point: it is no longer EVIDENCE OF A SECOND application.
APPLIED_SIGNAL_CATEGORIES: frozenset[str] = frozenset({"applied"})

# Application lifecycle status (ApplicationStatus values) by ascending progress.
# Used to advance monotonically (:func:`advance_application_status`).
#
# NOT the same scale as ``_STAGE_RANK`` above, and since ``assessment`` became a
# status (2026-08-12) the two no longer even share a maximum: stage ranks top
# out at 4 (``offer``), status ranks at 5 (``accepted``). Only ``_STAGE_RANK``
# values may be passed to :func:`_rank_to_status`; a status rank fed to it would
# read one stage too high.
_STATUS_RANK: dict[str, int] = {
    "applied": 1,
    "assessment": 2,
    "interviewing": 3,
    "offered": 4,
    "accepted": 5,
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
#
# Applied ONLY to whitespace-canonicalised text — both callers collapse runs to a
# single space first, and that is a precondition, not a nicety. The pattern used
# to open with ``\s*`` and close with ``.*$``, and both were quadratic under
# ``re.sub``, which retries at every start position (CodeQL py/polynomial-redos,
# alert 80). ``\s*`` re-scanned a whitespace run from every offset inside it, and
# ``.*$`` re-scanned a line from every offset whenever ``$`` was out of reach —
# 2.1 s and 0.33 s respectively on an 8,000-character name, both growing as n².
# A caller-supplied company string is unbounded (``ReviewClassifyRequest.company``),
# so that is reachable, not theoretical.
#
# The leading ``\s*`` is gone because both callers ``.strip()`` the result, which
# removes exactly the whitespace it used to eat. ``.*$`` is ``.*\Z`` under DOTALL
# because on single-line input the two are the same match and the second cannot
# fail, so it never backtracks. Both rewrites are equivalence-checked against the
# old pattern over the test corpus in ``test_company_name_regexes_are_linear.py``.
_VIA_TAIL = re.compile(
    r"(?:\bvia\b|\bthrough\b|\bon\b|[(\[]).*\Z", re.IGNORECASE | re.DOTALL
)

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

# "<Role> @ <Company>" — the at-sign an ATS puts between the job title and the
# employer, at the very END of the subject, which is where the employer sits in
# that grammar. Issue #325 is entirely about this pattern being tried FIRST,
# ahead of :data:`_EMPLOYER_ANCHORED`. Both fire on the real subject
#
#     "Important information about your application to
#      Systems Research Engineer, GPU Programming @ Together AI"
#
# and they cannot both be right: here "to" introduces the ROLE and the at-sign
# introduces the employer. One has to outrank the other, and the at-sign is the
# better claim — "<title> @ <company>" is a fixed convention with one meaning,
# while "application to X" is a preposition whose object is a company only when
# the subject happens not to name a role first. Anchored to the end so an
# at-sign anywhere else in a line cannot invent a company, and a trailing "!"
# or "." is tolerated because subjects carry them.
#
# Read only for mail from an ATS relay, and that restriction is load-bearing
# rather than cautious: "<title> @ <company>" is a convention of ATS subject
# lines, and off a relay the same shape is a time or a place. "Interview @ Noon"
# and "Coffee @ Home" both satisfy this pattern and neither names an employer —
# a person's mail is where they occur, and a person's mail is exactly what the
# relay test excludes. Steps 3 and 4 of :func:`resolve_employer` are fenced off
# the same way, for the same reason.
# The trailing run is POSSESSIVE. ``\s*[!?.]*\s*$`` holds two whitespace
# quantifiers either side of a punctuation one, so a subject ending in a long
# run of spaces made the engine try every way of splitting that run between them
# — 0.45 s on an 8,000-character subject, quadratic. No successful match ever
# needed those retries (giving a space back leaves ``[!?.]*`` facing whitespace,
# which it cannot match), so committing is equivalence-preserving; it is proven
# exhaustively over short strings rather than argued.
_EMPLOYER_AT_SIGN = re.compile(r"@\s*(" + _COMPANY_CAPTURE + r")\s*+[!?.]*+\s*+$")

# ...but an at-sign is also what an EMAIL ADDRESS is made of, so a capture whose
# dot is followed by more letters is a hostname ("… @ Careers.Acme.com") and is
# refused. The "@" branch of :func:`_employer_from_sender_name` refuses a
# hostname for the same reason, though with the blunter "any dot at all" — this
# one leaves a TRAILING dot alone, because "Acme Inc." is a company, not a host.
_CAPTURE_IS_HOSTNAME = re.compile(r"\.[A-Za-z]")

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
# Written as an unrolled loop rather than the obvious ``^\S+@\S+\.\S+$``: three
# greedy ``\S+`` runs separated by the very characters they can also match is
# quadratic (0.23 s on 8,000 at-signs). This form pins each run to the FIRST
# delimiter after it, which is the same language — the earliest ``@`` past index 0
# leaves the longest tail, so if any split satisfies the old pattern that one does
# — with no ambiguity left to backtrack through.
_NAME_IS_ADDRESS = re.compile(r"^\S[^\s@]*@[^\s][^\s.]*\.[^\s]+$")

# Pure filler that is never itself a role title (kept SEPARATE from the company
# stopwords, which reject legitimate title words like "Software"/"Engineer").
# Words that can never BE a job title on their own. Two groups: articles and
# mail-thread noise, and — added after the adversarial corpus caught it — the
# LIFECYCLE NOUNS that name what a message is about rather than what the job is.
#
# "Interview at <Employer>" is one of the commonest subjects an ATS sends, and
# ``_ROLE_PATTERNS``' "<TITLE> at <Company>" rule captured "Interview" from it.
# That is not a cosmetic wrong title: the role token IS the application's
# identity, so the interview mail keyed on "interview" while the confirmation
# keyed on the real title, and the board grew a second card. Same for "Offer
# from <Employer>" and "Assessment at <Employer>".
#
# Safe for real titles because ``_clean_role`` only rejects a capture when
# EVERY word is filler — "Application Engineer" and "Offer Management Lead"
# survive; the bare noun does not.
_ROLE_FILLER: frozenset[str] = frozenset(
    {"the", "a", "an", "your", "our", "my", "this", "that", "new", "re",
     "fw", "fwd", "update", "status", "position", "role", "opening",
     "interview", "interviewing", "application", "assessment", "offer",
     "invitation", "opportunity", "rejection", "confirmation"}
)

# Legal-notice phrases whose OWN next word is one of the role keywords, so the
# body patterns terminate on it and hand back the notice as a job title.
#
# Google's acknowledgement is the case that shipped: it closes with an
# equal-opportunity notice, "opportunity" is the weakest keyword in
# ``_ROLE_BODY_PATTERNS``, and the real board filed the Google card's position
# as `"Equal Employment`.
#
# MATCHED WHOLE, never as a prefix, and that is the whole care in this
# constant. "Equal Employment Opportunity Specialist" is a real job title and a
# prefix test would refuse it; the phrase is only a notice when the keyword that
# ENDED the capture was the phrase's own next word, which is exactly the case
# where the capture equals the stem and nothing more. Normalized through
# ``_normalize_token`` so quoting and punctuation cannot dodge it.
_LEGAL_NOTICE_STEMS: frozenset[str] = frozenset(
    {
        "equal employment",
        "equal opportunity",
        "equal employment opportunity",
        "affirmative action",
        "reasonable accommodation",
        "equal access",
    }
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
#: A parenthesised requisition id sitting between the title and the keyword that
#: terminates it — "…Annapurna Labs (ID: 10475660) position."
#:
#: IT MUST NOT COUNT AGAINST THE TITLE'S WIDTH. The role captures below are
#: bounded (``{3,90}``), and that bound is spent while the id is still inside the
#: span, even though :func:`_clean_role` deletes the id one line later. So the
#: bound is measured against text that is by construction not part of the answer.
#:
#: Measured, in the owner's mailbox on 2026-08-23. Amazon writes:
#:
#:     "...your application for the Software Development Engineer I – AI/ML
#:      Network Infrastructure, Annapurna Labs (ID: 10475660) position."
#:
#: "Software" to " position" is 92 characters WITH the id and 77 WITHOUT it. At
#: 92 the bound cannot be met, so the engine backtracks the preceding gap and
#: restarts the capture one word later — and applications 112 and 126 went to the
#: live board titled "Development Engineer I – AI/ML Network Infrastructure,
#: Annapurna Labs", each missing the first word of its own job title.
#:
#: Not a length problem to be solved by a bigger number: widening 90 to 120 was
#: measured on 2026-08-22 and made the corpus WORSE (splits 2 -> 3), because a
#: wider bound also lets prose through. The id is simply not part of what is
#: being bounded, so it is matched outside the bound instead.
#:
#: Optional, and the same label set :func:`_clean_role` strips, so the pattern
#: and the cleaner cannot disagree about what an id looks like. Case-insensitive
#: inline because one of the two patterns using it is not.
_ROLE_TRAILING_REQ = r"(?:\s*\(\s*(?i:(?:job\s*|requisition\s*|req\s*)?id[:\s#])[^)]*\))?"

_ROLE_BODY_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Ashby: "Thank you for applying to our role: Software Engineer I, Storage."
    re.compile(r"\brole:\s*(?P<role>[^.!?\n]{3,90}?)\s*(?=[.!?\n]|$)", re.IGNORECASE),
    # "...application for the <ROLE> position", "...interest in the <ROLE> position",
    # "...applying to our <ROLE> role", "...application for the <ROLE> role"
    #
    # The anchor must be the article NEAREST the trailing keyword, not the
    # leftmost one. ``re.search`` returns the leftmost match, so the plain form
    # of this pattern anchored on the first preposition+article in the sentence
    # and let the lazy capture stretch across everything up to the sentence's
    # single "position" — which is how SimpliSafe's rejection ("Thank you for
    # your interest in SimpliSafe and our Software Engineer I- User Systems
    # position.") yielded the role "interest in SimpliSafe and our Software
    # Engineer I- User Systems" and minted a SECOND card for a job already on
    # the board.
    #
    # The capture is therefore TEMPERED: it may not run across another
    # anchor+article sequence. The leftmost start ("for your ") can then no
    # longer match at all, so the engine advances to the innermost one
    # ("and our ") on its own. Re-anchoring beats post-cutting because it
    # happens before the length bound is spent, and it needs no second list of
    # prepositions to be kept in sync.
    #
    # ``and`` joins the anchor alternation for the same message: an employer
    # that names itself and then its role ("interest in <Employer> and our
    # <ROLE> position") offers no preposition at the inner anchor.
    re.compile(
        r"\b(?:for|in|to|and)\s+(?:the|our|your|a|an)\s+"
        r"(?P<role>(?:(?!\b(?:for|in|to|at|with|and)\s+(?:the|our|your|a|an)\s)"
        r"[^.!?\n]){3,90}?)" + _ROLE_TRAILING_REQ + r"\s+"
        r"(?:position|role|opening|opportunity|req)\b",
        re.IGNORECASE,
    ),
    # DoorDash-shaped: "...applying to DoorDash's <ROLE> position!" — the employer
    # sits between the verb and the title, so no article anchors the capture.
    #
    # WHICH IS WHY IT USED TO TAKE THE EMPLOYER WITH IT. With nothing to anchor
    # on, the capture began at the first capitalised word after the verb, and
    # for a possessive employer that is the employer:
    #
    #   "applying to <Employer>'s Frontend Engineer position!"
    #      -> "<Employer>'s Frontend Engineer"
    #
    # while the same application's rejection said "apply for the Frontend
    # Engineer opening at <Employer>" and yielded "Frontend Engineer". Two
    # tokens, two cards, one application — and the title there is SEVENTEEN
    # characters, so this was never about length. See #466.
    #
    # A job title never contains "<Word>'s "; an employer's possessive does.
    # Forbidding it INSIDE the capture is what makes the capture start after it,
    # and it leaves every non-possessive wording untouched.
    re.compile(
        r"\b(?:applying|applied|application)\b[^.!?\n]{0,40}?"
        r"(?P<role>[A-Z](?:(?!'s\s)[^.!?\n]){3,90}?)" + _ROLE_TRAILING_REQ
        + r"\s+(?:position|role)\b",
    ),
    # Microsoft-shaped: "submit your application for Software Engineer II
    # (Job number: 200045485)." No article before the title and no trailing
    # "position"/"role" keyword after it, so none of the patterns above can
    # see it, and every Microsoft card on the board has a blank position.
    #
    # THE PARENTHESISED REQUISITION IS THE TERMINATOR, and that is what makes
    # this safe to add. The other patterns end on a common noun that can also
    # appear mid-sentence; this one ends on an employer explicitly labelling a
    # requisition, immediately after the title. The label alternation is the
    # same set `_REQ_ID_PATTERNS` accepts, so a wording either yields both a
    # role and an id or neither, rather than one of the two.
    #
    # THE CAPTURE USED TO EXCLUDE "(" TOO, on the stated reasoning that this is
    # what stops it running past the label. That reasoning was wrong — the
    # LABEL is what stops it, and it still does. Excluding the character only
    # meant a title containing an ordinary parenthesis produced NO ROLE AT ALL:
    #
    #   "...application for Software Engineer I, Entry-Level
    #    (Graduation Date: Fall 2025-Summer 2026) (Job number: 200045485)."
    #      -> role = None
    #
    # which is a real DoorDash title. That confirmation carried a requisition id
    # and no role while its own rejection carried a role and no id, so nothing
    # joined them and the application opened a second card. `Software Engineer
    # II (Job number: 200045485)` is the control and is unchanged. See #466.
    re.compile(
        r"\b(?:application|applying|applied)\s+(?:for|to)\s+"
        r"(?P<role>[^.!?\n]{3,120}?)\s*"
        r"\(\s*(?:job|requisition|req|posting|position|vacancy)\s*"
        r"(?:number|no\.?|id|code|ref(?:erence)?)\b",
        re.IGNORECASE,
    ),
    # Lever-shaped: "Thank you for submitting your application to be a Software
    # Engineer, New Grad at Palantir." The title is named plainly, with no
    # article anchor before it and no "position"/"role" noun after it, so every
    # pattern above walks past it — measured against the owner's real mail on
    # 2026-08-23, where Palantir's card sat with a blank position while both of
    # its messages spelled the title out.
    #
    # THE EMPLOYER IS THE TERMINATOR. "at <Capitalised>" is what ends the
    # capture, the same way the parenthesised requisition ends the pattern
    # above: a lowercase "at a company like ..." is not an employer and does not
    # terminate, so the capture simply fails rather than running to the end of
    # the sentence.
    #
    # ANCHORED ON THE APPLICATION WORD, and that is the whole safety of it.
    # "to be a <Title> at <Employer>" is an extremely common English shape that
    # has nothing to do with applying — "we have invited you to be a Mentor at
    # Palantir University" is the control, and it is refused here and nowhere
    # else: it is Title-Case and possessive-free, so neither the article
    # tempering nor the possessive guard above can see anything wrong with it.
    # Only the missing verb refuses it.
    #
    # LAST IN THE TUPLE, deliberately. :func:`role_from_message` returns the
    # first pattern that yields a clean role, so a rule appended here can only
    # fire where every other rule already found nothing. It cannot change a
    # single capture the board already has.
    re.compile(
        r"\b(?:application|applying|applied)\b[^.!?\n]{0,40}?"
        r"\bto\s+be\s+(?:an?|the)\s+"
        r"(?P<role>[A-Z](?:(?!'s\s)[^.!?\n]){3,90}?)" + _ROLE_TRAILING_REQ
        + r"\s+at\s+[A-Z]",
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
    # Microsoft: "(Job number: 200045485)". The pattern above requires the
    # literal word "id" and Microsoft does not use it, so every Microsoft
    # confirmation returned no requisition id at all.
    #
    # THIS COST FOUR REAL APPLICATIONS. On 2026-08-21 four Microsoft
    # applications were submitted within five minutes of each other, for
    # Software Engineer II (200045485), Customer Experience Engineer
    # (200049333), Software Engineer (200043070) and Pre-Training (200007619).
    # Every confirmation carries its own number, in the Gmail snippet, well
    # inside the 200 characters the snippet gives us. None was read, so all
    # four had null identity at an employer that already had a row.
    #
    # THE PREFIX IS MANDATORY HERE, unlike the `id` pattern above where it is
    # optional. "id" is already a strong enough token to stand alone; "number"
    # is not, and a bare `number[:\s#]+\d{4,12}` would happily match an order
    # number, a case number, a phone number or a tracking number in an
    # employer's boilerplate footer. A wrong requisition id is worse than none:
    # `_pick_application` files a message with no identity onto the employer's
    # existing row, while a wrong one mints a duplicate card.
    re.compile(
        r"\b(?:job|requisition|req|posting|position|vacancy)\s*"
        r"(?:number|no\.?|code|ref(?:erence)?)[:\s#]+(?P<id>[A-Z]{0,3}-?\d{4,12})\b",
        re.IGNORECASE,
    ),
)

# Words a role token drops before comparison, so "Software Engineer I, Storage"
# and "Software Engineer I - Storage" are the same application and not two.
_ROLE_TOKEN_STRIP = re.compile(r"[^a-z0-9]+")


def unescape_entities(text: str) -> str:
    """Undo the HTML entities Gmail snippets arrive carrying.

    Snippets come back pre-escaped (``We&#39;ve received your application``).
    That matters twice over: an escaped apostrophe inside a captured role makes
    two spellings of one title compare unequal, and the raw entity is also what
    the user READS — the detail sheet rendered "Please don&#39;t be" verbatim on
    the live board, because the snippet is stored exactly as fetched.

    Uses the stdlib table rather than a hand-written handful, so every entity
    Gmail can emit is covered rather than the six that happened to show up.
    ``&`` is a cheap guard for the common case of no entities at all.
    """

    if not text or "&" not in text:
        return text
    return html.unescape(text)


# ── deadlines ────────────────────────────────────────────────────────────────
#
# The product's landing page opens by promising that an assessment's 48-hour
# deadline will not pass unseen. Everything below is what makes that true, and
# the governing rule is that a deadline is REPORTED, never inferred: if the mail
# does not state one, the application does not have one. A fabricated deadline
# is worse than none — it would have someone drop what they are doing for a date
# nobody set.
#
# So every pattern requires an explicit deadline cue ("complete by", "expires",
# "within 48 hours"). A date merely mentioned in passing — an interview slot, a
# start date, a copyright year — never qualifies.

_MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "january february march april may june july august september "
            "october november december"
        ).split(),
        start=1,
    )
}
_MONTHS.update(
    {m[:3]: i for m, i in list(_MONTHS.items())}
)

_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))

# The cue that a date is a DEADLINE and not just a date.
_DEADLINE_CUE = (
    r"(?:complete|submit|finish|respond|reply|return|accept|schedule)?[^.!?\n]{0,30}?"
    r"\b(?:due|deadline|expires?|expiring|by|before|no later than|within)\b"
)

# "within 48 hours", "you have 5 days", "48-hour window".
_RELATIVE_DEADLINE = re.compile(
    r"\b(?:within|in|you\s+have|have)\s+(?P<n>\d{1,3})\s*(?:-|\s)?\s*"
    r"(?P<unit>hours?|hrs?|days?|business\s+days?)\b",
    re.IGNORECASE,
)
_HYPHEN_WINDOW = re.compile(
    r"\b(?P<n>\d{1,3})\s*-\s*(?P<unit>hour|day)\s+(?:window|deadline|limit|period)\b",
    re.IGNORECASE,
)

# "by August 15, 2026", "before Aug 15", "expires on 08/15/2026".
_ABSOLUTE_WORD_DATE = re.compile(
    rf"\b(?P<month>{_MONTH_ALT})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?"
    rf"(?:,?\s*(?P<year>20\d{{2}}))?",
    re.IGNORECASE,
)
_ABSOLUTE_NUMERIC_DATE = re.compile(
    r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/(?P<year>20\d{2}|\d{2}))?\b"
)

# How far out a stated deadline may plausibly sit. Beyond this the parse is far
# likelier to be wrong than the employer is to mean it.
_MAX_DEADLINE_DAYS = 180


# A window belongs to the COMPANY, not the candidate. "We will get back to you
# within 5 business days" is the single most common sentence in application mail
# and it is not a deadline — it is a promise about them. Reading it as one would
# have put a fabricated due date on very nearly every card on the board.
_COMPANY_PROMISE = re.compile(
    r"\b(?:we(?:'|’)?ll|we\s+will|we\s+aim|our\s+team\s+will|the\s+team\s+will|"
    r"you(?:'|’)?ll\s+hear|you\s+will\s+hear|hear\s+(?:back\s+)?from\s+us|"
    r"get\s+back\s+to\s+you|be\s+in\s+touch|respond\s+to\s+(?:you|all)|"
    r"review\s+your\s+application)\b",
    re.IGNORECASE,
)

# The window belongs to the CANDIDATE: an instruction addressed to the reader.
_RECIPIENT_TASK = re.compile(
    r"\b(?:please|kindly|complete|submit|finish|return|accept|schedule|confirm|"
    r"you\s+(?:have|must|need|should)|your\s+(?:assessment|challenge|exercise|"
    r"take[-\s]?home|invitation|link))\b",
    re.IGNORECASE,
)


def _is_recipient_task(context: str) -> bool:
    """Is this clause telling the READER to do something by a time?

    Both halves are required. The promise test alone lets through a bare date
    with no owner; the task test alone lets through "we will review your
    application within 5 days", which contains "your application".
    """

    if _COMPANY_PROMISE.search(context):
        return False
    return bool(_RECIPIENT_TASK.search(context))


def _cue_window(text: str) -> list[str]:
    """The clauses that carry a deadline cue, so a stray date can't be read."""

    out: list[str] = []
    for match in re.finditer(_DEADLINE_CUE, text, re.IGNORECASE):
        # From the cue to the end of its clause — a deadline is stated forward
        # ("by August 15"), never backward — plus the run-up, which is where the
        # sentence says whose deadline it is.
        clause = text[match.start() : match.start() + 90]
        if _is_recipient_task(text[max(0, match.start() - 80) : match.start() + 90]):
            out.append(clause)
    return out


def extract_deadline(
    subject: str, snippet: str, received_at: datetime | None
) -> datetime | None:
    """The deadline a message STATES, in naive UTC — or None.

    Anchored to ``received_at`` because "within 48 hours" is meaningless without
    it, and because a parsed calendar date is only believable if it lands after
    the mail that announced it. Returns None for anything ambiguous: no cue, no
    anchor, a date that resolves into the past, or one absurdly far out.
    """

    if received_at is None:
        return None
    anchor = to_naive_utc(received_at)
    if anchor is None:
        return None

    text = unescape_entities(f"{subject or ''}. {snippet or ''}")

    # Relative windows first — they are unambiguous and the common case for
    # assessments ("complete within 48 hours").
    for pattern in (_RELATIVE_DEADLINE, _HYPHEN_WINDOW):
        for match in pattern.finditer(text):
            if not _is_recipient_task(
                text[max(0, match.start() - 80) : match.end() + 40]
            ):
                continue  # the company's promise about itself, not your deadline
            break
        else:
            continue
        n = int(match.group("n"))
        unit = match.group("unit").lower()
        if n == 0:
            continue
        if unit.startswith(("hour", "hr")):
            due = anchor + timedelta(hours=n)
        elif "business" in unit:
            # Weekends are not working days; step over them rather than
            # pretending a 5-business-day window is 5 calendar days.
            due = anchor
            remaining = n
            while remaining > 0:
                due += timedelta(days=1)
                if due.weekday() < 5:
                    remaining -= 1
        else:
            due = anchor + timedelta(days=n)
        if 0 < (due - anchor).total_seconds() <= _MAX_DEADLINE_DAYS * 86400:
            return due

    # Absolute dates, but only inside a clause that carries a deadline cue.
    for clause in _cue_window(text):
        for match in _ABSOLUTE_WORD_DATE.finditer(clause):
            month = _MONTHS.get(match.group("month").lower())
            if month is None:
                continue
            due = _resolve_calendar_date(
                anchor, month, int(match.group("day")), match.group("year")
            )
            if due is not None:
                return due
        for match in _ABSOLUTE_NUMERIC_DATE.finditer(clause):
            due = _resolve_calendar_date(
                anchor,
                int(match.group("month")),
                int(match.group("day")),
                match.group("year"),
            )
            if due is not None:
                return due
    return None


def _resolve_calendar_date(
    anchor: datetime, month: int, day: int, year: str | None
) -> datetime | None:
    """A stated calendar date as an end-of-day UTC deadline, or None.

    A year-less date takes the next occurrence at or after the mail — "complete
    by August 15" in a December message means the following August, not eight
    months ago. End of day because a date without a time is a whole day, and
    treating it as midnight would mark it overdue a day early.
    """

    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    years = (
        [int(year) if len(year) == 4 else 2000 + int(year)]
        if year
        else [anchor.year, anchor.year + 1]
    )
    for candidate_year in years:
        try:
            due = datetime(candidate_year, month, day, 23, 59, 59)
        except ValueError:
            continue  # e.g. Feb 30
        delta = (due - anchor).total_seconds()
        if 0 < delta <= _MAX_DEADLINE_DAYS * 86400:
            return due
    return None


def extract_req_id(subject: str, snippet: str = "") -> str | None:
    """Return the employer's own requisition id for this application, or None.

    This is the strongest identity signal available: two Amazon confirmations
    with different ids are two applications no matter how similar their titles
    read, and two messages carrying the same id are one application no matter
    how differently they word it.
    """

    for text in (subject or "", unescape_entities(snippet or "")):
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
    # Last line of defence: a capture that STILL spans a clause boundary is a
    # sentence fragment, not a title, and a wrong role is strictly worse than no
    # role — `_pick_application`'s rule 4 files a role-less message onto the
    # employer's existing row, while a wrong role mints a duplicate card.
    #
    # Reachable independently of the body pattern above: the Ashby ``role:``
    # pattern is deliberately untempered (Ashby prints the title verbatim after
    # the colon), so "applying to our role: Software Engineer and our Storage
    # team" arrives here intact. Refusing is the correct outcome.
    #
    # Scoped to a conjunction/preposition + article sequence, plus the bare
    # possessives "our"/"your" which never appear inside a real job title. A
    # bare "the" is NOT refused: "Head of the Americas" is a legitimate title,
    # and the cut above has already removed every "the" that follows a
    # preposition.
    if re.search(r"\b(?:and|for|in|to|at|with)\s+(?:the|our|your|a|an)\b", role, re.IGNORECASE):
        return None
    if re.search(r"\b(?:our|your)\b", role, re.IGNORECASE):
        return None
    # A capture that OPENS a quotation and never closes it was cut out of a
    # quoted phrase rather than parsed as a title. Google's acknowledgement ends
    # with an equal-opportunity notice citing a poster by name, and the weakest
    # of the trailing keywords — "opportunity" — sits inside that title:
    #
    #   ... please refer to the "Equal Employment Opportunity is the Law" poster
    #                           ^^^^^^^^^^^^^^^^^^ capture   ^^^^^^^^^^^ keyword
    #
    # which filed the real board's Google card as the position `"Equal
    # Employment`, stray quote and all. The unbalanced quote is the structural
    # tell and it is not specific to this sentence: any title lifted out of a
    # quoted span carries one. A BALANCED pair is left alone — `Engineer II
    # ("Platform")` is a real, if ugly, title.
    # Double quotes only. An apostrophe is ordinary inside a title ("Women's
    # Health", "Engineers' Lead") and counting it here would refuse real roles
    # to catch a case the guard below already catches on its own terms.
    if role.count('"') % 2:
        return None
    # Legal boilerplate that shares its next word with a role keyword. Matched
    # WHOLE and only whole: the phrase is refused when the capture is exactly it
    # — i.e. the keyword that terminated the capture was the boilerplate's own
    # next word — and kept when the title continues past it. "Equal Employment
    # Opportunity Specialist" is a real job title and must survive; "Equal
    # Employment" immediately before "Opportunity" is a legal notice.
    if _normalize_token(role) in _LEGAL_NOTICE_STEMS:
        return None
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

    body = unescape_entities(snippet or "")
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


def sub_key_from_parts(req_id: str | None, role: str | None) -> str | None:
    """The identity cascade, applied to values somebody ALREADY derived.

    The same order :func:`application_sub_key` uses — requisition id first, then
    the normalized role token — but reading parts that were extracted once, from
    the body, and then stored. Empty string is a derived "names nothing" and
    normalizes to ``None`` exactly like a missing one.

    Exists so that a caller holding derived parts and a caller holding raw text
    cannot disagree about the order of the cascade. They used to be able to.
    """

    return (req_id or None) or normalize_role_token(role)


def identity_or_derive(
    *,
    req_id: str | None,
    role: str | None,
    subject: str,
    snippet: str,
) -> str | None:
    """Which application this message names — from a derivation if there is one.

    THE ONE PLACE THAT DECIDES WHETHER TO TRUST A DERIVATION, for the same
    reason :func:`review_dedup_key` is the one place that decides what a
    decision is: the callers must not be able to disagree. There are three of
    them — the queue key, the card builder, and the ghosting sweep — and a rule
    written out three times is a rule with three answers.

    ``role``/``req_id`` are what the READER extracted, from the message body,
    and stored. Both ``None`` means no derivation exists for this message, not
    that it names nothing: a relay item from the client carries a snippet and
    never had a body, and every row written before the columns existed is in the
    same position. Those fall back to re-deriving from ``snippet``, which is
    exactly the old behaviour rather than a second competing answer.

    An empty string is a derived "names nothing" and resolves to ``None``, which
    stays a VALUE meaning "the same unknown" and not a failure — it is what
    keeps one employer's two identical acknowledgements a single decision.
    """

    role, req_id = identity_parts(
        req_id=req_id, role=role, subject=subject, snippet=snippet
    )
    return sub_key_from_parts(req_id, role)


def identity_parts(
    *,
    req_id: str | None,
    role: str | None,
    subject: str,
    snippet: str,
) -> tuple[str | None, str | None]:
    """``(role, req_id)`` — the derivation if there is one, else read the text.

    The half of :func:`identity_or_derive` that a caller minting a CARD needs,
    because a card shows the title itself and not the key that distinguishes it.
    Both go through here so the board and the queue cannot end up disagreeing
    about which application a message names — the failure #454 describes, where
    four of five sites computed a key one way and the fifth another.

    THE TRUST RULE LIVES HERE AND ONLY HERE. This function existed for one
    revision with the card builder carrying its own copy of the branch, and a
    mutation that removed the derivation left the card builder's tests green:
    the duplicate was doing the work, so nothing measured the rule. Both parts
    ``None`` means no derivation exists and the text is read instead; anything
    else is used as given, with ``""`` meaning "derived, names nothing".
    """

    if role is None and req_id is None:
        return (
            role_from_message(subject, snippet),
            extract_req_id(subject, snippet),
        )
    return (role or None, req_id or None)


def item_identity(item: PipelineItem) -> str | None:
    """:func:`identity_or_derive` for a message in flight."""

    return identity_or_derive(
        req_id=item.identity_req_id,
        role=item.identity_role,
        subject=item.subject,
        snippet=item.snippet,
    )


def item_identity_parts(item: PipelineItem) -> tuple[str | None, str | None]:
    """:func:`identity_parts` for a message in flight."""

    return identity_parts(
        req_id=item.identity_req_id,
        role=item.identity_role,
        subject=item.subject,
        snippet=item.snippet,
    )


def application_sub_key(subject: str, snippet: str = "") -> str | None:
    """WHICH application, within one employer, this message is about — or None.

    The identity cascade the whole module already uses, in one place:
    requisition id first (the employer's own key, and the only thing that tells
    two same-titled openings apart), then the normalized role token, then
    nothing — which is honest rather than empty. Plenty of real mail names no
    application at all: "Crusoe | Application Received" carries no role in its
    subject and no body to extract one from.

    None is a VALUE here, not a failure. Two messages that both name nothing are
    the same unknown, and callers that key on this rely on that: it is what
    keeps one employer's two identical acknowledgements a single decision.
    """

    return extract_req_id(subject, snippet) or normalize_role_token(
        role_from_message(subject, snippet)
    )


#: The width a snippet is STORED at — ``Email.body_snippet`` is
#: ``max_length=500`` and every writer truncates to it. The review key has to be
#: computed from the same text on both sides of a decision or the decision
#: cannot settle the row it was made about, so :func:`review_dedup_key`
#: truncates here too rather than trusting its caller to have done it.
#:
#: Not hypothetical. The pipeline keys on ``PipelineItem.snippet``, which the
#: sync endpoint accepts up to 2000 characters, while the persisted row holds
#: the first 500. A message whose role sits past character 500 was queued under
#: ``(thread, "backend engineer alarms")`` and settled against
#: ``(thread, None)`` — measured 2026-08-22, before this line existed. It would
#: have left the row unlinked and un-reviewed, re-queued on every sync forever.
STORED_SNIPPET_CHARS = 500


def review_dedup_key(
    *,
    message_id: str,
    thread_id: str | None,
    subject: str,
    snippet: str,
    identity_role: str | None = None,
    identity_req_id: str | None = None,
) -> tuple[str, str | None] | str:
    """The unit of ONE DECISION in the review queue — issue #454.

    A Gmail conversation is one decision only when it is about one application,
    and an ATS thread routinely is not: every acknowledgement an employer sends
    goes out under one subject from one no-reply address, and Gmail threads on
    subject plus sender. Measured in the owner's mailbox on 2026-08-22, thread
    ``19ff36237eef1ef3`` holds five Verkada messages naming FOUR different
    roles, and ``19fed820cd93d18e`` holds two Anthropic applications. Keyed on
    the thread alone the queue asked about one of the four and the other three
    reached no card, no entry and no counter.

    So the key is the thread PLUS which application the message names, using the
    same :func:`application_sub_key` the filing path
    (:func:`partition_applications`) has used for months. On the real Verkada
    thread that is four distinct tokens, with the duplicate acknowledgement of
    "Backend Engineer, Alarms" folding back into one: five messages, four
    decisions.

    THE CRUSOE CASE IS THE CONTROL AND IS UNCHANGED. Its two messages ("Crusoe |
    Application Received", emails 58 and 73 of thread ``19fed7e0706ee704``)
    carry no body, so both sub-keys are ``None`` — equal, one entry, one
    decision, exactly as before. Widening the key by identity can never narrow
    this: mail that names no application still collides with every other
    nameless message of its thread.

    NO THREAD, NO WIDENING. Unthreaded mail returns the bare ``message_id``
    rather than a ``(None, sub_key)`` pair, which would collide two different
    employers' "software engineer" mail into one entry. A message id is unique
    and cannot.

    Lives here, and is called from every place that decides how many decisions a
    set of messages is, because those places must not be able to disagree: the
    pipeline that builds the queue, the additive persist that keeps a settled
    conversation out of it, the endpoint that renders it, the classify that
    settles its siblings, and the summary tile that counts it. Four of those
    five said "thread" and the fifth had to as well; a fix at fewer than all
    five is invisible, because the rows exist and the screen still shows one.
    """

    if not thread_id:
        return message_id
    return (
        thread_id,
        identity_or_derive(
            req_id=identity_req_id,
            role=identity_role,
            subject=subject,
            snippet=snippet[:STORED_SNIPPET_CHARS],
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
    # Carried so the persisted row keeps the identity the reader derived from
    # the body instead of the persist layer re-deriving a weaker one from the
    # stored snippet. None means "this pass derived nothing" and the writer
    # leaves the stored column alone — the same ratchet ``snippet`` itself uses
    # two fields up.
    identity_role: str | None = None
    identity_req_id: str | None = None
    # The classifier's PROPOSAL for a ref that carries no committed category —
    # i.e. a review item, whose ``category`` is the literal ``"needs_review"``.
    # None on the rolled-application path, where ``category`` already IS the
    # commitment and there is nothing outstanding to propose.
    suggested_category: str | None = None
    # Carried from ``PipelineItem.method`` so the persisted row records which
    # classifier layer actually answered instead of asserting one (#496).
    # ``None`` means the server never saw a classifier run for this message.
    method: str | None = None


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
    # The deadline this application's mail STATES, if any. None is the common
    # and correct case — most mail states nothing, and nothing is what it gets.
    due_at: datetime | None = None
    # The evidence behind ``status`` when a rejection is involved, carried so the
    # persistent half can tell a genuine re-application from a rejection the
    # scan's window simply did not reach. ``latest_rejection_at`` is the newest
    # DATED rejection in the cluster (None when there is none, or when the only
    # rejection carries no date); ``latest_applied_signal_at`` is the newest
    # dated applied/pending_application signal. Both are cluster-wide maxima
    # rather than segment-scoped, because ``upsert_applications_for_user`` needs
    # the applied signal even on a cluster whose rejection it never saw.
    latest_rejection_at: datetime | None = None
    latest_applied_signal_at: datetime | None = None


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


@dataclass(frozen=True)
class DroppedVerdict:
    """A lifecycle verdict this pipeline threw away, named so it can be counted.

    THE DROP THAT COST A USER FOUR APPLICATIONS. On 2026-08-21 four Microsoft
    confirmations arrived within five minutes of each other. Each scored
    ``rejection`` at 0.60 — below :data:`REVIEW_FLOOR` — because the body
    carries a CONDITIONAL explainer ("if you see the job moved to an inactive
    state, that means ... you were not selected for the role"), and the sender's
    domain is not on ``rules.ATS_DOMAINS`` so the ATS floor did not catch them
    either. All four left by the terminal drop below. They produced no
    application row, no queue entry, no counter and — because the log was gated
    at ``AUTO_FILE_GATE`` and 0.60 is nowhere near it — no log line.

    The user's report was "I applied to 4 new Microsoft and a Google
    application, but when I sync it in the app, I'm not getting anything", and
    from the product's side that is indistinguishable from a quiet mailbox.
    Finding out which it was took a session, a mailbox read and a local
    reproduction, because nothing the running system emitted said "four
    messages that looked like application mail were discarded".

    So the drop is now COUNTED and NAMED. This carries no verdict and changes
    no routing; it exists so ``GET/POST /gmail/sync`` can answer the one
    question the product could not: did we see nothing, or did we throw
    something away?

    The sender's address deliberately does not ride along — it is the user's
    correspondent, and ``message_id`` already names the message. Same reasoning
    as ``_warn_if_capped`` in ``cloud/applications.py``.
    """

    message_id: str
    category: str
    confidence: float


def _rank_to_status(rank: int) -> str:
    """Roll a ``_STAGE_RANK`` value (a mail CATEGORY's rank) up to a status.

    Takes a stage rank, never a status rank — see the note on ``_STATUS_RANK``.
    Since ``assessment`` became a status the mapping is 1:1 with the stage
    ranks (1 applied, 2 assessment, 3 interview→interviewing, 4 offer→offered);
    rank 2 used to fold up into ``interviewing``, which is the fold this change
    removes.
    """

    if rank >= 4:
        return "offered"
    if rank >= 3:
        return "interviewing"
    if rank >= 2:
        return "assessment"
    return "applied"


# A standalone requisition code, in the NORMALIZED token form — lowercased,
# with punctuation already collapsed to spaces, so "JR0093214" arrives as
# "jr0093214" and "R-77120" as "r 77120". Only the unambiguous ATS shapes; the
# labelled patterns in ``_REQ_ID_PATTERNS`` need an explicit "id:" and so
# cannot be confused with a company name in the first place.
_REQ_CODE_TOKEN = re.compile(r"(?:r|jr|req)\s?\d{4,10}")


def _valid_company_token(token: str) -> bool:
    """A token is a usable company only if it is not a stopword, number or req id."""

    if not token or len(token) < 2:
        return False
    words = token.split()
    if all(w in _COMPANY_STOPWORDS for w in words):
        return False
    if words[0] in _COMPANY_STOPWORDS:
        return False
    # A requisition code identifies an APPLICATION, never an employer. Workday
    # and Greenhouse write subjects like "Interview for JR0093214 at <Employer>",
    # which puts the code exactly where ``_SUBJECT_COMPANY`` looks for a company
    # — so the code became the employer, minting a card titled "JR0093214" for a
    # company that does not exist AND splitting it off the real application whose
    # id it was. Rejecting it here lets the resolver fall through to the sender
    # name and the rest of the subject, which do name the employer.
    if _REQ_CODE_TOKEN.fullmatch(token):
        return False
    return re.fullmatch(r"[0-9]+", token) is None


def _clean_company_display(raw: str) -> str:
    r"""Trim a captured company string to a clean human display name.

    Whitespace is canonicalised FIRST rather than last. Every regex below is
    written for a one-line name, and until now nothing enforced that a name is
    one line. Two ways in: the USER-typed path (:func:`employer_from_text`, fed
    by the review-classify body, an unbounded JSON string), and — checked, not
    assumed — the extraction patterns themselves, because
    :data:`_COMPANY_CAPTURE`'s inter-word ``\s+`` matches a newline as happily
    as a space. Only :data:`_SUBJECT_COMPANY`, whose class is ``[\w&.\- ]``,
    cannot produce one.

    Collapsing at the door makes every caller obey the assumption the rest of
    the module already makes, and it is what keeps :data:`_VIA_TAIL` linear.
    It is also a behaviour change on exactly those inputs, deliberately: see
    ``test_company_name_regexes_are_linear.py``, which pins both the old and the
    new answer for a newline-bearing name.
    """

    text = re.sub(r"\s+", " ", raw or "")
    text = _VIA_TAIL.sub("", text).strip()
    text = _CORP_TAIL.sub("", text).strip(" ,.-&")
    text = re.sub(r"\s+", " ", text)
    return text


def _employer_from_subject(subject: str, ats_relay: bool = False) -> str | None:
    """Return the employer explicitly named in a subject, or None.

    Only trusts language that unambiguously names an employer: application/
    interview/offer "... at/with/to <Company>", "on behalf of <Company>", or a
    bare "at <Company>" — plus, for ATS mail only, a trailing "@ <Company>".
    The capture is cleaned and validated so a fragment like "The" or "Software"
    can never survive.

    ORDER IS THE MEANING, not a performance detail — see :data:`_EMPLOYER_AT_SIGN`.
    A subject that names both a role and a company ("... application **to**
    <Role> @ <Company>") satisfies two patterns at once, and whichever runs
    first decides whether the row files under the employer or under a job title.
    Until #325 the anchored pattern ran first and "your application to Systems
    Research Engineer, GPU Programming @ Together AI" filed as "Research
    Engineer" — "Systems" being eaten by :data:`_CORP_TAIL` on the way out.

    Two rules this leaves wrong, stated rather than papered over:

    - A subject naming a role with NO at-sign still yields the role. "Your
      application to Systems Research Engineer" alone returns "Research
      Engineer", because nothing in that line distinguishes it from "Your
      application to Stripe". Deciding it would need a role-vocabulary test, and
      the only place to put one is :func:`_valid_company_token` — which is also
      what the USER-typed company path goes through, so a company whose name
      reads like a title would stop being enterable by hand.
    - The at-sign path does not check whether it just named the RELAY. "Your
      application to Acme @ Greenhouse" resolves to Greenhouse, not Acme.
      Adding :func:`_names_the_relay` here would cost more than it saves: the
      live corpus holds a real Handshake application, and Handshake is in
      ``RELAY_DOMAINS``, so the check would refuse a genuine employer to guard
      against a subject shape nothing has yet sent.
    """

    patterns = (_EMPLOYER_ANCHORED, _EMPLOYER_ON_BEHALF, _EMPLOYER_BARE_AT)
    if ats_relay:
        patterns = (_EMPLOYER_AT_SIGN, *patterns)

    for pattern in patterns:
        match = pattern.search(subject or "")
        if not match:
            continue
        raw = match.group(1)
        if pattern is _EMPLOYER_AT_SIGN and _CAPTURE_IS_HOSTNAME.search(raw):
            # An address, not a company. Fall through to the other patterns
            # rather than returning None, so this branch can only ever ADD a
            # resolution — never take one away from the subjects that already
            # resolve without it.
            continue
        display = _clean_company_display(raw)
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

    text = re.sub(r"\s+", " ", raw or "")  # see _clean_company_display
    text = _VIA_TAIL.sub("", text).strip()
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
        head, tail = raw.rsplit("@", 1)
        head, tail = head.strip(), tail.strip()
        # A dot in the tail means it is a hostname ("…@ashbyhq.com"), not a name.
        if tail and "." not in tail:
            # ATS display names use the ``@`` in BOTH directions, and which
            # side holds the employer depends on which side names the relay:
            #
            #   "Team Talent @ MotherDuck"   -> employer is the TAIL
            #   "Medpace, Inc. @ icims"      -> employer is the HEAD
            #
            # The tail was already being rejected in the second shape — it
            # names the relay, so ``_names_the_relay`` refuses it — but the
            # fallback then took the WHOLE raw string, and the employer kept a
            # courier's name glued to it. That is the real board's
            # ``Medpace, Inc. @ icims`` card, which groups and sorts as a
            # different employer from the same company reached through any
            # other ATS.
            #
            # Reading the head in that case is not a special case for icims: it
            # is the same question asked of the other side. Whichever side names
            # the relay is the one carrying no employer information.
            if _names_the_relay(_normalize_token(tail.split(" ")[0]), relay_brand):
                if head:
                    candidates.append(head)
            else:
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


# How far apart two employer names may be and still be one employer typed twice:
# ONE edit — a substitution, an insertion, a deletion, or a swap of two adjacent
# letters, which is every way a hand slips on a keyboard.
_NEAR_MISS_MAX_EDITS = 1

# ...and the shortest name that edit may be applied to. Below five characters a
# single edit is most of the word, and the pairs it produces are real, DIFFERENT
# employers: Zoom/Loom, Bolt/Volt, Ramp/Rump.
_NEAR_MISS_MIN_LENGTH = 5

# The opening letters a reader recognises a brand by. Requiring them to agree is
# what separates "Verkada"/"Verkeda" — a slipped key in the middle of a name —
# from "Figma"/"Sigma" and "Notion"/"Motion", which are one edit apart and not
# the same company by any reading.
_NEAR_MISS_PREFIX = 2


def _within_one_edit(left: str, right: str) -> bool:
    """Is ``right`` reachable from ``left`` in at most one keyboard slip?

    Substitution, insertion, deletion, or a transposition of adjacent letters —
    the Damerau-Levenshtein neighbourhood at distance 1 — decided by walking the
    two strings once instead of filling a matrix. A bounded question does not
    need the general algorithm, and answering it this way keeps the serverless
    bundle free of a fuzzy-matching dependency it would otherwise carry for
    fifteen lines of work.
    """

    if left == right:
        return True
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    if len(long) - len(short) > _NEAR_MISS_MAX_EDITS:
        return False

    i = j = 0
    edits = 0
    while i < len(short) and j < len(long):
        if short[i] == long[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > _NEAR_MISS_MAX_EDITS:
            return False
        if len(short) == len(long):
            # Same length, so it is a substitution — unless the very next letter
            # on each side is the other's, which makes it one transposition
            # rather than the two substitutions it would otherwise count as.
            if short[i + 1 : i + 2] == long[j : j + 1] and short[i : i + 1] == long[j + 1 : j + 2]:
                i += 2
                j += 2
                continue
            i += 1
            j += 1
        else:
            j += 1  # the longer side carries the extra letter
    # Whatever is left unconsumed on either side is the edit that ends it.
    return edits + (len(long) - j) + (len(short) - i) <= _NEAR_MISS_MAX_EDITS


def near_miss_employer(token: str, existing: Iterable[str]) -> str | None:
    """The stored employer name ``token`` is probably a MISSPELLING of, or None.

    ``token`` is a match key that named no stored row; ``existing`` is the set of
    company names already on the board. Both sides are reduced to their leading
    normalized word before comparison, the same way :func:`matches_company_token`
    compares them, because a stored display name and a match key are minted
    differently — otherwise every multi-word employer on the board is invisible
    to this check.

    A candidate qualifies only when all four hold: at least
    :data:`_NEAR_MISS_MIN_LENGTH` characters on both sides, the same first
    :data:`_NEAR_MISS_PREFIX` characters, at most :data:`_NEAR_MISS_MAX_EDITS`
    edits apart, and not already equal (an equal token is not a near miss — the
    caller would have found the row).

    THIS RESULT IS A QUESTION, NEVER AN ACTION. It exists so the one caller —
    the review queue's naming path — can offer the stored spelling back to the
    human who just typed a new one. Nothing merges on it. That is the whole
    safety argument: the rule above is deliberately loose enough that two real
    and distinct employers can trip it (Stripe/Strive are one edit apart and
    share their first two letters), and loose is affordable precisely because
    the answer is shown to a person rather than acted on.

    Several candidates return the alphabetically first rather than None. Under
    confirm-semantics, ambiguity is a reason to ASK, not a reason to fall silent
    and mint the row that ambiguity was about — a board already holding both
    "Verkada" and "Verkata" is where a typo is most likely, not least.
    """

    typed = _normalize_token(token or "").split(" ")[0]
    if len(typed) < _NEAR_MISS_MIN_LENGTH:
        return None

    matches: list[tuple[str, str]] = []
    for display in existing:
        stored = _normalize_token(display or "").split(" ")[0]
        if len(stored) < _NEAR_MISS_MIN_LENGTH or stored == typed:
            continue
        if stored[:_NEAR_MISS_PREFIX] != typed[:_NEAR_MISS_PREFIX]:
            continue
        if _within_one_edit(typed, stored):
            matches.append((stored, display))

    return min(matches)[1] if matches else None


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
        # The FIRST normalized word, not the whole name space-stripped. Every
        # other token in this module is a single word, and
        # `matches_company_token` compares normalized names word-wise — so a
        # concatenated "ixllearning" matches the stored "IXL Learning" under no
        # rule at all. It cost the owner's board a fresh row per rebuild: the
        # lookup never found the existing one, the upsert minted another, and the
        # emptied predecessor was dismissed, forever.
        token = _normalize_token(named).split(" ")[0]
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
         "on behalf of <Company>", and — for ATS relays only — a trailing
         "@ <Company>"). This is the relay case (Lever/Greenhouse).
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

    from_subject = _employer_from_subject(subject, ats_relay=brand in ATS_RELAY_DOMAINS)
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


def is_terminal_status(value: str) -> bool:
    """Is this a status a mail signal may never override on its own?

    Exported so ``jobtracker.cloud.applications`` can ask the question without
    keeping a second copy of the set. A second copy is how ``assessment`` once
    came to mean ``interviewing`` in one place and a settable stage in another.
    """

    return value in _TERMINAL_STATUSES


def advance_application_status(current: str, incoming: str) -> str:
    """Return the status a stored row should hold given an incoming signal.

    Decided from ``current`` and ``incoming`` alone, and it guarantees exactly
    two things:

    - a TERMINAL status (rejected/accepted/withdrawn/ghosted) is never left, and
    - an in-flight row only moves FORWARD (applied → assessment → interviewing
      → offered), or to ``rejected`` on a rejection. It never downgrades — so a
      re-test mailed to a row already at ``interviewing`` leaves it there, and
      that deadline still lands, because ``due_at`` is recomputed from the mail
      independently of the status.

    What it does NOT know is who owns the row. "Never overrides a status the
    USER settled" is a separate rule that lives entirely in the callers, all in
    ``jobtracker.cloud.applications``: ``upsert_applications_for_user``,
    ``split_application_cloud`` and ``reconcile_orphaned_classifications`` each
    check ``_is_auto_row(row.source)`` before writing anything, and
    ``classify_review_item`` — where the human IS the signal, so the check would
    be wrong — instead flips ``source`` to ``gmail_user`` on the way out, but
    only when the stage actually moved. Claiming that invariant here is how the
    orphan catch-up came to omit it: the docstring made it look already handled.
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
        # Carried, not re-derived. The persist layer only ever sees the stored
        # ~200-character snippet, so re-deriving there would write a weaker
        # identity than the reader already computed from the body — and the two
        # would then disagree about the same message.
        identity_role=item.identity_role,
        identity_req_id=item.identity_req_id,
        # Carried for the same reason and with the same meaning for ``None``.
        method=item.method,
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


def _may_join(
    cluster_req_id: str | None,
    cluster_role_token: str | None,
    req_id: str | None,
    role_token: str | None,
) -> bool:
    """Does a message with this identity belong to a cluster with that one?

    The cascade this file documents is "requisition id first, then role token",
    and the docstrings on both :func:`partition_applications` and
    ``_pick_application`` state that nothing outranks the employer's own number.
    The code did not honour that: the two clauses were OR-ed, so a role-token
    match joined a cluster whose requisition id EXPLICITLY DISAGREED.

    Two openings at one employer routinely share a title — "Mechanical
    Engineer (R-40881)" and "Mechanical Engineer (R-40882)" — and the ids are
    the only thing that tells them apart. OR-ing collapsed them onto one card,
    which is the strictly worse direction of failure: a split leaves the user
    two cards to merge by hand, but a merge destroys a record silently and
    nothing on the board says a second application ever existed.

    The guard is narrow on purpose. It fires only when BOTH sides carry an id
    and the ids differ; when either is None the message may still join, which
    is what preserves "each message may carry the half of the identity the
    other lacked" — the confirmation brings the requisition id, the interview
    invite that follows brings only the title, and they are still one
    application.
    """

    if req_id is not None and cluster_req_id is not None and req_id != cluster_req_id:
        return False
    if req_id is not None and cluster_req_id == req_id:
        return True
    return role_token is not None and cluster_role_token == role_token


@dataclass(frozen=True)
class _Cluster:
    """One application's worth of gated mail, before it becomes a row."""

    company_token: str
    company_display: str
    req_id: str | None
    role_token: str | None
    role: str | None
    items: list[PipelineItem]


#: How far apart two acknowledgements may sit and still be about ONE submission.
#:
#: Not a tuning knob picked to make one mailbox come out right — the two shapes
#: it separates are an order of magnitude apart on either side, measured in the
#: owner's real mail on 2026-08-23:
#:
#:   ONE submission, two acknowledgements   Supabase, 2h01m apart (21:02 and
#:                                          23:03 on 10 August). Ashby's generic
#:                                          note and the Supabase talent team's,
#:                                          both reacting to the same submit.
#:   TWO submissions                        Google, 2 days and then 8 days apart
#:                                          (11, 13 and 21 August).
#:
#: Automation reacting to one event fires in minutes or hours. A person applying
#: again to the same employer, having named no role either time, took days. A day
#: sits between the two with a full order of magnitude of slack on both sides,
#: which is the same way DEPLOY_GRACE was chosen.
DOUBLE_ACK_WINDOW = timedelta(hours=24)


def acknowledgement_template(subject: str) -> str:
    """A subject reduced to the TEMPLATE it came from.

    Case, spacing, punctuation and emoji all vary between an employer's own
    acknowledgement and its ATS's, and none of them is part of which template
    fired. What matters is whether two subjects are the same generated string.
    """

    return " ".join(re.sub(r"[^0-9a-z]+", " ", subject.casefold()).split())


def group_double_acknowledgements(
    anchors: Sequence[PipelineItem],
) -> list[list[PipelineItem]]:
    """Group anonymous confirmations that acknowledge ONE submission — issue #480.

    An anonymous confirmation is mail that asserts an application and names
    nothing: no requisition id, no role, in the subject or the body. Two of them
    from one employer are genuinely ambiguous — the mail does not contain the
    answer — and until now every one of them minted its own card.

    THAT IS RIGHT FOR GOOGLE AND WRONG FOR SUPABASE, and the difference is not
    in what the messages say. Both of Supabase's were pulled in full on
    2026-08-23 and neither holds a role, a requisition, or a link:

        21:02  "Thanks for applying to Supabase 🚀"
               "Thanks for applying to Supabase. We're really glad you're
                interested in what we're building..."
        23:03  "Thank you for applying to Supabase!"
               "Thanks for your interest in a role with Supabase; we confirm
                your application has been received..."

    One submission. Two systems acknowledging it — Ashby's template and the
    talent team's — two hours apart. Google's three say the SAME sentence under
    the SAME subject on 11, 13 and 21 August, and are three real applications.

    So the signal is the acknowledgement's SHAPE, not its words. An employer's
    ATS emits one template per submission event: receiving the same template
    twice means the event happened twice, while two different templates in one
    window means two emitters reacted to one event. Both conditions are
    required, and each one alone would be wrong:

      * template alone — an employer that changes its wording between two
        applications weeks apart would silently lose one of them;
      * window alone — two genuine same-day applications, which
        ``repeat-anonymous`` in the corpus is built from, would collapse.

    WHY THE FAILURE DIRECTION MOVED. The rule this replaces argued that minting
    two cards was the safe error because "a user can merge them". There is no
    merge. `POST /applications/{id}/split` exists and has a UI prompt; no merge
    endpoint and no merge control exist anywhere in this repository. So the old
    failure was not the visible-and-remediable one it was documented as — it was
    unrecoverable, and it took the employer's future mail with it:
    ``known_multi`` makes every later role-less message from a two-card employer
    ``unplaced``, so it lands in the review queue asking which of two
    applications it belongs to when there is no right answer. Verified against
    the shipped code, 2026-08-23.

    THIS IS AN INFERENCE FROM DELIVERY SHAPE AND IT IS STATED AS ONE. Nothing in
    either Supabase message distinguishes it from the other. Where the mail is
    silent the product is guessing, and this changes which way it guesses.

    Anchors arrive oldest-first. Deterministic: no set or dict iteration.
    """

    groups: list[list[PipelineItem]] = []
    for item in anchors:
        template = acknowledgement_template(item.subject)
        joined = False
        for group in groups:
            # A group's clock runs from its OLDEST member, not its newest, so a
            # long chain of differently-worded acknowledgements cannot walk the
            # window forward indefinitely and swallow a later real application.
            earliest = to_naive_utc(group[0].received_at)
            current = to_naive_utc(item.received_at)
            if earliest is None or current is None:
                continue
            if current - earliest > DOUBLE_ACK_WINDOW:
                continue
            if any(acknowledgement_template(g.subject) == template for g in group):
                continue
            group.append(item)
            joined = True
            break
        if not joined:
            groups.append([item])
    return groups


def partition_applications(
    items: Iterable[PipelineItem],
    known_multi: frozenset[str] = frozenset(),
    known_threads: frozenset[str] = frozenset(),
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

    ONE narrow order-dependence survives the two passes, introduced by the
    requisition-id guard in :func:`_may_join`: a message carrying a role token
    but NO req id, at an employer holding two clusters that share that title and
    differ only by requisition id, joins whichever of them was minted first.
    Before the guard the question could not arise, because those two clusters
    were one. It is the right trade — the alternative is collapsing two
    applications — and the case needs an employer with two same-titled openings
    plus a message that names the title without the id, but it is stated here
    rather than left for someone to discover.

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

    ``known_multi`` — employer tokens the BOARD already holds several
    applications for. A real sync rolls up a delta, usually one message, so this
    function alone can only see what arrived in that batch: an employer with
    four cards and one role-less rejection in today's mail looks, from here,
    exactly like an employer with one application. It is not, and the difference
    is not cosmetic — ``advance_application_status`` treats a terminal status as
    final, so filing that rejection against whichever card sorted first freezes a
    live application against every later interview and offer. With the caller
    supplying what the board holds, the review-queue rule above applies to a
    delta exactly as it applies to a rebuild. Defaults to empty, which is the
    pure over-the-batch behaviour every existing caller had.
    """

    by_company: dict[str, list[tuple[PipelineItem, str, str | None, str | None, str | None]]] = {}
    for item in items:
        resolved = _qualifies_for_hard_row(item)
        if resolved is None:
            continue
        token, display = resolved
        # THE CARDS ARE BUILT HERE, so this is the site the user actually sees.
        # Fixing the queue keys and leaving this re-deriving from ``snippet``
        # would have fixed the plumbing and not the faucet: the board would go
        # on showing a blank position for every title printed past Gmail's ~200
        # characters, which is the whole of what was reported.
        #
        # Same fallback rule as everywhere else — a relay item carries no
        # derivation and is read from its snippet exactly as before.
        role, req = item_identity_parts(item)
        by_company.setdefault(token, []).append(
            (item, display, req, normalize_role_token(role), role)
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
                    if _may_join(c.req_id, c.role_token, req_id, role_token)
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
            # A NEW CONFIRMATION IS A NEW APPLICATION. AN UPDATE IS NOT.
            #
            # That is the whole rule, and ``APPLIED_SIGNAL_CATEGORIES`` is what
            # draws the line: a confirmation ASSERTS an application, while a
            # rejection, assessment, interview or offer REPORTS on one that
            # already exists. So a confirmation with no identity gets its own
            # card, and an update with no identity never mints one — it lands on
            # the application it is about.
            #
            # Google is why. Subject "Thanks for applying to Google", no role
            # anywhere in the body, no requisition number, no job link — three of
            # them arrived on 11, 13 and 21 August 2026 and all three folded onto
            # one card dated the 11th. A sync that classified every message
            # correctly showed the user a board that had not moved. Supabase is
            # the same shape at two.
            #
            # THREAD IS NOT AN IDENTITY, and is deliberately not used as one. The
            # four Microsoft confirmations of 21 August share a single Gmail
            # thread and are four separate applications; Gmail threaded them
            # because the sender and subject are byte-identical, which is a fact
            # about delivery and none about what the mail is. Thread is used
            # BELOW, and only below: to route an update to the right one of an
            # employer's applications, which is the case where a conversation
            # really does say "more about this one".
            #
            # Palantir is the control on the asymmetry — an anonymous
            # confirmation plus an anonymous rejection three days later stays one
            # application, and would have become two under a blanket split.
            #
            # The failure direction is deliberate and it is the one
            # :func:`_may_join` already argues for: an employer that sends two
            # confirmations for a SINGLE application, naming no role in either,
            # mints two cards — visible, and a user can merge them. The merge
            # they replace destroyed the record silently.
            anchors = sorted(
                (i for i in anonymous if i.category in APPLIED_SIGNAL_CATEGORIES),
                # Oldest first, message id breaking a tie, so cluster order — and
                # therefore which of them adopts a pre-existing row — never
                # depends on the order Gmail happened to return the mail in.
                key=lambda i: (to_naive_utc(i.received_at) or _NAIVE_EPOCH, i.message_id),
            )

            # SEVERAL of them, or none of this applies. One anonymous
            # confirmation is not evidence of a second application — it is the
            # ordinary case of mail that names no role, and rule 3 below has
            # always been right about it. Roblox is why: its email-verification
            # message ("thank you for submitting your application for a position
            # at Roblox") reads as a confirmation, carries no role, and belongs
            # to the application whose real confirmation named one. Splitting on
            # a single anonymous confirmation would mint it a card of its own.
            if len(anchors) < 2:
                anchors = []

            anchored_ids = {i.message_id for i in anchors}
            first_anchor_index = len(keyed)
            for group in group_double_acknowledgements(anchors):
                keyed.append(
                    _Cluster(
                        company_token=token,
                        company_display=display,
                        req_id=None,
                        role_token=None,
                        role=None,
                        items=list(group),
                    )
                )

            # THE UPDATES. Everything left names no role and asserts no new
            # application, so none of it may mint. A conversation that names
            # exactly one of the applications above places it — that is the
            # "don't open a new card for an update" half, and the only thing
            # thread is trusted for. Ambiguous or unthreaded, it falls to rule 3
            # unchanged: ``keyed`` now counts the anchors, so a lone confirmation
            # still adopts its employer's follow-ups exactly as before, and an
            # employer with several applications still sends them to the review
            # queue for the user to assign rather than guessing which one.
            # The mapping is over the CLUSTERS the anchors became, not over the
            # anchors, because two acknowledgements of one submission arrive in
            # two threads and are now one cluster: keyed on the anchor's own
            # position this would have marked both threads ambiguous and sent
            # every later Supabase update to the review queue.
            by_conversation: dict[str, int | None] = {}
            for offset, item in (
                (o, i)
                for o, cluster in enumerate(keyed[first_anchor_index:])
                for i in cluster.items
            ):
                if item.thread_id:
                    # None marks a thread that holds MORE THAN ONE application —
                    # the Microsoft shape. It names no single row, so an update
                    # arriving in it is as ambiguous as an unthreaded one.
                    by_conversation[item.thread_id] = (
                        None
                        if item.thread_id in by_conversation
                        else first_anchor_index + offset
                    )

            unclaimed: list[PipelineItem] = []
            for item in (i for i in anonymous if i.message_id not in anchored_ids):
                index = by_conversation.get(item.thread_id) if item.thread_id else None
                if index is None:
                    unclaimed.append(item)
                else:
                    keyed[index].items.append(item)

            if unclaimed:
                if token in known_multi and len(keyed) != 1:
                    # The board already holds several applications here. There
                    # is no "the employer's only cluster" to join even when this
                    # batch contains one message, so asking is the only honest
                    # move — the same answer a rebuild gives for the same mail.
                    #
                    # TWO KINDS OF MAIL ARE NOT AMBIGUOUS AND MUST NOT BE ASKED
                    # ABOUT. A confirmation asserts an application, so "which of
                    # these is it about?" is the wrong question entirely — it is
                    # about a new one, and sending it to the queue is how the
                    # user's second application to an employer stops appearing
                    # at all. And an update whose Gmail conversation already
                    # names exactly one stored card belongs to that card;
                    # ``known_threads`` carries only the unambiguous ones, so a
                    # thread holding two applications still gets asked about.
                    # Both become their own clusters and the resolver places
                    # them — which is the same order a rebuild uses.
                    for item in unclaimed:
                        if (
                            item.category in APPLIED_SIGNAL_CATEGORIES
                            or (item.thread_id and item.thread_id in known_threads)
                        ):
                            keyed.append(
                                _Cluster(
                                    company_token=token,
                                    company_display=display,
                                    req_id=None,
                                    role_token=None,
                                    role=None,
                                    items=[item],
                                )
                            )
                        else:
                            unplaced.append(item)
                elif not keyed:
                    keyed.append(
                        _Cluster(
                            company_token=token,
                            company_display=display,
                            req_id=None,
                            role_token=None,
                            role=None,
                            items=list(unclaimed),
                        )
                    )
                elif len(keyed) == 1:
                    keyed[0].items.extend(unclaimed)
                else:
                    unplaced.extend(unclaimed)

        clusters.extend(keyed)

    return clusters, unplaced


def unplaceable_message_ids(
    items: Iterable[PipelineItem],
    known_multi: frozenset[str] = frozenset(),
    known_threads: frozenset[str] = frozenset(),
) -> set[str]:
    """Message ids that name no role at an employer holding several applications.

    :func:`collect_review_items` promotes these into the queue so the user can
    say which application they belong to, rather than the pipeline picking one.
    """

    _clusters, unplaced = partition_applications(items, known_multi, known_threads)
    return {item.message_id for item in unplaced}


def roll_up_applications(
    items: Iterable[PipelineItem],
    known_multi: frozenset[str] = frozenset(),
    known_threads: frozenset[str] = frozenset(),
) -> list[RolledApplication]:
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

    That override is scoped to the LATEST JOURNEY SEGMENT. Applying again to a
    role you were rejected for is a second application, and it does not get a
    second row: the resolver keys on ``(employer, req_id or role_token)`` and
    matches terminal rows too, so the new confirmation lands on the settled one.
    Reading the status from the mail strictly newer than the newest dated
    rejection is what makes that row show the application the user actually
    made. ``latest_rejection_at`` and ``latest_applied_signal_at`` carry the
    evidence to :func:`~jobtracker.cloud.applications.upsert_applications_for_user`,
    which is the only place a stored terminal status may be left.

    A cluster with no applied signal after its newest dated rejection rolls up
    EXACTLY as it did before segments existed, undated rejections included. That
    is the whole compatibility claim, and ``backend/tests/test_reopen_after_rejection.py``
    asserts it field-for-field against a verbatim copy of the old algorithm.

    Deterministic and DB-free — the same input always yields the same rows,
    which is what makes the downstream upsert idempotent.
    """

    clusters, _unplaced = partition_applications(items, known_multi, known_threads)

    rolled: list[RolledApplication] = []
    for cluster in clusters:
        token, display, msgs = cluster.company_token, cluster.company_display, cluster.items
        categories = {m.category for m in msgs}
        has_rejection = "rejection" in categories
        max_rank = max((_STAGE_RANK.get(c, 0) for c in categories), default=1)

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

        # SEGMENTS. A rejection ends one; mail strictly newer than the newest
        # DATED rejection begins the next. Status is read from the latest
        # segment, so re-applying to a role you were turned down for shows the
        # application you actually made instead of the one that ended.
        #
        # Deliberately a set filter and not a chronological walk. A walk reads
        # as "the last message wins", which would downgrade an interviewing row
        # the moment a duplicate confirmation arrived after it; only a REJECTION
        # starts a segment, and within one the rollup is the same order-blind
        # maximum it has always been. Nothing here depends on the order mail
        # arrives in, so no tie-break is needed for a rebuild to be stable.
        #
        # Every ambiguity resolves toward STAY-REJECTED, because a false stay is
        # one visible bug a human can correct while a false reopen recurs on
        # every rebuild: an undated rejection cannot be ordered and so falls back
        # to the old rule wholesale; undated mail is never in a segment; and the
        # comparison is strict, so a confirmation at the rejection's own instant
        # does not reopen anything.
        latest_rejection_at = max(
            (
                to_naive_utc(m.received_at)
                for m in msgs
                if m.category == "rejection" and m.received_at is not None
            ),
            default=None,
        )
        latest_applied_signal_at = max(applied_dates, default=None)

        segment = (
            [
                m
                for m in msgs
                if m.received_at is not None
                and to_naive_utc(m.received_at) > latest_rejection_at
            ]
            if latest_rejection_at is not None
            else []
        )
        if any(m.category in ("applied", "pending_application") for m in segment):
            status = _rank_to_status(
                max((_STAGE_RANK.get(m.category, 0) for m in segment), default=1)
            )
        else:
            status = "rejected" if has_rejection else _rank_to_status(max_rank)

        role = cluster.role

        # The LATEST stated deadline wins: a rescheduled assessment supersedes
        # the original, and the newest message is the one that knows.
        stated = [
            (to_naive_utc(m.received_at), extract_deadline(m.subject, m.snippet, m.received_at))
            for m in msgs
        ]
        dated = [(seen, due) for seen, due in stated if due is not None and seen is not None]
        due_at = max(dated, key=lambda pair: pair[0])[1] if dated else None

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
                due_at=due_at,
                latest_rejection_at=latest_rejection_at,
                latest_applied_signal_at=latest_applied_signal_at,
            )
        )

    # Sorted by the full identity, not just the company: several applications at
    # one employer must come back in a stable order across syncs or the upsert
    # stops being idempotent.
    return sorted(rolled, key=lambda r: (r.company_token, r.req_id or "", r.role_token or ""))


def is_ats_sender(sender_email: str | None) -> bool:
    """Is this address a known Applicant Tracking System relay?

    Thin wrapper over ``classifier.rules.is_ats_sender``, imported inside the
    function on purpose. This module is otherwise free of ``jobtracker`` imports
    — that is what lets it be unit-tested without a Gmail token and what keeps
    ``sqlmodel`` and the classifier out of its import graph on a cold start. The
    list itself is NOT copied here: one definition, read late.
    """

    from jobtracker.classifier.rules import is_ats_sender as _rules_is_ats_sender

    return _rules_is_ats_sender(sender_email)


#: Text in which this message speaks about the READER'S OWN place in a hiring
#: process, rather than about jobs in general.
#:
#: ISSUE #447. This answers "is this mail about an application of yours?" and
#: deliberately never answers "what happened to it". Those are different
#: questions and conflating them is the defect #451 tracks: reference text
#: saying WHICH application a message concerns must never outrank report text
#: saying WHAT HAPPENED. Nothing here contributes to a category or a score. It
#: decides one thing — whether a human is asked — and the human supplies the
#: verdict.
#:
#: Why it is needed at all. An ATS rejection spends Gmail's whole ~186-character
#: snippet on a polite preamble, so when no body part can be extracted the
#: classifier sees only the thank-you and scores ``other`` at 0.50. ``other`` is
#: not a lifecycle category, so the ATS floor below did not reach it and the
#: message left through the terminal drop: no row, no queue entry, no counter.
#: 610 messages in the 15k corpus, and the residual ``pipeline`` already named
#: and declined to cover ("an ATS message that scores NOTHING in any category is
#: ``other`` and still drops").
#:
#: Why not simply queue everything an ATS relays. That is the widening declined
#: there, and ``tests/corpus_independent`` now has ``ats-relay-noise`` to make
#: the difference measurable: 400 job alerts, talent-community blasts, profile
#: nudges, surveys and referral asks, all from real relay domains, none about an
#: application the reader made. Sender alone queues all 400.
#:
#: EVERY ALTERNATIVE IS ONE OF THE FIVE PHRASES BELOW, and each was checked
#: against the four real rejections in the owner's mailbox (2026-08-22), which
#: between them use FOUR DIFFERENT ONES:
#:   · Anthropic  — "went into your application"
#:   · Palantir   — "proceeding with your candidacy"
#:   · Verkada    — "your interest in the Embedded Software Engineer ...
#:                  opportunity" — and it never uses the word "application"
#:   · TogetherAI — "taking the time to apply for the ... opening"
#: A signal measured against only the first would have looked perfect on a
#: corpus and missed a quarter of the real cases. The corpus family carries the
#: Verkada wording alongside the Together AI one for exactly this reason.
#:
#: The offer clause covers the rescinded-offer shape, where the sender's own
#: words are "we have had to withdraw the offer for this position" and the word
#: application never appears either.
#:
#: ``your assessment|interview`` COMPLETES THE CATEGORY rather than chasing a
#: wording. Every clause here has the same shape — a hiring-process artefact
#: that belongs to the READER — and application, candidacy and offer were three
#: of five. The two that were missing are the two the product has statuses for.
#: An assessment reminder ("our team noticed you haven't had a chance to
#: complete your assessments yet") names no application and is unmistakably
#: about one; 58 of them reached nothing in the 16.8k corpus.
#:
#: WHAT WAS DELIBERATELY NOT ADDED, because the line matters. Eight real
#: rejections still reach nothing: the snippet cuts at "thank you so much for
#: your interest in <Employer> and for the time and effort you have invested in
#: our process", one character before "with your application". Adding
#: ``invested in our process`` or ``in our hiring process`` takes the corpus to
#: 633/633 with zero noise — and it would be transcribing one sender's sentence
#: into the product, which is the closed loop ``observed.py`` exists to break.
#: The wording is not a category, it is a phrase. Left open and pinned instead.
# THE SPAN BETWEEN THE ANCHOR AND THE KEYWORD IS A JOB TITLE, so the only safe
# bound on it is a CLAUSE. It used to be `[\w,\ \-/]{0,60}`, a character class
# holding no `(`, `)`, `:` or `#`, and real titles carry all four:
#
#   Software Engineer I, Entry-Level (Graduation Date: Fall 2025-Summer 2026)
#   Software Engineer, Agentic AI Harness & Quality - <Product>
#   Software Engineer, C#
#
# So the #447 floor — which exists precisely to stop mail about a real
# application reaching nothing — could not see the mail whose title carried
# punctuation the class forgot. 5 messages per corpus run, on title shapes taken
# from the owner's mailbox. See #466.
#
# EXTENDING THE CHARACTER CLASS WAS THE OBVIOUS FIX AND IS THE WRONG ONE. `C#`
# already needed a character nobody anticipated; the next real title needs
# another. `[^.!?\n]` says what is actually true — a title sits inside one
# clause — which is the same assumption `_ROLE_PATTERNS` above already makes.
#
# The widening is bounded by the corpus's 400 `ats-relay-noise` messages, which
# are relayed by the same domains and reference no application of the reader's:
# zero of them enter the queue with this in place.
_APPLICATION_REFERENCE = re.compile(
    r"""(?xi)
      your\ application\b
    | your\ candidacy\b
    | \b(?:your|the)\ offer\b
    | your\ (?:assessment|interview)s?\b
    | your\ interest\ in\ (?:the\ |this\ |our\ )?
      [^.!?\n]{0,80}?(?:opportunity|position|role|opening)\b
    | \bappl(?:y|ied|ying)\ (?:for|to)\ (?:the\ |a\ |an\ )?
      [^.!?\n]{0,80}?(?:opportunity|position|role|opening)\b
    """
)


def references_an_application(subject: str, snippet: str) -> bool:
    """Does this message speak about an application the reader made?

    Subject and snippet only, because that is all a cloud scan is guaranteed to
    have: the body is read in flight when one can be extracted and is not
    retained, and the messages this exists for are precisely the ones where no
    body part could be extracted.

    Carries no verdict. See :data:`_APPLICATION_REFERENCE`.
    """

    return bool(_APPLICATION_REFERENCE.search(f"{subject} {snippet}"))


def collect_review_items(
    items: Iterable[PipelineItem],
    dropped_out: list[DroppedVerdict] | None = None,
    known_multi: frozenset[str] = frozenset(),
    known_threads: frozenset[str] = frozenset(),
) -> list[ReviewItem]:
    """Return the uncertain lifecycle verdicts that need a human decision.

    An item is review-worthy when it is NOT a hard-row contributor and either:
      - the classifier explicitly emitted ``needs_review``, or
      - it is a lifecycle verdict (not follow-up) at/above the review floor
        (0.70) — including one that clears the gate but whose employer could not
        be named (skipping is better than inventing a company), or
      - it is a lifecycle verdict (not follow-up) relayed by a known ATS, at ANY
        confidence — the ATS floor, see below.

    Anything below the review floor, or plain ``other`` noise, is omitted. That
    drop is terminal — the one path through this module that leaves no row and
    no queue entry behind — so it reports itself two ways:

      - a LIFECYCLE verdict under the floor is always logged AND appended to
        ``dropped_out`` when the caller passes a list. This is mail the
        classifier believed was about a job application and the pipeline threw
        away; it is the failure case, not the designed one, and it is what lets
        a sync say "4 discarded" instead of nothing at all. See
        :class:`DroppedVerdict` for the four applications that were lost to its
        previous silence.
      - anything else is logged only when the classifier was CONFIDENT
        (at/above ``AUTO_FILE_GATE``) — a confident ``follow_up``, dropped by
        design, or a category outside the canonical vocabulary, which is a bug.

    ``dropped_out`` is an out-parameter rather than a second return value so
    every existing caller keeps unpacking a plain list.

    Deduplicated by THREAD AND WHICH APPLICATION the message names (newest
    wins), falling back to ``message_id`` for mail with no thread id. One Gmail
    conversation is one decision *per application*: the owner's queue asked them
    to classify "Crusoe | Application Received" twice (emails 58 and 73 — two
    messages, one thread ``19fed7e0706ee704``), and keying on the thread alone
    fixed that by losing three of the four applications in Verkada's thread
    ``19ff36237eef1ef3``. See #454 and the comment at the key itself. Newest-
    first overall.
    """

    items = list(items)
    # Gated mail that names no role at an employer holding several applications.
    # It clears the precision gate, so the loop below would skip it as "already a
    # real application row" — but there is no single row it belongs to, and
    # picking one would settle the wrong application (see
    # :func:`partition_applications`). Asking is the only honest move.
    unplaceable = unplaceable_message_ids(items, known_multi, known_threads)

    best: dict[tuple[str, str | None] | str, ReviewItem] = {}
    for item in items:
        if item.message_id not in unplaceable and _qualifies_for_hard_row(item) is not None:
            continue  # already a real application row

        is_needs_review = item.category == "needs_review"
        is_lifecycle = (
            item.category in JOB_LIFECYCLE_CATEGORIES and item.category != "follow_up"
        )
        # THE ATS FLOOR — issue #166.
        #
        # Mail relayed by a known ATS is never dropped silently. A cloud scan
        # classifies from Gmail's ~200-character ``snippet``, and an ATS
        # rejection spends that entire budget on a polite preamble — so the
        # classifier reads a CONFIRMATION and scores it as one. Whether the
        # message clears ``REVIEW_FLOOR`` at all then comes down to whether its
        # SUBJECT happens to contain a confirmation phrase: Verkada's did (+2,
        # 0.70, the queue), Together AI's did not (0.60, gone). #166 is that
        # knife-edge, and #238 proved it by execution.
        #
        # What this does and does not do. It routes to the HUMAN REVIEW QUEUE
        # and nothing else — it never files a row, never asserts a status and
        # never writes a verdict, because ``_qualifies_for_hard_row`` above still
        # requires ``AUTO_FILE_GATE`` and is untouched. So a floored message
        # cannot make the board confidently WRONG, which is the failure mode
        # that ruled out the obvious alternative fix (adding Greenhouse's
        # rejection subject template as a pattern scores the same message
        # ``applied`` at +6 and would auto-file a rejection as APPLIED).
        #
        # Bounded three ways, so "never dropped" cannot become "queue floods":
        #   - LIFECYCLE ONLY. ``other`` — which is what a classifier miss and
        #     ATS job-alert noise both produce — still drops, and so does a
        #     category outside the canonical vocabulary, which stays a logged
        #     bug rather than becoming a queue entry.
        #   - ``follow_up`` stays excluded, exactly as it is above the floor.
        #   - the sender must be on ``rules.ATS_DOMAINS``, a closed list of
        #     transactional relays. Ordinary company and personal mail below the
        #     floor is dropped exactly as before.
        #
        # Known residual as of #166, stated rather than hidden: an ATS message
        # that scores NOTHING in any category is ``other`` and still drops.
        # Covering that means queueing mail on the strength of its sender alone,
        # which is a wider decision than #166 needs.
        #
        # THAT RESIDUAL IS NOW COVERED — see the clause below and #447. It was
        # not theoretical: it was 610 messages in the 15k corpus, every one about
        # a real application, reaching no card, no queue and no counter. What
        # made covering it safe was finding a signal narrower than the sender,
        # which is ``references_an_application``.
        # #447 WIDENS THIS BY ONE CLAUSE, and only one. A message an ATS relayed
        # that scores no lifecycle category at all is queued when — and only
        # when — its own text refers to an application the reader made. That is
        # the residual named four paragraphs up, and the clause is what keeps
        # covering it from becoming "queue on the sender alone": the corpus's
        # 400 ``ats-relay-noise`` messages are relayed by the same domains,
        # score the same ``other`` 0.50, and reference nothing of the reader's,
        # so they still drop.
        #
        # Still routes to the HUMAN QUEUE and nothing else: everything the
        # paragraph above says about not filing a row, not asserting a status
        # and not writing a verdict holds unchanged, because
        # ``_qualifies_for_hard_row`` is untouched and still wants
        # ``AUTO_FILE_GATE``. A referenced message cannot make the board wrong;
        # it can only get a person asked.
        # SCOPED TO ``other``, and that scope is load-bearing rather than tidy.
        # The three shapes #166 deliberately drops each drop for their own
        # reason, and only ONE of them is what #447 is about:
        #
        #   · ``other`` — a classifier miss. THIS is the 610, and the reference
        #     clause is what separates them from the ATS noise that also lands
        #     here.
        #   · ``follow_up`` — excluded from filing AND from the queue by design,
        #     above the floor as well as below it. It is the user's own chasing
        #     mail; queueing it asks them to classify themselves.
        #   · a category outside the canonical vocabulary — a BUG, whose
        #     contract is that it is LOGGED rather than turned into a queue
        #     entry. Queueing it would hide the bug behind a plausible row.
        #
        # An earlier draft of this wrote ``is_lifecycle or references(...)``,
        # which reversed the second and third as a side effect and was caught by
        # `test_the_floor_does_not_swallow_the_three_shapes_that_must_stay_dropped`
        # — the test for #166 doing its job on #447's change.
        ats_floor = is_ats_sender(item.sender_email) and (
            is_lifecycle
            or (
                item.category == "other"
                and references_an_application(item.subject, item.snippet)
            )
        )
        if (
            not is_needs_review
            and not ats_floor
            and not (is_lifecycle and item.confidence >= REVIEW_FLOOR)
        ):
            # THE ONLY TERMINAL DROP IN THE PIPELINE, and until now a silent one.
            #
            # An item that gets here produces nothing at all: no application row
            # (:func:`partition_applications` skipped it), no queue row, no
            # counter, no log. A verdict the classifier was CONFIDENT about
            # leaving by that door is worth a line, because the absence of one is
            # how three separate persistence drops shipped without anyone
            # noticing the product had recorded zero non-applied statuses.
            #
            # Gated at the auto-file threshold rather than logged unconditionally,
            # and that gate does real work: the cloud rules classifier returns
            # ``other`` at confidence 0.0, so ordinary inbox noise — the bulk of
            # every scan — cannot reach this line. What does reach it is a
            # confident ``follow_up`` (0.90 on "Following up on my application"),
            # which is dropped BY DESIGN, and any category outside the canonical
            # vocabulary, which is a bug. Both are things you want to see.
            #
            # Volume, stated honestly: this is per SYNC, not per message. A
            # confident follow_up that stays inside the scan window is logged
            # again on every sync, indefinitely — messages x syncs, not messages.
            # Bounded and cheap, but do not read a repeated line as a new drop.
            #
            # Reporting only. Nothing below this line changes what is returned.
            #
            # A LIFECYCLE verdict leaving here is an ACCIDENT and is always
            # logged and always counted. It is mail the classifier itself
            # believed was about a job application, discarded for scoring below
            # ``REVIEW_FLOOR``. The old gate was ``>= AUTO_FILE_GATE``, which is
            # backwards for this purpose: the CONFIDENT drops are the designed
            # ones (``follow_up``), and the unconfident ones are the failures.
            # Four of them cost the owner four Microsoft applications in
            # silence; see :class:`DroppedVerdict`.
            #
            # Volume stays bounded because this is the lifecycle branch only.
            # ``other`` — inbox noise, and the bulk of every scan — takes the
            # ``elif`` and stays silent unless it was confident, exactly as
            # before. A lifecycle verdict under the floor is rare by
            # construction: it needs a real category AND a score too weak to
            # queue.
            if is_lifecycle:
                if dropped_out is not None:
                    dropped_out.append(
                        DroppedVerdict(
                            message_id=item.message_id,
                            category=item.category,
                            confidence=item.confidence,
                        )
                    )
                logger.warning(
                    "Pipeline dropped a lifecycle verdict BELOW the review "
                    "floor: category=%s confidence=%.2f message_id=%s. It "
                    "scored under %.2f and its sender is not a known ATS relay, "
                    "so it produced no application row and no review-queue "
                    "entry. This is mail the classifier thought was about a job "
                    "application.",
                    item.category,
                    item.confidence,
                    item.message_id,
                    REVIEW_FLOOR,
                )
            elif item.confidence >= AUTO_FILE_GATE:
                # Category, confidence and message id — the three facts the
                # brief above asks for. The sender's ADDRESS used to ride along
                # and no longer does: it is the user's correspondent, it is
                # mail-derived, and the message id already names the message it
                # came from (see ``_warn_if_capped`` in cloud/applications.py).
                logger.warning(
                    "Pipeline dropped a confident verdict: category=%s "
                    "confidence=%.2f message_id=%s. It is neither a "
                    "lifecycle category that can be filed nor needs_review, so "
                    "it produced no application row and no review-queue entry.",
                    item.category,
                    item.confidence,
                    item.message_id,
                )
            continue

        # Named for the queue whenever the message got here on a job-mail
        # signal — a lifecycle verdict, or the #447 reference clause. Gating this
        # on ``is_lifecycle`` alone would have put every referenced ``other``
        # into the queue with no company against it, which is a worse row to
        # hand a person than the one they get now: the whole point of queueing
        # these is that a human can act on them.
        employer = (
            resolve_employer(item.sender_email, item.subject, item.sender_name)
            if (is_lifecycle or ats_floor)
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
        key = review_dedup_key(
            message_id=item.message_id,
            thread_id=item.thread_id,
            subject=item.subject,
            snippet=item.snippet,
            identity_role=item.identity_role,
            identity_req_id=item.identity_req_id,
        )
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
