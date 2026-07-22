# Execution plan — Filtering Confidence and Variant Safeguards

**Status:** implemented in PR #45 (`e967b91`). This file is the historical
staged plan and verification contract. Companion to [README.md](README.md),
which defines the assessment contract, evidence architecture, harness split,
and privacy model.

## Ground rules

- Keep each change focused and preserve unrelated working-tree edits.
- Never modify a user-owned private search profile or candidate profile.
- Public corpus cases, tests, docs, URLs, employers, and posting text are wholly
  fictional and timeless. Raw harvests stay under `private/` or `tmp/`.
- Edit canonical modules under `scripts/shared/`, then regenerate vendored copies;
  never hand-edit a `_vendor/` file.
- Keep normal search recall-safe: `review` is retained and normal execution remains
  successful. Only the explicit audit and deterministic test gates fail on review
  or novelty.
- Any behavioral edit to a skill's `SKILL.md`, `LESSONS.md`, or `reference.md`
  follows the risk-based canary gate in `evals/README.md`. The planned instruction
  changes are behavioral and therefore require job-search canaries.
- Salary remains metadata only. No stage may introduce salary filtering.

## Stage 0 — Public design record

Create only:

- `design/filtering-variant-safeguards/README.md`;
- `design/filtering-variant-safeguards/execution-plan.md`.

The design is complete when it records the tri-state assessment contract,
full-evidence location/workplace behavior, both harness types, routine-versus-audit
semantics, structural novelty limits, private harvest/public promotion, and the
stages below.

**Gate:** public leak guard exits zero, and no file outside this design directory is
changed by the documentation-only work.

## Stage 1 — Canonical full-evidence location/workplace assessment

### 1.1 Add the assessment primitive

Extend `scripts/shared/location.py` with a JSON-compatible posting assessment that
returns:

- `result: match | no_match | review`;
- `confidence: high | medium | low`;
- stable `rule_ids`;
- evidence records with stable IDs, source, normalized signal, and polarity;
- concise reason and structural signature.

Keep `classify_location()`, `classify_locations()`, and `is_match()` as temporary
compatibility adapters. They derive their answers from the new assessment and are
marked for eventual removal only after all consumers migrate.

The posting-level API accepts raw location, title, full description, ATS workplace
hint, and injected policy. Extraction and policy folding are separate functions so
the corpus can assert both evidence recognition and the final result.

### 1.2 Route every location consumer

Migrate:

- `.agents/skills/job-search/scripts/scoring.py`;
- `.agents/skills/job-search/scripts/company_roles.py`;
- `scripts/shared/job_metadata.py`;
- `.agents/skills/job-search/scripts/handoff.py` metadata flow;
- `.agents/skills/application-tracker/scripts/status.py --check-locations`;
- discovery and targeted-role rendering.

The tracker reads each job's exact `jd_file`, combines it with recorded location and
workplace, and runs the same vendored assessment. A multi-role folder is checked
per job rather than by a merged location-only approximation.

Source adapters in `sources.py` continue to normalize ATS workplace fields, but
those values remain evidence. No source-specific boolean may bypass the canonical
assessor.

### 1.3 Location regressions

Add focused tests for:

- preferred office alone;
- explicit US-remote alone;
- preferred office **or** US-remote;
- hybrid/onsite at a non-preferred office;
- foreign-only remote and mixed-region wording;
- title geography conflicting with a generic distributed hint;
- full-description evidence beyond display truncation;
- explicit negation and source/JD conflicts producing `review`;
- bullet-, slash-, semicolon-, and newline-separated location alternatives;
- search, metadata, handoff, and tracker parity.

**Stage gate:**

```bash
.venv/bin/python -m unittest discover -s scripts/shared/tests
.venv/bin/python -m unittest discover \
  -s .agents/skills/job-search/scripts/tests \
  -t .agents/skills/job-search/scripts/tests
.venv/bin/python -m unittest discover \
  -s .agents/skills/application-tracker/scripts/tests
.venv/bin/python scripts/vendoring/sync_vendored.py --check
```

No location `review` case may disappear from the in-process result merely because
a legacy adapter still exposes a boolean.

## Stage 2 — Correct other filters and lock pipeline invariants

### 2.1 Sponsorship

Put the canonical sponsorship evidence assessment in the shared metadata layer and
make job-search `visa.py` an adapter for legacy labels and display tags.

Required behavior:

- specific positive immigration sponsorship language may produce `match`;
- explicit denial produces `no_match`;
- conflicting positive and negative clauses produce `review`;
- missing language is `review` when sponsorship is required;
- generic uses of `sponsor`, unrelated `perm` substrings, and broad immigration
  marketing do not satisfy `require_positive`;
- an employer-history signal may affect score/provenance but cannot override an
  explicit posting denial.

### 2.2 Title/seniority and YOE

Return canonical assessments for title/seniority and required YOE. Title
neutralization occurs before exclusion checks and emits evidence showing which
phrase was neutralized.

