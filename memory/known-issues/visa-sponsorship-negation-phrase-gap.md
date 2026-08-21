# `classify_sponsorship()` still misses denials that match no phrase at all

- **Status**: **REOPENED 2026-08-20, then closed again the same day** on
  `fix/sponsorship-negation-safety` — see the third correction below. The 2026-08-02
  CLOSED line stands as history and its own three reproduction lines still print
  `unlikely`, `unknown`, `unknown`; what it got wrong was the CLASS. (Closed 2026-08-02;
  narrowed 2026-07-31; **severity corrected upward 2026-08-01** — the 2026-07-31
  correction pass wrote a safety claim into this file that the code did not have, see
  the note below.)
- **Severity**: **was high, reproduced at high again on 2026-08-20, now closed.** The
  high-severity shape is *a denial reaching the candidate as an explicit **offer***, and
  on 2026-08-20 it reproduced in four one-clause sentences that had nothing to do with
  the unreachable-cue mechanism this file was written about. Before the fix this file
  read: a denial shape returned `verdict: likely`, `confidence: high`, `decision: match`,
  `classify_visa: yes`, so a posting that refused sponsorship in writing was shortlisted,
  unflagged, for the one candidate who cannot take it.
- **Area**: job-search
- **Source**: GH issue #15 (comment thread); reconfirmed in
  `evals/results/stage2-canary-gate-19c3ff8-20260720.md` and
  `evals/results/stage3-canary-gate-446a954-20260720.md` (`js-visa-require-positive`
  rows); escalated by the live stage-1 example-profile run of 2026-07-31 (11,638 raw
  postings); narrowed by task
  `2026-07-31-sponsorship-negation-defeats-require-positive`; **severity restored
  2026-08-01** after an independent re-run of the reproduction below

> **Correction, 2026-08-01.** Between 2026-07-31 and this entry, this file said the
> severity was *"medium (was high — the classifier no longer reports a denial as an
> explicit offer, so `--visa-policy require_positive` is safe again …)"* and that *"An
> unrecognized denial classifies `unknown`"*. Both were false when written, and the
> reproduction below shows it in one command. The edit that introduced them was made by
> the pass whose stated purpose was removing false statements from tracked records, so
> nothing downstream re-checked them. **A severity line is a safety claim; it is
> re-measured on the tree that ships it, never carried forward from a prior read.**

> **Third correction, 2026-08-20 — the CLASS, not the mechanism and not the wording.**
> This file has been CLOSED since 2026-08-02 on the strength of a sentence that says the
> high-severity shape *"no longer reproduces"*. It did reproduce, on `origin/main`, in
> four sentences shorter and plainer than anything the file discusses:
>
> ```text
> H-1B sponsorship is unavailable.          -> match / likely / HIGH
> H-1B sponsorship is not offered.          -> match / likely / HIGH
> Green card sponsorship is unavailable.    -> match / likely / HIGH
> Immigration sponsorship is not offered …  -> match / likely / HIGH
> ```
>
> Through `scoring.visa_ok` with `needs_sponsorship: true`, under BOTH policies:
> `kept=True label=yes review_reasons=[]`. Cause: every negation rule in the module reads
> BACKWARD from the sponsorship phrase, and these sentences put the refusal in the head
> noun's own PREDICATE, where nothing was looking; `unavailable` was also absent from
> `_SPONSOR_NEGATION_CUE_RE`, though it carries its negation as a prefix and is the most
> common word a board refuses with.
>
> **The 2026-08-02 entry's own three reproduction lines still print exactly what it says
> they print** — measured again on the same tree, `unlikely` / `unknown` / `unknown`. So
> the mechanism-level work was sound and the wording-level claim was true. What was false
> was the CLASS-level sentence built on top of them: three green wordings do not close
> "a denial reported as an offer", and this file has now been wrong about that same
> sentence twice, in the same direction, eighteen days apart.
>
> The two prior corrections say a severity line is re-measured on the tree that ships it.
> That rule was followed and still missed this, because it was applied to the
> reproductions the file already contained. **A CLOSED line on a defect CLASS is only as
> good as the sentences it was measured over, and re-running the ones already written
> down cannot falsify it.** Closing a class needs inputs the fix was not built from —
> which is what `evals/` and the blind waves in GH #304 are for, and what this entry
> should have demanded before printing the word CLOSED. Fixed on
> `fix/sponsorship-negation-safety`; see the 2026-08-20 section below.

