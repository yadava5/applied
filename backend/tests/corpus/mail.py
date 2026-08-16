"""A 400-case mail corpus for the CLASSIFIER, and how it is built.

Sibling of :mod:`generator`, not a replacement. That module invents mail to
measure *application identity* (does one application land on one card). This
one invents mail to measure *classification* (does the verdict in the message
reach the right category). They share the invented-employer pool — importing it
rather than minting a second cast is deliberate; two pools drift and then two
corpora describe two different fictional worlds.

What this measures
------------------
Production is rules-only: ``hybrid.py`` short-circuits on
``settings.deployment == "cloud"`` before embeddings or SetFit are consulted,
so ``RulesClassifier`` alone is what Vercel runs. Locally the same call is a
three-layer cascade. Every number this corpus produces describes the RULES
LAYER, which is the production one.

The text handed to ``classify()`` is derived exactly as production derives it::

    text = extract_body_text(payload) or snippet          # gmail_oauth.py:1332

so a message whose payload yields no text (header-only, or a ``text/calendar``
part with no ``text/plain`` sibling) really does fall back to the ~186-character
Gmail snippet, and a verdict past ``_MAX_BODY_CHARS`` (4000) really is cut. The
defect classes are exercised through the production decode path rather than
pre-decoded into plain text, because a pre-decoded HTML case measures nothing.

How the cases were authored — and the trap that shape avoids
------------------------------------------------------------
Every body and subject here was written from
``Documents/Applied-Funding/mail-corpus-spec.md``: published ATS template text,
real subject conventions, and the eleven confusion pairs that document measured
against the live classifier. **No case was written by reading**
``classifier/rules.py``, **and no case has been softened to make it pass.**

That is not fastidiousness. The classifier's patterns were themselves written
by reading the classifier's past failures — which is why they cover
``(other|another) candidate`` and not ``a different candidate``. A corpus
authored from the patterns inherits exactly that blind spot and then certifies
it as covered: a check that cannot fail. A case the classifier gets wrong is a
finding, not a bug in the case.

Provenance, tracked per case
----------------------------
``VERIFIED``  published template text quoted in the spec (Workable's public
              library, Greenhouse's documented sender domains, RFC 6047).
``MEASURED``  text the spec states it ran through the live classifier; the
              eleven confusion pairs are of this kind.
``COLLECTED`` a real-world phrasing the spec lists but does not individually
              mark VERIFIED (the rejection verdict and softener lists).
``INFERRED``  realistic flavour, invented. Present for variation only.

The rule the spec sets and this module keeps: **no confusion pair rests on
INFERRED text alone.** Nobody should later cite a number derived from flavour
as evidence about real mail, so the report breaks results down by provenance.

Weighting
---------
Chosen by JUDGEMENT and recorded as judgement — see :data:`WEIGHTING`. No
public data exists on the share of messages in a job seeker's inbox by class;
everything available is either employer-side and conditional on stage (Ashby's
passthrough rates) or content-farm material with circular citation. The
existing ``classifier_eval_v*.jsonl`` files are uniform per class, which is a
balance *choice* and must not be mistaken for an observed distribution. This
corpus is weighted toward INTERVIEW and OFFER because those two have never once
fired in production (issue #348), so that is where measurement is worth most.

This is an INSTRUMENT, not a gate. It asserts no accuracy threshold anywhere.
Thresholds get asserted in a later change, once the honest numbers exist.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Any

from .generator import _POOL

# ── the shape of one case ────────────────────────────────────────────────────

#: A Gmail ``format=full`` payload node: nested dicts, arbitrary depth.
Payload = dict[str, Any]

CATEGORIES = ("applied", "interview", "offer", "rejection", "assessment", "other")

#: Cases per expected class. Judgement, not data. See the module docstring.
WEIGHTING: dict[str, int] = {
    "interview": 110,
    "offer": 85,
    "rejection": 75,
    "applied": 50,
    "assessment": 45,
    "other": 35,
}
TOTAL = sum(WEIGHTING.values())  # 400

PROVENANCES = ("VERIFIED", "MEASURED", "COLLECTED", "INFERRED")


@dataclass(frozen=True)
class MailCase:
    """One generated message plus the category it means to a human reader."""

    case_id: str
    axis: str
    expected: str
    subject: str
    sender: str
    payload: Payload
    #: The Gmail snippet. Used by the classifier ONLY when the payload yields
    #: no text — which is production's own fallback, not a convenience here.
    snippet: str
    provenance: str
    defects: tuple[str, ...] = ()
    pair: str | None = None
    note: str = ""
    #: True when this message would plausibly arrive via an ATS relay, whether
    #: or not it actually does. The company-domain share is measured over these.
    ats_origin: bool = False
    #: Where the verdict phrase was deliberately placed, for the truncation and
    #: overlong-subject cases. ``None`` everywhere else. The offset is the
    #: ACHIEVED one, computed against the collapsed text, never the requested
    #: one — a fixture that reports its intent rather than its content is how a
    #: truncation case ends up not truncated.
    verdict_offset: int | None = None
    verdict_text: str | None = None
    verdict_in: str = "body"  # "body" or "subject"
    extra: dict[str, Any] = field(default_factory=dict)


# ── payload construction: Gmail ``format=full`` shapes ───────────────────────

_WS = re.compile(r"\s+")
_SCRIPT_OR_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.I)
_TAG = re.compile(r"<[^>]+>")


def collapse(text: str) -> str:
    """Whitespace collapse, matching ``extract_body_text``'s normalisation."""

    return _WS.sub(" ", text).strip()


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def plain(text: str) -> Payload:
    return {"mimeType": "text/plain", "body": {"data": _b64(text)}}


def html(markup: str) -> Payload:
    return {"mimeType": "text/html", "body": {"data": _b64(markup)}}


def alternative(text: str, markup: str) -> Payload:
    return {"mimeType": "multipart/alternative", "parts": [plain(text), html(markup)]}


def mixed(*parts: Payload) -> Payload:
    return {"mimeType": "multipart/mixed", "parts": list(parts)}


def calendar_part(ics: str, method: str) -> Payload:
    """A ``text/calendar`` part. RFC 6047: the ``method`` parameter MUST match
    the iCalendar ``METHOD`` property, so both are set from one argument.

    ``extract_body_text`` handles ``text/plain`` and ``text/html`` and nothing
    else, so a calendar part with no plain sibling contributes NO text. That is
    not a flaw in the fixture; it is the thing being measured.
    """

    return {
        "mimeType": "text/calendar",
        "headers": [
            {
                "name": "Content-Type",
                "value": f"text/calendar; method={method}; charset=UTF-8; component=vevent",
            }
        ],
        "body": {"data": _b64(ics)},
    }


def attachment(filename: str) -> Payload:
    return {
        "mimeType": "application/ics",
        "filename": filename,
        "body": {"attachmentId": "att-" + filename},
    }


def header_only() -> Payload:
    """A payload Gmail answered for with headers only — no body data at all.

    ``extract_body_text`` returns ``""`` and production falls back to the
    snippet. Roughly ~186 characters, which is where the truncation half of
    this corpus lives.
    """

    return {"mimeType": "text/plain", "body": {"size": 0}}


# The expression that turns a payload into the string the classifier sees lives
# in :func:`mail_report.derive`, not here: this module invents the mail and must
# not import the code under measurement.

GMAIL_SNIPPET_CHARS = 186  # the measured average, cloud/gmail_client.py


def snippet_of(text: str) -> str:
    """Gmail-style snippet: collapsed, truncated to the measured average."""

    return collapse(text)[:GMAIL_SNIPPET_CHARS]


def html_to_text(markup: str) -> str:
    """Mirror of ``gmail_client._html_to_text``, used only to build snippets."""

    return collapse(_TAG.sub(" ", _SCRIPT_OR_STYLE.sub(" ", markup)))


# ── the invented cast ────────────────────────────────────────────────────────
#
# Employers come from :mod:`generator`'s pool. Identity is not scored here, so
# names may repeat across cases; what matters is that no real company appears.

EMPLOYERS: tuple[tuple[str, str], ...] = _POOL

ROLES = (
    "Backend Engineer",
    "Platform Engineer",
    "Site Reliability Engineer",
    "Data Engineer",
    "Machine Learning Engineer",
    "Software Engineer II",
    "Infrastructure Engineer",
    "Full Stack Engineer",
    "Security Engineer",
    "Product Engineer",
    "Systems Engineer",
    "Developer Experience Engineer",
)

RECRUITERS = (
    ("Dana Whitfield", "dana.whitfield"),
    ("Marcus Ellery", "marcus.ellery"),
    ("Priya Raman", "priya.raman"),
    ("Tomas Iglesias", "tomas.iglesias"),
    ("Lena Hoffmann", "lena.hoffmann"),
    ("Camille Rousseau", "camille.rousseau"),
    ("Yuki Tanaka", "yuki.tanaka"),
    ("Rowan Blake", "rowan.blake"),
    ("Imani Osei", "imani.osei"),
    ("Nils Berger", "nils.berger"),
)

CANDIDATE = "Alex"

#: VERIFIED ATS relay senders (spec §7). Only the ones the spec verified.
ATS_SENDERS = (
    "no-reply@greenhouse.io",
    "no-reply@us.greenhouse-mail.io",
    "no-reply@eu.greenhouse-mail.io",
    "no-reply@anz.greenhouse.io",
    "no-reply@hire.lever.co",
    "applicant@hire.lever.co",
    "uuil8994uu9p@email.workable.com",
    "k29fjq0bzx4t@email.workable.com",
    "wrenmarsh@myworkday.com",
)

#: Assessment and scheduling vendors. The spec could NOT verify any of these
#: sender domains, and none of them is in ``ATS_DOMAINS``. Cases using them are
#: therefore INFERRED on the sender axis and carry no ATS bonus.
VENDOR_SENDERS = (
    "no-reply@hackerrank.example",
    "invites@codesignal.example",
    "no-reply@codility.example",
    "scheduling@karat.example",
    "no-reply@hirevue.example",
)

CALENDAR_SENDERS = ("calendar-notification@google.com", "notifications@calendly.com")


class Builder:
    """Accumulates cases, hands out the cast, and tracks the class budget."""

    def __init__(self) -> None:
        self.cases: list[MailCase] = []
        self._n = 0
        self._e = 0
        self._r = 0
        self._p = 0
        self._req = 10480

    # -- cast ---------------------------------------------------------------

    def employer(self) -> tuple[str, str]:
        pair = EMPLOYERS[self._e % len(EMPLOYERS)]
        self._e += 1
        return pair

    def role(self) -> str:
        r = ROLES[self._r % len(ROLES)]
        self._r += 1
        return r

    def recruiter(self) -> tuple[str, str]:
        p = RECRUITERS[self._p % len(RECRUITERS)]
        self._p += 1
        return p

    def req(self) -> str:
        self._req += 7
        return f"R-{self._req}"

    def domain(self, display: str) -> str:
        return re.sub(r"[^a-z]", "", display.lower()) + ".example"

    def ats_sender(self, i: int) -> str:
        return ATS_SENDERS[i % len(ATS_SENDERS)]

    def company_sender(self, display: str, i: int) -> str:
        local = ("no-reply", "careers", "recruiting", "talent")[i % 4]
        return f"{local}@{self.domain(display)}"

    def human_sender(self, display: str) -> str:
        _name, local = self.recruiter()
        return f"{local}@{self.domain(display)}"

    # -- accumulation -------------------------------------------------------

    def add(self, case: MailCase) -> MailCase:
        self.cases.append(case)
        return case

    def make(
        self,
        *,
        axis: str,
        expected: str,
        subject: str,
        sender: str,
        payload: Payload,
        snippet: str,
        provenance: str,
        defects: tuple[str, ...] = (),
        pair: str | None = None,
        note: str = "",
        ats_origin: bool = False,
        verdict_offset: int | None = None,
        verdict_text: str | None = None,
        verdict_in: str = "body",
        extra: dict[str, Any] | None = None,
    ) -> MailCase:
        self._n += 1
        assert expected in CATEGORIES, expected
        assert provenance in PROVENANCES, provenance
        return self.add(
            MailCase(
                case_id=f"c{self._n:04d}",
                axis=axis,
                expected=expected,
                subject=subject,
                sender=sender,
                payload=payload,
                snippet=snippet,
                provenance=provenance,
                defects=defects,
                pair=pair,
                note=note,
                ats_origin=ats_origin,
                verdict_offset=verdict_offset,
                verdict_text=verdict_text,
                verdict_in=verdict_in,
                extra=extra or {},
            )
        )

    def count(self, category: str) -> int:
        return sum(1 for c in self.cases if c.expected == category)