YOE extraction, hard filtering, and score penalties use one title-plus-description
input order and one confidence rule:

- only high-confidence general required YOE can match, reject, or penalize;
- preferred, technology-specific, domain-specific, missing, and ambiguous YOE is
  retained as review/context;
- score code consumes the assessment rather than reparsing text.

### 2.3 Dedupe and deterministic ordering

Replace first-fetch-wins deduplication with best-row selection:

1. group by canonical posting identity;
2. choose the highest score;
3. use documented stable tie-breakers;
4. apply diversity/top-K after semantic rejection and blacklist checks.

Add invariant tests for:

- recency anchoring and monotonic age boundaries;
- AI-native decisions carrying registry-tag or JD-signal provenance;
- blacklist dominance over every score and review state;
- best duplicate surviving every input permutation;
- deterministic diversity cap/backfill;
- direct run and snapshot refilter equivalence.

Salary extraction may be tested for metadata preservation, but it must not appear
in any filter predicate or invariant that controls eligibility.

**Stage gate:**

```bash
.venv/bin/python -m unittest discover -s scripts/shared/tests
.venv/bin/python -m unittest discover \
  -s .agents/skills/job-search/scripts/tests \
  -t .agents/skills/job-search/scripts/tests
.venv/bin/python scripts/vendoring/sync_vendored.py --check
```

## Stage 3 — Build the semantic corpus and snapshot audit

### 3.1 Public corpus

Add `.agents/skills/job-search/filter_variants/` with:

- a versioned schema;
- maintainer instructions;
- fictional cases for location/workplace, sponsorship, title/seniority, and YOE;
- stable case, rule, and evidence IDs;
- expected result, confidence, evidence classes, and structural signature.

Each case is minimal. A new case must represent a new decision boundary, evidence
combination, conflict, or materially different token shape; punctuation-only
duplicates do not expand the corpus.

### 3.2 Corpus and signature library

Add `.agents/skills/job-search/scripts/filter_variants.py` to:

- parse and lint corpus records;
- dispatch each domain to its production assessor;
- build stable structural signatures;
- compare actual and expected assessments;
- group records without exposing raw private values.

The signature uses only domain, evidence channels, normalized signal classes,
polarity/negation, conflict state, and rule family. It excludes literal company,
title, location, URL, date, salary, and description values.

### 3.3 Validator and audit CLI

Add `.agents/skills/job-search/scripts/validate_filter_variants.py` with two modes:

```bash
# Public deterministic corpus; zero means every labeled case matches.
.venv/bin/python \
  .agents/skills/job-search/scripts/validate_filter_variants.py \
  --check

# Local no-network audit of a pre-filter snapshot.
.venv/bin/python \
  .agents/skills/job-search/scripts/validate_filter_variants.py \
  --snapshot tmp/search_cache/example-stage1-latest.json \
  --profile example \
  --out tmp/filtering-variant-harvest/review.yaml
```

The exact fixture path in tests is synthetic. A maintainer auditing a private
profile substitutes a private snapshot and profile path; neither appears in tracked
output.

Audit behavior:

- inspect full snapshot descriptions, not light JSON projections;
- assess only signal-bearing shapes;
- group unknown/review cases by structural signature;
- write a YAML label stub with counts, evidence classes, rule IDs, and private
  pointers needed for manual review;
- never write directly into the tracked corpus;
- exit zero only when every signal-bearing case is decisive, every signature is
  known, and every invariant passes;
- exit nonzero for any `review`, novel signature, malformed assessment, or
  invariant failure.

Use separate exit codes for expected audit findings and execution/schema errors so
automation can distinguish “label this variant” from “the tool broke.”

### 3.4 Novelty-limit tests

Prove that:

- capitalization and punctuation variants share a signature;
- changed evidence channels, negation, or conflict state create a new signature;
- repeated postings create one grouped label stub;
- identifiers and raw posting text do not enter signatures;
- irrelevant prose with no known marker does not create unbounded novelty;
- the documented blind spot remains explicit: marker-free novel semantics cannot
  be detected deterministically.

**Stage gate:**

```bash
.venv/bin/python \
  .agents/skills/job-search/scripts/validate_filter_variants.py \
  --check
.venv/bin/python -m unittest discover \
  -s .agents/skills/job-search/scripts/tests \
  -t .agents/skills/job-search/scripts/tests
```

## Stage 4 — Preserve the review queue in routine search

Change `search_jobs.py` so semantic filtering partitions postings into matches,
no-matches, and reviews rather than chaining booleans.

Required output behavior:

- matches continue through scoring, dedupe, diversity, and ranking;
- no-matches are counted by stable rule ID;
- reviews remain in a separate report under `tmp/` or configured private
  discoveries storage;
- compact and full summaries show review count and report path;
- JSON output makes review status explicit instead of encoding it as a normal
  match;
