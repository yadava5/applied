"""Bounds that more than one layer has to agree about.

WHY THIS MODULE EXISTS. ``_MAX_COMPANY_LEN`` was declared in
``cloud/pipeline.py`` and imported from there by ``cloud/applications.py``'s
request models. That was fine while every enforcer was application code. It
stops being fine the moment the DATABASE has to know the same number: making
``database/models.py`` import the classifier pipeline to learn a length would
drag five thousand lines of regex into the ORM's import graph to fetch an
integer.

So the number moves to a leaf that both can import, and neither owns. The
alternative — retyping ``300`` in the CHECK constraint — is the drift #581
exists to prevent, and a CHECK that disagrees with the request models is worse
than neither: one of them would reject a value the other accepted, and which
one you hit would depend on the write path.
"""

#: The longest employer name any writer may put on ``applications.company``.
#:
#: NOT A STYLE PREFERENCE. ``ix_applications_company`` is a btree, and Postgres
#: refuses an index entry over 2704 bytes — ``ProgramLimitExceededError: index
#: row size 2720 exceeds btree version 4 maximum 2704``. Inside the sync's
#: single transaction that takes the WHOLE batch with it: measured, ``AAA +
#: POISON + ZZZ`` left zero rows, including the innocent message that had
#: already flushed, and nothing commits — so every later sync re-reads the same
#: mail and re-poisons.
#:
#: 300 CHARACTERS, AND THE UNIT MATTERS. ``length()`` is character semantics on
#: both engines, and 300 characters is at most 1,200 bytes of UTF-8 — comfortably
#: inside the btree limit even for four-byte code points, which is why the bound
#: is expressed in characters rather than bytes.
#:
#: The value is deliberately far above anything real: the longest employer name
#: in production is 21 characters (76 rows, read 2026-09-06), and the longest
#: sender name in the independent corpus is 42. This is a rail against a hostile
#: or malformed value, not an editorial judgement about names.
#:
#: WHAT TO RE-MEASURE BEFORE MOVING IT (#737). Read those two figures as REACH,
#: not as acceptance. Neither corpus came near this number, so the diff offered
#: as evidence that 300 refuses no real mail — every corpus re-run with the
#: bound lifted to 1e9, zero movers — was arithmetic: over ``tests/corpus/`` the
#: longest display ``resolve_employer`` produced was 19 characters, so that same
#: zero would have come back for any bound above 19, including a badly wrong
#: one. ``tests/corpus/generator.py``'s ``employer-name-length`` axis now holds
#: a message at 300 and at 301 on every door mail can reach (2 sender display
#: name, 3 domain brand, 4 subject), and
#: ``tests/test_the_corpus_reaches_the_employer_bound.py`` runs the corpus both
#: ways: measured 2026-09-08, 0 movers over the 202 cases that predate the axis
#: and 4 over the 210 that include it. Every one of those four is ADMISSIBLE at
#: the wire — ``ScannedMessageIn`` bounds the same fields at 512/512/2000 and
#: takes all of them — so this constant really is the only thing refusing them.
#: Door 1 is an HTTP body rather than mail and keeps its synthetic on-boundary
#: cover in ``tests/test_an_employer_name_is_bounded.py``.
#:
#: Changing this number reds that module by design. The fixtures were built
#: against 300 and stop sitting on the bound the moment it moves — re-measure
#: them against the new value instead of re-baselining the assertion.
MAX_COMPANY_LEN = 300