# ── template text ────────────────────────────────────────────────────────────
#
# The VERIFIED blocks are Workable's publicly published templates, the most
# reproduced source of this language on the web. Slots are filled
# programmatically so 400 cases are 400 renderings of real shapes rather than
# 400 hand-typed strings.

# VERIFIED — Workable, "Scheduling an interview email template".
T_INTERVIEW_WORKABLE = """Hi {candidate},

Thank you for applying to {employer}.

Your application for the {role} position stood out to us and we would like to
invite you for an interview at our offices to get to know you a bit better.

You will meet with the {dept} department manager, {recruiter}. The interview
will last about {minutes} minutes and you'll have the chance to discuss the
{role} position and learn more about our company. Please bring photo ID to pass
reception.

Would you be available on {date}?

Looking forward to hearing from you,

All the best,
{recruiter}
{employer}
"""

# VERIFIED — Workable, "Phone interview invitation email template" shape.
T_INTERVIEW_PHONE = """Hi {candidate},

Thank you for applying to {employer}. We reviewed your application for the
{role} position and would like to invite you for a phone interview with
{recruiter} from our talent team.

The call will last about {minutes} minutes. Would you be available on {date}?
If none of those windows work, please share your availability for the rest of
the week and we will find a time.

Looking forward to speaking with you,
{recruiter}
"""

# VERIFIED — Workable, "Candidate rejection email template".
T_REJECTION_WORKABLE = """Dear {candidate},

Thank you for taking the time to consider {employer}. We wanted to let you know
that we have chosen to move forward with a different candidate for the {role}
position.

Our team was impressed by your skills and accomplishments. We think you could
be a good fit for other future openings and will reach out again if we find a
good match.

We wish you all the best in your job search and future professional endeavors.

Regards,
{recruiter}
"""

# VERIFIED — Workable, "Formal job offer letter template".
T_OFFER_WORKABLE = """Dear {candidate},

Thank you for taking the time to interview with our team over the past few
weeks. We are delighted to extend this offer of employment for the position of
{role} at {employer}.

Your starting salary will be ${salary} per year, payable in accordance with the
Company's standard payroll schedule. You will also be eligible for an annual
incentive bonus, expressed as a percentage of base salary, and a grant of stock
options subject to a four-year vesting schedule (25% after one year, then
monthly installments thereafter).

This offer is contingent upon satisfactory completion of a background check and
your signing of the Company's proprietary information and confidentiality
agreements. Your start date will be {date}.

Please indicate your agreement with these terms by signing below by {deadline}.
Employment with {employer} is at will.

Sincerely,
{recruiter}
{employer}
"""

# COLLECTED — a confirmation body built from the spec's §1 reliable signals,
# including the §1 trap sentences that name a future interview.
T_APPLIED = """Hi {candidate},

Thank you for applying to {employer}. We have received your application for the
{role} position ({req}) and it is under review.

Our team reviews every application we receive. If your background matches what
we are looking for, a recruiter will reach out to schedule an interview. You may
also be invited to complete an assessment as part of the process.

Please do not reply to this email; this inbox is not monitored.

{employer} is an equal opportunity employer.
"""

# COLLECTED — assessment invitation body from the spec's §4 signals.
T_ASSESSMENT = """Hi {candidate},

You have been invited to take the {employer} - {role} Screen as the next step in
your application.

The assessment has 3 questions and a 90 minute time limit. Please begin your
assessment before the link expires in 7 days.

Start test

{employer} Talent Team
"""


# ── verdict phrasings ────────────────────────────────────────────────────────

#: (phrase, provenance). Only the two the spec explicitly marks are VERIFIED.
REJECTION_VERDICTS: tuple[tuple[str, str], ...] = (
    ("we have chosen to move forward with a different candidate for the {role} position", "VERIFIED"),
    ("we have decided not to move forward with your application", "COLLECTED"),
    ("we will not be proceeding with your candidacy at this time", "COLLECTED"),
    ("we've decided to pursue other applicants", "COLLECTED"),
    ("we have decided to pursue other candidates", "COLLECTED"),
    ("you have not been selected", "COLLECTED"),
    ("you were not selected for this position", "COLLECTED"),
    ("we are unable to offer you a position at this time", "COLLECTED"),
    ("we have extended an offer to another candidate", "COLLECTED"),
    ("we've decided to go in a different direction", "COLLECTED"),
    ("the position has been filled", "COLLECTED"),
    ("we will not be advancing your candidacy", "COLLECTED"),
    ("we won't be proceeding with your application", "COLLECTED"),
    ("we are moving forward with candidates whose experience more closely aligns", "COLLECTED"),
    ("after careful consideration we have decided to move forward with other candidates", "COLLECTED"),
    ("we are unable to proceed with your candidacy", "COLLECTED"),
)

REJECTION_SOFTENERS: tuple[tuple[str, str], ...] = (
    ("We wish you all the best in your job search and future professional endeavors.", "VERIFIED"),
    ("We were impressed by your skills and accomplishments.", "VERIFIED"),
    ("We think you could be a good fit for other future openings.", "VERIFIED"),
    ("We encourage you to apply for future openings.", "COLLECTED"),
    ("We will keep your resume on file.", "COLLECTED"),
    ("This was not an easy decision.", "COLLECTED"),
    ("We had an exceptionally strong applicant pool this year.", "COLLECTED"),
)

INTERVIEW_VERDICTS: tuple[tuple[str, str], ...] = (
    ("we would like to invite you for an interview", "VERIFIED"),
    ("your application for the {role} position stood out to us", "VERIFIED"),
    ("please share your availability for the coming week", "COLLECTED"),
    ("please book a time that works for you using the link below", "COLLECTED"),
    ("we would like to schedule a 45 minute conversation with the hiring manager", "COLLECTED"),
    ("looking forward to meeting you", "COLLECTED"),
    ("you will meet with the platform team", "COLLECTED"),
    ("please pick a time that works for you", "COLLECTED"),
)

OFFER_VERDICTS: tuple[tuple[str, str], ...] = (
    ("we are delighted to extend this offer of employment for the position of {role}", "VERIFIED"),
    ("we are pleased to offer you the position of {role}", "COLLECTED"),
    ("your annual base salary will be ${salary}, payable in accordance with our standard payroll schedule", "VERIFIED"),
    ("please review and sign the attached offer letter", "COLLECTED"),
    ("this offer expires on {deadline}", "COLLECTED"),
    ("your start date will be {date}", "COLLECTED"),
)

FILLER = (
    "Our engineering organisation is arranged around small teams that own their "
    "services end to end, from design through to production support. ",
    "The team you would be joining maintains the ingestion tier and the storage "
    "layer beneath it, and is currently rebuilding both on a new scheduler. ",
    "We try to keep the process short and to give you a clear answer at every "
    "stage rather than leaving you to guess where things stand. ",
    "Everyone you speak with will have read your application beforehand, so you "
    "will not be asked to repeat what is already written down. ",
    "We publish our engineering levels and the expectations attached to each one, "
    "and we are happy to walk through them at any point in the process. ",
    "Reimbursement for travel is handled by the recruiting coordinator, who will "
    "be copied on the logistics thread once a date is agreed. ",
)


def render(template: str, **kw: Any) -> str:
    """Fill slots, leaving unknown ones untouched so a typo is visible."""

    out = template
    for key, value in kw.items():
        out = out.replace("{" + key + "}", str(value))
    return out


_PAD_WORDS: tuple[str, ...] = tuple(
    " ".join(FILLER).replace(",", "").replace(".", "").split()
)
# Short words, longest first, so the last few characters before the target can
# be filled exactly rather than jumped over.
_SHORT_WORDS = ("that", "with", "from", "for", "and", "the", "at", "by", "of", "in",
                "is", "on", "to", "a")


def pad_verdict(prefix: str, verdict: str, target: int, tail: str = "") -> tuple[str, int]:
    """Place ``verdict`` so it STARTS at collapsed offset ~``target``.

    Two things make this fiddly, and both have already produced a wrong case in
    this file:

    1. ``extract_body_text`` collapses whitespace BEFORE it caps at 4000, so
       padding with blank lines shrinks under collapse and lands a nominally
       truncated verdict inside the budget — a truncation case that is not
       truncated, passing for the wrong reason.
    2. Padding a whole sentence at a time overshoots. The first version of this
       function padded in ~130-character chunks, so a case labelled "verdict at
       150" actually placed it at 227 — outside the 186-character snippet it
       was built to sit inside. The label said one thing and the fixture did
       another, which is the worst failure an instrument can have.

    So padding is word-by-word, finishing with short words, and the ACHIEVED
    offset is returned and recorded rather than assumed.
    """

    body = prefix.rstrip() + "\n\n"
    i = 0
    while True:
        need = target - len(collapse(body)) - 1
        if need <= 0:
            break
        word = _PAD_WORDS[i % len(_PAD_WORDS)]
        i += 1
        if len(word) + 1 > need:
            short = next((s for s in _SHORT_WORDS if len(s) + 1 <= need), None)
            if short is None:
                break
            word = short
        body += word + " "
        if i % 14 == 0:
            body += "\n\n"
    full = body + verdict
    offset = collapse(full).index(collapse(verdict))
    if tail:
        full += "\n\n" + tail
    return full, offset


def overlong_subject(verdict: str, at: int) -> str:
    """A subject longer than 500 characters with the verdict starting at ``at``."""

    filler = "Regarding your recent application and the next stage of the process "
    head = (filler * 20)[:at]
    return head + verdict + " " + (filler * 4)[:60]


# ── helpers shared by the axes ───────────────────────────────────────────────


def _plain(b: Builder, **kw: Any) -> MailCase:
    body = kw.pop("body")
    return b.make(payload=plain(body), snippet=snippet_of(body), **kw)


def _snippet_only(b: Builder, **kw: Any) -> MailCase:
    """A message Gmail answered with headers only — the live residual path.

    The full body is kept in ``extra`` even though nothing classifies on it:
    the recorded verdict offset is an offset into THAT string, and without it
    the invariant that the offset is real degenerates into a check that cannot
    fail.
    """

    body = kw.pop("body")
    extra = dict(kw.pop("extra", None) or {})
    extra["full_body"] = body
    return b.make(payload=header_only(), snippet=snippet_of(body), extra=extra, **kw)


# ── axis: the eleven confusion pairs ─────────────────────────────────────────

# MEASURED — the spec ran this prefix and both continuations.
P1_PREFIX = (
    "Thank you so much for taking the time to speak with our team about the {role} "
    "role. We really enjoyed our conversation and were impressed by the depth of "
    "your experience with distributed systems and the thoughtful questions you "
    "asked about our architecture."
)
P1_SHORT = "Thank you so much for taking the time to speak with our team about the {role} role."
P1_REJECT = (
    "Unfortunately, after careful consideration, we have decided not to move "
    "forward with your application at this time."
)
P1_INVITE = (
    "We would like to invite you back for a final round with the hiring manager. "
    "Please pick a time that works for you using the link below."
)


