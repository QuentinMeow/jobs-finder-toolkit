# Filtering Confidence and Variant Safeguards

**Status:** implemented in PR #45 (`e967b91`). See
[execution-plan.md](execution-plan.md) for the historical staged plan and
verification contract.

## Problem

The search pipeline currently turns several uncertain text classifications into
booleans. That makes an unrecognized phrase indistinguishable from a confident
rejection, allows duplicated classifiers to drift, and can make fetch order affect
which duplicate survives. Location is the clearest example: the answer may depend
on the structured location, a title suffix, an office-or-remote alternative in the
full job description, and an ATS workplace hint. No one field is authoritative in
every posting.

The safeguard must keep routine search useful without silently losing uncertain
postings. It must also learn new semantic shapes from real searches without putting
real postings or job-hunt data in the public repository.

## Goals

- One explainable assessment contract for every high-stakes semantic filter.
- One full-evidence location/workplace decision shared by search, metadata,
  handoff, targeted company-role search, and application validation.
- Deterministic tests for known language variants and deterministic invariants for
  fields that do not need a phrase corpus.
- A strict, no-network snapshot audit that detects review cases and new structural
  signatures.
- A privacy-preserving loop from private or temporary harvests to fictional public
  regression cases.

This design does not use an AI model in the routine classifier or test path. An
agent is useful only after the deterministic audit identifies a new or conflicting
shape that needs a policy decision.

## Canonical assessment contract

Every semantic assessor returns the same JSON-compatible shape:

```yaml
result: match                 # match | no_match | review
confidence: high              # high | medium | low
rule_ids:
  - location.us_remote_explicit
evidence:
  - id: location-field-1
    source: location          # location | title | description | ats_workplace
    signal: us_remote
    polarity: positive
    text: "Remote within the United States"
reason: "The posting explicitly allows US-remote work."
structural_signature: "location_workplace|description|us_remote|unopposed"
```

The fields have distinct meanings:

- **`result`** is the policy answer. `match` and `no_match` require enough
  consistent evidence to decide; `review` means missing, conflicting, or
  unsupported evidence. Callers must not coerce `review` to `false`.
- **`confidence`** measures evidence strength, not desirability. It never overrides
  `result`; a low-confidence signal becomes `review`, not a low-confidence hard
  rejection.
- **`rule_ids`** are stable identifiers for the rules that produced the result.
  Reports and corpus expectations compare IDs instead of fragile prose.
- **`evidence`** records stable IDs, source channels, normalized signal classes,
  polarity, and the relevant text. Raw text may appear in private reports; tracked
  corpus evidence is fictional.
- **`reason`** is concise human-readable output derived from the structured fields.
- **`structural_signature`** groups semantically equivalent variants without
  including employer names, URLs, exact locations, dates, or entire descriptions.

Compatibility helpers may still return an old category or boolean while consumers
are migrated, but they must adapt from the canonical assessment rather than
reimplement policy.

### Delivered contract (implementation note)

The shipped assessments use a deliberately **compact, stable evidence-ID
contract** rather than the fully expanded per-source `evidence` objects sketched
above:

- `evidence` and `review_reasons` are ordered tuples/lists of **stable rule-ID
  strings** (for example `preferred_metro`, `foreign_scope`,
  `remote_onsite_conflict`, `sponsorship.negative.*`, `title.excluded.*`). The
  richer `{id, source, signal, polarity, text}` object is the illustrative and
  private-audit shape; the `id`/`signal`/`polarity` it carries are exactly what
  the stable rule-ID string already encodes, so production/runtime does not
  inflate every consumer to rich objects. The `text` field of that shape only
  ever appears in **private** reports, never in tracked corpus or signatures.
- The audit `structural_signature` is built **only** from the domain, decision,
  confidence, and stable rule/conflict **families**. Those families encode the
  material polarity and evidence channels without retaining the specific literal
  token. It never contains a company, title, URL, date, salary, delimiter, or raw
  description/location prose, so cosmetic and employer-specific variants collapse
  to one signature.
- Title/seniority and required-YOE are canonical assessment **helpers**
  (`scoring.assess_title`, `job_metadata.assess_required_yoe`) consumed by both
  the production filters and `filter_variants.py`, so the corpus and the live
  pipeline can never drift.

**Production/runtime vs strict audit boundary.** Routine search consumes the
compact contract: `match` and `no_match` drive the ranked shortlist, and every
`review` (location ambiguity, signal-bearing sponsorship uncertainty, and title
leadership ambiguity) is preserved in the runtime review queue without failing
the run. The strict snapshot audit replays production gate order and fails on an
unresolved, unlabeled `review` or a **new rule-family structural signature**.
An intentional review family becomes known only through a fictional corpus case;
it remains in routine review output but no longer creates repeated maintenance
failures. Private reports may attach evidence excerpts for labeling. Code and this
document must stay consistent: the delivered compact evidence-ID contract above
is authoritative.

