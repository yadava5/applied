"""ONE JOB, WRITTEN THE TWO WAYS AN ATS WRITES IT, IS ONE IDENTITY KEY (#636).

Two readers in ``jobtracker/cloud/pipeline.py`` can name a job title from an ATS
subject. :func:`_role_from_lead_segment` reads the leading segment of
Greenhouse's standard rejection, ``<Employer> Follow-Up for <Role> |
<Candidate>``. :func:`_role_from_trailing_segment` reads the shape where the
employer BRACKETS the subject and the title sits in the last segment,
``<Employer> | <Boilerplate> | <Role> - <Employer> (<Location>)``. One posting
reaches one mailbox in both shapes, days apart, and the board has to file them
onto one card.

The identity key is ``normalize_role_token(role)``, so the requirement is not
that the two readers return the same STRING. It is that they never mint two
different KEYS for one job — two keys is a second card for an application the
board already tracks, and the second card then captures half of that job's
future mail. Everything below compares through that accessor and never compares
strings, because the split is a token phenomenon: ``normalize_role_token``
deletes the brackets but KEEPS the bracketed word, so ``Backend Engineer
(Remote)`` and ``Backend Engineer`` are two tokens for what may be one job.

WHERE THE TITLES COME FROM
--------------------------
Real job post names, read on 2026-08-31 from public applicant-tracking board
APIs — nothing here was invented, and nothing here came out of a mailbox:

    https://boards-api.greenhouse.io/v1/boards/<token>/jobs      76 boards
    https://api.lever.co/v0/postings/<token>?mode=json           10 boards
    https://api.ashbyhq.com/posting-api/job-board/<token>        50 boards

13,046 post names, 12,127 of them distinct. These are PUBLIC POSTINGS: the same
bytes any visitor to the board sees, carrying no correspondence, no sender, no
thread and nothing about any applicant. That is why they may live in a public
repository when a subject line out of the owner's inbox may not — see
``docs/TEST_DATA_POLICY.md``.

The titles below are BYTE-EXACT. Not one required an alteration to embed: no
encoding fix, no normalisation, nothing stripped. Nine of them carry a leading
or trailing space exactly as the board published it (``' Account Executive,
Select, San Mateo'`` opens with one; ``'Technical Support Specialist '`` closes
with one), and ``'Senior Manager, Quality – Development Programs (R5315)'``
carries an EN DASH rather than the hyphen it looks like. Those are the reason
this module quotes rather than describes: a title that has been tidied is no
longer evidence about what an ATS writes.

Only the post name is real. The employer (``Northwind``) and the candidate field
are invented, as they are everywhere else in this suite.

WHAT THIS SAMPLE CANNOT SEE, stated rather than implied
-------------------------------------------------------
* SaaS-era vendors only. Greenhouse, Lever and Ashby publish an open board API;
  Workday, Taleo and iCIMS do not, and their title conventions are absent here.
  A defect that only their wording reaches is invisible to this file.
* POSTINGS, not delivered mail. A board publishes the title; the ATS then
  renders it into a subject line, and a template can truncate, re-case or
  re-punctuate on the way. This measures the reader against the published
  string, which is the input the reader is given but not always the input it
  gets.
* One snapshot, one day. Titles rotate; 2026-08-31 is what these are.
* The two located renderings are NOT independent measurements.
  ``_TRAILING_SEGMENT_PAREN`` strips the tail parenthetical unconditionally, so
  ``<Role> - Northwind (Remote)`` and ``<Role> - Northwind (San Francisco, CA)``
  reduce to the same segment as ``<Role> - Northwind``. They exercise the strip
  path, which is worth exercising, but the per-rendering counts below are three
  times one per-title measurement and must not be read as three.

WHAT WAS MEASURED
-----------------
Over the whole 13,046-title pool at the three location settings — 39,138
renderings::

    two different keys (a split):        0
    both readers resolve, one key:  23,604
    exactly one reader resolves:     4,947
    neither resolves:               10,587

The 153 titles below are a stratified sample of that pool, drawn by a seeded
script, deduplicated and sorted. THAT SCRIPT IS NOT COMMITTED: it reads a
13,046-title harvest that has no place in this repository, so the literal below
IS the artifact and the counts in this docstring are its audit trail rather than
a promise that a regeneration would reproduce it. 70 titles end in a
parenthetical (spread across all three vendors and across the content kinds the
pool actually contains — a team, discipline or product qualifier, a place, a
work arrangement, a language, an employment type, a cohort or date, a region and
a level), 83 do not, 8 carry a parenthetical that is NOT at the end, 59 carry a
spaced dash and 15 carry two or more commas. On the sample: 459 renderings, 0
splits, 348 resolving to at least one key.

WHICH OF THESE TESTS CAN FAIL, measured by mutation rather than argued
----------------------------------------------------------------------
The convergence test is the headline and it is the WEAKEST of the six, which is
worth saying out loud in the file rather than discovering later. All four
mutations below were run against this module; the counts are what pytest
printed.

* Delete ``if _TRAILING_SEGMENT_PAREN.search(role): return None`` from
  :func:`_role_from_trailing_segment` and convergence still passes with 0
  splits. In this harness the post name is FIXED, so both renderings carry the
  same parenthetical and the two readers agree on a title nobody would want.
  What reds is ``test_a_role_side_parenthetical_is_refused_by_the_trailing_reader``,
  at 52 of the 70 sampled paren-ending titles. The other 18 are refused by
  something else anyway — 7 name no title head noun, 5 hit the work-arrangement
  scan, 4 fail the post-head shape rule, 1 hits the lifecycle scan and 1 is not
  title-shaped — so the guard is not the only thing standing there. It is what
  stands there for a place, a product qualifier, a language or a cohort, which
  is most of what a board actually brackets.
* Replace that refusal with a STRIP — the alternative the reader's own docstring
  argues against — and convergence reds at 180 of 459 renderings, because the
  trailing reader then hands back ``AI Ops Engineer`` where the lead reader
  hands back ``AI Ops Engineer (People Team)``. The refusal test reds with it,
  at 60 of 70: a strip is not a refusal.
* Stub :func:`_role_from_trailing_segment` to ``None`` — a reader that has
  stopped reading — and the vacuity floor STILL PASSES, at 348 of 459. On this
  sample that reader resolves nothing the lead reader does not already resolve,
  so deleting it costs the count nothing. What reds is the directional control:
  0 of 83 non-parenthetical titles agree, and 0 of 70 de-parenthesised twins
  resolve. The refusal test passes there too, vacuously, which is exactly why
  the control exists.
* Stub :func:`_role_from_lead_segment` to ``None`` instead and the vacuity floor
  reds at 156 of 459, taking the agreement control with it. The twin test
  survives that one, which is what makes it the TRAILING reader's own control.

So four failure modes, four different tests, and no one of them covers the
others. The vacuity floor is what stops the lead reader going quiet; the twin
test is what stops the trailing one, because the floor cannot see that reader
die. Every floor is a measurement on THIS sample with a margin subtracted, and
each one names both numbers where it is declared.
"""