- normal search and `--refilter` exit zero when processing succeeds, even with a
  nonempty review queue;
- handoff does not automatically treat a review row as approved.

The dedicated validator from Stage 3 remains strict and exits nonzero on that same
snapshot until the new shape is labeled or the classifier is corrected.

Add regressions that feed one match, one no-match, and one review through both a
fresh in-memory run and `--refilter`, then assert:

- the match is ranked;
- the no-match is absent and counted;
- the review is present in the review report;
- normal exit is zero;
- snapshot-audit exit is nonzero with an actionable stub.

**Stage gate:**

```bash
JOBHUNT_CONFIG="$PWD/config.example.yaml" \
  .venv/bin/python -m unittest discover \
  -s .agents/skills/job-search/scripts/tests \
  -t .agents/skills/job-search/scripts/tests
```

## Stage 5 — Integrate public CI and maintenance instructions

### Tests and CI

Add:

- corpus-driven location and metadata tests under `scripts/shared/tests/`;
- job-search semantic, invariant, audit, review-queue, and dedupe tests;
- application-tracker parity tests;
- a job-search unit-test step and corpus-validation step in
  `.github/workflows/ci.yml`;
- the same commands in `CONTRIBUTING.md`.

CI uses only `config.example.yaml`, the public example profile, and fictional
fixtures. It never reads a private overlay, performs a live posting audit, or
requires network access.

### Skill instructions

Update job-search documentation with the smallest delta that makes the new behavior
operational:

- `SKILL.md`: routine search summary and strict audit command;
- `reference.md`: corpus schema, private harvest, labeling, synthetic promotion,
  and exit-code details;
- `LESSONS.md`: durable high-stakes edge cases only.

Do not paste the design into the skill. Keep the quickstart short and point to the
reference tier for maintenance.

Because these edits change workflow and verdict semantics, run all job-search
canaries on a pinned model and record the result per `evals/README.md`.

**Stage gate:**

```bash
.venv/bin/python scripts/metrics/instruction_budget.py --strict
.venv/bin/python scripts/maintenance/gardener/gardener.py verify-links
.venv/bin/python scripts/publish/check_public.py
```

## Stage 6 — Final verification and rollout

Run from the repository root with the public example config:

```bash
# Regenerate, then prove every vendored consumer is byte-identical.
.venv/bin/python scripts/vendoring/sync_vendored.py
.venv/bin/python scripts/vendoring/sync_vendored.py --check

# Deterministic semantic corpus.
.venv/bin/python \
  .agents/skills/job-search/scripts/validate_filter_variants.py \
  --check

# Unit and cross-layer regression suites.
.venv/bin/python -m unittest discover -s scripts/shared/tests
JOBHUNT_CONFIG="$PWD/config.example.yaml" \
  .venv/bin/python -m unittest discover \
  -s .agents/skills/job-search/scripts/tests \
  -t .agents/skills/job-search/scripts/tests
JOBHUNT_CONFIG="$PWD/config.example.yaml" \
  .venv/bin/python -m unittest discover \
  -s .agents/skills/application-tracker/scripts/tests
.venv/bin/python -m unittest discover \
  -s .agents/skills/resume-writer/scripts/tests

# Syntax, instruction, link, and privacy gates.
.venv/bin/python -m compileall scripts .agents/skills/*/scripts
.venv/bin/python scripts/metrics/instruction_budget.py --strict
.venv/bin/python scripts/maintenance/gardener/gardener.py verify-links
.venv/bin/python scripts/publish/check_public.py
```

Then run the job-search canaries and record their pinned-model results. The final
verification record must state:

- corpus cases all pass;
- the synthetic review fixture makes normal search exit zero and audit exit
  nonzero;
- direct search, refilter, handoff metadata, and tracker location checks agree;
- invariant tests pass under input permutations;
- vendored copies are synchronized;
- the public leak guard reports zero findings.

## Private maintenance loop after rollout

The live audit is intentionally local and not a CI gate:

1. Search normally; investigate only when the review report is nonempty.
2. Audit the resulting snapshot with `validate_filter_variants.py --snapshot`.
3. Keep the raw report under `private/` or
   `tmp/filtering-variant-harvest/`.
4. Decide the expected policy result using the full private evidence.
5. Reproduce the semantic structure with a fictional public case.
6. Update production rules and stable IDs, then run the complete Stage 6 gate.

Do not weaken the audit to make a new signature pass. Either classify it with an
evidence-backed rule, keep it as an intentional review case, or document why the
marker is outside the supported domain.

## Rollback boundaries

Each stage is independently reversible:

- compatibility adapters preserve old callers during the location migration;
- corpus and audit tooling do not change normal search until Stage 4;
- review reporting is additive and uses private/temporary outputs;
- CI integration lands only after deterministic local gates pass.

If parity, recall, or canaries regress, stop at the current stage and revert that
focused change. Do not bypass the tri-state contract, audit exit behavior, vendor
drift check, or leak guard.
