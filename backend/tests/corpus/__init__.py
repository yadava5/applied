"""Adversarial mail corpus: a measurement instrument for application identity.

Two modules, deliberately separate:

* :mod:`generator` invents the mail. Every employer, role and body in it is
  fictional — the owner's real mailbox may not enter a committed fixture. The
  SHAPES are real (ATS relay domains, subject templates, the phrasings that
  break the role extractor); the names are not.
* :mod:`harness` drives the REAL pipeline over that mail and scores where
  identity resolution splits one application into two cards or merges two into
  one.
"""