from __future__ import annotations

import re

from jobtracker.cloud.pipeline import (
    _role_from_lead_segment,
    _role_from_trailing_segment,
    normalize_role_token,
)

#: Invented, like every employer in this suite. The trailing reader only accepts
#: a dash-terminated title when what follows the dash echoes the employer the
#: LEADING segment named, so the same name has to appear in both places.
EMPLOYER = "Northwind"

#: ``None`` is the rendering with no location field at all. The other two are the
#: two shapes a board writes into it — a work arrangement and a place.
LOCATIONS: tuple[str | None, ...] = (None, "Remote", "San Francisco, CA")


def lead_subject(title: str, employer: str = EMPLOYER) -> str:
    """Greenhouse's standard rejection subject for ``title``."""

    return f"{employer} Follow-Up for {title} | Candidate Name"


def trailing_subject(title: str, location: str | None, employer: str = EMPLOYER) -> str:
    """The employer-bracketed acknowledgement subject for ``title``."""

    tail = f"{title} - {employer}"
    if location is not None:
        tail = f"{tail} ({location})"
    return f"{employer} | Application Received | {tail}"


#: A DELIBERATE COPY of the shape ``_TRAILING_SEGMENT_PAREN`` matches, not an
#: import of it. This regex decides which stratum a sampled title belongs to, and
#: a stratum defined by the product's own constant moves whenever that constant
#: moves — silently, taking the assertions in
#: :func:`test_the_committed_sample_still_has_both_strata` with it. The test owns
#: its own definition of "ends in a parenthetical" so that a widened product
#: regex reds here instead of quietly re-drawing the sample.
TAIL_PARENTHETICAL = re.compile(r"\([^()]*\)\s*$")