def _axis_p1_same_prefix(b: Builder) -> None:
    """P1 — warm rejection vs. warm invitation, identical for 277 characters.

    Built at all four budget boundaries. The 150 and 300 cases go through the
    SNIPPET path (header-only payload), which is the only place a ~186-character
    budget is real; the 600 and 4500 cases go through the body path, where 4000
    is the cap.
    """

    for target, path in ((30, "snippet"), (150, "snippet"), (300, "snippet"),
                         (600, "body"), (4500, "body")):
        display, _tok = b.employer()
        role = b.role()
        name, _ = b.recruiter()
        # target < 60 is the control: a verdict that fits ENTIRELY in a snippet.
        prefix = (
            "" if target < 60
            else render(P1_SHORT if target < 200 else P1_PREFIX, role=role)
        )
        body, offset = pad_verdict(
            f"Dear {CANDIDATE},\n\n" + prefix, P1_REJECT, target, tail=f"Regards,\n{name}"
        )
        kw = {
            "axis": "P1-same-prefix",
            "expected": "rejection",
            "subject": f"Thank you from {display}",
            "sender": b.ats_sender(target),
            "provenance": "MEASURED",
            "defects": (f"truncation:{path}-{target}",),
            "pair": "P1",
            "note": "warm preamble, verdict at the stated offset",
            "ats_origin": True,
            "verdict_offset": offset,
            "verdict_text": P1_REJECT,
            "extra": {"verdict_target": target},
            "body": body,
        }
        if path == "snippet":
            _snippet_only(b, **kw)
        else:
            _plain(b, **kw)

    # The twin: same 277-character opening, opposite verdict.
    display, _tok = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    body, offset = pad_verdict(
        f"Dear {CANDIDATE},\n\n" + render(P1_PREFIX, role=role),
        P1_INVITE,
        600,
        tail=f"Best,\n{name}",
    )
    _plain(
        b,
        axis="P1-same-prefix",
        expected="interview",
        subject=f"Thank you from {display}",
        sender=b.ats_sender(3),
        provenance="MEASURED",
        defects=("truncation:body-600",),
        pair="P1",
        note="identical prefix to the P1 rejections, opposite verdict",
        ats_origin=True,
        verdict_offset=offset,
        verdict_text=P1_INVITE,
        extra={"verdict_target": 600},
        body=body,
    )


def _axis_p2_invite_vs_confirmation(b: Builder) -> None:
    """P2 — both open with Workable's confirmation sentence; they diverge at ~95."""

    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    opening = (
        f"Hi {CANDIDATE},\n\nThank you for applying to {display}.\n\n"
        f"Your application for the {role} position "
    )
    _plain(
        b,
        axis="P2-invite-vs-confirmation",
        expected="interview",
        subject=f"Invitation to interview - {display}",
        sender=b.ats_sender(0),
        provenance="VERIFIED",
        pair="P2",
        note="Workable's published invitation; opens with the confirmation sentence",
        ats_origin=True,
        body=opening
        + "stood out to us and we would like to invite you for an interview at our "
        f"offices to get to know you a bit better. The interview will last about 45 "
        f"minutes and you will meet with the platform department manager.\n\n"
        f"Would you be available on Tuesday 18 August between 2pm and 5pm?\n\n"
        f"All the best,\n{name}\n",
    )
    _plain(
        b,
        axis="P2-invite-vs-confirmation",
        expected="applied",
        subject=f"Your application for {role} at {display}",
        sender=b.ats_sender(1),
        provenance="VERIFIED",
        pair="P2",
        note="the confirmation twin; identical first 95 characters",
        ats_origin=True,
        body=opening
        + "has been received and is under review. Our team reviews every application "
        "we receive and we will be in touch if your background matches what we are "
        "looking for.\n\nPlease do not reply to this email.\n",
    )


def _axis_p3_rejection_as_offer(b: Builder) -> None:
    """P3 — a rejection whose verdict sentence contains the word 'offer'."""

    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    _plain(
        b,
        axis="P3-rejection-as-offer",
        expected="rejection",
        subject=f"Thank you for your interest in {display}",
        sender=b.ats_sender(2),
        provenance="MEASURED",
        pair="P3",
        note="'extended an offer to another candidate' — the verdict names an offer",
        ats_origin=True,
        body=f"Dear {CANDIDATE},\n\nThank you for your interest in {display}. After "
        f"completing our interview process we have extended an offer to another "
        f"candidate for the {role} position.\n\nWe were impressed by your skills and "
        f"accomplishments and we encourage you to apply for future openings.\n\n"
        f"Regards,\n{name}\n",
    )
    display2, _ = b.employer()
    _plain(
        b,
        axis="P3-rejection-as-offer",
        expected="offer",
        subject=f"Job offer from {display2}",
        sender=b.human_sender(display2),
        provenance="VERIFIED",
        pair="P3",
        note="the true-offer twin, shared vocabulary, company-domain human sender",
        body=render(
            T_OFFER_WORKABLE,
            candidate=CANDIDATE,
            employer=display2,
            role=role,
            recruiter=name,
            salary="182,000",
            date="7 September 2026",
            deadline="22 August 2026",
        ),
    )


def _axis_p4_quoted_thread(b: Builder) -> None:
    """P4 — the latest text and the quoted text disagree. Both polarities."""

    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    _plain(
        b,
        axis="P4-quoted-thread",
        expected="rejection",
        subject=f"RE: Interview invitation - {role} at {display}",
        sender=b.ats_sender(4),
        provenance="MEASURED",
        pair="P4",
        note="new text rejects; the quote below is the old invitation",
        ats_origin=True,
        body=f"Hi {CANDIDATE},\n\nThank you for making the time to meet the team last "
        f"week. After careful consideration we have decided not to move forward with "
        f"your application at this time.\n\nRegards,\n{name}\n\n"
        f"On Mon, 10 Aug 2026 at 09:14, {name} <{b.human_sender(display)}> wrote:\n"
        f"> Hi {CANDIDATE},\n>\n> We would like to invite you to interview. Please "
        f"schedule a time using the link below to meet the hiring team.\n>\n"
        f"> Looking forward to meeting you,\n> {name}\n",
    )
    display2, _ = b.employer()
    _plain(
        b,
        axis="P4-quoted-thread",
        expected="interview",
        subject="RE: Update on your application",
        sender=b.ats_sender(5),
        provenance="MEASURED",
        pair="P4",
        note="mirror: the QUOTE is the rejection, the new text re-opens the process",
        ats_origin=True,
        body=f"Hi {CANDIDATE},\n\nA {role} opening has re-opened on the platform team "
        f"and the hiring manager asked me to bring you back. Please pick a time that "
        f"works for you using the link below and we will get the final round on the "
        f"calendar.\n\nBest,\n{name}\n\n"
        f"On Fri, 1 Aug 2026 at 16:02, {name} <{b.human_sender(display2)}> wrote:\n"
        f"> Dear {CANDIDATE},\n>\n> We wanted to let you know that we have chosen to "
        f"move forward with a different candidate for the {role} position.\n>\n"
        f"> We wish you all the best in your job search.\n",
    )


def _axis_p5_silent_subject(b: Builder) -> None:
    """P5 — an offer whose subject carries no offer vocabulary, and its twin."""

    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    _plain(
        b,
        axis="P5-silent-subject",
        expected="offer",
        subject=f"Next steps - {display}",
        sender=b.human_sender(display),
        provenance="MEASURED",
        pair="P5",
        note="full compensation block, no offer vocabulary in the subject",
        body=f"Hi {CANDIDATE},\n\nThank you for taking the time to interview with the "
        f"team. I am delighted to confirm the details we discussed on Friday for the "
        f"{role} role.\n\nYour annual base salary will be $182,000, payable in "
        f"accordance with our standard payroll schedule, with a target bonus of 12% "
        f"and an option grant vesting over four years, 25% after one year and monthly "
        f"thereafter. Your start date will be 7 September 2026 and employment is at "
        f"will.\n\nPlease indicate your agreement by 22 August 2026.\n\n{name}\n",
    )
    display2, _ = b.employer()
    _plain(
        b,
        axis="P5-silent-subject",
        expected="interview",
        subject=f"Next steps - {display2}",
        sender=b.human_sender(display2),
        provenance="INFERRED",
        pair="P5",
        note="identical subject, but this one is a scheduling request",
        body=f"Hi {CANDIDATE},\n\nThank you for taking the time to speak with me "
        f"yesterday. The next step for the {role} role is a 60 minute system design "
        f"session with two engineers from the platform team.\n\nPlease share your "
        f"availability for the coming week and I will send an invitation.\n\n{name}\n",
    )


def _axis_p6_assessment_vs_interview(b: Builder) -> None:
    """P6 — vendors that call an assessment an interview, and vice versa."""

    display, _ = b.employer()
    role = b.role()
    _plain(
        b,
        axis="P6-assessment-vs-interview",
        expected="assessment",
        subject=f"{display} - {role} Screen",
        sender=VENDOR_SENDERS[0],
        provenance="VERIFIED",
        pair="P6",
        note="HackerRank defaults the invite subject to the test NAME; no vocabulary",
        body=render(T_ASSESSMENT, candidate=CANDIDATE, employer=display, role=role),
    )
    display2, _ = b.employer()
    _plain(
        b,
        axis="P6-assessment-vs-interview",
        expected="assessment",
        subject=f"HireVue on-demand interview - {display2}",
        sender=VENDOR_SENDERS[4],
        provenance="INFERRED",
        pair="P6",
        note="the vendor calls its assessment an interview",
        body=f"Hi {CANDIDATE},\n\n{display2} has invited you to complete an on-demand "
        f"interview. You will record answers to 5 questions in your own time; there is "
        f"a 2 minute time limit per question and the link expires in 5 days.\n\n"
        f"Begin your assessment\n",
    )
    display3, _ = b.employer()
    name, _ = b.recruiter()
    _plain(
        b,
        axis="P6-assessment-vs-interview",
        expected="interview",
        subject=f"{display3} - your assessment results and next steps",
        sender=b.ats_sender(6),
        provenance="MEASURED",
        pair="P6",
        note="congratulations-on-completing suppresses the invitation in the same body",
        ats_origin=True,
        body=f"Hi {CANDIDATE},\n\nCongratulations on completing your assessment. The "
        f"next step is a technical interview with our engineering team. Please pick a "
        f"time using the scheduling link below.\n\nLooking forward to meeting you,\n"
        f"{name}\n",
    )


# ── calendar ─────────────────────────────────────────────────────────────────

ICS = """BEGIN:VCALENDAR
PRODID:-//Google Inc//Google Calendar 70.9054//EN
VERSION:2.0
CALSCALE:GREGORIAN
METHOD:{method}
BEGIN:VEVENT
DTSTART:20260818T180000Z
DTEND:20260818T184500Z
DTSTAMP:20260814T120000Z
ORGANIZER;CN={recruiter}:mailto:{organizer}
UID:{uid}@google.com
ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT={partstat};RSVP=TRUE
 ;CN=alex@example.com;X-NUM-GUESTS=0:mailto:alex@example.com
SEQUENCE:{sequence}
STATUS:{status}
SUMMARY:{summary}
DESCRIPTION:{description}
END:VEVENT
END:VCALENDAR
"""

CAL_BODY = """You have been invited to the following event.

{summary}

When  Tue 18 Aug 2026 14:00 - 14:45 (EDT)
Where Google Meet
Who   {organizer} - organizer
      alex@example.com

Going?   Yes - Maybe - No    more options

Invitation from Google Calendar
"""


def _ics(**kw: Any) -> str:
    base = {
        "method": "REQUEST",
        "sequence": "0",
        "status": "CONFIRMED",
        "partstat": "NEEDS-ACTION",
        "uid": "ev0001",
        "description": "Interview with the platform team.",
    }
    base.update(kw)
    return render(ICS, **base)