> **Second correction, 2026-08-01 — the MECHANISM, not the severity.** The entry above
> restored a true severity and then explained it with a false cause: it said the
> reproduction's third sentence is out of scope because
> `_SPONSOR_NEGATION_MAX_GAP_TOKENS` is 8 and the sentence "puts 17 tokens between
> `unable` and `offer visa sponsorship`". Measured with the module's own internals, the
> distance is **12** tokens and the budget is **never consulted** — a clause break inside
> the parenthetical truncates the scope first, so `_sponsor_last_cue` returns `None`. The
> `Symptom` bullet and repair option (a) below are rewritten from measurement.
> **A known-issue that misdescribes its own defect is worse than none**: repair (a) as it
> was written ("stop counting tokens inside a parenthetical") would have been implemented,
> measured against the count, and left the filed reproduction returning `likely`/high.

## Symptom

`classify_sponsorship()` / `assess_sponsorship()` (in `automation/shared/job_metadata.py`)
scan a job description for an explicit sponsorship denial or offer and return
`unlikely` / `likely` / `unknown`. Polarity is now decided structurally, but the
*evidence detector* is still a fixed tuple of substring phrases, so a denial that
matches **neither** list is invisible and the posting classifies `unknown`:

- "We do not offer relocation or visa sponsorship." — the denial phrases need
  "offer sponsorship" contiguous, and the offer phrases need "visa sponsorship
  available" / "offer visa sponsorship"; neither matches, so nothing fires and the
  negation scope has nothing to act on.
