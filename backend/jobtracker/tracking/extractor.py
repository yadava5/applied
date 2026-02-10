"""
Company and Position Extraction
================================

Extracts company names and job positions from email content.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Known Company Domains (expand as needed)
# =============================================================================

# Domain suffix → Company name mapping
# None = ATS platform, extract company from email content
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
    # "for the [Position] position"
    r"for (?:the |our )?([A-Za-z0-9\s\-/()]+?)\s+(?:position|role|opportunity)",
    # "application for [Position]"
    r"application (?:for|to)(?: the)?\s+([A-Za-z0-9\s\-/()]+?)(?:\s+at\s+|\s+position|\s+role|\s*[,!.]|\s*$)",
    # "as a [Position]"
    r"as (?:a |an )?([A-Za-z0-9\s\-/()]+?)(?:\s+at\s+|\s*[,!.]|\s*$)",
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
                # Check direct mapping
                for known_domain, company in DOMAIN_TO_COMPANY.items():
                    if domain.endswith(known_domain):
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
                if len(cleaned) > 2:  # Valid company name
                    return (cleaned, 0.9, "subject_pattern")

            # Method 3: Parse body
            company = self._extract_from_text(body)
            if company:
                cleaned = self._clean_company_name(company)
                if len(cleaned) > 2:
                    return (cleaned, 0.75, "body_pattern")

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
                if len(company) > 2 and len(company) < 100:
                    return company
        return None

    def _clean_company_name(self, name: str) -> str:
        """Clean up extracted company name."""
        # Remove trailing punctuation
        name = re.sub(r"[,!.]+$", "", name)
        # Remove common suffixes
        name = re.sub(r"\s+(Inc\.?|LLC|Ltd\.?|Corp\.?|Corporation|Company)$", "", name, flags=re.IGNORECASE)
        # Remove extra whitespace
        name = " ".join(name.split())
        return name.strip()


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
    ) -> tuple[Optional[str], float, str]:
        """
        Extract position from email.

        Returns:
            (position, confidence, method)
        """
        # Method 1: Parse subject line (highest confidence)
        position = self._extract_from_text(subject)
        if position and self._is_valid_position(position):
            return (self._clean_position(position), 0.9, "subject_pattern")

        # Method 2: Parse body
        position = self._extract_from_text(body)
        if position and self._is_valid_position(position):
            return (self._clean_position(position), 0.75, "body_pattern")

        return (None, 0.0, "none")

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
        # Should contain at least one job-related keyword
        job_keywords = [
            "engineer", "developer", "manager", "analyst", "designer",
            "scientist", "architect", "lead", "director", "specialist",
            "consultant", "coordinator", "associate", "intern", "senior",
            "junior", "software", "data", "product", "marketing", "sales",
            "operations", "hr", "finance", "support", "qa", "devops",
        ]
        position_lower = position.lower()
        return any(kw in position_lower for kw in job_keywords)

    def _clean_position(self, position: str) -> str:
        """Clean up extracted position."""
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
        sender_email, subject, body
    )
    position, position_conf, position_method = position_extractor.extract(
        subject, body
    )

    return ExtractionResult(
        company=company,
        position=position,
        company_confidence=company_conf,
        position_confidence=position_conf,
        extraction_method=f"{company_method}/{position_method}",
    )