def _axis_p7_calendar(b: Builder) -> None:
    """P7 — the four iMIP methods, plus the RSVP echoes.

    RFC 6047 fixes the ``method`` parameter and the ``METHOD`` property; it says
    nothing about the Subject header, so the subjects here are the client
    conventions users actually filter on and are marked INFERRED.

    Structurally the important part: ``extract_body_text`` handles ``text/plain``
    and ``text/html`` and nothing else, so a calendar part with no plain sibling
    contributes no text at all and the message classifies on its snippet.
    """

    display, _ = b.employer()
    role = b.role()
    name, local = b.recruiter()
    organizer = f"{local}@{b.domain(display)}"
    summary = f"{role} Phone Screen"

    shapes = (
        ("REQUEST", "0", "CONFIRMED", f"Invitation: {summary} @ Tue 18 Aug 2026 2pm - 2:45pm (EDT) (alex@example.com)",
         "interview", "calendar:request", "new invitation"),
        ("REQUEST", "1", "CONFIRMED", f"Updated invitation: {summary} @ Wed 19 Aug 2026 10am - 10:45am (EDT)",
         "interview", "calendar:reschedule", "SEQUENCE:1 reschedule"),
        ("CANCEL", "2", "CANCELLED", f"Canceled event: {summary} @ Tue 18 Aug 2026",
         "interview", "calendar:cancel", "a cancellation must NOT read as a rejection"),
        ("REPLY", "0", "CONFIRMED", f"Accepted: {summary} @ Tue 18 Aug 2026",
         "other", "calendar:reply", "someone else's RSVP landing in the inbox"),
    )
    for method, seq, status, subject, expected, defect, note in shapes:
        ics = _ics(
            method=method,
            sequence=seq,
            status=status,
            recruiter=name,
            organizer=organizer,
            summary=summary,
            partstat="ACCEPTED" if method == "REPLY" else "NEEDS-ACTION",
        )
        b.make(
            axis="P7-calendar",
            expected=expected,
            subject=subject,
            sender=CALENDAR_SENDERS[0],
            payload=mixed(calendar_part(ics, method), attachment("invite.ics")),
            snippet=snippet_of(render(CAL_BODY, summary=summary, organizer=organizer)),
            # The PAYLOAD is verified: RFC 6047 fixes the method parameter and
            # the METHOD property, and invite.ics is the documented Gmail filter
            # idiom. Only the Subject line format is a client convention.
            provenance="VERIFIED",
            defects=(defect, "calendar:no-plain-sibling"),
            pair="P7",
            note=note + "; text/calendar with no text/plain sibling",
            extra={"subject_provenance": "INFERRED"},
        )

    # The same invitation WITH a plain alternative — the control that shows how
    # much of the calendar result is the missing part and how much is the prose.
    ics = _ics(method="REQUEST", recruiter=name, organizer=organizer, summary=summary)
    text = render(CAL_BODY, summary=summary, organizer=organizer)
    b.make(
        axis="P7-calendar",
        expected="interview",
        subject=f"Invitation: {summary} @ Tue 18 Aug 2026 2pm - 2:45pm (EDT) (alex@example.com)",
        sender=CALENDAR_SENDERS[0],
        payload=mixed(alternative(text, f"<html><body><p>{text}</p></body></html>"),
                      calendar_part(ics, "REQUEST")),
        snippet=snippet_of(text),
        provenance="VERIFIED",
        defects=("calendar:request",),
        pair="P7",
        note="control: identical invitation that DOES carry a text/plain part",
        extra={"subject_provenance": "INFERRED"},
    )

    # Your own RSVP echoing back — should be OTHER or deduplicated, never a verdict.
    b.make(
        axis="P7-calendar",
        expected="other",
        subject=f"Declined: {summary} @ Tue 18 Aug 2026 (alex@example.com)",
        sender=CALENDAR_SENDERS[0],
        payload=plain("alex@example.com has declined this invitation.\n"),
        snippet="alex@example.com has declined this invitation.",
        provenance="INFERRED",
        defects=("calendar:rsvp-echo",),
        pair="P7",
        note="the candidate's own RSVP bouncing back into the inbox",
    )


def _axis_p8_cold_outreach(b: Builder) -> None:
    """P8 — a recruiter's cold approach vs. real progress on an application."""

    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    _plain(
        b,
        axis="P8-cold-outreach",
        expected="other",
        subject=f"{role} opportunity at {display}",
        sender=b.human_sender(display),
        provenance="MEASURED",
        pair="P8",
        note="a role the candidate never applied to; must not become an application",
        body=f"Hi {CANDIDATE},\n\nI came across your profile and I think you would be a "
        f"great fit for a {role} role we are hiring for at {display}. Would you be open "
        f"to a quick 15 minute chat this week to discuss the role?\n\nBest,\n{name}\n",
    )
    display2, _ = b.employer()
    _plain(
        b,
        axis="P8-cold-outreach",
        expected="interview",
        subject=f"Following up on your application - {display2}",
        sender=b.human_sender(display2),
        provenance="MEASURED",
        pair="P8",
        note="the same sentence, but prefixed by a real application; this IS progress",
        body=f"Hi {CANDIDATE},\n\nFollowing up on your application for {role} at "
        f"{display2}. Would you be open to a quick 15 minute chat this week to discuss "
        f"the role?\n\nBest,\n{name}\n",
    )


def _axis_p9_someone_elses_outcome(b: Builder) -> None:
    """P9 — an outcome that belongs to somebody else."""

    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    _plain(
        b,
        axis="P9-someone-elses-outcome",
        expected="other",
        subject="Your referral has been hired!",
        sender=b.company_sender(display, 2),
        provenance="MEASURED",
        pair="P9",
        note="somebody else accepted an offer",
        body="Great news - the candidate you referred has accepted our offer and will "
        "be joining the team. Your referral bonus will be paid out next cycle.\n",
    )
    _plain(
        b,
        axis="P9-someone-elses-outcome",
        expected="other",
        subject="Your referral was moved to interview",
        sender=b.company_sender(display, 3),
        provenance="MEASURED",
        pair="P9",
        note="somebody else's interview",
        body=f"The candidate you referred for the {role} role has been moved to "
        f"interview. You can follow their progress in the referral portal.\n",
    )
    _plain(
        b,
        axis="P9-someone-elses-outcome",
        expected="other",
        subject="Please provide a reference for Jordan",
        sender=b.ats_sender(7),
        provenance="MEASURED",
        pair="P9",
        note="a reference request about a third party",
        ats_origin=True,
        body=f"Jordan has listed you as a reference for a {role} position at {display}. "
        f"Please complete the short form below by Friday.\n",
    )


def _axis_p10_rescission(b: Builder) -> None:
    """P10 — a withdrawn offer and the offer it shares its vocabulary with."""

    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    _plain(
        b,
        axis="P10-rescission",
        expected="rejection",
        subject="Regarding your offer of employment",
        sender=b.human_sender(display),
        provenance="MEASURED",
        pair="P10",
        note="a rescission uses the same subject as the offer it withdraws",
        body=f"Dear {CANDIDATE},\n\nWe regret to inform you that due to a change in "
        f"headcount we must withdraw the offer of employment extended to you on 1 "
        f"August for the {role} position.\n\nThis was not an easy decision and we are "
        f"sorry to deliver this news so late in the process.\n\nSincerely,\n{name}\n",
    )
    display2, _ = b.employer()
    _plain(
        b,
        axis="P10-rescission",
        expected="offer",
        subject="Regarding your offer of employment",
        sender=b.human_sender(display2),
        provenance="MEASURED",
        pair="P10",
        note="minimal pair: identical subject, the offer is being EXTENDED",
        body=f"Dear {CANDIDATE},\n\nWe are pleased to extend the offer of employment for "
        f"the {role} position at {display2}, revised to reflect the equity discussion "
        f"we had on Tuesday.\n\nYour annual base salary will be $190,000 and the option "
        f"grant has been increased. This offer expires on 22 August 2026.\n\n"
        f"Sincerely,\n{name}\n",
    )


def _axis_p11_marketing(b: Builder) -> None:
    """P11 — marketing carrying the whole vocabulary, and the invitation that
    must survive the footer that looks like marketing."""

    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    _plain(
        b,
        axis="P11-marketing",
        expected="other",
        subject=f"5 new {role} jobs for you",
        sender="alerts@jobboard.example",
        provenance="MEASURED",
        pair="P11",
        note="regression anchor: relaxing negatives can flip this to a verdict",
        body=f"New jobs matching your alert. {display} is interviewing now. Apply today "
        f"and get an offer faster.\n\nUnsubscribe from job alerts.\n",
    )
    display2, _ = b.employer()
    _plain(
        b,
        axis="P11-marketing",
        expected="interview",
        subject=f"Invitation to interview - {display2}",
        sender=b.ats_sender(0),
        provenance="VERIFIED",
        pair="P11",
        note="a real invitation carrying a vendor footer; a body-matched marketing "
        "veto would suppress exactly this",
        ats_origin=True,
        body=f"Hi {CANDIDATE},\n\nYour application for the {role} position stood out to "
        f"us and we would like to invite you for an interview. Please book a time that "
        f"works for you using the link below.\n\nLooking forward to meeting you,\n"
        f"{name}\n\n---\nYou are receiving this because you applied via our careers "
        f"site. Manage your notification preferences or unsubscribe from this "
        f"newsletter.\n",
    )


# ── axis: transfer encodings ─────────────────────────────────────────────────


def quoted_printable(text: str, wrap: int = 73) -> str:
    """Encode to quoted-printable with soft line breaks, the way a mailer does.

    Wrapping at ``wrap`` puts ``=\\r\\n`` inside words, which is the defect that
    matters: a verdict phrase split mid-word no longer matches anything.
    """

    out: list[str] = []
    for ch in text:
        if ch == "=":
            out.append("=3D")
        elif ord(ch) > 126:
            out.extend(f"={byte:02X}" for byte in ch.encode("utf-8"))
        else:
            out.append(ch)
    encoded = "".join(out)
    lines: list[str] = []
    for line in encoded.split("\n"):
        while len(line) > wrap:
            lines.append(line[:wrap] + "=\r\n")
            line = line[wrap:]
        lines.append(line)
    return "\n".join(lines)


def soft_break(text: str, word: str, at: int) -> str:
    """Split one word across a soft line break: ``for=\\r\\nward``."""

    return text.replace(word, word[:at] + "=\r\n" + word[at:], 1)


def encoded_word_q(text: str) -> str:
    """RFC 2047 ``=?UTF-8?Q?...?=``. Gmail's API does NOT decode Subject."""

    body = "".join(
        "_" if ch == " "
        else ch if ch.isalnum() or ch in "-"
        else "".join(f"={byte:02X}" for byte in ch.encode("utf-8"))
        for ch in text
    )
    return f"=?UTF-8?Q?{body}?="


def encoded_word_b(text: str) -> str:
    return "=?UTF-8?B?" + base64.b64encode(text.encode("utf-8")).decode("ascii") + "?="