## Full-evidence location/workplace architecture

`automation/shared/location.py` becomes the canonical owner of a posting-level
assessment. The job-search, application-tracker, and resume-writer skills consume
byte-identical vendored copies.

### Inputs

The assessor receives all available posting evidence in one call:

1. raw structured `location`;
2. full `title`, including geographic suffixes;
3. the **full** job-description text;
4. the normalized ATS or aggregator workplace hint;
5. the injected location policy.

The light search JSON may continue to truncate descriptions for display, but no
correctness decision may use a display truncation such as `description[:400]`.
Source-provided `remote` or `hybrid` values are evidence, not ground truth.

### Evidence extraction

Extraction produces claims before policy is applied:

- geography: preferred metro, other US office, US-wide eligibility, foreign-only,
  mixed region, or unknown;
- workplace: remote, hybrid, onsite, office choice, or unknown;
- obligation: required office, optional office, remote alternative, or no clear
  obligation;
- polarity: explicit allowance, explicit denial/negation, or weak hint;
- provenance: location field, title, full description, or ATS hint.

This separation prevents the word `remote` from erasing an explicit office
requirement and prevents a city named in unrelated prose from becoming the posting
location.

### Decision precedence

1. Explicit role-specific statements and their negations outrank source hints.
2. An explicit preferred-office **or US-remote** choice is a match when the
   candidate may select either alternative.
3. Hybrid or onsite work at a non-preferred office is not generic remote work.
4. Explicit foreign-only scope or a required non-preferred office is `no_match`.
5. Contradictory authoritative statements, a weak remote hint with no eligible
   geography, or an unrecognized signal-bearing shape is `review`.
6. A structured ATS hint contributes only when it does not conflict with stronger
   posting text.

For example, a fictional Harbor Lantern Systems posting with location
`North America` and description `Choose our preferred office or work remotely
within the United States` is a high-confidence `match`. If its description instead
says `This role is hybrid at the listed non-preferred office`, a generic ATS
`remote` hint cannot make it pass; the conflict is preserved for review.

### Consumers

The same assessment flows through:

- `scoring.location_ok` and the main filter/rank pipeline;
- `job_metadata.classify_workplace` and handoff metadata;
- `company_roles.py`;
- location rendering for multi-location postings;
- application-tracker `status.py --check-locations`, using each job's exact
  `jd_file` and recorded workplace.

Search and tracker parity is an invariant: the same evidence and policy must
produce the same result, confidence, evidence classes, and rule IDs.

## Other semantic assessors

The labeled corpus covers four domains:

| Domain | Decisive behavior | Review behavior |
|---|---|---|
| Location/workplace | Explicit eligible alternative matches; explicit incompatible obligation rejects | Missing scope, source/JD conflict, or unknown location/workplace phrase |
| Sponsorship | Explicit applicable sponsorship matches; explicit denial rejects | Silence, contradictory clauses, generic unrelated use of “sponsor,” or ambiguous authorization wording |
| Title/seniority | Included role and compatible level match; excluded role family or explicit incompatible level rejects | Neutralized phrases, unfamiliar level syntax, or conflicting title/metadata |
| Required YOE | High-confidence general requirement at or below the cap matches; above the cap rejects | Preferred, tool-specific, contextual, missing, or otherwise non-high-confidence requirement |

Sponsorship has one canonical assessment; `visa.py` becomes a compatibility and
display adapter. Substring accidents such as an unrelated word containing `perm`
cannot count as positive evidence, and a generic statement about sponsoring an
event cannot satisfy a positive sponsorship policy.

YOE filtering and scoring use the same title-plus-description extraction and the
same confidence threshold. Contextual or preferred experience remains visible in
metadata but never hard-drops or penalizes a posting.

**Salary is not a filter.** It remains extracted metadata for display, comparison,
and handoff. Missing, malformed, or low-confidence salary data must not affect
`match`, `no_match`, ranking eligibility, or the review queue.

## Two harness types

### 1. Labeled semantic corpus

The public corpus lives under
`skills/job-search/filter_variants/`. It contains a schema version, stable
case IDs, a domain, fictional posting inputs, injected policy, and exact expected
result/confidence/rule/evidence classes. It covers location/workplace,
sponsorship, title/seniority, and required YOE.

