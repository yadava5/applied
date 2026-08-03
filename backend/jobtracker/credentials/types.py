"""Credential dataclasses shared by desktop and cloud backends.

These types are the on-the-wire contract between any credential
backend (macOS Keychain or Supabase Postgres) and its callers. They
MUST stay byte-compatible with the original ``jobtracker.credentials``
module (pre-split) so JSON blobs serialized against the old code can
still be read after the C4 split.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class GmailCredentials:
    """Gmail OAuth2 credentials."""

    access_token: str
    refresh_token: str
    token_expiry: datetime
    email: str
    scopes: list[str]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""

        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_expiry": self.token_expiry.isoformat(),
            "email": self.email,
            "scopes": self.scopes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GmailCredentials":
        """Create from dictionary (JSON deserialization)."""

        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            token_expiry=datetime.fromisoformat(data["token_expiry"]),
            email=data["email"],
            scopes=data.get("scopes", []),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, raw: str) -> "GmailCredentials":
        return cls.from_dict(json.loads(raw))

    def is_expired(self) -> bool:
        """Return True if the access token has expired (5-minute buffer)."""

        return datetime.now() >= (self.token_expiry - timedelta(minutes=5))


@dataclass
class ICloudCredentials:
    """iCloud Mail credentials (email + app-specific password)."""

    email: str
    app_password: str

    def to_dict(self) -> dict:
        return {"email": self.email, "app_password": self.app_password}

    @classmethod
    def from_dict(cls, data: dict) -> "ICloudCredentials":
        return cls(email=data["email"], app_password=data["app_password"])

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, raw: str) -> "ICloudCredentials":
        return cls.from_dict(json.loads(raw))
