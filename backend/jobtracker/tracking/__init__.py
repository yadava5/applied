"""
Application Tracking Module
===========================

Automatically extracts company names, positions, and links emails to applications.
"""

from .extractor import (
    CompanyExtractor,
    PositionExtractor,
    extract_company_and_position,
    get_company_extractor,
    get_position_extractor,
)
from .linker import ApplicationLinker, get_application_linker

__all__ = [
    "CompanyExtractor",
    "PositionExtractor",
    "ApplicationLinker",
    "extract_company_and_position",
    "get_company_extractor",
    "get_position_extractor",
    "get_application_linker",
]