#: Job post names, byte-exact, from the boards named in the module docstring.
#: Sorted and deduplicated. This list is the artifact rather than a cache of one:
#: the script that drew it read a harvest that is not in this repository.
TITLES: list[str] = [
    " Account Executive, Select, San Mateo",
    "401(k) Consultant",
    "AI Architect - GTM Systems",
    "AI Ops Engineer (People Team)",
    "AI Support Engineer - Dublin (Weekend Shift)",
    "Account Associate - SF (Portuguese speaking)",
    "Account Director, Central US (Remote)",
    "Account Director, Enterprise (East)",
    "Account Director, Large Enterprise (FSI)",
    "Account Executive, Product Sales, Billing",
    "Account Manager - Enterprise",
    "Account Partner - R&D and Quality",
    "Assistant Manager, Ocean Operations (Gurugram)",
    "Associate General Counsel, Privacy & Compliance",
    "Associate Product Manager, New Grad (2027 Start)",
    "Associate Sales Engineer, SE Desk (French Bilingual)",
    "Associate Sourcing Specialist (R5490)",
    "Backend Engineer - Ingestion (Europe/UK timezone)",
    "Client Account Manager, Retail Enterprise Sales (Dutch Speaking)",
    "Cloud Software Consultant (Remote)",
    "Commercial Account Executive - Israel",
    "Compounding Pharmacy Technician - Boynton Beach, FL (Temp)",
    "Customer Success Manager, Mid Market, EMEA",
    "Data Analyst, Operations (IP & Legal Compliance)",
    "Data Scientist - Music Mission",
    "Data Scientist, Core Data -  PhD (2026)",
    "Delivery Solutions Architect - Public Sector",
    "Deployment Strategist - UK Government",
    "Derivatives Trader",
    "Director of Product, Growth/AI",
    "Director, Avionics Engineering, V-BAT",
    "Ecosystem Sales Manager, Carahsoft (Washington DC)",
    "Engagement Manager, Public Sector (Midwest)",
    "Enterprise Sales Executive (Benelux)",
    "Enterprise Solution Architect, Quote-to-Revenue (Paris)",
    "Finance and Equity Analyst - Rotational Program",
    "Forward Deployed Engineer (FDE) - Seattle",
    "Forward Deployed Engineer - Software Engineer - Singapore",
    "Forward Deployed Engineer, Agentic Platform (UK/Europe)",
    "Forward Deployed Software Engineer, Internship - France",
    "Fraud Operations Associate SDC",
    "Full-Stack Engineer, Core Services (Senior Level)",
    "Growth - Digital Marketing (Enterprise)",
    "Growth Marketing Manager Lead ",
    "Implementation Specialist - Caper (Contractor)",
    "Langfuse - DevRel Engineer, Events & Community (EMEA)",
    "Legal Operations Analyst II",
    "Machine Learning Engineering Manager - Ads Engagement Modeling ",
    "Managed Services Consultant - R&D (Korean Speaking)",
    "Manager, Mid Market (East)",
    "Manager, Product Management - Roundtripping (London, United Kingdom)",
    "Manager, Sales Development - French",
    "Manager, Solutions Consultants, France",
    "Master Class - Business Consultant - Life Sciences Commercial (France)",
    "Master Class - Business Consultant - Life Sciences Quality (United States)",
    "Member of Technical Staff, AI Agent Development Lead",
    "Payroll Operations Manager",
    "People Operations Specialist, Singapore (6 Month Contract)",
    "Performance Solutions Partner I",
    "Principal Product Manager - Ecosystems & Connectors",
    "Product Expert - Link Key People",
    "Product Manager - Strategic Partner Integrations",
    "Product Manager, Agent Harness & Modelling",
    "Product Manager, Identity & Access Management",
    "Product Marketing Manager - Figma Weave (Tel Aviv, Israel) ",
    "Program Lead, Suno Emerging Creator Program (Contract)",
    "Real Estate Strategic Planning Lead",
    "Regional Vice President, Enterprise, Growth",
    "Sales Development Representative (German fluency) ",
    "Sales Development Representative (Nordics) - Dublin",
    "Sales Development Representative - Barcelona (Hybrid)",
    "Sales Director, Majors (TOLA)",
    "Sanctions, Operations Associate(CDMX)",
    "Security Engineer, Incident Response",
    "Security engineer, detection and response",
    "Senior Android Engineer - Alarms",
    "Senior Associate, Strategic Finance (International)",
    "Senior Backend Engineer, Analytics Instrumentation (Golang)",
    "Senior Business Development Lead - Hivemind - Nordics",
    "Senior Construction Manager",
    "Senior Consultant (Remote - Denmark)",
    "Senior Consultant - Post-Implementation",
    "Senior Consultant - Software Implementation (Remote)",
    "Senior Counsel, Commercial (Robotics)",
    "Senior Director of Machine Learning (Experiences)",
    "Senior Engineer, Software Autonomy Applications (R4829)",
    "Senior Engineer, VBAT Software Test Automation (Hiring Multiple Levels)",
    "Senior Engineering Technician, Operations Support",
    "Senior Hardware Engineer - GPU & AI Infrastructure",
    "Senior Localisation Program Manager, Product (Fixed Term Contract)",
    "Senior Machine Learning Manager, Video Ranking ",
    "Senior Manager, Content & Product Marketing",
    "Senior Manager, Quality – Development Programs (R5315)",
    "Senior Manager, Safety AI",
    "Senior Production Engineer, Managed Cloud",
    "Senior SASE Specialist, Enterprise (West)",
    "Senior Sales Engineer - Majors (East)",
    "Senior Software Engineer - AI (EMEA)",
    "Senior Software Engineer - Performance Tuning - Elasticsearch",
    "Senior Software Engineer, AI Product Insights",
    "Senior Software Engineer, Analytics & Search (OLAP Platform)",
    "Senior Software Engineer, Core AI Infrastructure",
    "Senior Software Engineer, iOS, Monetization",
    "Senior Software Engineer- Agentic Platform & Integrations (Full Stack)",
    "Senior Staff Engineer, AMP",
    "Senior Staff Machine Learning Engineer, Feed Relevance",
    "Senior Threat Intelligence Engineer",
    "Senior Threat Investigator, Safety Investigations",
    "Senior/Commercial Strategy Consultant",
    "Senior/Staff Design Engineer, iOS",
    "Software Engineer - Infrastructure (Mid - Senior)",
    "Software Engineer - Privacy & Compliance",
    "Software Engineer - Product (New Grad)",
    "Software Engineer II (Mobile Developer - Android/Kotlin) - Mobile App Growth",
    "Software Engineer II (Networking) - Platform Infra ",
    "Software Engineer, AI Gateway",
    "Software Engineer, Agent (Dutch speaking)",
    "Software Engineer, Backend (Platform)",
    "Software Engineer, Distributed Systems",
    "Software Engineer, Distributed Systems & AI Agents (Senior Level)",
    "Software Engineer, New Grad (Dec 2026)",
    "Software Engineer, Platform (Runtime)",
    "Software Engineer, Production Engineering",
    "Songwriting Camp Manager",
    "Specialist Solutions Architect, Payments (Mandarin Speaking)",
    "Specialist Solutions Architect, Radar (Fraud/Risk)",
    "Sr, Product Manager II - Gantt View (Hybrid, Bangalore)",
    "Sr. Client Partner [12-Month Fixed Term] Beauty, Health and Household",
    "Sr. Client Partner, Grocery",
    "Sr. Forward Deployed Engineer (FDE) - Communications, Media, Entertainment & Games",
    "Sr. Forward Deployed Engineer (FDE) - Digital Native Business ",
    "Sr. Forward Deployed Engineer (FDE) - Retail",
    "Sr. Talent Acquisition Partner (Technical)",
    "Staff Engineer, Field Support - X-BAT Aircraft Systems (R5081)",
    "Staff Software Engineer - Frontend (NYC)",
    "Staff UX Researcher, Payments Growth (Mixed Methods)",
    "Staff User Researcher - Consumer",
    "Staff, Analytics Engineer, GTM Data Science & Analytics",
    "State Enterprise Account Executive - MD, PA",
    "Strategic Account Executive - Saudi Arabia",
    "Support Engineer (EMEA - Weekends)",
    "Team Lead, Strategic Sourcing (IT, SaaS, Hardware)",
    "Technical Program Manager, Finance Systems & Compliance",
    "Technical Support Specialist ",
    "Technician II, Facilities (5444)",
    "Technology Enablement Analyst",
    "Territory Account Executive (Based in Melbourne)",
    "Territory Account Executive , Retail - Charlottesville, VA",
    "Territory Account Executive , SMB - NW Houston, TX",
    "Territory Account Executive, Retail  - Carmel, IN",
    "Transit Ambassador",
    "Transit Manager",
    "Workday Business Systems Analyst, People Systems",
]

