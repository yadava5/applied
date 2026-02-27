#!/usr/bin/env python3
"""Generate balanced, neutral, synthetic mock training data in JSONL format."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

LABELS = [
    "applied",
    "pending_application",
    "interview",
    "rejection",
    "offer",
    "assessment",
    "follow_up",
    "other",
]

COMPANIES = [
    "Northstar Systems",
    "Harbor Analytics",
    "Cedar Labs",
    "Summit Platform",
    "Orbit Dynamics",
    "Atlas Data",
    "Openfield Technologies",
    "Pioneer Cloud",
    "SignalForge",
    "Lighthouse Networks",
    "Bluepeak Software",
    "Vector Grid",
]

ROLES = [
    "Software Engineer",
    "Data Analyst",
    "Product Manager",
    "Backend Engineer",
    "Frontend Engineer",
    "Security Engineer",
    "Machine Learning Engineer",
    "Site Reliability Engineer",
    "QA Engineer",
    "Business Analyst",
    "Cloud Engineer",
    "Platform Engineer",
]

APPLIED_TEMPLATES = [
    ("Application received for {role}", "Thank you for applying to {company}. We received your application for the {role} role and will review it."),
    ("Thanks for applying to {company}", "Your application for {role} has been submitted successfully. Our team will share updates soon."),
    ("Submission confirmation: {role}", "We confirm receipt of your application for {role} at {company}."),
    ("We received your job application", "This message confirms your application for {role} at {company} was received."),
    ("Application complete", "Your application is complete and has been submitted for the {role} role at {company}."),
    ("Application status: submitted", "Your submission for the {role} position at {company} is now in review."),
]

PENDING_TEMPLATES = [
    ("Complete your application for {role}", "Your application for {role} at {company} is incomplete. Please finish required steps to proceed."),
    ("Action required for your application", "Additional information is needed before we can review your application for {role}."),
    ("Continue your application", "Please continue and submit your {role} application at {company}."),
    ("Application deadline approaching", "Please complete your remaining application steps for the {role} role before the deadline."),
    ("Missing information in your application", "We need additional details to continue your {role} application at {company}."),
    ("Finish required application steps", "To be considered for {role}, complete the pending application tasks."),
]

INTERVIEW_TEMPLATES = [
    ("Interview invitation: {role}", "We would like to schedule an interview for the {role} role at {company}. Please share availability."),
    ("Phone screen scheduling", "Please select a time for a phone screen with our hiring team for the {role} position."),
    ("Interview time selection", "Use this scheduling link to book your interview with {company}."),
    ("Phone screen availability", "Could you share your availability for a phone screen about the {role} role?"),
    ("Interview scheduling request", "Please pick an interview slot for the {role} position at {company}."),
    ("Next step: interview", "As a next step, we would like to arrange an interview with the hiring team."),
    ("Availability for call with hiring manager", "Please send your availability for a call with the hiring manager."),
    ("Meet our team", "We invite you to meet our team and discuss the {role} opportunity at {company}."),
]

REJECTION_TEMPLATES = [
    ("Update on your application", "After careful consideration, we are not moving forward with your application for {role} at {company}."),
    ("Application decision", "Thank you for your interest in {company}. We selected candidates with closer alignment for this role."),
    ("Role status update", "We regret to inform you that we will not proceed with your candidacy for {role}."),
    ("Not moving forward", "At this time, we are not moving forward with your candidacy for the {role} position."),
    ("Decision on candidacy", "We have made a decision on your candidacy and will not be proceeding further."),
    ("Position has been filled", "The {role} role at {company} has been filled, so we are closing your application."),
]

OFFER_TEMPLATES = [
    ("Offer for {role} at {company}", "We are pleased to extend an offer for the {role} position at {company}."),
    ("Offer letter attached", "Please review and sign your offer letter for the {role} role."),
    ("Compensation and start date", "Your compensation details and proposed start date are included in this offer package."),
    ("Compensation package details", "Your compensation package details for the {role} offer are attached."),
    ("Start date confirmation", "Please confirm the proposed start date for your offer at {company}."),
    ("Formal employment offer", "This email is your formal employment offer for the {role} position."),
]

ASSESSMENT_TEMPLATES = [
    ("Assessment invitation for {role}", "Please complete the technical assessment for the {role} role at {company}."),
    ("Coding challenge request", "As a next step, complete the coding exercise for your {role} application."),
    ("Skills test reminder", "Reminder: submit the assessment for the {role} role before the deadline."),
    ("Assessment follow-up", "Following up on the technical assessment we sent for the {role} position."),
    ("Online test window", "Your online assessment for {role} is now available for completion."),
    ("Take-home exercise", "Please submit the take-home exercise for your {role} application."),
]

FOLLOW_UP_TEMPLATES = [
    ("Following up on my application", "I am following up on the status of my application for {role} at {company}."),
    ("Checking in on interview process", "Could you share any updates regarding my interview process for {role}?"),
    ("Application status check", "I wanted to check in on next steps for my application with {company}."),
    ("Wanted to follow up on my candidacy", "I wanted to follow up on my candidacy for the {role} position."),
    ("Circling back on the role", "I am circling back on the {role} role and wanted to ask for an update."),
    ("Quick follow-up", "Quick follow-up to ask whether there are any updates on my application status."),
]

OTHER_TEMPLATES = [
    ("Security alert for your account", "A new sign-in was detected. If this was not you, reset your password."),
    ("Weekly newsletter", "Here are this week's product updates and general announcements."),
    ("Order confirmation", "Your order has been processed and is now being prepared for shipment."),
    ("Promotional offer", "Limited time offer: use this coupon to save on your next purchase."),
    ("Verification code", "Your one-time verification code is included for account access."),
    ("Daily digest", "Your daily digest is ready. Manage preferences or unsubscribe."),
]

NEUTRAL_APPENDIX = [
    "This is an automated message.",
    "Please reply to this email if you have questions.",
    "Thank you for your time.",
    "No action is needed unless noted above.",
    "Please keep this message for your records.",
]

TEMPLATES = {
    "applied": APPLIED_TEMPLATES,
    "pending_application": PENDING_TEMPLATES,
    "interview": INTERVIEW_TEMPLATES,
    "rejection": REJECTION_TEMPLATES,
    "offer": OFFER_TEMPLATES,
    "assessment": ASSESSMENT_TEMPLATES,
    "follow_up": FOLLOW_UP_TEMPLATES,
    "other": OTHER_TEMPLATES,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate balanced mock training data")
    parser.add_argument("--seed", type=int, default=20260226)
    parser.add_argument("--per-label", type=int, default=40)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data" / "external" / "mock_training_data.jsonl",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)

    rows: list[dict[str, str]] = []

    for label in LABELS:
        templates = TEMPLATES[label]
        for i in range(args.per_label):
            company = rng.choice(COMPANIES)
            role = rng.choice(ROLES)
            subject_template, body_template = rng.choice(templates)

            subject = subject_template.format(company=company, role=role)
            body_text = body_template.format(company=company, role=role)

            # Add neutral variation token to reduce near-duplicates.
            variant = f"Ref-{label[:3].upper()}-{i+1:03d}"
            body_text = f"{body_text} {rng.choice(NEUTRAL_APPENDIX)} {variant}."

            rows.append(
                {
                    "subject": subject,
                    "body_text": body_text,
                    "label": label,
                }
            )

    rng.shuffle(rows)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")

    print(f"generated_rows={len(rows)}")
    print(f"per_label={args.per_label}")
    print(f"seed={args.seed}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