def _axis_encodings(b: Builder) -> None:
    """Transfer encodings and encoded subjects.

    CAVEAT, and it belongs in every number derived from this axis: Gmail's API
    normally hands back CTE-DECODED bytes, so quoted-printable artifacts
    reaching ``classify()`` is not a verified production condition. What IS
    verified from the code is that ``extract_body_text`` performs no
    quoted-printable decoding of its own — it base64url-decodes the transport
    wrapper and nothing else. These cases therefore measure what the classifier
    does with text that carries QP artifacts, and the carrier is INFERRED.

    The Subject cases are different and are NOT hypothetical:
    ``_parse_metadata_message`` reads ``headers["subject"]`` verbatim, so an
    RFC 2047 encoded-word really does reach ``classify()`` undecoded.
    """

    # -- quoted-printable bodies --
    for expected, verdict, prov in (
        ("rejection", "we have decided not to move forward with your application", "COLLECTED"),
        ("interview", "we would like to invite you for an interview", "VERIFIED"),
        ("offer", "we are delighted to extend this offer of employment", "VERIFIED"),
    ):
        display, _ = b.employer()
        role = b.role()
        name, _ = b.recruiter()
        body = (
            f"Dear {CANDIDATE},\n\nThank you for the time you've given us during the "
            f"{role} process — we don't take it for granted.\n\nWe write to let you know "
            f"that {verdict} at this time.\n\nRegards,\n{name}\n"
        )
        b.make(
            axis="encodings",
            expected=expected,
            subject=f"Update on your {display} application",
            sender=b.ats_sender(1),
            payload=plain(quoted_printable(body)),
            snippet=snippet_of(body),
            provenance=prov,
            defects=("encoding:quoted-printable",),
            note="=3D and =E2=80=99 artifacts plus 73-column soft breaks",
            ats_origin=True,
        )

    # -- a soft break splitting the verdict phrase mid-word --
    for expected, phrase, word, at, prov in (
        ("rejection", "we have decided not to move forward with your application", "forward", 3, "COLLECTED"),
        ("interview", "we would like to invite you for an interview", "interview", 5, "VERIFIED"),
        ("offer", "we are pleased to offer you the position", "position", 4, "COLLECTED"),
    ):
        display, _ = b.employer()
        role = b.role()
        name, _ = b.recruiter()
        body = (
            f"Dear {CANDIDATE},\n\nRegarding the {role} position at {display}: "
            f"{phrase}.\n\nRegards,\n{name}\n"
        )
        b.make(
            axis="encodings",
            expected=expected,
            subject=f"Update on your application - {display}",
            sender=b.ats_sender(2),
            payload=plain(soft_break(quoted_printable(body, wrap=200), word, at)),
            snippet=snippet_of(body),
            provenance=prov,
            defects=("encoding:qp-soft-break-in-verdict",),
            note=f"'{word}' split across a soft line break inside the verdict",
            ats_origin=True,
        )

    # -- a body that is base64 INSIDE the part, i.e. the CTE was not applied --
    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    inner = (
        f"Dear {CANDIDATE},\n\nWe have chosen to move forward with a different "
        f"candidate for the {role} position.\n\nRegards,\n{name}\n"
    )
    b.make(
        axis="encodings",
        expected="rejection",
        subject=f"Your application to {display}",
        sender=b.ats_sender(3),
        payload=plain(base64.b64encode(inner.encode()).decode("ascii")),
        snippet=snippet_of(inner),
        provenance="VERIFIED",
        defects=("encoding:base64-not-decoded",),
        note="a text/plain part whose CONTENT is still base64 — mis-declared, not "
        "the normal transport encoding (which _decode_part already reverses)",
        ats_origin=True,
    )

    # -- encoded subjects; these are real, Gmail hands Subject over undecoded --
    subjects = (
        (encoded_word_q("Update on your application"), "subject:encoded-word-Q", "rejection",
         "we have decided not to move forward with your application", "COLLECTED"),
        (encoded_word_b("Invitation to interview"), "subject:encoded-word-B", "interview",
         "we would like to invite you for an interview", "VERIFIED"),
        ("[EXTERNAL] " + encoded_word_q("Job offer from Ambervale"), "subject:encoded-word-mixed",
         "offer", "we are delighted to extend this offer of employment", "VERIFIED"),
        (encoded_word_q("Update on your ") + "\r\n " + encoded_word_q("application"),
         "subject:encoded-word-folded", "rejection", "you have not been selected", "COLLECTED"),
        (encoded_word_q("Votre candidature"), "subject:encoded-word-Q", "assessment",
         "you have been invited to take an online assessment with a 90 minute time limit",
         "COLLECTED"),
    )
    for subject, defect, expected, verdict, prov in subjects:
        display, _ = b.employer()
        role = b.role()
        name, _ = b.recruiter()
        body = (
            f"Dear {CANDIDATE},\n\nRegarding the {role} position at {display}: "
            f"{verdict}.\n\nRegards,\n{name}\n"
        )
        _plain(
            b,
            axis="encodings",
            expected=expected,
            subject=subject,
            sender=b.ats_sender(4),
            provenance=prov,
            defects=(defect,),
            note="RFC 2047 encoded-word reaching classify() undecoded",
            ats_origin=True,
            body=body,
        )


# ── axis: HTML-only bodies ───────────────────────────────────────────────────

PIXEL = '<img src="https://track.example/o.gif?m=1" width="1" height="1" alt="" style="display:block">'
STYLE = (
    "<style>.btn{background:#111;color:#fff;padding:12px 20px} "
    ".preheader{display:none!important;max-height:0;overflow:hidden} "
    "@media(max-width:600px){.wrap{width:100%!important}}</style>"
)


def _axis_html(b: Builder) -> None:
    """HTML-only bodies: no ``text/plain`` sibling anywhere in the tree."""

    # 1. A rejection that exists only as HTML.
    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    markup = (
        f"<html><head>{STYLE}</head><body><table width='600'><tr><td>"
        f"<p>Dear {CANDIDATE},</p>"
        f"<p>Thank you for taking the time to consider {display}. We wanted to let you "
        f"know that we have chosen to move forward with a different candidate for the "
        f"{role} position.</p>"
        f"<p>We wish you all the best in your job search and future professional "
        f"endeavors.</p><p>Regards,<br>{name}</p>{PIXEL}</td></tr></table></body></html>"
    )
    b.make(
        axis="html",
        expected="rejection",
        subject=f"Your application to {display}",
        sender=b.ats_sender(5),
        payload=html(markup),
        snippet=snippet_of(html_to_text(markup)),
        provenance="VERIFIED",
        defects=("html:only", "html:table", "html:tracking-pixel", "html:style-block"),
        note="regression anchor: script/style are stripped BEFORE tags, so the CSS "
        "must not leak into the classified text as prose",
        ats_origin=True,
    )

    # 2. CSS-hidden preheader that CONTRADICTS the visible text. Both polarities.
    for expected, hidden, visible, prov in (
        ("interview",
         "Unfortunately we have decided not to move forward with your application.",
         "We would like to invite you for an interview with the hiring manager. "
         "Please pick a time that works for you.",
         "COLLECTED"),
        ("rejection",
         "Great news - we would like to invite you for an interview!",
         "Thank you for taking the time to consider us. We have chosen to move forward "
         "with a different candidate for the position.",
         "VERIFIED"),
    ):
        display, _ = b.employer()
        markup = (
            f"<html><head>{STYLE}</head><body>"
            f"<div class='preheader' style='display:none;max-height:0;overflow:hidden'>"
            f"{hidden}</div>"
            f"<table><tr><td><p>Dear {CANDIDATE},</p><p>{visible}</p></td></tr></table>"
            f"{PIXEL}</body></html>"
        )
        b.make(
            axis="html",
            expected=expected,
            subject=f"Update on your application - {display}",
            sender=b.ats_sender(6),
            payload=html(markup),
            snippet=snippet_of(html_to_text(markup)),
            provenance=prov,
            defects=("html:only", "html:hidden-preheader-contradicts"),
            note="display:none preheader carries the OPPOSITE verdict and is not "
            "stripped, so it reaches the classifier ahead of the visible text",
            ats_origin=True,
        )

    # 3. A panel itinerary: a table of times and names, almost no prose.
    display, _ = b.employer()
    role = b.role()
    rows = "".join(
        f"<tr><td>{t}</td><td>{who}</td><td>{topic}</td></tr>"
        for t, who, topic in (
            ("10:00 - 10:45", "Priya Raman, Engineering Manager", "System Design"),
            ("11:00 - 11:45", "Nils Berger, Staff Engineer", "Coding"),
            ("12:00 - 12:45", "Imani Osei, Director", "Values"),
            ("13:00 - 13:30", "Rowan Blake, Recruiter", "Wrap-up"),
        )
    )
    markup = (
        f"<html><body><h2>{role} - Wednesday 19 August</h2>"
        f"<table>{rows}</table><p>{display}</p>{PIXEL}</body></html>"
    )
    b.make(
        axis="html",
        expected="interview",
        subject="Your interview schedule - Wednesday 19 August",
        sender=b.company_sender(display, 1),
        payload=html(markup),
        snippet=snippet_of(html_to_text(markup)),
        provenance="INFERRED",
        defects=("html:only", "html:table", "html:tracking-pixel"),
        note="an onsite loop as a table: high density of names and times, no prose",
        ats_origin=True,
    )

    # 4. An assessment that is a single button.
    display, _ = b.employer()
    role = b.role()
    markup = (
        f"<html><head>{STYLE}</head><body><table><tr><td>"
        f"<img src='https://cdn.example/logo.png' alt='{display}'>"
        f"<a class='btn' href='https://assess.example/t/9f2'>Start test</a>"
        f"<p>90 minutes. Expires in 7 days.</p></td></tr></table>{PIXEL}</body></html>"
    )
    b.make(
        axis="html",
        expected="assessment",
        subject=f"{display} - {role} Screen",
        sender=VENDOR_SENDERS[1],
        payload=html(markup),
        snippet=snippet_of(html_to_text(markup)),
        provenance="INFERRED",
        defects=("html:only", "html:button-only"),
        note="a single button and a deadline; the whole message is 40 characters of prose",
    )

    # 5. An offer letter that lives in the attachment, with an HTML cover note.
    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    markup = (
        f"<html><body><p>Hi {CANDIDATE},</p><p>Please review and sign the attached "
        f"offer letter for the {role} position. Let me know if anything looks wrong.</p>"
        f"<p>{name}</p></body></html>"
    )
    b.make(
        axis="html",
        expected="offer",
        subject=f"Please review and sign: Employment Agreement - {CANDIDATE}",
        sender=b.human_sender(display),
        payload=mixed(html(markup), attachment("offer-letter.pdf")),
        snippet=snippet_of(html_to_text(markup)),
        provenance="INFERRED",
        defects=("html:only", "attachment:carries-the-verdict"),
        note="the compensation block is in the PDF; the mail body says almost nothing",
    )


# ── axis: subject defects ────────────────────────────────────────────────────


def _axis_subjects(b: Builder) -> None:
    """The subject zoo. The BODY carries the verdict except where the defect is
    about the subject carrying it (the overlong cases)."""

    verdicts = (
        ("rejection", "we have chosen to move forward with a different candidate", "VERIFIED"),
        ("interview", "we would like to invite you for an interview", "VERIFIED"),
        ("offer", "we are delighted to extend this offer of employment", "VERIFIED"),
        ("assessment", "you have been invited to take an online assessment", "COLLECTED"),
    )

    shapes: tuple[tuple[str, str], ...] = (
        ("", "subject:empty"),
        ("   ", "subject:whitespace-only"),
        ("R-10482", "subject:bare-req-id"),
        ("\U0001f389 Congratulations!", "subject:emoji"),
        ("⚠️ Action Required", "subject:emoji"),
        ("[EXTERNAL] Update on your application", "subject:external-prefix"),
        ("[SPAM?] Update on your application", "subject:spam-prefix"),
        ("Re: Fwd: Re: Your application", "subject:stacked-re"),
        ("RE: YOUR APPLICATION", "subject:uppercase-re"),
        ("AW: Ihre Bewerbung", "subject:aw-de"),
        ("WG: Ihre Bewerbung", "subject:wg-de"),
        ("RE : Votre candidature", "subject:re-fr-spaced"),
        ("Re: 【重要】ご応募の件", "subject:japanese"),
    )
    for i, (subject, defect) in enumerate(shapes):
        expected, verdict, prov = verdicts[i % len(verdicts)]
        display, _ = b.employer()
        role = b.role()
        name, _ = b.recruiter()
        _plain(
            b,
            axis="subjects",
            expected=expected,
            subject=subject,
            sender=b.ats_sender(i),
            provenance=prov,
            defects=(defect,),
            note="the verdict is in the body; the subject is the defect",
            ats_origin=True,
            body=f"Dear {CANDIDATE},\n\nRegarding the {role} position at {display}: "
            f"{verdict}.\n\nRegards,\n{name}\n",
        )

    # Overlong subjects. The verdict lives ONLY in the subject, so the case
    # isolates subject handling. ``email_clients/parser.py`` truncates at
    # ``subject[:497] + "..."`` — but the CLOUD path does not truncate at all,
    # it passes the raw header through, so the 520 case is a live difference
    # between the two ingest paths rather than a hypothetical.
    for at, defect in ((480, "subject:overlong-verdict-at-480"), (520, "subject:overlong-verdict-at-520")):
        display, _ = b.employer()
        name, _ = b.recruiter()
        _plain(
            b,
            axis="subjects",
            expected="rejection",
            subject=overlong_subject(
                "we have decided not to move forward with your application", at
            ),
            sender=b.ats_sender(at),
            provenance="COLLECTED",
            defects=(defect,),
            note=f"subject longer than 500 chars, verdict starts at {at}",
            ats_origin=True,
            verdict_offset=at,
            verdict_text="we have decided not to move forward with your application",
            verdict_in="subject",
            extra={"verdict_target": at},
            body=f"Dear {CANDIDATE},\n\nPlease see the subject line of this message.\n\n"
            f"Regards,\n{name}\n{display}\n",
        )