PAREN_ENDING: list[str] = [t for t in TITLES if TAIL_PARENTHETICAL.search(t.strip())]
NON_PAREN_ENDING: list[str] = [t for t in TITLES if not TAIL_PARENTHETICAL.search(t.strip())]

#: Measured on this sample: 348 of the 459 renderings resolve to at least one
#: key. Floored at 300 — a margin of 48, about 14% — so that a real recall change
#: in either reader is allowed to move the number while a reader that has gone
#: quiet cannot. Without this floor, test one passes perfectly for a pipeline
#: whose readers both return ``None`` for everything.
RESOLVED_RENDERING_FLOOR = 300

#: Measured: 52 of the 83 non-parenthetical titles resolve through the TRAILING
#: reader and agree with the lead reader's token. Floored at 40, a margin of 12.
TRAILING_AGREEMENT_FLOOR = 40

#: Measured: 61 of the 70 paren-ending titles resolve through the trailing reader
#: once the parenthetical is deleted from the title. Floored at 50, a margin of
#: 11. This is the only assertion here that reds when the TRAILING reader alone
#: goes quiet and the lead reader keeps working — see the module docstring.
DEPARENTHESISED_TWIN_FLOOR = 50

#: Measured: the committed sample holds 70 paren-ending titles and 83 without.
#: Floored at 60 and 70, margins of 10 and 13.
PAREN_STRATUM_FLOOR = 60
NON_PAREN_STRATUM_FLOOR = 70


