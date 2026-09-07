"""The employer's own spelling of its name beats a title-cased domain label.

`_corporate_identity` already preferred the subject's spelling over the domain
when the two agree — that is what turns "Twitchjobs" into "Twitch". It agreed
by PREFIX in either direction, which covers a domain that ADDS to the brand and
misses the one that PRECEDES it. A SaaS company whose bare name was already
registered mails from ``make<brand>``, ``get<brand>``, ``join<brand>`` — and
title-casing that label printed a name the message itself never used.

Found on a real board: a card read a concatenated domain label while its own
confirmation subject spelled the company. All fixtures below are invented
(`docs/TEST_DATA_POLICY.md`); only the SHAPE is transcribed.

Two halves, and the second is the one that needed the corpus to get right:

* `_brand_head_agrees` — a closed list of marketing heads, never bare
  containment, with a four-character floor on the token.
* `_SUBJECT_NAMES_EMPLOYER_NOUN` — the noun form ("your application to X"),
  kept as a SEPARATE pattern that licenses only the head agreement. Folded into
  the verb pattern as an alternation it re-keyed 43 corpus employers who had
  nothing to do with this defect, because the prefix agreement that was already
  there began firing on subjects it had never seen. Tokens fell 9113 -> 9070.
  `test_one_employer_gets_one_spelling` caught it.
"""

from jobtracker.cloud import pipeline as p


def _display(sender: str, subject: str = "", sender_name: str | None = None):
    resolved = p.resolve_employer(sender, subject, sender_name)
    return None if resolved is None else resolved[1]


def _token(sender: str, subject: str = "", sender_name: str | None = None):
    resolved = p.resolve_employer(sender, subject, sender_name)
    return None if resolved is None else resolved[0]


# --- the defect ------------------------------------------------------------


def test_a_marketing_head_on_the_domain_does_not_become_the_company_name():
    """``make<brand>`` mails you; the subject says ``<brand>``. Print theirs."""

    assert (
        _display(
            "recruiting-no-reply@makealderbrook.test",
            "Thank you for your application to Alderbrook, Sam!",
            "Alderbrook's Recruiting Team",
        )
        == "Alderbrook"
    )


def test_the_token_moves_with_the_display():
    """Deliberate, and the module says why: a display of "Alderbrook" under a
    match key of "makealderbrook" is unfindable by its own token on the next
    sync, so the sync files a duplicate."""

    assert (
        _token(
            "recruiting-no-reply@makealderbrook.test",
            "Thank you for your application to Alderbrook, Sam!",
        )
        == "alderbrook"
    )


def test_every_head_in_the_closed_list_is_reachable():
    """A head nobody can reach is a line that cannot fail."""

    # An empty list would make the loop below vacuous and this test would pass
    # having graded nothing — the shape that has shipped here before.
    assert len(p._BRAND_HEADS) >= 4, "the head list emptied; the loop grades nothing"
    for head in p._BRAND_HEADS:
        sender = f"careers@{head}alderbrook.test"
        assert (
            _display(sender, "Thank you for your application to Alderbrook")
            == "Alderbrook"
        ), f"the {head!r} head does not agree"


# --- the guards, each of which must refuse ---------------------------------


def test_a_head_outside_the_closed_list_is_not_a_head():
    """The fence against bare containment. ``palace`` ends with ``ace`` and
    that must never be agreement."""

    assert (
        _display("no-reply@palacealderbrook.test", "Your application to Alderbrook")
        == "Palacealderbrook"
    )


def test_a_short_token_cannot_agree():
    """``my``, ``us`` and ``co`` are real company names, and at that length the
    residue of almost any domain agrees with almost any subject."""

    assert _display("no-reply@getcue.test", "Your application to Cue") == "Getcue"


def test_a_role_in_the_object_position_is_not_an_employer():
    """The same guard the relay half applies, now reachable on this branch."""

    assert (
        _display("no-reply@makealderbrook.test", "Your application to Data Engineer")
        == "Makealderbrook"
    )


def test_the_noun_form_does_not_license_for():
    """"application FOR Software Engineer" is the commonest subject in the
    corpus. Admitting ``for`` on the noun would capture the role as the
    company — the defect #882 removed from the relay half."""

    assert (
        _display("no-reply@makealderbrook.test", "Your application for Software Engineer")
        == "Makealderbrook"
    )


def test_a_company_merely_mentioned_is_not_the_sender():
    """The agreement test's original purpose, unchanged."""

    assert _display("no-reply@halberd.test", "Thanks for applying to Ironvale") == "Halberd"


# --- the regression the corpus caught --------------------------------------


def test_the_noun_form_licenses_only_the_head_agreement():
    """THE 43-EMPLOYER REGRESSION, pinned as a property rather than a count.

    A subject naming the employer in the noun form, from a domain that already
    agrees by PREFIX, must resolve exactly as it did before the noun form
    existed — by the domain, keeping its whole brand as the token. Letting the
    noun form reach the prefix agreement shortened
    ``alderbrookanalytics`` to ``alderbrook`` across the corpus.
    """

    sender = "talent@alderbrookanalytics.test"
    subject = "Update on your application to Alderbrook Analytics"
    assert _token(sender, subject, "Alderbrook Analytics Talent") == "alderbrookanalytics"


def test_the_verb_form_keeps_the_prefix_agreement_it_always_had():
    """The directional control for the test above: the same domain and the same
    employer under the VERB form still take the subject's spelling, so the test
    above is pinning the noun/verb split and not simply the prefix agreement
    being dead."""

    assert (
        _token("no-reply@alderbrookjobs.test", "Thanks for applying to Alderbrook")
        == "alderbrook"
    )


def test_the_two_patterns_do_not_overlap():
    """Written out because the split is the safety property: a subject the verb
    form matches must never fall through to the noun form, or `heads_only`
    would be set for a case that used to reach both agreements."""

    verb = "Thanks for applying to Alderbrook"
    assert p._SUBJECT_NAMES_EMPLOYER.search(verb) is not None
    assert p._SUBJECT_NAMES_EMPLOYER_NOUN.search(verb) is None

    noun = "Thank you for your application to Alderbrook"
    assert p._SUBJECT_NAMES_EMPLOYER.search(noun) is None
    assert p._SUBJECT_NAMES_EMPLOYER_NOUN.search(noun) is not None