- A negation cue that the clause scope cannot reach is not applied. **This does not
  fail safe.** When the phrase left unguarded is an OFFER phrase, the sentence is
  scored as an explicit offer, not as silence — so a denial with a parenthetical in
  the middle of it ("We are unable, given current headcount constraints and the
  timeline for this particular opening, to offer visa sponsorship.") returns
  `likely` / `high` / `match` and `classify_visa` → `yes`.

  **The mechanism, measured rather than assumed** (corrected 2026-08-01 — see the
  note below; the previous version of this bullet named the wrong cause and the
  wrong number, and one of the repairs offered downstream was written against
  them). Two independent bounds can put a cue out of reach, and for the sentence
  filed here it is the SECOND one, not the first:

  1. `_SPONSOR_NEGATION_MAX_GAP_TOKENS` (8) — the token budget between the cue and
     the phrase. Real distance in that sentence: **12 tokens**, not 17.
  2. `_SPONSOR_CLAUSE_BREAK_RE` — the clause scope is cut at the nearest boundary
     BEFORE the budget is ever consulted. In that sentence it matches `and the`
     at offset 51, inside the parenthetical, so the scope is
     `' timeline for this particular opening, to '` and `_sponsor_last_cue`
     returns **`None`**. `unable` is not in scope at all, and the 8-token budget
     is never reached.

  So the sentence fails on the clause break, and its token count is irrelevant to
  it. The budget bound is real and does fire on other wordings — the same sentence
  with the coordinator removed ("We are unable, given current headcount constraints
  for this particular opening, to offer visa sponsorship.") puts `unable` back in
  scope at a 9-token gap and is refused by the budget — but a repair aimed only at
  the count leaves the filed reproduction exactly where it is.

A second, opposite shape is still live: denial phrases carry **no**
immigration-context gate (offer phrases do), so a non-immigration use of "sponsor"
can read as a visa denial — "We do not sponsor community events" matches
`do not sponsor` and returns `unlikely`, which DROPS the posting under both visa
policies. The export-control sense of the word is now guarded specifically (below);
the general case is not.

## Reproduction

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'automation/shared')
from job_metadata import assess_sponsorship as a
for t in ('We do not offer relocation or visa sponsorship.',
          'We do not sponsor community events.',
          'We are unable, given current headcount constraints and the timeline '
          'for this particular opening, to offer visa sponsorship.'):
    print(a(t)['verdict'], a(t)['confidence'], a(t)['decision'])
"
# prints:
#   unknown  unknown  review     <- should be 'unlikely' (denial matches no phrase)
#   unlikely high     no_match   <- should be 'unknown'  (non-immigration "sponsor")
#   likely   high     match      <- should be 'unlikely'; THIS is the high-severity one
```

Re-run 2026-07-31 on the stack tip `40871e6`: the first two print `unknown` then
`unlikely`, exactly as stated. Re-run 2026-08-01 on the branch that carries this
correction: all three reproduce, including the third — which the previous version of this
file said could no longer happen. Re-run again on `wip/42-sponsorship-recall` (the branch
carrying the quantifier-confidence fix below): **all three still print exactly the lines
above.** That change touches the denial side's confidence only and closes none of these
three; nothing here is fixed by it.

The one figure in this file that is **not** reproducible is "roughly 28 of 430 `likely`
rows on the 2026-07-31 run" (and the 11,638 raw postings behind it). Those come from a
live keyless board sweep whose postings have since moved on; they are recorded as what
that run reported, not as a claim about any tree, and nothing here depends on them.

## Impact

Three shapes, and they do not cost the same.

1. **A denial reported as an offer (high).** When a denial's sentence carries an offer
   substring that the negation scope cannot reach, the posting classifies `likely` at
   `high` confidence with `decision: match`, so `--visa-policy require_positive` — the
   policy chosen precisely by someone who needs sponsorship — returns it with **no**
   `sponsorship_requires_review` flag. The user is pointed at an employer that said no
   in writing. This is the reason the entry's severity is high.
2. **A denial reported as silence (medium).** An unrecognized denial classifies
   `unknown`, and the default `exclude_negative` policy keeps `unknown`, so the posting
   reaches the candidate as if sponsorship were merely unstated — advisory-only output
   (the skill always tells the agent to verify with the employer), but a weaker signal
   than the JD actually gave.
3. **A non-denial reported as a denial (medium).** The posting is dropped silently
   under both policies; it needs an unrelated "sponsor" use in the JD, which is uncommon.

## Root cause

`_SPONSOR_NEGATIVE` / `_SPONSOR_POSITIVE` are fixed substring tuples. Detection is still
lexical: if no phrase from either tuple matches, there is nothing for the negation scope
to act on. And `_SPONSOR_NEGATIVE` hits are accepted without the `_SPONSOR_CONTEXT_RE`
gate that non-strong `_SPONSOR_POSITIVE` hits must pass.

## Fixed on 2026-07-31 (kept as history)

Three wrong-polarity symptoms this file used to describe are resolved **for the wordings
named below**. Item 2 is the one that was over-claimed: the negation scope closed the
shapes it can reach, not the class. Pinned by tests in
`automation/shared/tests/test_job_metadata.py`,
`skills/job-search/scripts/tests/test_visa.py`, and
`skills/job-search/filter_variants/corpus.yaml`:

1. **The original phrase-list misses.** "Immigration Sponsorship support will NOT be
   available for this position" and "We are unable to provide visa sponsorship"
   classified `unknown`; both now classify `unlikely`.
2. **The escalation — a denial reported as an explicit offer.** A denial containing an
   offer substring ("does not currently offer visa sponsorship", "no H1-B visa
   sponsorship available") returned `decision: match`, `confidence: high`, so
   `--visa-policy require_positive` surfaced postings that refuse sponsorship — roughly
   28 of 430 `likely` rows on the 2026-07-31 run. A bounded negation scope now reads an
   offer phrase inside a negated clause as a denial of that offer — **but only when the
   cue is within 8 tokens of the phrase.** Outside that window the class is untouched;
   see Symptom, and the third line of the reproduction. Claiming otherwise is what made
   this file's severity wrong.
3. **Export-control boilerplate read as an immigration denial.** "…must be eligible to
   obtain the required authorizations without sponsorship for an export license"
   returned `unlikely` / high confidence, and the default policy drops denials, so
   export-controlled postings disappeared silently. A sentence that is export-control
   language with no immigration word in it is no longer sponsorship evidence.

## Fixed on 2026-08-01 (kept as history)

**A quantified denial promoted to a confident offer.** The 2026-07-31 scope-limit rule
("not for *every* role" negates a universal, so it is a limit on an offer rather than a
refusal) accepted the bare word `all` as well. `all` also has a collective reading, so
"We are unable to sponsor visas for **all** new hires" — a flat denial that names the
population it covers — was read as a scope limit, which **deleted** the denial. Deleting
it dissolved the `denial + positive -> review` conflict, so the same JD's unrelated
positive phrase was left unopposed and the posting graded `likely` / `high` / `match`
with `classify_visa: yes`. The rule is now restricted to DISTRIBUTIVE quantifiers
(`every` / `each`, plus an explicit `guarantee` hedge). Pinned by
`QuantifiedDenialTests`, `test_require_positive_never_presents_a_quantified_denial_as_an_offer`,
and the `sponsorship-quantified-denial-*` / `sponsorship-do-not-sponsor-all-*` corpus
cases.

**…and the same quantifier failing the other way (fixed in the same day's second pass).**
Removing `all` from the scope-limit cue stopped it deleting a denial, and let it fall
through to the ordinary denial path instead, which asserts `high` confidence from the mere
presence of a denial. So "we do not sponsor all roles" — the sentence the entry above calls
ambiguous in so many words — graded `no_match` / `unlikely` / **high** with **no**
`sponsorship_requires_review` flag, and was dropped under BOTH visa policies. It only drops
when no `_SPONSOR_POSITIVE` phrase survives the context gate, so the class it swallowed was
exactly *postings whose offer is phrased in words the phrase list does not contain* — the
same class this whole entry is about. A posting stating "our immigration team supports H-1B
and green card cases, but we do not sponsor all roles" was deleted silently; the same
sentence with `every` was kept and flagged.

The repair is the one option (b) above describes, applied to the denial side: the phrase
**stays a denial** (it never leaves the `denial` list, so no promotion to `likely`/`match`
is reachable — the invariant the pass before it existed to protect is untouched), and the
VERDICT layer stops treating an unsettled denial as a confident one. Alone it now lands
`review` / `unknown` / low, kept and flagged. Any one SETTLED denial elsewhere in the
posting still decides it outright. Pinned by
`QuantifiedDenialTests::test_a_quantified_denial_alone_is_not_a_confident_refusal`,
`::test_an_unsettled_denial_never_hides_an_offlist_sponsor`,
`::test_one_settled_denial_outranks_any_number_of_unsettled_ones`,
`test_require_positive_never_drops_a_quantified_denial_silently`,
`test_a_settled_denial_is_still_dropped_under_both_policies`, and three corpus cases.

**Recorded as method:** three consecutive revisions of this one classifier each fixed one
direction of the same quantifier by reopening the other. What made the fourth different is
not a better cue list — it is that the evidence layer and the verdict layer were separated:
the evidence layer records that the reading is unsettled and keeps the denial, and only the
verdict layer's confidence changes. A cue-list edit alone can only trade one error for the
other.

Worth recording as method, not just as a bug: the invariant the scope-limit rule was
written under — *a scope limit may only REMOVE a denial, never create an offer* — holds
of the evidence lists by construction and was never enforced at the VERDICT level, where
removing a denial is itself a two-step promotion (`review`/`unknown`/low →
`match`/`likely`/high). The unenforced half is where the defect landed.

## Deliberately NOT fixed (recorded so the record cannot be misread as a regression)

An independent verification pass published three sentences as one blocking finding — a
posting that refuses sponsorship reaching the shortlist as `yes` / `likely`, unflagged.
Two are closed. **The third is unchanged on purpose, and no document said so**, which
leaves a reader reconciling the two records to conclude that a fix regressed. Measured on
`wip/42-sponsorship-recall`:

| Reproduction | Now | Closed? |
|---|---|---|
| green-card offer + "unable to sponsor visas for **all** new hires" | `unclear` / `unknown` / flagged | yes |
| "relocation and immigration support" + "cannot sponsor **every** applicant" | **`yes` / `likely` / unflagged** | **no — by design** |
| H-1B benefits + "do not sponsor **all** candidates" | `unclear` / `unknown` / flagged | yes |

The middle row is written with `every`, and reading it as an offer plus a limit on that
offer is the whole point of the distributive rule: `not (for every applicant)` entails that
some applicants ARE sponsored, so an employer that provides immigration support and cannot
sponsor every applicant is a sponsor. Grading it `unclear` is the regression that rule was
written to fix (`sponsorship-offer-then-scope-limit-is-an-offer` in the corpus, and
`require_positive` returning zero against the clearest sponsor in an 11.7k-posting scan).
It is not on the list above because it is **not believed to be wrong**; if it is ever shown
to be, the fix is the discourse-relation reading the decision record lists under
alternatives, not a narrowing of the quantifier — which is what the three previous revisions
each tried, in alternating directions.

All three rows were re-measured on the fix branch tip `f016aec` and are byte-identical
to the readings above. The long-parenthetical denial, which this section used to record
as the open high-severity item, is closed — see the 2026-08-02 entry below.

## Fixed on 2026-08-02 (kept as history)

All three remaining shapes, as three independent commits, each gated on a **frozen
verdict matrix** of 51 rows — the three reproductions, all three "Deliberately NOT
fixed" rows, every `domain: sponsorship` corpus case, and the named tripwires —
measured BEFORE and AFTER every change, with "change nothing" an allowed outcome for a
row. 35 of 35 pre-existing correct rows came out byte-identical; only the six target
rows moved.

1. **The unreachable negation cue (the high-severity one).** Repair **(b)** — fail
   toward review — was implemented; **(a)** was not, and both bounds sit exactly where
   they were, so `sponsorship-offer-after-clause-restart` is untouched. The evidence
   layer records the cue as unreachable and only the verdict layer's confidence changes:
   the posting lands `review` / `unknown` / low, kept and flagged. This closes the
   token-budget bound as well as the clause break. Pinned by
   `SponsorshipUnreachableCueTests`,
   `test_require_positive_never_presents_an_unreachable_cue_as_an_offer`, and the
   `sponsorship-unreachable-cue-*` corpus cases.

   **Repair (b) as this file described it is not sufficient on its own.** Implemented
   literally it demotes `sponsorship-offer-after-clause-restart`,
   `test_contrastive_conjunction_ends_the_negation` and
   `test_a_denial_beside_a_hedged_offer_is_a_conflict_not_a_drop`. Two exclusions are
   required, both measured: an offer phrase that OPENS its own clause
   (`_sponsor_clause_scope` returns `''` there, against
   `' timeline for this particular opening, to '` for the filed sentence), and a
   negation already SPENT by an unambiguous break — terminal punctuation, a dash, or a
   contrastive conjunction. The comma and coordinator breaks are deliberately excluded
   from that set: those are the ones that fire inside an aside.

2. **Detection.** A negation reaching a bare sponsorship HEAD through an OFFER VERB is a
   denial of that offer, resolved through the module's existing `_sponsor_negation`
   scope — no third notion of "reach" — with a tight 5-token verb-to-head window. The
   offer verb is what separates the denial from EEO copy: "we do not discriminate
   against candidates who need visa sponsorship" puts a cue five tokens from the head
   and is the OPPOSITE of a denial, so a cue-plus-head rule alone would have deleted
   employers that sponsor. Pinned by `SponsorshipOffListDenialTests` and four corpus
   cases.

   Two integration constraints this entry did not name, both found by measurement. The
   rule must be a **fallback only** — a head already covered by a listed phrase keeps
   its existing path, or it steals `sponsorship-negated-offer-phrase`'s rule ids, which
   `test_negated_offer_with_adverb_is_unlikely` pins exactly. And its synthetic denial
   span must run from the CUE to the head, not from the head, or
   `_sponsor_denial_is_negated` reads the rule's own cue as an outer negation and grades
   a flat denial as a double negative.

3. **The false-denial shape.** Only phrases whose "sponsor" is a bare transitive VERB
   with no object of its own are gated on immigration context; every other denial names
   "sponsorship" as the head noun, where the object IS sponsorship. Pinned by
   `SponsorshipNonImmigrationDenialTests` and three corpus cases.

   **This entry's own suggestion could not be implemented as written.** A
   `_SPONSOR_STRONG_NEGATIVE` set defined as "phrases naming visa / H-1B / immigration /
   green card explicitly" cannot contain `not offer sponsorship`, which names none of
   them and is a real refusal — so under that definition the symmetric gate this entry
   warned about is unavoidable. The dividing line is grammatical (bare verb vs. head
   noun), not the strength of the wording, and it is pinned from both sides by
   `sponsorship-denial-naming-sponsorship-needs-no-context` and
   `sponsorship-non-immigration-sponsee-is-not-a-denial`.

   The gate also could not reuse `_SPONSOR_CONTEXT_RE`: that pattern is anchored on
   `\bvisa\b`, which does **not** match "visas", and these denials are routinely written
   with the plural. Widening the shared pattern would have loosened the OFFER gate, so a
   separate, deliberately wider `_SPONSOR_IMMIGRATION_RE` was added. It errs toward
   KEEPING a denial, because dropping a real one hides it at high confidence while
   keeping a non-immigration one costs only a review flag.

**Two limits, pinned as tests rather than left implicit:**

- the immigration gate's window is positional (±120 chars), so a real offer near a
  non-immigration "sponsor" keeps that denial and the posting reads as a CONFLICT — kept
  and flagged, never dropped and never promoted
  (`test_the_context_window_errs_toward_keeping_the_denial`);
- repair (b) costs recall on postings that put a negation and an unrelated offer in one
  sentence, exactly as this entry predicted when it proposed the repair.

**Recorded as method, extending the 2026-08-01 note.** This is the fifth pass over one
classifier, and the first three alternated — each fixed one direction by reopening the
other. What made passes four and five different is not a better cue list. It is two
things: separating the evidence layer from the verdict layer, and a frozen verdict
matrix measured before and after every single change, in which "change nothing" is an
allowed outcome for a row. Three of this entry's own prescriptions turned out to be
wrong in detail, and the matrix caught all three within minutes — none of them by
review.

## The matrix is now a tracked artifact (2026-08-10)

The method above kept working and kept being thrown away: each pass rebuilt the matrix by
hand and none of them committed it, so the sixth pass started by rediscovering the fifth
pass's row set. It is now tracked, and there is no reason to build another one.

- **Rows**: `skills/job-search/filter_variants/sponsorship_verdict_matrix.yaml` — 79 rows,
  frozen at `origin/main` 399a6ec. Every `baseline` block is HISTORY and is never
  re-measured; a row a landed change deliberately moved carries an `expect` block beside
  its baseline, so the move is recorded in the file rather than argued in a commit message.
  Twelve baselines are deliberately WRONG readings — that is what makes them measurements.
- **Runner**: `skills/job-search/scripts/sponsorship_matrix.py` — `--check` is the gate and
  is wired into the unit suite by
  `skills/job-search/scripts/tests/test_sponsorship_matrix.py`; `--diff` reports which rows
  moved from the frozen baseline and whether each move was predicted.
  Note it imports `job_metadata` from the skill's `_vendor/` copy, so re-vendor
  (`automation/vendoring/sync_vendored.py`) before trusting a run mid-change.
- `expected-unchanged` rows are tripwires and may never carry an `expect` block; the lint
  refuses the file if one does. An `expected-change` row that did NOT move is a reported
  outcome, not a failure — "change nothing" stays an allowed outcome for any row.

**Sixth pass, same day (#231 / #238a / #265), measured on it:** 12 of 79 rows moved, all 12
predicted, 0 unpredicted. Six off-list denial shapes were added as PATTERNS rather than
phrases (each with a word gate derived from its own mandatory anchor), and a denial scoped
to new/initial/cap-subject petitions in a posting that welcomes transfers is now unsettled
rather than a silent drop — the same evidence/verdict split, applied to a third ambiguity.

**Still open, and frozen rather than fixed:** a CONDITIONAL offer ("if approved by
counsel, the company will sponsor H-1B candidates") grades `match` / `likely` / `high`,
which `--visa-policy require_positive` returns unflagged. It is the hedged-offer rule's
grammar one step over. Three readings are frozen as the matrix's `conditional-offer` rows;
the work is filed as
`tasks/0_backlog/2026-08-10-conditional-sponsorship-offers-grade-as-unhedged`.
*(Closed 2026-08-20 — all three `conditional-offer` rows now carry an `expect` block; see
the 2026-08-20 section.)*

## Fixed on 2026-08-20 — negation is now read on BOTH sides of the head

Branch `fix/sponsorship-negation-safety`, measured on the tracked matrix (now 101 rows,
101 agreeing) plus the public corpus.

**The defect.** Every negation rule in `job_metadata` read backward from the sponsorship
phrase. The head noun's own predicate comes *after* it, and that is where a JD writes the
refusal — so "H-1B sponsorship is unavailable." found no cue, the offer substring
`h-1b sponsorship` stood unopposed, and the posting graded `match` / `likely` / **high**.
Two independent causes, both closed:

- **direction.** A forward scope was added: the existing clause scope plus one break the
  backward side never needed — a relative pronoun or subordinator. That break is the whole
  safety argument, because it is what separates "sponsorship is not offered" (a denial)
  from "sponsorship is available for candidates WHO ARE NOT authorized to work here" (an
  offer). A cue inside the tight budget denies the offer; one the budget refuses lands
  `review`, the same evidence/verdict split every other ambiguity here uses. The expletive
  "there" is a forward-only break addition: the shared break set recognizes a coordinated
  clause by its SUBJECT and lists referring expressions only, so ", and there is no
  relocation budget" demoted a plain offer until it was added.
- **vocabulary.** `unavailable` / `unavailability` joined `_SPONSOR_NEGATION_CUE_RE`.

**Shipped in the same pass**, each with its tripwire pinned beside it:

- **#233 / #304 offer recall** — `sponsorship is available` (context-gated, deliberately
  NOT strong: the bare sentence with no immigration word stays `unknown`, exactly as its
  contiguous twin always has), `h-1b transfer(s)`, `immigration assistance`, `visa
  support`. `_SPONSOR_CONTEXT_RE` was anchored on the singular `visa`, so "we sponsor …
  employment visas" failed its own gate; the nouns are now number-neutral.
- **#238** — a U.S.-person status list stated as an applicant REQUIREMENT is a denial.
  Anchored on "must" with a person-noun subject, and defused by a visa/EAD/authorized-to-
  work escape so the INCLUSIVE form of the same list (#265) and EEO copy stay clear.
- **#265** — an explicit transfer welcome is an OFFER. A posting that refuses new
  petitions and invites transfers is now a flagged conflict rather than a silent drop.
  Consequence recorded because it moved three pinned tests: a flat refusal beside an
  explicit transfer offer is `review`, not `no_match`. The invariant is unchanged —
  the denial stays in the evidence and the verdict may never reach `match`/`likely` —
  but the posting is kept and flagged instead of deleted.
- **#286 (sponsorship half)** — the export-control sense gate now applies only to phrases
  containing "sponsor". That ambiguity belongs to ONE noun; a citizenship bar has no
  second sense, and gating it too suppressed the only evidence a firmware posting carried,
  after which `signal_present` came back false and the default policy attached no review
  reason. `signal_present` is now true whenever any rule fired.
- **#304, the unsafe half only** — a condition FRONTED to the sentence ("If approved by
  counsel, …", "Once legal signs off, …") and frequency hedges ("sometimes") no longer
  read as settled offers. This closes the `conditional-offer` rows the sixth pass froze
  and the backlog item it filed. The rest of #304 — its recall failures and its call for
  proposition parsing instead of phrase lists — is NOT closed here.

**Measured, on 59 fictional probe sentences that are not in the corpus** (before → after):
offers 18/25 → 24/25, denials 9/25 → 25/25, neutral 9/9 → 8/9 — the single neutral move is
the #265 inclusive status list, which #265 asks to be read as an offer. On the 132 tracked
corpus + matrix rows, `likely` went 20 → 18: three deliberate conditional-offer demotions,
one recovered offer, and no legitimate positive lost.

**Recorded as method, extending the two notes above.** Passes four and five credited the
evidence/verdict split and the frozen matrix. Both held here — the matrix caught twelve
rows this pass would otherwise have moved silently, and every one of them turned out to be
either a target or an evidence-only addition. Neither instrument could have found the
defect, because both replay sentences that were already written down. **The matrix proves a
change did not move what it should not; it cannot tell you the class is closed.** That
needs sentences the fix was not built from.

## The repair options, as they stood before the fix (kept as history)

Three independent pieces; any can ship alone.

0. **The unreachable negation cue (the high-severity remainder).** An offer phrase whose
   governing cue is out of scope is scored as an offer rather than ignored. Two candidate
   repairs, and the choice is an owner call because they trade recall against safety
   differently — but note first that they are **not** interchangeable here: only (b) closes
   the reproduction filed above.
   - **(a) Widen the reach.** Stop `_SPONSOR_CLAUSE_BREAK_RE` ending the scope on a
     coordinator that sits INSIDE a comma-delimited parenthetical (the `and the` that cuts
     the filed sentence), and stop counting that parenthetical's tokens against
     `_SPONSOR_NEGATION_MAX_GAP_TOKENS`. **Both halves are required**: skipping the tokens
     alone changes only the count, and the filed sentence never reaches the count — it
     loses its cue to the clause break first. Widening the scope is also the riskier half,
     because the clause break is what stops "no relocation budget, and visa sponsorship is
     available" reading as a denial of the offer; any change here must keep
     `sponsorship-offer-after-clause-restart` green.
   - **(b) Fail toward review instead.** Leave both bounds alone, and make a cue that is
     present in the sentence but unreachable *demote* the offer to `unknown` rather than
     leaving it `likely` — kept and flagged, the way every other ambiguity in this module
     now resolves (see the 2026-08-01 quantifier entry below, which is the same move
     applied to the denial side). This closes the reproduction whichever bound cut the cue,
     and costs recall only on postings that put a negation and an unrelated offer in one
     sentence.
   Measure both against the corpus before choosing.
1. **Detection.** Give the denial side the structural treatment the offer side now has:
   when a negation cue governs an *offer verb* ("not offer", "not provide", "cannot
   extend"), accept a bare sponsorship head ("visa sponsorship", "sponsorship") within a
   tight window (≈5 tokens) as the denied object. Keep the window tight — a generic
   "cue … sponsorship head" rule misfires on EEO copy such as "we do not discriminate
   against candidates who need visa sponsorship", which is not a denial.
2. **The false-denial shape.** Gate generic denial phrases ("do not sponsor",
   "no sponsorship") on immigration context the way non-strong offer phrases are gated,
   with a `_SPONSOR_STRONG_NEGATIVE` set (phrases naming visa / H-1B / immigration /
   green card explicitly) exempt from the gate. Measure first: "This role does not offer
   sponsorship." carries no immigration word either, so a naive symmetric gate would turn
   a real denial into `unknown` — that regression is pinned by
   `sponsorship-explicit-denial` in the corpus.

Add fictional regressions to `skills/job-search/filter_variants/corpus.yaml`, run
`validate_filter_variants.py`, and re-vendor with
`automation/vendoring/sync_vendored.py`.
