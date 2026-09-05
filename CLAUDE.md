# Applied

A job-application tracker that reads a mailbox and files what it finds. Python
backend (`backend/`), Next.js app (`apps/web/`), classifier and ML assets
(`ml/`). The repository is **public**.

## Read before you change these

| about to change | read first |
| --- | --- |
| `backend/jobtracker/classifier/rules.py` or a port of it | `docs/CLASSIFIER_RULES_GOVERNANCE.md` |
| a fixture, docstring or comment holding a sender address, employer, requisition number or role title | `docs/TEST_DATA_POLICY.md` |
| anything carrying a `DEC-nnn` marker | `docs/DECISIONS.md` |
| a model's path to production | `docs/ML_PROMOTION_POLICY.md` |
| what the corpus is allowed to claim | `docs/ML_CORPUS_INTEGRITY.md` |

`docs/DECISIONS.md` is the record of choices whose rejected alternative is
attractive and whose reason is invisible from the code. It says what was chosen
against, and for each entry whether anything actually enforces it. If you are
about to undo something and a `DEC-nnn` marker is in your diff, that entry is
addressed to you.

## Two standing rules, because both have been broken by accident

**This repository is public, and a comment is as published as a fixture.** No
real mailbox content — addresses, subjects, requisition numbers, message ids —
in fixtures, docstrings, comments, commit messages or issue bodies.
`scripts/check_test_data.py` catches addresses inside four scan roots and
nothing else; the rest is on the writer.

**A gate that has never been shown to fail has not been tested.** Every check
in this repository is expected to carry a demonstration that it reds — a
mutation, a fixture, a deleted line — and several have been found green from
birth and green forever. If you ship a gate, ship the proof it can fail.

## Verification

Backend tests run on Python 3.11 (`backend/.venv311`); 3.13 has no
testcontainers and the Postgres modules silently skip there, which is green.
The web app builds with pnpm. The three checks required on `main` are "README
numbers agree with the code", "Scan for secrets" and "Test data baseline agrees
with the tree" — note that the test suite itself is not among them.