Cases are small semantic examples, not snapshots. Textual variations that are
materially equivalent share a structural signature; boundary and contradiction
cases have separate signatures. The validator lints the schema, runs each case
through the production assessors, and prints a field-level diff on failure.

### 2. Invariant harness

Fields whose correctness is mathematical, provenance-based, or pipeline-wide use
property/invariant tests instead of an open-ended phrase corpus:

- **Recency:** age is anchored to fetch time during snapshot refiltering; boundary
  behavior is monotonic; unknown dates are never fabricated.
- **AI provenance:** a hard AI-company decision must identify an allowed registry
  tag or JD evidence rule; employer-name resemblance alone is not provenance.
- **Blacklist:** a blacklisted posting never reaches match or review output,
  regardless of score or other assessments.
- **Deduplication:** the best-scoring equivalent row survives, independent of fetch
  order, with deterministic tie-breaking.
- **Diversity/top-K:** the per-employer cap and documented backfill behavior are
  deterministic and do not resurrect rejected or blacklisted rows.

These invariants also test direct-search versus snapshot-refilter parity.

## Routine search and strict snapshot audit

The pipeline partitions normalized postings into three semantic outcomes:

- `match`: eligible for scoring and the ranked shortlist;
- `no_match`: excluded with counted rule IDs;
- `review`: retained in a separate review queue with evidence and reason.

A normal search continues and exits zero when execution succeeds, even if review
items exist. Its summary includes review count and report path. Review rows are not
silently dropped and are not automatically handed off as approved applications.
The report defaults to a path under `tmp/` or the configured private discoveries
area.

The dedicated snapshot audit is deliberately stricter. It replays the full
pre-filter snapshot without network access in production gate order. A title
rejection short-circuits location/visa/YOE checks, and a definite location
rejection short-circuits later checks, so irrelevant postings cannot create
maintenance noise. It groups profile-relevant review items by structural
signature and emits actionable YAML label stubs. It exits nonzero when it finds:

- any `review` assessment whose structural family has no fictional corpus label;
- a new signal-bearing structural signature;
- a malformed assessment or corpus record; or
- an invariant or search/tracker parity violation.

This split protects recall during normal use while making an explicit audit a
blocking maintenance gate.

## Structural-signature novelty and its limits

A signature is built from the domain, evidence-channel set, normalized signal
classes, polarity/negation shape, conflict state, and rule family. It must not
contain literal company names, titles, URLs, dates, salary values, or full text.
Cosmetic changes such as punctuation or capitalization therefore do not create
novelty, while a new contradiction or evidence-source combination does.

The audit inspects only **signal-bearing** records and groups repeated examples
under one signature. This bounds noise and label work: one new structure creates
one label stub, not one failure per posting.

Structural novelty is not semantic omniscience. It can be detected only when text
contains a known domain marker, produces an unclassified signal shape, or conflicts
with another evidence channel. Completely novel wording with no recognized marker
cannot be distinguished from irrelevant prose by deterministic code. Corpus
coverage, conservative `review` outcomes, and periodic private audits reduce this
risk; they cannot eliminate it.

## Private harvest and public promotion

Real snapshots, discovery reports, company research, and raw label stubs stay in
the git-ignored private overlay or a purpose-named directory under `tmp/`, such as
`tmp/filtering-variant-harvest/`. They are never copied into tracked tests.

The promotion workflow is:

1. Run the snapshot audit locally and group failures by structural signature.
2. Review the private evidence and decide the intended policy result.
3. Write a new **fictional** minimal case that reproduces only the semantic shape,
   using a made-up employer, `.example` URL if needed, and timeless wording.
4. Add or adjust a stable rule ID and the public corpus expectation.
5. Run the corpus, unit/invariant suites, vendoring check, and public leak guard.
6. Delete or retain the raw harvest only under private/temporary storage according
   to local retention policy.

The public corpus is therefore synthetic even when a private posting revealed the
gap. Dated live data, real posting prose, real search profiles, and real
candidate/employer identifiers never cross the boundary.

## Ownership

- `automation/shared/location.py`: canonical location/workplace assessment.
- `automation/shared/job_metadata.py`: canonical shared metadata evidence, including
  workplace and required YOE extraction.
- job-search `visa.py` and `scoring.py`: adapters and policy integration, not
  duplicate phrase truth.
- job-search `filter_variants/` plus validator scripts: public semantic corpus,
  structural signatures, and snapshot audit.
- `search_jobs.py`: partitioning, review preservation, deterministic pipeline
  integration, and summary/report output.
- application-tracker: independent validation using the same vendored assessment.

Vendored copies remain generated artifacts. Canonical shared modules are edited
once and synchronized with `automation/vendoring/sync_vendored.py`.
