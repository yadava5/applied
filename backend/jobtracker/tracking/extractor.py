"""
Company and Position Extraction
================================

Extracts company names and job positions from email content.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

from jobtracker.classifier.rules import domain_matches

logger = logging.getLogger(__name__)

COMPANY_NAME_CANONICAL = {
    "fanduel": "FanDuel",
    "epm scientific": "EPM Scientific",
    "rbc": "RBC",
}

GENERIC_ATS_SENDER_NAMES = {
    "workday",
    "greenhouse",
    "lever",
    "linkedin",
    "job alerts",
    "jobs",
    "recruiting",
    "careers",
    "talent acquisition",
}


# =============================================================================
# Known Company Domains (expand as needed)
# =============================================================================

# Sender domain → Company name mapping.
# None = ATS platform, extract company from email content.
#
# Every key is a bare registrable domain, lower-case, no leading dot and no
# full hostnames — and the lookup below relies on that, because it matches with
# ``rules.domain_matches``: the sender's domain must BE the key or be a proper
# subdomain of it. It used to be ``domain.endswith(known_domain)``, which had no
# boundary at all, so ``evil-greenhouse.io`` read as Greenhouse and
# ``evil-google.com`` was attributed to Google at 0.95 confidence. That is the
# same defect class as CodeQL ``py/incomplete-url-substring-sanitization``
# (alert 50) and this one nothing flagged, because what it decides is not a URL:
# it decides WHICH EMPLOYER an application is filed under, and whether the mail
# is read as ATS relay traffic at all. A misfiled card is the reachable harm.
#
# ``myworkday.com`` is the one key that is a string suffix of another
# (``workday.com``) and it is listed FIRST, because the loop below breaks on the
# first hit. Under the anchored match the two are disjoint and the order no
# longer decides anything — but the order is load-bearing history, so leave it.
DOMAIN_TO_COMPANY: dict[str, str] = {
    # ATS Platforms (need body/subject parsing)
    "greenhouse-mail.io": None,
    "greenhouse.io": None,
    "lever.co": None,
    "ashbyhq.com": None,
    "myworkday.com": None,
    "workday.com": None,
    "smartrecruiters.com": None,
    "icims.com": None,
    "jobvite.com": None,
    "taleo.net": None,
    "brassring.com": None,
    "successfactors.com": None,
    "gem.com": None,  # Recruiting platform
    "beamery.com": None,
    "phenom.com": None,
    "avature.net": None,
    "cornerstoneondemand.com": None,
    "recruitee.com": None,
    "bamboohr.com": None,
    # LinkedIn - extract company from body
    "linkedin.com": None,
    # Direct company domains
    "spacex.com": "SpaceX",
    "google.com": "Google",
    "apple.com": "Apple",
    "microsoft.com": "Microsoft",
    "amazon.com": "Amazon",
    "meta.com": "Meta",
    "netflix.com": "Netflix",
    "nvidia.com": "NVIDIA",
    "tesla.com": "Tesla",
    "adobe.com": "Adobe",
    "salesforce.com": "Salesforce",
    "oracle.com": "Oracle",
    "ibm.com": "IBM",
    "intel.com": "Intel",
    "uber.com": "Uber",
    "lyft.com": "Lyft",
    "airbnb.com": "Airbnb",
    "stripe.com": "Stripe",
    "plaid.com": "Plaid",
    "coinbase.com": "Coinbase",
    "robinhood.com": "Robinhood",
    "doordash.com": "DoorDash",
    "instacart.com": "Instacart",
    "openai.com": "OpenAI",
    "anthropic.com": "Anthropic",
    "anduril.com": "Anduril Industries",
    "palantir.com": "Palantir",
    "snowflake.com": "Snowflake",
    "databricks.com": "Databricks",
    "datadog.com": "Datadog",
    "twilio.com": "Twilio",
    "cloudflare.com": "Cloudflare",
    "mongodb.com": "MongoDB",
    "elastic.co": "Elastic",
    "confluent.io": "Confluent",
    "hashicorp.com": "HashiCorp",
    "atlassian.com": "Atlassian",
    "gitlab.com": "GitLab",
    "github.com": "GitHub",
    "figma.com": "Figma",
    "canva.com": "Canva",
    "notion.so": "Notion",
    "asana.com": "Asana",
    "monday.com": "monday.com",
    "zoom.us": "Zoom",
    "slack.com": "Slack",
    "discord.com": "Discord",
    "reddit.com": "Reddit",
    "snap.com": "Snap Inc.",
    "tiktok.com": "TikTok",
    "bytedance.com": "ByteDance",
    "stubhub.com": "StubHub",
    "ticketmaster.com": "Ticketmaster",
    "yelp.com": "Yelp",
    "grubhub.com": "Grubhub",
    "postmates.com": "Postmates",
    "flexport.com": "Flexport",
    "rippling.com": "Rippling",
    "gusto.com": "Gusto",
    "deel.com": "Deel",
    "remote.com": "Remote",
    "turing.com": "Turing",
    "toptal.com": "Toptal",
}


# =============================================================================
# Company Extraction Patterns
# =============================================================================

# Patterns to extract company name from email body/subject
COMPANY_PATTERNS = [
    # "Thank you for applying to [Company]!" - with name after comma
    r"[Tt]hank(?:s| you) for (?:applying|your (?:application|interest))(?: to| in)\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:,\s*[A-Z][a-z]+[!.]|\s*[!.])",
    # "Thank you for applying to [Company]" - simpler version
    r"[Tt]hank(?:s| you) for (?:applying|your (?:application|interest))(?: to| in)\s+([A-Z][A-Za-z0-9\s&'-]+?)(?:\s+for\s+|\s+as\s+|\s*$)",
    # "Your application to [Company] has been received"
    r"[Yy]our (?:application|interest)(?: to| at| for| in)\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\s+has\s+|\s*[,!.])",
    # "application was sent to [Company]"
    r"application was sent to\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\s*[,!.]|\s*$)",
    # "Thank You from [Company]"
    r"[Tt]hank(?:s| you)\s+from\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\s*[,!.]|\s*$)",
    # "Your application to [Position] at [Company]"
    r"[Yy]our application to [A-Za-z0-9\s\-/()]+?\s+at\s+([A-Z][A-Za-z0-9\s&.,()'-]+?)(?:\s*[,!.]|\s*$)",
    # "Your application for [Position] at [Company]"
    r"[Yy]our application for [A-Za-z0-9\s\-/()]+?\s+at\s+([A-Z][A-Za-z0-9\s&.,()'-]+?)(?:\s*[,!.]|\s*$)",
    # "Your update from [Company]"
    r"[Yy]our update from\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\s*[,!.]|\s*$)",
    # "Application update from [Company]"
    r"[Aa]pplication update from\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\s*[,!.]|\s*$)",
    # "Update on your application at [Company]"
    r"[Uu]pdate on your application (?:at|with|from)\s+([A-Z][A-Za-z0-9\s&.,()'-]+?)(?:\s*[,!.]|\s*$)",
    # "for your application at [Company]"
    r"for your application (?:at|with)\s+([A-Z][A-Za-z0-9\s&.,()'-]+?)(?:\s*[,!.]|\s*$)",
    # Workday/ATS templates: "interest in working with [Company]"
    r"interest in working with\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\s+position(?:\s+of)?|\s+role(?:\s+of)?|<|\r|\n|[!.])",
    # ATS templates: "thank you for your interest in [Company]"
    r"thank(?:s| you) for your interest in\s+([A-Z][A-Za-z0-9\s&.,()'-]+?)(?:\s+position(?:\s+of)?|\s+role(?:\s+of)?|<|\r|\n|[!.,])",
    # ATS templates: "interest in joining us here at [Company]"
    r"interest in joining us(?: here)? at\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:<|\r|\n|[!.,])",
    # ATS templates: "A career at [Company] ..."
    r"a career at\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\s+(?:is|offers|means)|<|\r|\n|[!.,])",
    # ATS templates: "careers at [Company]"
    r"careers?\s+at\s+([A-Z][A-Za-z0-9\s&.,()'-]+?)(?:<|\r|\n|[!.,])",
    # ATS templates: "opportunities at [Company]"
    r"opportunities at\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:<|\r|\n|[!.,])",
    # Workday/ATS templates: "job openings at [Company] Careers"
    r"job openings at\s+([A-Z][A-Za-z0-9\s&.,'-]+?)\s+careers",
    # "[Company] - In response to your application" (subject line pattern)
    r"^([A-Z][A-Za-z0-9\s&.,'-]+?)\s*[-–—]\s*(?:[Ii]n response|[Rr]egarding|[Rr]e:)",
    # "We at [Company]"
    r"[Ww]e (?:at|here at)\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\s+(?:are|have|would|want))",
    # "The [Company] team" / "The [Company] Recruiting Team"
    r"[Tt]he\s+([A-Z][A-Za-z0-9\s&.,'-]+?)\s+(?:[Tt]eam|[Rr]ecruiting|[Hh]iring)",
    # "from [Company] Recruiting"
    r"[Ff]rom\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\s+[Rr]ecruiting|\s+[Hh]iring|\s+[Tt]eam)",
    # "at [Company] for the position" 
    r"at\s+([A-Z][A-Za-z0-9\s&.,'-]+?)\s+for\s+(?:the\s+)?(?:position|role)",
    # "[Company] has received your application"
    r"^([A-Z][A-Za-z0-9\s&.,'-]+?)\s+has\s+received\s+your",
]


# =============================================================================
# Position Extraction Patterns
# =============================================================================

POSITION_PATTERNS = [
    # Subject style: "Thank you for applying to [Company] - [Position]"
    r"[Tt]hank(?:s| you) for applying to\s+[A-Z][A-Za-z0-9\s&.,()'-]+?\s*[-:]\s*([A-Za-z0-9][A-Za-z0-9\s\-/(),&]+?)(?:\s*[,!.]|\s*$)",
    # "for applying to the [Position] role at [Company]"
    r"for applying to\s+(?:the |our )?([A-Za-z0-9\s\-/(),&]+?)\s+(?:position|role|opportunity)(?:\s+at\s+[A-Z][A-Za-z0-9\s&.,()'-]+?)?",
    # "for the [Position] position"
    r"for (?!applying\b)(?:the |our )?([A-Za-z0-9\s\-/(),&]+?)\s+(?:position|role|opportunity)",
    # "application to our [Position] role"
    r"application (?:for|to)\s+(?:the |our )?([A-Za-z0-9\s\-/(),&]+?)\s+(?:position|role|opportunity)",
    # "application for [Position]"
    r"application (?:for|to)(?: the)?\s+([A-Za-z0-9\s\-/(),&]+?)(?:\s+at\s+|\s+position|\s+role|\s*[,!.]|\s*$)",
    # "Your application to [Position] at [Company]"
    r"[Yy]our application to\s+([A-Za-z0-9\s\-/(),&]+?)\s+at\s+[A-Z]",
    # "Your application to [Position] at [Company] was sent/submitted/received/viewed"
    r"[Yy]our application to\s+([A-Za-z0-9\s\-/(),&]+?)\s+at\s+[A-Z][A-Za-z0-9\s&.,()'-]+?\s+(?:was|has been)\s+(?:sent|submitted|received|viewed)",
    # "application was sent to [Company] for [Position]"
    r"application was sent to\s+[A-Z][A-Za-z0-9\s&.,()'-]+?\s+for\s+(?:the\s+)?([A-Za-z0-9\s\-/(),&]+?)(?:\s+position|\s+role|\s*[,!.]|\s*$)",
    # LinkedIn one-line confirmation text:
    # "Your application was sent to [Company] [Position] [Company] [Location] View job:"
    r"your application was sent to\s+[A-Z][A-Za-z0-9\s&.,()'-]+?\s+([A-Za-z0-9][A-Za-z0-9\s\-/(),&]+?)\s+[A-Z][A-Za-z0-9\s&.,()'-]+?\s+(?:[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*(?:,\s*[A-Z]{2}|,\s*United States)|San Francisco Bay Area|Remote)\s+view job:",
    # LinkedIn plain-text block:
    # "Your application was sent to [Company]\n[Position]\n[Company]\n[Location]\nView job:"
    r"your application was sent to\s+[A-Z][A-Za-z0-9\s&.,()'-]+?\s*\n+\s*([^\n]{3,120}?)\s*\n+\s*[A-Z][A-Za-z0-9\s&.,()'-]+?\s*\n+\s*[^\n]{2,120}\s*\n+\s*view job:",
    # LinkedIn quoted-printable/plaintext variants where lines collapse into large spaces.
    r"your application was sent to\s+[A-Z][A-Za-z0-9\s&.,()'-]+?\s{2,}([A-Za-z0-9][A-Za-z0-9\s\-/(),&]+?)\s{2,}[A-Z][A-Za-z0-9\s&.,()'-]+?\s{2,}[A-Za-z][^\n]{0,120}?\s+view job:",
    # "we have received your application for the [Position] role"
    r"we (?:have|['’]ve) received your application for\s+(?:the\s+)?([A-Za-z0-9\s\-/(),&]+?)(?:\s+\(|\s+position|\s+role|\s*[,!.]|\s*$)",
    # "as a [Position]"
    r"as (?:a |an )([A-Za-z0-9\s\-/(),&]+?)(?:\s+at\s+|\s*[,!.]|\s*$)",
    # "[Position] at [Company]" in subject
    r"^([A-Za-z0-9\s\-/()]+?)\s+(?:at|@)\s+[A-Z]",
    # "In response to your application for [Position]"
    r"[Ii]n response to your application for\s+([A-Za-z0-9\s\-/()]+?)(?:\s*[,.]|\s*$)",
    # "your [Position] application"
    r"your\s+([A-Za-z0-9\s\-/()]+?)\s+application",
]


# =============================================================================
# Extraction Result
# =============================================================================


@dataclass
class ExtractionResult:
    """Result of company/position extraction."""

    company: Optional[str] = None
    position: Optional[str] = None
    company_confidence: float = 0.0
    position_confidence: float = 0.0
    extraction_method: str = "none"


# =============================================================================
# Company Extractor
# =============================================================================


class CompanyExtractor:
    """Extracts company names from emails."""

    def __init__(self):
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE | re.MULTILINE) for p in COMPANY_PATTERNS
        ]

    def extract(
        self,
        sender_email: Optional[str],
        subject: str,
        body: str,
        sender_name: Optional[str] = None,
    ) -> tuple[Optional[str], float, str]:
        """
        Extract company name from email.

        Returns:
            (company_name, confidence, method)
        """
        is_ats_email = False
        direct_company = None

        # Method 1: Check sender domain
        if sender_email:
            domain = self._extract_domain(sender_email)
            if domain:
                # Check direct mapping — anchored on a dot boundary, see the
                # note on DOMAIN_TO_COMPANY.
                for known_domain, company in DOMAIN_TO_COMPANY.items():
                    if domain_matches(domain, known_domain):
                        if company:  # Direct mapping exists
                            direct_company = company
                        else:
                            # ATS domain - must parse subject/body
                            is_ats_email = True
                        break

        # For ATS emails, always try to extract from content first
        if is_ats_email or direct_company is None:
            # Method 2: Parse subject line (highest priority for ATS)
            company = self._extract_from_text(subject)
            if company:
                cleaned = self._clean_company_name(company)
                if self._is_valid_company_name(cleaned):
                    return (cleaned, 0.9, "subject_pattern")

            # Method 3: Parse body
            company = self._extract_from_text(body)
            if company:
                cleaned = self._clean_company_name(company)
                if self._is_valid_company_name(cleaned):
                    return (cleaned, 0.75, "body_pattern")

            # Method 3b: ATS sender display name fallback
            if is_ats_email and sender_name:
                sender_company = self._extract_from_sender_name(sender_name)
                if sender_company:
                    return (sender_company, 0.72, "sender_name")

        # Use direct company mapping if found
        if direct_company:
            return (direct_company, 0.95, "domain_direct")

        # Method 4: Infer from domain (only for non-ATS, non-generic domains)
        if sender_email and not is_ats_email:
            domain = self._extract_domain(sender_email)
            if domain and not self._is_generic_domain(domain):
                company = self._domain_to_company_name(domain)
                if company:
                    return (company, 0.7, "domain_inferred")

        return (None, 0.0, "none")

    def _extract_domain(self, email: str) -> Optional[str]:
        """Extract domain from email address."""
        if "@" not in email:
            return None
        return email.split("@")[-1].lower()

    def _domain_to_company_name(self, domain: str) -> Optional[str]:
        """Convert domain to company name."""
        # Remove common subdomains
        parts = domain.split(".")
        if len(parts) >= 2:
            # e.g., "no-reply.company.com" -> "company"
            name = parts[-2] if parts[-2] not in ("co", "com", "io", "ai") else parts[-3] if len(parts) > 2 else parts[-2]
            # Capitalize
            return name.title()
        return None

    def _is_generic_domain(self, domain: str) -> bool:
        """Check if domain is a generic email provider."""
        generic = [
            "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
            "icloud.com", "protonmail.com", "mail.com", "aol.com",
        ]
        return domain in generic

    def _extract_from_text(self, text: str) -> Optional[str]:
        """Extract company name from text using patterns."""
        for pattern in self._compiled_patterns:
            match = pattern.search(text)
            if match:
                company = match.group(1).strip()
                if not (2 < len(company) < 100):
                    continue
                cleaned = self._clean_company_name(company)
                if self._is_valid_company_name(cleaned):
                    return cleaned
        return None

    def _extract_from_sender_name(self, sender_name: str) -> Optional[str]:
        """Extract company candidate from ATS sender display name."""
        cleaned = self._clean_company_name(sender_name or "")
        lowered = cleaned.lower().strip()
        if not lowered:
            return None
        if lowered in GENERIC_ATS_SENDER_NAMES:
            return None
        if any(
            token in lowered
            for token in ("workday", "greenhouse", "lever", "job alerts", "jobs")
        ):
            return None
        if self._is_valid_company_name(cleaned):
            return cleaned
        return None

    def _clean_company_name(self, name: str) -> str:
        """Clean up extracted company name."""
        # Remove obvious leading determiners
        name = re.sub(r"^(?:the|our)\s+", "", name, flags=re.IGNORECASE)
        # Remove leading context words from ATS templates
        name = re.sub(
            r"^(?:a career at|working with|work with|careers at|jobs at|joining us(?: here)? at)\s+",
            "",
            name,
            flags=re.IGNORECASE,
        )
        # Remove trailing punctuation
        name = re.sub(r"[,!.]+$", "", name)
        # Remove common suffixes
        name = re.sub(r"\s+(Inc\.?|LLC|Ltd\.?|Corp\.?|Corporation|Company)$", "", name, flags=re.IGNORECASE)
        # Remove career portal suffixes.
        name = re.sub(
            r"\s+(?:careers?|career site|jobs portal|portal)$",
            "",
            name,
            flags=re.IGNORECASE,
        )
        # Drop recruiting context parentheticals often appended in subject lines
        # (e.g. "(YC W25)") while preserving the core company name.
        name = re.sub(r"\s+\((?:yc|w\d+|s\d+|f\d+)[^)]*\)$", "", name, flags=re.IGNORECASE)
        # Remove extra whitespace
        name = " ".join(name.split())
        # Trim trailing conjunction artifacts from templated ATS copy.
        name = re.sub(r"\s+(?:and|&)\s*$", "", name, flags=re.IGNORECASE)
        cleaned = name.strip()
        return COMPANY_NAME_CANONICAL.get(cleaned.lower(), cleaned)

    def _is_valid_company_name(self, name: str) -> bool:
        """Reject obvious non-company phrase fragments."""
        if len(name) < 2 or len(name) > 80:
            return False

        lowered = name.lower()
        blocked_phrases = [
            "future as our",
            "as our",
            "your application",
            "your interest",
            "for your application",
            "position of",
            "hiring team",
            "recruiting team",
        ]
        if any(phrase in lowered for phrase in blocked_phrases):
            return False

        # Position-like fragments are often false positives from "application for ..."
        # templates and should not be treated as company names.
        if lowered.endswith((" role", " position", " opportunity")):
            return False

        blocked_tokens = {
            "future",
            "our",
            "role",
            "position",
            "application",
            "interest",
            "experience",
            "candidate",
            "candidacy",
            "team",
            "career",
            "careers",
            "job",
            "jobs",
            "opening",
            "openings",
        }
        tokens = [token for token in re.split(r"\s+", lowered) if token]
        if len(tokens) >= 2:
            blocked_count = sum(token in blocked_tokens for token in tokens)
            if blocked_count >= max(2, len(tokens) - 1):
                return False

        return True


# =============================================================================
# Position Extractor
# =============================================================================


class PositionExtractor:
    """Extracts job positions from emails."""

    def __init__(self):
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE | re.MULTILINE) for p in POSITION_PATTERNS
        ]

    def extract(
        self,
        subject: str,
        body: str,
        company_hint: Optional[str] = None,
    ) -> tuple[Optional[str], float, str]:
        """
        Extract position from email.

        Returns:
            (position, confidence, method)
        """
        # Method 0: LinkedIn "application sent" confirmation blocks can include
        # role text in-between repeated company names.
        linkedin_position = self._extract_from_linkedin_confirmation(
            body, company_hint
        )
        if linkedin_position and self._is_valid_position(linkedin_position):
            return (self._clean_position(linkedin_position), 0.8, "linkedin_sent_block")

        # Method 1: Parse subject line (highest confidence)
        position = self._extract_from_text(subject)
        if position and self._is_valid_position(position):
            return (self._clean_position(position), 0.9, "subject_pattern")

        # Method 2: Parse body
        position = self._extract_from_text(body)
        if position and self._is_valid_position(position):
            return (self._clean_position(position), 0.75, "body_pattern")

        return (None, 0.0, "none")

    def _extract_from_linkedin_confirmation(
        self,
        text: str,
        company_hint: Optional[str],
    ) -> Optional[str]:
        """Extract role from LinkedIn confirmation body using repeated company anchor."""
        if not text:
            return None

        lowered = text.lower()
        if "your application was sent to" not in lowered or "view job:" not in lowered:
            return None

        if not company_hint:
            return None

        company_pattern = self._company_hint_pattern(company_hint)
        pattern = re.compile(
            rf"your application was sent to\s+{company_pattern}\s+(.+?)\s+{company_pattern}\s+(?:.+?)\s+view job:",
            re.IGNORECASE | re.DOTALL,
        )

        match = pattern.search(text)
        if not match:
            return None

        candidate = " ".join(match.group(1).split()).strip(" -")
        return candidate or None

    def _company_hint_pattern(self, company_hint: str) -> str:
        """Build tolerant regex for matching company text with optional legal suffix."""
        escaped = re.escape(company_hint.strip())
        escaped = escaped.replace(r"\ ", r"\s+")
        return rf"{escaped}(?:\s+(?:Inc\.?|LLC|Ltd\.?|Corp\.?|Corporation|Company))?"

    def _extract_from_text(self, text: str) -> Optional[str]:
        """Extract position from text using patterns."""
        for pattern in self._compiled_patterns:
            match = pattern.search(text)
            if match:
                position = match.group(1).strip()
                if len(position) > 3 and len(position) < 100:
                    return position
        return None

    def _is_valid_position(self, position: str) -> bool:
        """Check if extracted text looks like a job position."""
        position_lower = position.lower()
        blocked_phrases = [
            "selection process",
            "hiring process",
            "move through",
            "work together",
            "your status as",
            "interested in joining",
            "our team as",
            "we appreciate",
        ]
        if any(phrase in position_lower for phrase in blocked_phrases):
            return False

        if len(position.split()) > 14:
            return False

        # Should contain at least one job-related keyword
        job_keywords = [
            "engineer", "developer", "manager", "analyst", "designer",
            "scientist", "architect", "lead", "director", "specialist",
            "consultant", "coordinator", "associate", "intern", "senior",
            "junior", "software", "data", "product", "marketing", "sales",
            "operations", "hr", "finance", "support", "qa", "devops",
            "program", "fellowship", "apprentice",
        ]
        return any(kw in position_lower for kw in job_keywords)

    def _clean_position(self, position: str) -> str:
        """Clean up extracted position."""
        # Handle noisy over-captures seen in templated confirmation emails.
        lower = position.lower()
        marker = " and for your application to "
        if marker in lower:
            start = lower.rfind(marker) + len(marker)
            position = position[start:]

        # Remove leading context phrases and determiners.
        position = re.sub(
            r"^(?:your\s+application\s+to\s+|your\s+interest\s+in\s+[A-Za-z0-9\s&.,'-]+\s+and\s+for\s+your\s+application\s+to\s+)",
            "",
            position,
            flags=re.IGNORECASE,
        )
        position = re.sub(
            r"^(?:for\s+)?applying\s+to\s+(?:the\s+|our\s+)?",
            "",
            position,
            flags=re.IGNORECASE,
        )
        position = re.sub(r"^(?:our|the|a|an)\s+", "", position, flags=re.IGNORECASE)
        # If capture includes a trailing company segment, trim it.
        position = re.sub(r"\s+at\s+[A-Z][A-Za-z0-9\s&.,'-]+$", "", position)
        # Remove extra whitespace
        position = " ".join(position.split())
        # Remove trailing punctuation
        position = re.sub(r"[,!.]+$", "", position)
        return position.strip()


# =============================================================================
# Singleton Instances
# =============================================================================

_company_extractor: Optional[CompanyExtractor] = None
_position_extractor: Optional[PositionExtractor] = None


def get_company_extractor() -> CompanyExtractor:
    """Get singleton CompanyExtractor instance."""
    global _company_extractor
    if _company_extractor is None:
        _company_extractor = CompanyExtractor()
    return _company_extractor


def get_position_extractor() -> PositionExtractor:
    """Get singleton PositionExtractor instance."""
    global _position_extractor
    if _position_extractor is None:
        _position_extractor = PositionExtractor()
    return _position_extractor


def extract_company_and_position(
    sender_email: Optional[str],
    subject: str,
    body: str,
    sender_name: Optional[str] = None,
) -> ExtractionResult:
    """
    Extract company and position from email.

    Args:
        sender_email: Sender email address
        subject: Email subject
        body: Email body text

    Returns:
        ExtractionResult with company, position, and confidences
    """
    company_extractor = get_company_extractor()
    position_extractor = get_position_extractor()

    company, company_conf, company_method = company_extractor.extract(
        sender_email, subject, body, sender_name
    )
    position, position_conf, position_method = position_extractor.extract(
        subject, body, company_hint=company
    )

    return ExtractionResult(
        company=company,
        position=position,
        company_confidence=company_conf,
        position_confidence=position_conf,
        extraction_method=f"{company_method}/{position_method}",
    )
