"""One rule for "is this board row this employer?", asserted on both sides.

WHY THIS FILE EXISTS. The filed-mail ledger asks the user which application a
correction is about, and it decides which rows to OFFER in TypeScript while the
backend decides which rows to ACCEPT in Python. Those are the same question, and
when the two answers diverged the product did the worst possible thing quietly:
the ledger found no candidates, asked nothing, and the backend — which did match
the employer — tie-broke the correction onto that employer's oldest live row.
Measured against the real endpoint before the fix:

    board  [(1 "Northwind Traders" applied), (2 "Northwind Traders" applied)]
    mail   no-reply@greenhouse.io, sender name "Northwind Hiring Team"
    ledger candidates 0  ->  asksWhichApplication false
    POST   {"category": "interview"}  ->  application_id 1, moved to interviewing

A board name LONGER than the name the mail uses is the ordinary case — the token
is built from the FIRST WORD of a display name — so that gap covered most real
ATS mail.

``apps/web/tests/fixtures/employer-token-match.json`` is the single table of
answers. This file runs it through :func:`pipeline.matches_company_token`;
``apps/web/tests/unit/reclassify-asks-which-application.test.mjs`` runs the same
rows through ``matchesEmployerToken``. Neither side can be "corrected" alone,
because there is only one answer to correct.

THE OTHER HALF OF THE AGREEMENT IS THE WIRE, and it lives where the fixtures
do: ``test_gmail_oauth_cloud.py`` asserts that ``employer_token`` reaches the
client on UNLINKED rows, because a rule both sides agree on is worth nothing if
the token never arrives. The previous attempt shipped ``company``, which is the
LINKED application's name and is therefore null on exactly the population the
question is asked about.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobtracker.cloud import pipeline

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TABLE = _REPO_ROOT / "apps" / "web" / "tests" / "fixtures" / "employer-token-match.json"


def _cases() -> list[dict[str, object]]:
    table = json.loads(_TABLE.read_text())
    assert table["rule"].startswith("normalize both sides"), (
        "the shared table changed which rule it describes; both implementations "
        "have to move with it"
    )
    cases = list(table["cases"])
    # A table with no negative rows would pass against a function that returns
    # True unconditionally, which is the shape of gate this repo keeps finding.
    assert any(case["matches"] is False for case in cases)
    assert any(case["matches"] is True for case in cases)
    return cases


@pytest.mark.parametrize(
    "case", _cases(), ids=lambda c: f"{c['company'] or '<blank>'}|{c['token'] or '<blank>'}"
)
def test_the_shared_table_is_what_matches_company_token_answers(case) -> None:
    assert pipeline.matches_company_token(str(case["company"]), str(case["token"])) is bool(
        case["matches"]
    ), case["why"]

