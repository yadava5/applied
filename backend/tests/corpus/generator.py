"""A deterministic, wholly INVENTED corpus of adversarial job mail.

Why this file exists
--------------------
A rejection for an application already on the board minted a SECOND card. The
extractor had captured ``interest in <Employer> and our <Title>`` as the role,
so the rejection's identity key did not match the confirmation's and the
resolver saw a new application. One reproduction proves one bug; it says
nothing about how often that *shape* fires, or whether a fix pushes the error
the other way. This corpus is the instrument that answers both.

The hard rule: every employer, role, sender and body below is fictional.
The owner's mailbox holds genuine applications to real employers, and this
repository is not private. What is borrowed from reality is the *shape* — the
ATS relay domains, the subject templates, the exact phrasings that break the
role extractor. Real-world shapes, fictional companies.

Determinism
-----------
The generator takes a seed and every choice derives from it, so a corpus is
byte-identical between runs. A corpus that differs between runs cannot be a
regression gate.

Ground truth, and the trap in it
--------------------------------
Every case carries the application identity it *should* land on. ``identity``
is opaque: two cases sharing it MUST end on one card, two with different keys
MUST NOT.

The subtle part — and the first version of this file got it wrong — is that
ground truth has to agree with the PRODUCT's identity rule, which is
``(employer, req_id or role_token)``. Reusing one employer+role pair under two
different identity keys makes the harness report a MERGE for behaviour that is
correct, and those false positives swamp the real ones. So employers are handed
out from a disjoint pool (:meth:`_Builder.employer`): no two axes share one
unless the axis is deliberately about sharing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from jobtracker.cloud.pipeline import PipelineItem

# Comfortably above AUTO_FILE_GATE (0.85) so gated mail actually reaches the
# clusterer. The harness self-checks that a non-trivial number got through;
# a corpus that silently falls below the gate measures nothing at all.
CONF_HIGH = 0.94
CONF_LOW = 0.55  # deliberately below the gate — belongs in review, not on a card

EPOCH = datetime(2026, 3, 2, 9, 0, 0)


@dataclass(frozen=True)
class Case:
    """One generated email plus what the pipeline is supposed to do with it."""

    item: PipelineItem
    axis: str
    # The application this mail belongs to. ``None`` means it must never become
    # or join an application at all (newsletters, cold approaches, invites).
    identity: str | None
    # Expected employer token, or None when no employer is identifiable.
    employer: str | None
    # Expected role as the human title, or None when the mail names no role.
    role: str | None
    note: str = ""
    # True when the CORRECT outcome is the review queue rather than a card:
    # role-less mail at an employer that already holds several applications.
    expect_review: bool = False


# ── the invented cast ────────────────────────────────────────────────────────
#
# None of these is a real company; the names are compounds chosen so that a
# collision with a live employer is implausible. Three are RESERVED because
# their shape is the point of a specific axis and cannot be swapped for a
# generic name.

# camel-cased, no space — the shape that let the leftmost anchor run away.
RESERVED_CAMEL = ("SafeHarbor", "safeharbor")
# the employer name itself contains a role word.
RESERVED_ROLEWORD = ("Perigee Systems", "perigee systems")
# an ampersand that arrives HTML-escaped.
RESERVED_AMPERSAND = ("Marlowe & Finch", "marlowe finch")

_POOL: tuple[tuple[str, str], ...] = (
    ("Aetherloom", "aetherloom"),
    ("Alderpoint", "alderpoint"),
    ("Ambervale", "ambervale"),
    ("Arcwright", "arcwright"),
    ("Ashgrove Systems", "ashgrove systems"),
    ("Basalt Row", "basalt row"),
    ("Beaconfall", "beaconfall"),
    ("Bellwether Metrics", "bellwether metrics"),
    ("Blackmoor Analytics", "blackmoor analytics"),
    ("Bramblewick", "bramblewick"),
    ("Brightpath Health", "brightpath health"),
    ("Calderra", "calderra"),
    ("Cindermill", "cindermill"),
    ("Cobalt Ridge", "cobalt ridge"),
    ("Copperline", "copperline"),
    ("Dunmarrow", "dunmarrow"),
    ("Eastvale Robotics", "eastvale robotics"),
    ("Emberlyn", "emberlyn"),
    ("Fernwhistle", "fernwhistle"),
    ("Fieldstone Grid", "fieldstone grid"),
    ("Flintlock Data", "flintlock data"),
    ("Foxglove Systems", "foxglove systems"),
    ("Glasshouse Labs", "glasshouse labs"),
    ("Greywater Tech", "greywater tech"),
    ("Halcyon Grid", "halcyon grid"),
    ("Harrowgate", "harrowgate"),
    ("Hollowmere", "hollowmere"),
    ("Ironvale", "ironvale"),
    ("Jasperline", "jasperline"),
    ("Kestrel Dynamics", "kestrel dynamics"),
    ("Larkspur AI", "larkspur ai"),
    ("Lumafold", "lumafold"),
    ("Meridian Freight", "meridian freight"),
    ("Northwind Robotics", "northwind robotics"),
    ("Oakenshield Data", "oakenshield data"),
    ("Orrery Data", "orrery data"),
    ("Quillhaven", "quillhaven"),
    ("Redthorn Labs", "redthorn labs"),
    ("Riverbend Optics", "riverbend optics"),
    ("Saltmarsh Analytics", "saltmarsh analytics"),
    ("Silverbrook", "silverbrook"),
    ("Slateforge", "slateforge"),
    ("Sundial Analytics", "sundial analytics"),
    ("Tessellate AI", "tessellate ai"),
    ("Thornfield Grid", "thornfield grid"),
    ("Vantara Labs", "vantara labs"),
    ("Westmoor Systems", "westmoor systems"),
    ("Whitecliff Health", "whitecliff health"),
    ("Windrow Logistics", "windrow logistics"),
    ("Yarrowdale", "yarrowdale"),
    ("Zephyrline", "zephyrline"),
    ("Netherford", "netherford"),
    ("Ospreybank", "ospreybank"),
    ("Pinewhistle", "pinewhistle"),
    ("Ravenmoor Labs", "ravenmoor labs"),
    ("Stonebridge Optics", "stonebridge optics"),
    ("Tallowmere", "tallowmere"),
    ("Umberfield", "umberfield"),
    ("Verdantia", "verdantia"),
    ("Wrenmarsh", "wrenmarsh"),
    ("Xanthe Systems", "xanthe systems"),
    ("Yewbank Data", "yewbank data"),
    ("Zinnia Grid", "zinnia grid"),
    ("Cragmont", "cragmont"),
    ("Dovetail Metrics", "dovetail metrics"),
    ("Elmshollow", "elmshollow"),
    ("Frostvale", "frostvale"),
    ("Gullwing Tech", "gullwing tech"),
    ("Hazelmoor", "hazelmoor"),
    ("Inglewood Robotics", "inglewood robotics"),
    ("Juniper Falls", "juniper falls"),
    ("Kilnbrook", "kilnbrook"),
    ("Lanternwood", "lanternwood"),
    ("Mosswright", "mosswright"),
)

# Two employers sharing a leading word are ONE employer to
# ``matches_company_token`` (it accepts a leading-word match), so a pool with a
# duplicated first word would manufacture merges that are correct behaviour.
# Asserted at import rather than trusted: this is exactly the kind of quiet
# corpus defect that makes every downstream number wrong.
_FIRST_WORDS = [t.split(" ")[0] for _d, t in _POOL]
if len(set(_FIRST_WORDS)) != len(_FIRST_WORDS):
    _dupes = sorted({w for w in _FIRST_WORDS if _FIRST_WORDS.count(w) > 1})
    raise RuntimeError(f"invented employers share a leading word: {_dupes}")


class _Builder:
    """Accumulates cases with monotonic ids and a disjoint employer pool."""

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.cases: list[Case] = []
        self._n = 0
        self._pool = list(_POOL)
        self._taken = 0

    def employer(self) -> tuple[str, str]:
        """Hand out an employer no other axis has used.

        Disjointness is what keeps ground truth honest: two axes sharing an
        employer AND a role would be one application by the product's own rule,
        and scoring them as two would report a MERGE that is not a bug.
        """

        if self._taken >= len(self._pool):
            raise RuntimeError("invented-employer pool exhausted; add more names")
        pair = self._pool[self._taken]
        self._taken += 1
        return pair

    def add(
        self,
        *,
        axis: str,
        category: str,
        sender: str,
        subject: str,
        snippet: str = "",
        sender_name: str | None = None,
        identity: str | None,
        employer: str | None,
        role: str | None,
        conf: float = CONF_HIGH,
        note: str = "",
        expect_review: bool = False,
        day: int | None = None,
    ) -> None:
        self._n += 1
        mid = f"m{self._n:04d}"
        when = EPOCH + timedelta(days=self._n if day is None else day, minutes=self._n % 37)
        self.cases.append(
            Case(
                item=PipelineItem(
                    message_id=mid,
                    category=category,
                    sender_email=sender,
                    subject=subject,
                    sender_name=sender_name,
                    received_at=when,
                    confidence=conf,
                    thread_id=f"t{self._n:04d}",
                    snippet=snippet,
                ),
                axis=axis,
                identity=identity,
                employer=employer,
                role=role,
                note=note,
                expect_review=expect_review,
            )
        )


def _axis_employer_name_in_role(b: _Builder) -> None:
    """The reported bug's shape, and its neighbours.

    ``Thank you for your interest in <Employer> and our <Title> position`` —
    the leftmost ``in <article>`` anchor is unavailable, so the extractor
    anchors early and swallows the employer name into the role. Every case
    pairs a confirmation (which extracts cleanly) with a later message using
    the hostile phrasing, so a mismatch shows up as a SECOND CARD rather than
    a merely cosmetic title.
    """

    roles = [
        "Software Engineer I- User Systems",
        "Backend Engineer II",
        "Data Engineer, Platform",
        "Site Reliability Engineer",
        "Machine Learning Engineer, Ranking",
        "Product Analyst, Growth",
        "Cloud Security Engineer",
        "Mobile Engineer, iOS",
    ]
    for role in roles:
        display, token = b.employer()
        ident = f"{token}|{role}"
        b.add(
            axis="employer-name-in-role",
            category="applied",
            sender="no-reply@greenhouse-mail.io",
            sender_name=f"{display} Recruiting",
            subject=f"Thank you for applying to {display}",
            snippet=f"Thank you for your interest in the {role} position. We have received your application.",
            identity=ident, employer=token, role=role,
            note="clean anchor: 'in the <ROLE> position'",
        )
        b.add(
            axis="employer-name-in-role",
            category="rejection",
            sender="no-reply@greenhouse-mail.io",
            sender_name=f"{display} Recruiting",
            subject=f"Update on your application to {display}",
            snippet=(
                f"Thank you for your interest in {display} and our {role} position. "
                "After careful review we have decided to move forward with other candidates."
            ),
            identity=ident, employer=token, role=role,
            note="THE REPORTED BUG: employer name inside the role phrase",
        )

    # The camel-cased reserved name, mentioned TWICE in one clause.
    display, token = RESERVED_CAMEL
    ident = f"{token}|Platform Engineer"
    b.add(
        axis="employer-name-in-role",
        category="applied",
        sender="no-reply@ashbyhq.com",
        sender_name=f"{display} Talent",
        subject=f"Thanks for applying to {display}",
        snippet="Thank you for applying to our role: Platform Engineer.",
        identity=ident, employer=token, role="Platform Engineer",
        note="Ashby 'role:' anchor",
    )
    b.add(
        axis="employer-name-in-role",
        category="interview",
        sender="no-reply@ashbyhq.com",
        sender_name=f"{display} Talent",
        subject=f"{display} interview",
        snippet=(
            f"At {display} we were impressed by your interest in {display} "
            "and our Platform Engineer role. Let us find a time."
        ),
        identity=ident, employer=token, role="Platform Engineer",
        note="employer named twice in one clause",
    )

    # The employer name itself CONTAINS a role word ("Systems").
    display, token = RESERVED_ROLEWORD
    ident = f"{token}|Embedded Engineer"
    for cat, snip in (
        ("applied", "Thank you for your interest in the Embedded Engineer position."),
        ("rejection",
         f"Thank you for your interest in {display} and our Embedded Engineer position. "
         "We will not be moving forward."),
    ):
        b.add(
            axis="employer-name-in-role",
            category=cat,
            sender="no-reply@lever.co",
            sender_name=f"{display} via Lever",
            subject=f"Your application to {display}",
            snippet=snip,
            identity=ident, employer=token, role="Embedded Engineer",
            note="employer name contains a role word",
        )


def _axis_multiple_keyword_occurrences(b: _Builder) -> None:
    """``position`` / ``role`` / ``opening`` several times in one body.

    A lazy quantifier stretching to the FIRST keyword and a greedy one to the
    LAST give different roles; whichever the extractor picks must at least be
    STABLE across the confirmation and the follow-up, or one application
    becomes two.
    """

    display, token = b.employer()
    ident = f"{token}|Data Scientist"
    b.add(
        axis="multi-keyword", category="applied",
        sender="no-reply@greenhouse-mail.io", sender_name=display,
        subject=f"Thank you for applying to {display}",
        snippet="Thank you for your application for the Data Scientist position.",
        identity=ident, employer=token, role="Data Scientist",
    )
    b.add(
        axis="multi-keyword", category="assessment",
        sender="no-reply@greenhouse-mail.io", sender_name=display,
        subject=f"Next step for your {display} application",
        snippet=(
            "We reviewed your application for the Data Scientist position. "
            "This position is a hybrid role, and the opening remains open. "
            "Please complete the assessment for the Data Scientist role."
        ),
        identity=ident, employer=token, role="Data Scientist",
        note="'position' x2, 'role' x2, 'opening' x1 in one body",
    )

    display, token = b.employer()
    ident = f"{token}|Security Engineer"
    b.add(
        axis="multi-keyword", category="applied",
        sender="no-reply@ashbyhq.com", sender_name=f"{display} Hiring",
        subject=f"Thanks for applying to {display}",
        snippet="Thank you for applying to our role: Security Engineer.",
        identity=ident, employer=token, role="Security Engineer",
    )
    b.add(
        axis="multi-keyword", category="rejection",
        sender="no-reply@ashbyhq.com", sender_name=f"{display} Hiring",
        subject=f"Your {display} application",
        snippet=(
            "We had many strong applicants for the Security Engineer position. "
            "Although this role is now closed, we encourage you to apply to another "
            "opening when a new position opens."
        ),
        identity=ident, employer=token, role="Security Engineer",
        note="three trailing keywords after the real title",
    )

    # The role word appears BEFORE the title as well as after it.
    display, token = b.employer()
    ident = f"{token}|Compiler Engineer"
    b.add(
        axis="multi-keyword", category="applied",
        sender="no-reply@lever.co", sender_name=f"{display} via Lever",
        subject=f"Your application to {display}",
        snippet="Thank you for your interest in the Compiler Engineer position.",
        identity=ident, employer=token, role="Compiler Engineer",
    )
    b.add(
        axis="multi-keyword", category="interview",
        sender="no-reply@lever.co", sender_name=f"{display} via Lever",
        subject=f"{display} next steps",
        snippet=(
            "This role has been popular. Regarding the position you applied to, "
            "the Compiler Engineer position, we would like to speak with you."
        ),
        identity=ident, employer=token, role="Compiler Engineer",
        note="a keyword precedes the real title",
    )


def _axis_no_role_anywhere(b: _Builder) -> None:
    """Subject and body both silent about the role.

    Correct behaviour depends on context and the corpus expresses both:

    * at an employer with exactly ONE application, the mail joins it;
    * at an employer with SEVERAL, the mail is unplaceable and belongs in the
      review queue — guessing would settle the wrong application terminally.
    """

    # Sole application at this employer: role-less mail must JOIN it.
    for _ in range(2):
        display, token = b.employer()
        ident = f"{token}|__norole__"
        for cat, subj, snip in (
            ("applied", f"Thanks for applying to {display}",
             "We have received your application. Our team will be in touch."),
            ("applied", f"{display} application received",
             "Thanks for your interest. We review every application carefully."),
            ("rejection", f"An update from {display}",
             "We have decided not to move forward at this time. We wish you the best."),
        ):
            b.add(
                axis="no-role-anywhere", category=cat,
                sender="no-reply@ashbyhq.com", sender_name=f"{display} Hiring Team",
                subject=subj, snippet=snip,
                identity=ident, employer=token, role=None,
                note="employer names no role in ANY of its mail — one honest row",
            )

    # Employer with two named applications, then role-less mail: REVIEW.
    display, token = b.employer()
    for role in ("Frontend Engineer", "Backend Engineer"):
        b.add(
            axis="no-role-anywhere", category="applied",
            sender="no-reply@lever.co", sender_name=f"{display} via Lever",
            subject=f"Your application to {display}",
            snippet=f"Thank you for your interest in the {role} position.",
            identity=f"{token}|{role}", employer=token, role=role,
        )
    b.add(
        axis="no-role-anywhere", category="rejection",
        sender="no-reply@lever.co", sender_name=f"{display} via Lever",
        subject=f"Update from {display}",
        snippet="Thank you for your time. We have decided to move forward with other candidates.",
        identity=None, employer=token, role=None, expect_review=True,
        note="role-less at a 2-application employer: MUST go to review, not guess",
    )


def _axis_no_employer(b: _Builder) -> None:
    """A bare ATS relay whose display name names nobody.

    The pinned characterisation test says these resolve to None rather than
    minting a "Joinhandshake" row. These pin it harder, across more relays.
    """

    for sender, name, subj in (
        ("alerts@mail.joinhandshake.com", "Handshake", "New jobs for you"),
        ("alerts@mail.joinhandshake.com", "Handshake", "Your weekly job matches"),
        ("no-reply@myworkday.com", None, "Application status update"),
        ("no-reply@greenhouse-mail.io", None, "An update on your application"),
        ("notifications@ats.rippling.com", None, "Your application"),
        ("no-reply@lever.co", "Recruiting Team", "Thank you for applying"),
        ("careers@icims.com", "Careers", "Application received"),
        ("no-reply@pageuppeople.com", None, "Application update"),
        ("no-reply@smartrecruiters.com", "Talent Team", "Thanks for applying"),
        ("jobs@workable.com", "Hiring", "We received your application"),
    ):
        b.add(
            axis="no-employer", category="applied",
            sender=sender, sender_name=name, subject=subj,
            snippet="Thank you for your application. We will be in touch shortly.",
            identity=None, employer=None, role=None,
            note="relay names no employer: must mint nothing",
        )


def _axis_contradicting_signals(b: _Builder) -> None:
    """Subject says one thing, body says another, domain says a third."""

    # Subject names role A, body names role B. ONE application; the pipeline
    # must not let the disagreement mint two.
    display, token = b.employer()
    ident = f"{token}|Infrastructure Engineer"
    b.add(
        axis="contradicting", category="applied",
        sender="no-reply@greenhouse-mail.io", sender_name=display,
        subject=f"Your application for the Infrastructure Engineer role at {display}",
        snippet="Thank you for your interest in the Infrastructure Engineer position.",
        identity=ident, employer=token, role="Infrastructure Engineer",
    )
    b.add(
        axis="contradicting", category="interview",
        sender="no-reply@greenhouse-mail.io", sender_name=display,
        subject=f"Your application for the Infrastructure Engineer role at {display}",
        snippet="Great news about your application for the Cloud Infrastructure Engineer position.",
        identity=ident, employer=token, role="Infrastructure Engineer",
        note="subject role != body role, same application",
    )

    # Sender domain implies a relay, body/display name the employer.
    display, token = b.employer()
    b.add(
        axis="contradicting", category="applied",
        sender="no-reply@ats.rippling.com", sender_name=display,
        subject=f"Thank you for applying to {display}",
        snippet="Thank you for your interest in the Logistics Analyst position.",
        identity=f"{token}|Logistics Analyst", employer=token, role="Logistics Analyst",
        note="relay domain must not become the employer",
    )

    # A req id that disagrees with an IDENTICAL role: the id is the stronger
    # signal and must win, so these are TWO applications despite one title.
    display, token = b.employer()
    for req in ("R-40881", "R-40882"):
        b.add(
            axis="contradicting", category="applied",
            sender="no-reply@myworkday.com", sender_name=display,
            subject=f"Thank you for applying to {display}",
            snippet=(
                f"Thank you for your interest in the Mechanical Engineer position ({req}). "
                "We have received your application."
            ),
            identity=f"{token}|{req}", employer=token, role="Mechanical Engineer",
            note="same title, DIFFERENT req id: must stay two applications",
        )

    # Display name names employer X, body names employer Y.
    display, token = b.employer()
    other, _other_token = b.employer()
    b.add(
        axis="contradicting", category="applied",
        sender="no-reply@greenhouse-mail.io", sender_name=display,
        subject=f"Thank you for applying to {display}",
        snippet=(
            f"Thank you for your interest in the Field Engineer position. "
            f"This role was posted by our partner {other}."
        ),
        identity=f"{token}|Field Engineer", employer=token, role="Field Engineer",
        note="a second employer named in the body must not win",
    )


def _axis_employer_spelling_variants(b: _Builder) -> None:
    """One employer spelled five ways must resolve to ONE application."""

    display, token = RESERVED_CAMEL
    ident = f"{token}|Network Engineer"
    for spelling in ("SafeHarbor", "Safeharbor", "SAFEHARBOR", "SafeHarbor, Inc.", "Safe Harbor"):
        b.add(
            axis="employer-spelling", category="applied",
            sender="no-reply@greenhouse-mail.io", sender_name=spelling,
            subject=f"Thank you for applying to {spelling}",
            snippet="Thank you for your interest in the Network Engineer position.",
            identity=ident, employer=token, role="Network Engineer",
            note=f"spelling variant: {spelling!r}",
        )

    # A two-word employer, same treatment.
    display, token = b.employer()
    ident = f"{token}|Systems Analyst"
    base = display.split(" ")[0]
    for spelling in (display, display.upper(), display.lower(), f"{display}, Inc.", base):
        b.add(
            axis="employer-spelling", category="applied",
            sender="no-reply@lever.co", sender_name=spelling,
            subject=f"Your application to {spelling}",
            snippet="Thank you for your interest in the Systems Analyst position.",
            identity=ident, employer=token, role="Systems Analyst",
            note=f"spelling variant: {spelling!r}",
        )


def _axis_role_punctuation_variants(b: _Builder) -> None:
    """One role punctuated several ways must resolve to ONE application."""

    display, token = b.employer()
    ident = f"{token}|SoftwareEngineerIUserSystems"
    for variant in (
        "Software Engineer I- User Systems",
        "Software Engineer I, User Systems",
        "Software Engineer I (User Systems)",
        "Software Engineer I - User Systems",
        "Software Engineer I -- User Systems",
        "Software Engineer I / User Systems",
    ):
        b.add(
            axis="role-punctuation", category="applied",
            sender="no-reply@ashbyhq.com", sender_name=f"{display} Talent",
            subject=f"Thanks for applying to {display}",
            snippet=f"Thank you for applying to our role: {variant}.",
            identity=ident, employer=token, role=variant,
            note=f"punctuation variant: {variant!r}",
        )


def _axis_ats_relays(b: _Builder) -> None:
    """Each relay brand, with the employer named only in display name/subject.

    This is the applying-THROUGH-a-relay half of the distinction the pinned
    characterisation test protects. The applying-TO-the-relay half (a bare
    relay naming no employer) lives in :func:`_axis_no_employer`, and the two
    must not converge: here the employer is named and must win; there nothing
    is named and nothing may be minted.
    """

    relays = [
        ("no-reply@greenhouse-mail.io", "Greenhouse"),
        ("no-reply@us.greenhouse-mail.io", "Greenhouse"),
        ("no-reply@lever.co", "Lever"),
        ("no-reply@ashbyhq.com", "Ashby"),
        ("no-reply@myworkday.com", "Workday"),
        ("notifications@ats.rippling.com", "Rippling"),
        ("alerts@mail.joinhandshake.com", "Handshake"),
        ("no-reply@icims.com", "iCIMS"),
        ("no-reply@smartrecruiters.com", "SmartRecruiters"),
        ("no-reply@workable.com", "Workable"),
    ]
    roles = ["QA Engineer", "Solutions Architect", "Technical Writer",
             "Data Analyst", "Systems Engineer", "Support Engineer",
             "Research Engineer", "Kernel Engineer", "Growth Marketer",
             "Operations Associate"]

    for (sender, brand), role in zip(relays, roles):
        display, token = b.employer()
        ident = f"{token}|{role}"
        b.add(
            axis="ats-relay", category="applied",
            sender=sender, sender_name=f"{display} via {brand}",
            subject=f"Your application to {display}",
            snippet=f"Thank you for your interest in the {role} position at {display}.",
            identity=ident, employer=token, role=role,
            note=f"applied THROUGH {brand}: employer named, relay is transport",
        )
        b.add(
            axis="ats-relay", category="rejection",
            sender=sender, sender_name=f"{display} via {brand}",
            subject=f"Update on your application to {display}",
            snippet=(
                f"Thank you for your interest in {display} and our {role} position. "
                "We are moving forward with other candidates."
            ),
            identity=ident, employer=token, role=role,
            note=f"rejection via {brand}, hostile role phrasing",
        )


def _axis_sequences(b: _Builder) -> None:
    """The single most important sequence: one application, four stages.

    Confirmation → assessment → interview → rejection, as four separate mails
    over weeks. The card must MOVE, not multiply. This is what the user
    actually watched break.
    """

    specs = [
        ("Software Engineer I- User Systems", "no-reply@greenhouse-mail.io"),
        ("Backend Engineer II", "no-reply@lever.co"),
        ("Data Engineer, Platform", "no-reply@ashbyhq.com"),
        ("Site Reliability Engineer", "no-reply@myworkday.com"),
        ("Product Analyst, Growth", "notifications@ats.rippling.com"),
        ("Research Engineer, Inference", "no-reply@greenhouse-mail.io"),
        ("Staff Software Engineer", "no-reply@icims.com"),
    ]
    for role, sender in specs:
        display, token = b.employer()
        ident = f"{token}|{role}"
        stages = [
            ("applied", f"Thank you for applying to {display}",
             f"Thank you for your interest in the {role} position. We have received your application."),
            ("assessment", f"Next steps for your {display} application",
             f"Please complete the online assessment for the {role} position within 48 hours."),
            ("interview", f"Interview invitation from {display}",
             f"We would like to invite you to interview for the {role} position."),
            ("rejection", f"Update on your application to {display}",
             f"Thank you for your interest in {display} and our {role} position. "
             "After careful consideration we will not be moving forward."),
        ]
        for i, (cat, subj, snip) in enumerate(stages):
            b.add(
                axis="sequence", category=cat,
                sender=sender, sender_name=display,
                subject=subj, snippet=snip,
                identity=ident, employer=token, role=role,
                day=100 + i * 7,
                note=f"stage {i + 1}/4 — the card must MOVE, not multiply",
            )


def _axis_two_roles_one_employer(b: _Builder) -> None:
    """Two genuinely different applications at one employer: exactly two cards.

    This is the MERGE detector. A fix that refuses roles more aggressively
    pushes errors here, where they silently destroy a record the user cannot
    get back.
    """

    pairs = [
        ("Frontend Engineer", "Backend Engineer"),
        ("Data Engineer", "Data Scientist"),
        ("Research Engineer", "Research Scientist"),
        ("Operations Analyst", "Operations Manager"),
        ("Hardware Engineer", "Firmware Engineer"),
        # near-identical titles differing by one level token
        ("Software Engineer I", "Software Engineer II"),
        ("Analyst, Pricing", "Analyst, Risk"),
        ("Product Manager", "Product Designer"),
    ]
    for role_a, role_b in pairs:
        display, token = b.employer()
        for role in (role_a, role_b):
            ident = f"{token}|{role}"
            b.add(
                axis="two-roles-one-employer", category="applied",
                sender="no-reply@greenhouse-mail.io", sender_name=display,
                subject=f"Thank you for applying to {display}",
                snippet=f"Thank you for your interest in the {role} position.",
                identity=ident, employer=token, role=role,
                note="two distinct applications at one employer",
            )
            b.add(
                axis="two-roles-one-employer", category="interview",
                sender="no-reply@greenhouse-mail.io", sender_name=display,
                subject=f"Interview for your {display} application",
                snippet=f"We would like to invite you to interview for the {role} position.",
                identity=ident, employer=token, role=role,
                note="follow-up must land on its OWN card",
            )


def _axis_non_job_mail(b: _Builder) -> None:
    """Mail that must never mint an application.

    NOTE ON WHAT THIS MEASURES — read before quoting it as a passing gate.
    These carry ``category='other'`` or a sub-gate confidence, which is how the
    real classifier labels them, but it also means ``_qualifies_for_hard_row``
    excludes them BY CONSTRUCTION. So "non-job mail does not mint a card"
    cannot fail here. This axis pins the GATE's behaviour, not the
    classifier's; measuring the classifier is a different instrument
    (``tests/test_scan_classify.py``, ``tests/test_rules_classifier_*.py``).
    """

    noise = [
        ("newsletter@aetherloom.example", "Aetherloom Weekly: five things we shipped",
         "Read this week's product notes."),
        ("marketing@calderra.example", "Calderra is hiring across the board",
         "See our open roles and refer a friend."),
        ("events@halcyon-grid.example", "You are invited: Halcyon Grid tech talk",
         "Join us Thursday for a talk on distributed storage."),
        ("digest@orrery-data.example", "Your weekly job digest",
         "12 new roles matching your profile."),
        ("calendar-notification@mail.example", "Invitation: Coffee chat",
         "This is a calendar invitation."),
        ("no-reply@kestrel-dynamics.example", "Kestrel Dynamics product update",
         "New features are now available."),
        ("billing@slateforge.example", "Your receipt", "Thanks for your payment."),
        ("survey@quillhaven.example", "How did we do?", "Take our two-minute survey."),
    ]
    for sender, subj, snip in noise:
        b.add(
            axis="non-job-mail", category="other",
            sender=sender, sender_name=None, subject=subj, snippet=snip,
            identity=None, employer=None, role=None,
            note="noise: must mint nothing (excluded by the gate, see docstring)",
        )

    # Recruiter COLD APPROACHES — a lifecycle-ish category but below the
    # auto-file gate, so they belong in review rather than on the board.
    for _ in range(3):
        display, token = b.employer()
        b.add(
            axis="non-job-mail", category="interview",
            sender=f"recruiter@{token.replace(' ', '')}.example",
            sender_name=f"Talent at {display}",
            subject=f"Opportunity at {display}",
            snippet="I came across your profile and thought you might be a fit for a role on our team.",
            identity=None, employer=None, role=None,
            conf=CONF_LOW, expect_review=True,
            note="cold approach below the gate: review, never a card",
        )


def _axis_hostile_text(b: _Builder) -> None:
    """Entities, look-alikes, very long bodies, quoted chains, empty snippets."""

    # HTML entities in the role: must compare equal to the unescaped spelling.
    display, token = RESERVED_AMPERSAND
    ident = f"{token}|Analytics & Reporting Lead"
    b.add(
        axis="hostile-text", category="applied",
        sender="no-reply@greenhouse-mail.io", sender_name=display,
        subject=f"Thank you for applying to {display}",
        snippet="Thank you for your interest in the Analytics &amp; Reporting Lead position.",
        identity=ident, employer=token, role="Analytics & Reporting Lead",
        note="&amp; in the role",
    )
    b.add(
        axis="hostile-text", category="rejection",
        sender="no-reply@greenhouse-mail.io", sender_name=display,
        subject=f"Update from {display}",
        snippet="We&#39;ve reviewed your application for the Analytics & Reporting Lead position.",
        identity=ident, employer=token, role="Analytics & Reporting Lead",
        note="&#39; apostrophe plus the unescaped & — same application",
    )

    # A very long body: the real title sits past the pattern's 90-char bound.
    display, token = b.employer()
    ident = f"{token}|Distributed Systems Engineer"
    b.add(
        axis="hostile-text", category="applied",
        sender="no-reply@lever.co", sender_name=f"{display} via Lever",
        subject=f"Your application to {display}",
        snippet="Thank you for your interest in the Distributed Systems Engineer position.",
        identity=ident, employer=token, role="Distributed Systems Engineer",
    )
    b.add(
        axis="hostile-text", category="rejection",
        sender="no-reply@lever.co", sender_name=f"{display} via Lever",
        subject=f"Update from {display}",
        snippet=(
            "We want to begin by thanking you sincerely for the considerable time and "
            "genuine care you invested throughout every stage of our hiring process, "
            "which we know is a significant commitment, and for your interest in the "
            "Distributed Systems Engineer position."
        ),
        identity=ident, employer=token, role="Distributed Systems Engineer",
        note="real title past the 90-char capture bound",
    )

    # Empty snippet, everything in the subject; then a quoted reply chain.
    display, token = b.employer()
    ident = f"{token}|Kernel Engineer"
    b.add(
        axis="hostile-text", category="applied",
        sender="no-reply@ashbyhq.com", sender_name=display,
        subject=f"Your application for the Kernel Engineer role at {display}",
        snippet="",
        identity=ident, employer=token, role="Kernel Engineer",
        note="empty snippet, role only in the subject",
    )
    b.add(
        axis="hostile-text", category="rejection",
        sender="no-reply@ashbyhq.com", sender_name=display,
        subject=f"Re: Your application for the Kernel Engineer role at {display}",
        snippet=(
            "> On Tuesday you wrote:\n> Thank you for your interest in the Kernel Engineer position.\n"
            "Unfortunately we are not moving forward."
        ),
        identity=ident, employer=token, role="Kernel Engineer",
        note="body is a quoted reply chain",
    )

    # Unicode look-alikes / stray whitespace in the employer name.
    display, token = b.employer()
    ident = f"{token}|Platform Reliability Engineer"
    for name in (display, f"{display} ", f"{display}–", f"{display} "):
        b.add(
            axis="hostile-text", category="applied",
            sender="no-reply@greenhouse-mail.io", sender_name=name,
            subject=f"Thank you for applying to {name}",
            snippet="Thank you for your interest in the Platform Reliability Engineer position.",
            identity=ident, employer=token, role="Platform Reliability Engineer",
            note=f"unicode look-alike in employer name: {name!r}",
        )

    # A very long role title, and the same application with it truncated.
    display, token = b.employer()
    long_role = "Senior Staff Software Engineer, Distributed Storage and Replication"
    ident = f"{token}|{long_role}"
    b.add(
        axis="hostile-text", category="applied",
        sender="no-reply@ashbyhq.com", sender_name=display,
        subject=f"Thanks for applying to {display}",
        snippet=f"Thank you for applying to our role: {long_role}.",
        identity=ident, employer=token, role=long_role,
        note="very long title",
    )
    b.add(
        axis="hostile-text", category="interview",
        sender="no-reply@ashbyhq.com", sender_name=display,
        subject=f"{display} interview",
        snippet=f"We would like to interview you for the {long_role} position.",
        identity=ident, employer=token, role=long_role,
        note="same long title via a different anchor",
    )


def _axis_req_id_identity(b: _Builder) -> None:
    """Requisition ids: the strongest identity signal, and its failure shapes."""

    # Same req id, different titles: ONE application.
    display, token = b.employer()
    ident = f"{token}|JR0093214"
    b.add(
        axis="req-id", category="applied",
        sender="no-reply@myworkday.com", sender_name=display,
        subject=f"Thank you for applying to {display}",
        snippet="Thank you for your interest in the Robotics Software Engineer position (Job ID: JR0093214).",
        identity=ident, employer=token, role="Robotics Software Engineer",
    )
    b.add(
        axis="req-id", category="interview",
        sender="no-reply@myworkday.com", sender_name=display,
        subject=f"Interview for JR0093214 at {display}",
        snippet="Regarding requisition JR0093214, we would like to schedule a conversation.",
        identity=ident, employer=token, role="Robotics Software Engineer",
        note="same req id, no title: must join, not mint",
    )

    # A year / salary must NOT be read as a req id and split the card.
    display, token = b.employer()
    ident = f"{token}|Staff Engineer"
    b.add(
        axis="req-id", category="applied",
        sender="no-reply@greenhouse-mail.io", sender_name=display,
        subject=f"Thank you for applying to {display}",
        snippet="Thank you for your interest in the Staff Engineer position. Start date 2027.",
        identity=ident, employer=token, role="Staff Engineer",
    )
    b.add(
        axis="req-id", category="rejection",
        sender="no-reply@greenhouse-mail.io", sender_name=display,
        subject=f"Update from {display}",
        snippet="Thank you for your interest in the Staff Engineer position. The range was 180000 to 220000.",
        identity=ident, employer=token, role="Staff Engineer",
        note="bare numbers must not become a req id and split the card",
    )

    # Req id in the SUBJECT on one mail and the BODY on the next.
    display, token = b.employer()
    ident = f"{token}|R-77120"
    b.add(
        axis="req-id", category="applied",
        sender="no-reply@myworkday.com", sender_name=display,
        subject=f"{display} — Requisition ID: R-77120",
        snippet="Thank you for your interest in the Test Engineer position.",
        identity=ident, employer=token, role="Test Engineer",
    )
    b.add(
        axis="req-id", category="rejection",
        sender="no-reply@myworkday.com", sender_name=display,
        subject=f"Update from {display}",
        snippet="Regarding req R-77120, we have filled the position.",
        identity=ident, employer=token, role="Test Engineer",
        note="req id moves from subject to body across two mails",
    )


_AXES = (
    _axis_employer_name_in_role,
    _axis_multiple_keyword_occurrences,
    _axis_no_role_anywhere,
    _axis_no_employer,
    _axis_contradicting_signals,
    _axis_employer_spelling_variants,
    _axis_role_punctuation_variants,
    _axis_ats_relays,
    _axis_sequences,
    _axis_two_roles_one_employer,
    _axis_non_job_mail,
    _axis_hostile_text,
    _axis_req_id_identity,
)


def generate(seed: int = 20260815) -> list[Case]:
    """Build the corpus. Deterministic: same seed, byte-identical output."""

    b = _Builder(seed)
    for axis in _AXES:
        axis(b)
    return b.cases


if __name__ == "__main__":  # pragma: no cover - human inspection aid
    cases = generate()
    print(f"{len(cases)} cases")
    by_axis: dict[str, int] = {}
    for c in cases:
        by_axis[c.axis] = by_axis.get(c.axis, 0) + 1
    for axis, n in sorted(by_axis.items()):
        print(f"  {axis:28s} {n:4d}")