# ── axis: truncation beyond P1 ───────────────────────────────────────────────


def _axis_truncation(b: Builder) -> None:
    """The three coexisting budgets, on classes other than REJECTION.

    ~186  the Gmail snippet, live whenever the body fetch produced nothing
    500   ``parser._generate_snippet`` (the local ingest path)
    4000  ``_MAX_BODY_CHARS`` on the cloud path
    """

    cases = (
        ("interview", "we would like to invite you for an interview at our offices", "VERIFIED"),
        ("offer", "we are delighted to extend this offer of employment for the position", "VERIFIED"),
        ("assessment", "you have been invited to take an online assessment, 90 minute time limit", "COLLECTED"),
        ("applied", "we have received your application and it is under review", "COLLECTED"),
    )
    for expected, verdict, prov in cases:
        for target, path in ((30, "snippet"), (150, "snippet"), (300, "snippet"),
                             (600, "body"), (4500, "body")):
            display, _ = b.employer()
            role = b.role()
            name, _ = b.recruiter()
            if target < 60:
                # The control. Everything else in this axis measures a verdict
                # the classifier could not fully see; without a case where it
                # CAN, a uniformly bad column says nothing about the budget.
                prefix = f"Dear {CANDIDATE},"
            else:
                prefix = (
                    f"Dear {CANDIDATE},\n\nThank you for your interest in the {role} "
                    f"position at {display}."
                )
            body, offset = pad_verdict(prefix, verdict + ".", target, tail=f"Regards,\n{name}")
            kw = {
                "axis": "truncation",
                "expected": expected,
                "subject": f"Regarding your candidacy - {role}",
                "sender": b.ats_sender(target // 7),
                "provenance": prov,
                "defects": (f"truncation:{path}-{target}",),
                "note": f"verdict placed at collapsed offset {offset}",
                "ats_origin": True,
                "verdict_offset": offset,
                "verdict_text": verdict,
                "extra": {"verdict_target": target},
                "body": body,
            }
            if path == "snippet":
                _snippet_only(b, **kw)
            else:
                _plain(b, **kw)


# ── axis: localisation ───────────────────────────────────────────────────────


def _axis_localisation(b: Builder) -> None:
    """Localised mail at US-headquartered multinationals. All INFERRED as corpus
    content; the phrasings are the spec's §9 examples."""

    rows = (
        ("es", "Actualización sobre tu candidatura",
         "Hola {candidate},\n\nGracias por tu interés en {employer}. Lamentamos "
         "informarte que no continuaremos con tu candidatura para el puesto de {role}.\n\n"
         "Te deseamos mucho éxito en tu búsqueda.\n\nSaludos,\n{recruiter}\n",
         "rejection", "locale:es"),
        ("de", "Ihre Bewerbung bei {employer}",
         "Sehr geehrte(r) {candidate},\n\nvielen Dank für Ihr Interesse an "
         "{employer}. Leider müssen wir Ihnen mitteilen, dass wir Ihre Bewerbung "
         "für die Position {role} nicht weiter berücksichtigen können.\n\n"
         "Mit freundlichen Grüßen,\n{recruiter}\n",
         "rejection", "locale:de"),
        ("fr", "Votre candidature chez {employer}",
         "Bonjour {candidate},\n\nNous vous remercions de l'intérêt que vous "
         "portez à {employer}. Nous ne donnerons pas suite à votre candidature "
         "pour le poste de {role}.\n\nCordialement,\n{recruiter}\n",
         "rejection", "locale:fr"),
        ("ja", "【{employer}】選考結果のご連絡",
         "{candidate} 様\n\nこの度は弊社の{role}に"
         "ご応募いただきありがとうご"
         "ざいます。誠に残念ながら、"
         "今回はご期待に沿えない結果"
         "となりました。\n\n{recruiter}\n",
         "rejection", "locale:ja"),
        ("fr", "Invitation à un entretien - {employer}",
         "Bonjour {candidate},\n\nVotre candidature pour le poste de {role} a retenu "
         "notre attention et nous souhaiterions vous inviter à un entretien. "
         "Seriez-vous disponible mardi prochain ?\n\nCordialement,\n{recruiter}\n",
         "interview", "locale:fr"),
    )
    for _lang, subject, body, expected, defect in rows:
        display, _ = b.employer()
        role = b.role()
        name, _ = b.recruiter()
        _plain(
            b,
            axis="localisation",
            expected=expected,
            subject=render(subject, employer=display),
            sender=b.ats_sender(3),
            provenance="INFERRED",
            defects=(defect,),
            note="localised mail; the classifier's vocabulary is English",
            ats_origin=True,
            body=render(body, candidate=CANDIDATE, employer=display, role=role, recruiter=name),
        )

    # Bilingual EN/FR: the French half repeats the English verdict.
    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    _plain(
        b,
        axis="localisation",
        expected="rejection",
        subject=f"Update on your application / Suivi de votre candidature - {display}",
        sender=b.ats_sender(0),
        provenance="INFERRED",
        defects=("locale:bilingual-en-fr",),
        note="Canadian bilingual mail; both halves carry the same verdict",
        ats_origin=True,
        body=f"Dear {CANDIDATE},\n\nThank you for your interest in {display}. We have "
        f"decided not to move forward with your application for the {role} position.\n\n"
        f"--\n\nBonjour {CANDIDATE},\n\nNous vous remercions de votre intérêt "
        f"pour {display}. Nous ne donnerons pas suite à votre candidature pour le "
        f"poste de {role}.\n\n{name}\n",
    )

    # RTL with explicit embedding marks.
    for defect, text in (
        ("locale:rtl-ar",
         "‫عزيزي {candidate}، نأسف "
         "لإبلاغك بأننا لن "
         "نتابع طلبك لوظيفة "
         "{role}.‬"),
        ("locale:rtl-he",
         "‫שלום {candidate}, אנו מצטערים "
         "להודיע כי לא נמשיך "
         "עם מועמדותך לתפקיד "
         "{role}.‬"),
    ):
        display, _ = b.employer()
        role = b.role()
        _plain(
            b,
            axis="localisation",
            expected="rejection",
            subject=f"Update on your application - {display}",
            sender=b.ats_sender(1),
            provenance="INFERRED",
            defects=(defect,),
            note="RTL body with U+202B embedding marks",
            ats_origin=True,
            body=render(text, candidate=CANDIDATE, role=role),
        )


# ── axis: threads ────────────────────────────────────────────────────────────


def _axis_threads(b: Builder) -> None:
    """Deep quoted threads. ``classify()`` never sees In-Reply-To or References
    — only subject, body and sender — so a thread is only ever as visible as
    its quoted text, and the quoted text is where the old verdicts live."""

    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    turns = (
        ("interview", f"We would like to invite you for an interview for the {role} role."),
        ("candidate", "Tuesday at 2pm works for me, thank you."),
        ("interview", "Great - the team would like to schedule a final round."),
        ("candidate", "Happy to. Any time on Thursday."),
        ("rejection", "After careful consideration we have decided not to move forward "
                      "with your application at this time."),
    )
    quoted = ""
    for depth, (_who, text) in enumerate(reversed(turns[:-1])):
        prefix = "> " * (depth + 1)
        quoted += f"{prefix}{text}\n{prefix}\n"
    _plain(
        b,
        axis="threads",
        expected="rejection",
        subject=f"Re: Re: Re: Invitation to interview - {display}",
        sender=b.human_sender(display),
        provenance="MEASURED",
        defects=("thread:six-deep-alternating",),
        note="five turns, verdicts alternating; the LATEST is the rejection",
        body=f"Hi {CANDIDATE},\n\n{turns[-1][1]}\n\nRegards,\n{name}\n\n"
        f"On 12 Aug 2026, {name} wrote:\n{quoted}",
    )

    # The mirror: an old rejection quoted beneath a fresh invitation.
    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    _plain(
        b,
        axis="threads",
        expected="interview",
        subject=f"Re: Fwd: Re: Your application to {display}",
        sender=b.human_sender(display),
        provenance="MEASURED",
        defects=("thread:quote-disagrees",),
        note="the quote rejects, the new text invites",
        body=f"Hi {CANDIDATE},\n\nThe {role} req has re-opened. Please share your "
        f"availability for the coming week and we will get you back in front of the "
        f"team.\n\n{name}\n\n"
        f"> Dear {CANDIDATE},\n>\n> We have chosen to move forward with a different "
        f"candidate for the {role} position.\n>\n> We wish you all the best in your job "
        f"search.\n",
    )

    # A forwarded chain the candidate forwarded to themselves.
    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    _plain(
        b,
        axis="threads",
        expected="offer",
        subject=f"Fwd: Job offer from {display}",
        sender="alex@example.com",
        provenance="INFERRED",
        defects=("thread:self-forward",),
        note="the candidate forwarded the offer to themselves; sender is now the user",
        body=f"---------- Forwarded message ----------\nFrom: {name} "
        f"<{b.human_sender(display)}>\nSubject: Job offer from {display}\n\n"
        f"Dear {CANDIDATE},\n\nWe are delighted to extend this offer of employment for "
        f"the position of {role} at {display}. Your annual base salary will be $178,000, "
        f"payable in accordance with the Company's standard payroll schedule. "
        f"Employment is at will.\n\n{name}\n",
    )


# ── axis: automated wrappers ─────────────────────────────────────────────────

LEGAL = (
    "This message and any attachments are confidential and intended solely for the "
    "addressee. If you have received this message in error, please notify the sender "
    "immediately and delete it from your system. Any unauthorised copying, disclosure "
    "or distribution of the material in this message is strictly prohibited. Neither "
    "the company nor any of its subsidiaries accepts liability for any statement made "
    "which is clearly the sender's own and not expressly made on behalf of the "
    "company. Please consider the environment before printing this email. Registered "
    "office: 1 Example Way. Company number 00000000. VAT number GB000000000."
)


def _axis_wrappers(b: Builder) -> None:
    """No-reply wrappers, disclaimer footers longer than the message, and the
    one-line human reply that is a genuine interview in 24 characters."""

    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    _plain(
        b,
        axis="wrappers",
        expected="interview",
        subject="Re: Backend Engineer - next step",
        sender=b.human_sender(display),
        provenance="INFERRED",
        defects=("wrapper:mobile-signature",),
        note="a genuine interview in 24 characters, beneath a phone signature",
        body="Does Tuesday 2pm work?\n\nSent from my iPhone\n",
    )

    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    _plain(
        b,
        axis="wrappers",
        expected="rejection",
        subject=f"Update on your application - {display}",
        sender=b.ats_sender(2),
        provenance="COLLECTED",
        defects=("wrapper:legal-footer-longer-than-message",),
        note="the disclaimer is six times the length of the verdict",
        ats_origin=True,
        body=f"Dear {CANDIDATE},\n\nYou have not been selected for the {role} "
        f"position.\n\nRegards,\n{name}\n\n--\n{LEGAL}\n",
    )

    display, _ = b.employer()
    role = b.role()
    _plain(
        b,
        axis="wrappers",
        expected="applied",
        subject=f"Application received - {role}",
        sender=b.ats_sender(0),
        provenance="COLLECTED",
        defects=("wrapper:automated-no-reply",),
        note="automated confirmation; do-not-reply wrapper on both sides of the verdict",
        ats_origin=True,
        body=f"This is an automated message, please do not reply.\n\nWe have received "
        f"your application for the {role} position at {display} and it is under "
        f"review.\n\nThis is an automated message, please do not reply.\n",
    )

    display, _ = b.employer()
    role = b.role()
    name, _ = b.recruiter()
    _plain(
        b,
        axis="wrappers",
        expected="interview",
        subject=f"Convocation à un entretien - {display}",
        sender=b.ats_sender(1),
        provenance="INFERRED",
        defects=("wrapper:ne-pas-repondre", "locale:fr"),
        note="French no-reply wrapper around a French invitation",
        ats_origin=True,
        body=f"NE PAS RÉPONDRE À CE MESSAGE\n\nBonjour {CANDIDATE},\n\nNous "
        f"souhaiterions vous inviter à un entretien pour le poste de {role}. "
        f"Merci d'indiquer vos disponibilités.\n\n{name}\n",
    )


# ── the bulk: template renderings that top each class up to its budget ───────
#
# Subjects come from the spec's per-class lists, VERIFIED ones first. Bodies are
# the published templates with the slots filled and the verdict phrase cycled
# through the collected phrasings, so 400 cases are 400 renderings of real
# shapes rather than 400 hand-typed strings.

SUBJECTS: dict[str, tuple[tuple[str, str], ...]] = {
    "interview": (
        ("Invitation to interview - {employer}", "VERIFIED"),
        ("Interview with {employer} for the {role} position", "VERIFIED"),
        ("Invitation to phone interview - {employer}", "VERIFIED"),
        ("Phone interview with {employer} for the {role} position", "VERIFIED"),
        ("Re: Your application for {role} at {employer}", "INFERRED"),
        ("Next steps - {role} @ {employer}", "INFERRED"),
        ("{employer} - Recruiter Screen", "INFERRED"),
        ("Let's find a time to chat, {candidate}", "INFERRED"),
        ("Availability request: {role}", "INFERRED"),
        ("{employer} <> {candidate} - 45 min intro", "INFERRED"),
        ("Your interview with {employer} is confirmed", "INFERRED"),
        ("Onsite Itinerary - {role} - Wed 19 Aug", "INFERRED"),
        ("Action required: schedule your interview", "INFERRED"),
        ("Following up on your application - {employer}", "INFERRED"),
        ("Great news about your {employer} application", "INFERRED"),
    ),
    "offer": (
        ("Job offer from {employer}", "VERIFIED"),
        ("{employer} job offer", "VERIFIED"),
        ("Job offer for the position of {role} at {employer}", "VERIFIED"),
        ("Your offer from {employer}", "INFERRED"),
        ("Offer Letter - {candidate} - {role}", "INFERRED"),
        ("Next steps - {employer}", "INFERRED"),
        ("Following up on our conversation", "INFERRED"),
        ("Welcome to {employer}!", "INFERRED"),
        ("Please review and sign: Employment Agreement", "INFERRED"),
        ("Action required: your offer expires Friday", "INFERRED"),
        ("Updated offer - {role}", "INFERRED"),
        ("{employer} - Compensation Summary", "INFERRED"),
        ("Your {employer} equity grant", "INFERRED"),
        ("Complete with DocuSign: Offer Letter - {candidate}", "INFERRED"),
    ),
    "rejection": (
        ("Your application to {employer}", "VERIFIED"),
        ("Thank you from {employer}", "INFERRED"),
        ("Update on your application", "INFERRED"),
        ("Update on your {employer} application", "INFERRED"),
        ("Regarding your candidacy - {role}", "INFERRED"),
        ("{employer} - {role} ({req})", "INFERRED"),
        ("Following up on your application", "INFERRED"),
        ("Thank you for your interest in {employer}", "INFERRED"),
        ("An update from the {employer} recruiting team", "INFERRED"),
        ("Your {employer} application status has changed", "INFERRED"),
        ("Thanks for interviewing with us", "INFERRED"),
    ),
    "applied": (
        ("Your application for {role} at {employer}", "VERIFIED"),
        ("Thank you for applying to {employer}", "INFERRED"),
        ("We received your application - {role} ({req})", "INFERRED"),
        ("Application Received: {role}", "INFERRED"),
        ("{employer}: Application Confirmation", "INFERRED"),
        ("Thanks for your interest in {employer}", "INFERRED"),
        ("[{employer}] Your application has been submitted", "INFERRED"),
        ("Application submitted successfully", "INFERRED"),
        ("Your {employer} application - next steps", "INFERRED"),
        ("Confirmation of your application ({req})", "INFERRED"),
        ("Thank you for your interest in a career at {employer}", "INFERRED"),
    ),
    "assessment": (
        ("{employer} - {role} Screen", "VERIFIED"),
        ("Your HackerRank test invitation from {employer}", "INFERRED"),
        ("Invitation to complete an online assessment - {employer}", "INFERRED"),
        ("[Action Required] Your {employer} Assessments Invitation", "INFERRED"),
        ("Coding Challenge - {role} @ {employer}", "INFERRED"),
        ("Take-home exercise: {employer}", "INFERRED"),
        ("Your CodeSignal assessment is ready", "INFERRED"),
        ("Codility test invitation - {employer}", "INFERRED"),
        ("Karat interview - schedule your session", "INFERRED"),
        ("Reminder: your assessment expires in 48 hours", "INFERRED"),
        ("{employer} - Work Sample Review", "INFERRED"),
        ("Complete your pre-employment screening", "INFERRED"),
    ),
    "other": (
        ("5 new {role} jobs for you", "INFERRED"),
        ("Jobs you may be interested in", "INFERRED"),
        ("{candidate}, your weekly job digest", "INFERRED"),
        ("{role} opportunity at {employer}", "INFERRED"),
        ("You appeared in 14 searches this week", "INFERRED"),
        ("Complete your profile to get 3x more offers", "INFERRED"),
        ("{employer} is interviewing now - apply today", "INFERRED"),
        ("Your interview prep course is ready", "INFERRED"),
        ("Limited time offer: 40% off Premium", "INFERRED"),
        ("Please provide a reference for Jordan", "INFERRED"),
    ),
}

OTHER_BODIES: tuple[str, ...] = (
    "New jobs matching your alert:\n\n{role} at {employer}\n{role} at {employer}\n\n"
    "See all 5 matches. Unsubscribe from job alerts.\n",
    "Here are the jobs we think you should see this week, {candidate}. {employer} is "
    "hiring and is interviewing now. Apply today.\n\nManage your alerts.\n",
    "Hi {candidate}, I came across your profile and thought of a {role} opening at "
    "{employer}. Would you be open to a quick chat?\n\n{recruiter}\n",
    "Your profile appeared in 14 recruiter searches this week, including one at "
    "{employer}. Upgrade to Premium to see who viewed you and get an offer faster.\n",
    "Your interview prep course is ready, {candidate}. 12 lessons covering system "
    "design, coding and behavioural rounds, with a {role} track. Start today.\n",
    "Jordan has listed you as a reference for a {role} position at {employer}. Please "
    "complete the short reference form by Friday.\n",
    "You have 3 saved jobs expiring soon at {employer}. Complete your application "
    "before the posting closes.\n",
)


def _sender_for(b: Builder, expected: str, i: int, display: str) -> tuple[str, bool]:
    """Pick a sender, and say whether the message is ATS-origin.

    ~2 in 7 ATS-origin messages come from the COMPANY's own domain, because a
    rebranded ATS tenant sends from ``no-reply@theircompany.com`` and the
    sender signal is present-or-absent, never reliably negative. Nothing in the
    corpus may silently depend on the +0.05 ATS bonus.

    Offers are different and deliberately so: they come from a named human on
    the company domain, which denies them the bonus entirely — the spec
    measured that +0.05 as the whole margin by which a real offer cleared the
    auto-file gate.
    """

    if expected == "offer":
        if i % 8 == 7:
            return b.ats_sender(i), True
        if i % 8 == 6:
            return "dse@docusign.example", False
        return b.human_sender(display), False
    if expected == "other":
        return ("alerts@jobboard.example" if i % 3 else b.human_sender(display)), False
    if expected == "assessment" and i % 3 == 0:
        return VENDOR_SENDERS[i % len(VENDOR_SENDERS)], False
    # The modulus is set so the WHOLE corpus lands in the 25-30% band, not just
    # this loop: the hand-built axes lean on ATS relays, which drags the overall
    # share down. The invariant test measures the corpus, not the intention.
    if i % 5 in (0, 1):
        return b.company_sender(display, i), True
    return b.ats_sender(i), True


def _bulk_body(b: Builder, expected: str, i: int, display: str, role: str,
               name: str, req: str) -> tuple[str, str, str]:
    """Return (body, provenance, shape) for one bulk case.

    The SHAPE matters as much as the count. An earlier draft rendered every
    interview case from Workable's canonical invitation, which opens "Thank you
    for applying to..." — 110 cases would then have measured ONE sentence 110
    times and reported it as a class-wide rate. Each class therefore cycles
    through several genuinely different real-world shapes, and the shape is
    recorded on every case so the report can say which phrasing families break
    rather than only how many.
    """

    date = f"Tuesday {11 + (i % 15)} August"
    minutes = (30, 45, 60)[i % 3]

    if expected == "interview":
        shape = (
            "workable-invite", "workable-phone", "self-schedule", "confirmed",
            "recruiter-screen", "availability-request", "onsite-itinerary",
            "reschedule",
        )[i % 8]
        if shape == "workable-invite":
            return render(
                T_INTERVIEW_WORKABLE, candidate=CANDIDATE, employer=display, role=role,
                recruiter=name, dept=("Platform", "Infrastructure", "Data")[i % 3],
                minutes=minutes, date=f"{date} between 2pm and 5pm",
            ), "VERIFIED", shape
        if shape == "workable-phone":
            return render(
                T_INTERVIEW_PHONE, candidate=CANDIDATE, employer=display, role=role,
                recruiter=name, minutes=minutes, date=f"{date} between 10am and 1pm",
            ), "VERIFIED", shape
        if shape == "self-schedule":
            return (
                f"Hi {CANDIDATE},\n\nThe hiring team for the {role} role would like to "
                f"speak with you. Please book a time that works for you using the link "
                f"below; the calendar is open for the next two weeks.\n\n"
                f"https://scheduling.example/{req.lower()}\n\n{name}\n{display}\n"
            ), "COLLECTED", shape
        if shape == "confirmed":
            return (
                f"Hi {CANDIDATE},\n\nYour interview with {display} is confirmed for "
                f"{date} at 2:00pm ET. You will meet with the platform team for "
                f"{minutes} minutes.\n\nJoining info: https://meet.example/{req.lower()}\n\n"
                f"Looking forward to meeting you,\n{name}\n"
            ), "COLLECTED", shape
        if shape == "recruiter-screen":
            return (
                f"Hi {CANDIDATE},\n\nI look after recruiting for the {role} opening at "
                f"{display}. I'd like to set up a {minutes} minute call to walk through "
                f"your background and what the team is working on.\n\nAre you free "
                f"{date}?\n\n{name}\n"
            ), "COLLECTED", shape
        if shape == "availability-request":
            return (
                f"Hi {CANDIDATE},\n\nWe'd like to move ahead with the {role} process. "
                f"Could you share two or three windows that work for you next week? I "
                f"will send an invitation once we have a time.\n\nPlease share your "
                f"availability for the coming week.\n\n{name}\n"
            ), "COLLECTED", shape
        if shape == "onsite-itinerary":
            return (
                f"Hi {CANDIDATE},\n\nHere is your itinerary for {date} at our office.\n\n"
                f"10:00 System Design with Priya Raman\n"
                f"11:00 Coding with Nils Berger\n"
                f"12:00 Lunch with the team\n"
                f"13:00 Values conversation with Imani Osei\n\n"
                f"Please bring photo ID for reception. You will meet with four members "
                f"of the {role} team over the course of the day.\n\n{name}\n"
            ), "INFERRED", shape
        # reschedule — carries "unfortunately", which real reschedules do
        return (
            f"Hi {CANDIDATE},\n\nUnfortunately our hiring manager is travelling this "
            f"week, so we have moved your {role} interview to {date} at 3:00pm. The "
            f"format is unchanged: {minutes} minutes with the platform team.\n\n"
            f"Apologies for the change, and please pick a time that works for you if "
            f"that slot does not.\n\n{name}\n"
        ), "COLLECTED", shape

    if expected == "offer":
        shape = (
            "workable-formal", "verbal-confirm", "esign", "comp-summary",
            "updated-offer", "welcome",
        )[i % 6]
        formal = render(
            T_OFFER_WORKABLE, candidate=CANDIDATE, employer=display, role=role,
            recruiter=name, salary=f"{160 + (i % 40)},000",
            date=f"{7 + (i % 20)} September 2026", deadline=f"{18 + (i % 10)} August 2026",
        )
        if shape == "workable-formal":
            return formal, "VERIFIED", shape
        if shape == "verbal-confirm":
            # No monetary figure and never the word "offer" — the spec measured
            # this shape at 0.75, under the gate.
            return (
                f"Hi {CANDIDATE},\n\nThank you for taking the time to interview with the "
                f"team. I am delighted to confirm the details we discussed on Friday for "
                f"the {role} role.\n\nYour start date will be {7 + (i % 20)} September "
                f"2026 and employment is at will. Let me know if anything looks "
                f"wrong.\n\n{name}\n"
            ), "MEASURED", shape
        if shape == "esign":
            return (
                f"Hi {CANDIDATE},\n\nPlease review and sign the attached offer letter for "
                f"the {role} position at {display}. The document expires in 7 days.\n\n"
                f"Review and sign\n\n{name}\n"
            ), "COLLECTED", shape
        if shape == "comp-summary":
            return (
                f"Hi {CANDIDATE},\n\nAs promised, the compensation summary for the {role} "
                f"role.\n\nAnnual base salary ${160 + (i % 40)},000, payable in accordance "
                f"with our standard payroll schedule\nTarget bonus 12% of base\n"
                f"Options vesting over four years, 25% after one year then monthly\n"
                f"Start date {7 + (i % 20)} September 2026\n\nThis is contingent upon a "
                f"background check. Please indicate your agreement by {18 + (i % 10)} "
                f"August 2026.\n\n{name}\n"
            ), "VERIFIED", shape
        if shape == "updated-offer":
            return (
                f"Hi {CANDIDATE},\n\nWe have revised the {role} package following our "
                f"conversation. Unfortunately we cannot match your current equity, but we "
                f"have increased base to ${170 + (i % 30)},000 and added a signing "
                f"bonus.\n\nThis offer expires on {18 + (i % 10)} August 2026.\n\n{name}\n"
            ), "COLLECTED", shape
        return (
            f"Hi {CANDIDATE},\n\nWelcome to {display}! We are thrilled you will be "
            f"joining us as a {role} on {7 + (i % 20)} September 2026. Your onboarding "
            f"buddy will be in touch next week.\n\nBy signing below you confirm the terms "
            f"we agreed. Employment is at will.\n\n{name}\n"
        ), "INFERRED", shape

    if expected == "rejection":
        shape = (
            "workable-template", "post-interview", "terse", "position-filled",
            "keep-on-file",
        )[i % 5]
        verdict, prov = REJECTION_VERDICTS[i % len(REJECTION_VERDICTS)]
        softener, _sprov = REJECTION_SOFTENERS[i % len(REJECTION_SOFTENERS)]
        verdict = render(verdict, role=role)
        if shape == "workable-template":
            return render(
                T_REJECTION_WORKABLE, candidate=CANDIDATE, employer=display, role=role,
                recruiter=name,
            ), "VERIFIED", shape
        if shape == "post-interview":
            return (
                f"Dear {CANDIDATE},\n\nThank you for taking the time to meet the team "
                f"last week and for the thoughtful questions you asked about how we run "
                f"the {role} function.\n\nThe panel was impressed by your experience and "
                f"the discussion was one of the strongest we have had this cycle.\n\n"
                f"After careful consideration, {verdict}.\n\n{softener}\n\nRegards,\n"
                f"{name}\n"
            ), prov, shape
        if shape == "terse":
            return f"Dear {CANDIDATE},\n\n{verdict.capitalize()}.\n\n{name}\n", prov, shape
        if shape == "position-filled":
            return (
                f"Dear {CANDIDATE},\n\nThank you for your interest in the {role} position "
                f"at {display}. The position has been filled and we are no longer "
                f"accepting candidates for this requisition ({req}).\n\n{softener}\n\n"
                f"Regards,\n{name}\n"
            ), "COLLECTED", shape
        return (
            f"Dear {CANDIDATE},\n\nThank you for taking the time to consider {display}. "
            f"{verdict.capitalize()} for the {role} position.\n\nWe will keep your "
            f"resume on file and encourage you to apply for future openings.\n\n"
            f"{softener}\n\nRegards,\n{name}\n"
        ), prov, shape

    if expected == "applied":
        shape = ("ats-confirmation", "submitted", "under-review", "next-steps-trap")[i % 4]
        if shape == "ats-confirmation":
            return render(
                T_APPLIED, candidate=CANDIDATE, employer=display, role=role, req=req
            ), "COLLECTED", shape
        if shape == "submitted":
            return (
                f"Hi {CANDIDATE},\n\nYour application has been submitted for the {role} "
                f"position ({req}) at {display}. You can track its status from your "
                f"candidate portal.\n\nPlease do not reply to this email.\n"
            ), "COLLECTED", shape
        if shape == "under-review":
            return (
                f"Hi {CANDIDATE},\n\nThank you for applying to {display}. We have received "
                f"your application for the {role} position and it is under review. Our "
                f"team reviews every application we receive and we will be in touch.\n\n"
                f"{display} is an equal opportunity employer.\n"
            ), "COLLECTED", shape
        return (
            f"Hi {CANDIDATE},\n\nThanks for your interest in {display}. We have received "
            f"your application for the {role} position.\n\nIf your background matches "
            f"what we are looking for, a recruiter will reach out to schedule an "
            f"interview, and you may be invited to complete an assessment. We will be in "
            f"touch to schedule next steps either way.\n\nDo not reply to this message.\n"
        ), "COLLECTED", shape

    if expected == "assessment":
        shape = ("vendor-invite", "takehome", "reminder", "screening", "bare-test-name")[i % 5]
        if shape == "vendor-invite":
            return render(
                T_ASSESSMENT, candidate=CANDIDATE, employer=display, role=role
            ), "COLLECTED", shape
        if shape == "takehome":
            return (
                f"Hi {CANDIDATE},\n\n{display} has invited you to complete a take-home "
                f"exercise for the {role} position. Please allow about three hours and "
                f"submit within 7 days; the link expires after that.\n\nBegin your "
                f"assessment\n"
            ), "COLLECTED", shape
        if shape == "reminder":
            return (
                f"Hi {CANDIDATE},\n\nReminder: your {display} assessment expires in 48 "
                f"hours. 3 questions, 90 minute time limit.\n\nStart test\n"
            ), "COLLECTED", shape
        if shape == "screening":
            return (
                f"Hi {CANDIDATE},\n\nAs part of the {role} process at {display}, please "
                f"complete your pre-employment screening. It takes about 20 minutes and "
                f"must be finished before your start date.\n\nComplete screening\n"
            ), "INFERRED", shape
        # HackerRank's default: the subject is the test name and the body says
        # almost nothing that names an assessment.
        return (
            f"Hi {CANDIDATE},\n\nYou have been invited by {display}.\n\n"
            f"{display} - {role} Screen\n90 minutes\n\nStart test\n"
        ), "VERIFIED", shape

    shape = ("digest", "cold-outreach", "upsell", "reference", "prep-course",
             "referral", "expiring-saved")[i % 7]
    return render(
        OTHER_BODIES[i % len(OTHER_BODIES)], candidate=CANDIDATE, employer=display,
        role=role, recruiter=name,
    ), "INFERRED", shape


def _axis_bulk(b: Builder) -> None:
    """Top every class up to its budget with template renderings."""

    for expected in ("interview", "offer", "rejection", "applied", "assessment", "other"):
        want = WEIGHTING[expected] - b.count(expected)
        subjects = SUBJECTS[expected]
        for i in range(want):
            display, _ = b.employer()
            role = b.role()
            name, _ = b.recruiter()
            req = b.req()
            subject_tpl, _sprov = subjects[i % len(subjects)]
            sender, ats_origin = _sender_for(b, expected, i, display)
            body, prov, shape = _bulk_body(b, expected, i, display, role, name, req)
            _plain(
                b,
                axis="bulk",
                expected=expected,
                subject=render(
                    subject_tpl, employer=display, role=role, candidate=CANDIDATE, req=req
                ),
                sender=sender,
                provenance=prov,
                defects=(f"shape:{expected}/{shape}",),
                note="template rendering",
                ats_origin=ats_origin,
                body=body,
            )

AXES = (
    _axis_p1_same_prefix,
    _axis_p2_invite_vs_confirmation,
    _axis_p3_rejection_as_offer,
    _axis_p4_quoted_thread,
    _axis_p5_silent_subject,
    _axis_p6_assessment_vs_interview,
    _axis_p7_calendar,
    _axis_p8_cold_outreach,
    _axis_p9_someone_elses_outcome,
    _axis_p10_rescission,
    _axis_p11_marketing,
    _axis_encodings,
    _axis_html,
    _axis_subjects,
    _axis_truncation,
    _axis_localisation,
    _axis_threads,
    _axis_wrappers,
    _axis_bulk,
)


def generate() -> list[MailCase]:
    """Build the corpus. Deterministic: no RNG, no clock, no environment."""

    b = Builder()
    for axis in AXES:
        axis(b)
    if len(b.cases) != TOTAL:
        raise RuntimeError(
            f"corpus is {len(b.cases)} cases, not {TOTAL}; the budget and the axes "
            "have diverged"
        )
    for category, want in WEIGHTING.items():
        got = b.count(category)
        if got != want:
            raise RuntimeError(f"{category}: {got} cases, budgeted {want}")
    return b.cases


METADATA: dict[str, Any] = {
    "total": TOTAL,
    "weighting": WEIGHTING,
    "weighting_basis": (
        "JUDGEMENT, not data. No public figure exists for the share of messages "
        "in a job seeker's inbox by class; the available numbers are either "
        "employer-side and conditional on stage or content-farm material with "
        "circular citation. Weighted toward INTERVIEW and OFFER because neither "
        "has ever fired in production (issue #348)."
    ),
    "measures": "the RULES layer alone, which is what production runs",
    "is_a_gate": False,
}