def _describe(title: str, location: str | None, lead: str | None, trailing: str | None) -> str:
    return (
        f"  title={title!r}  location={location!r}\n"
        f"    lead     -> {lead!r}  token={normalize_role_token(lead)!r}\n"
        f"    trailing -> {trailing!r}  token={normalize_role_token(trailing)!r}"
    )


def test_one_job_written_two_ways_never_mints_two_keys() -> None:
    """The property: at most one identity key per job, never two different ones."""

    splits: list[str] = []
    for title in TITLES:
        lead = _role_from_lead_segment(lead_subject(title))
        for location in LOCATIONS:
            trailing = _role_from_trailing_segment(trailing_subject(title, location))
            keys = {normalize_role_token(role) for role in (lead, trailing) if role}
            keys.discard(None)
            if len(keys) > 1:
                splits.append(_describe(title, location, lead, trailing))

    assert not splits, (
        f"{len(splits)} of {len(TITLES) * len(LOCATIONS)} renderings mint TWO identity keys "
        f"for one job. Each one is a second card for an application the board already "
        f"tracks, which then captures half of that job's mail:\n"
        + "\n".join(splits[:20])
        + (f"\n  ...and {len(splits) - 20} more" if len(splits) > 20 else "")
    )


def test_the_sample_resolves_enough_to_mean_anything() -> None:
    """Vacuity floor. Convergence is free for a reader that answers ``None``."""

    resolved = 0
    for title in TITLES:
        lead = _role_from_lead_segment(lead_subject(title))
        for location in LOCATIONS:
            trailing = _role_from_trailing_segment(trailing_subject(title, location))
            keys = {normalize_role_token(role) for role in (lead, trailing) if role}
            keys.discard(None)
            if keys:
                resolved += 1

    assert resolved >= RESOLVED_RENDERING_FLOOR, (
        f"only {resolved} of {len(TITLES) * len(LOCATIONS)} renderings resolved to any "
        f"identity key at all (floor {RESOLVED_RENDERING_FLOOR}, measured 348 when this "
        f"sample was committed). Convergence is satisfied perfectly by two readers that "
        f"never resolve anything, so a drop here makes "
        f"test_one_job_written_two_ways_never_mints_two_keys meaningless rather than green."
    )


def test_a_role_side_parenthetical_is_refused_by_the_trailing_reader() -> None:
    """The guard the convergence rests on, asserted directly.

    ``<Role> (Remote) - <Employer>`` and ``<Role> - <Employer> (Remote)`` are one
    posting written two ways, and the tail-side strip only reaches the second. So
    a parenthetical on the ROLE side refuses outright — keeping it would hand
    back ``Software Engineer (Remote)`` where the other placement hands back
    ``Software Engineer``, and ``normalize_role_token`` keeps the bracketed word.
    """

    leaked: list[str] = []
    for title in PAREN_ENDING:
        subject = trailing_subject(title, None)
        role = _role_from_trailing_segment(subject)
        if role is not None:
            leaked.append(
                f"  title={title!r}\n"
                f"    subject={subject!r}\n"
                f"    role -> {role!r}  token={normalize_role_token(role)!r}"
            )

    assert not leaked, (
        f"{len(leaked)} of {len(PAREN_ENDING)} sampled titles ending in a parenthetical "
        f"resolved through the trailing reader. Each one mints a token the other placement "
        f"of the same parenthetical does not:\n"
        + "\n".join(leaked[:20])
        + (f"\n  ...and {len(leaked) - 20} more" if len(leaked) > 20 else "")
    )


def test_the_trailing_reader_resolves_titles_without_a_parenthetical() -> None:
    """Directional control. The refusal above is free if the reader is dead."""

    agreeing: list[str] = []
    for title in NON_PAREN_ENDING:
        lead = _role_from_lead_segment(lead_subject(title))
        trailing = _role_from_trailing_segment(trailing_subject(title, None))
        if lead and trailing and normalize_role_token(lead) == normalize_role_token(trailing):
            agreeing.append(title)

    assert len(agreeing) >= TRAILING_AGREEMENT_FLOOR, (
        f"only {len(agreeing)} of {len(NON_PAREN_ENDING)} non-parenthetical sampled titles "
        f"resolved through the TRAILING reader to the same token as the lead reader "
        f"(floor {TRAILING_AGREEMENT_FLOOR}, measured 52 when this sample was committed). "
        f"test_a_role_side_parenthetical_is_refused_by_the_trailing_reader passes trivially "
        f"when the trailing reader refuses everything; this is what says it does not."
    )


def test_deleting_the_parenthetical_flips_the_same_title_to_resolving() -> None:
    """The one-edit twin: same title, parenthetical removed, opposite outcome."""

    flipped: list[str] = []
    unchanged: list[str] = []
    for title in PAREN_ENDING:
        twin = TAIL_PARENTHETICAL.sub("", title.strip()).strip()
        role = _role_from_trailing_segment(trailing_subject(twin, None))
        (flipped if role is not None else unchanged).append(f"{title!r} -> {twin!r}")

    assert len(flipped) >= DEPARENTHESISED_TWIN_FLOOR, (
        f"only {len(flipped)} of {len(PAREN_ENDING)} sampled paren-ending titles began "
        f"resolving once the trailing parenthetical was deleted (floor "
        f"{DEPARENTHESISED_TWIN_FLOOR}, measured 61 when this sample was committed). The "
        f"parenthetical is supposed to be the whole difference for these; if removing it "
        f"changes nothing, the refusal asserted above is not the rule doing the work.\n"
        f"  did not flip: " + "\n                ".join(unchanged[:10])
    )


def test_the_committed_sample_still_has_both_strata() -> None:
    """Neither stratum may quietly empty out under a future edit."""

    assert len(PAREN_ENDING) >= PAREN_STRATUM_FLOOR, (
        f"the committed sample holds {len(PAREN_ENDING)} titles ending in a parenthetical "
        f"(floor {PAREN_STRATUM_FLOOR}, 70 as committed). "
        f"test_a_role_side_parenthetical_is_refused_by_the_trailing_reader is green over an "
        f"empty list."
    )
    assert len(NON_PAREN_ENDING) >= NON_PAREN_STRATUM_FLOOR, (
        f"the committed sample holds {len(NON_PAREN_ENDING)} titles that do not end in a "
        f"parenthetical (floor {NON_PAREN_STRATUM_FLOOR}, 83 as committed). Those are the "
        f"controls for the refusal, and without them nothing here is directional."
    )
    assert sorted(set(TITLES)) == TITLES, (
        "TITLES must stay sorted and deduplicated: the sampler emitted it that way, so a "
        "list out of that order has been hand-edited, and a duplicate silently double-weights "
        "one title in every count above."
    )
