# Verification — 2026-08-01-memory-still-reports-fixed-bugs-as-open

Every entry was re-verified against the code before its status changed. Nothing here was
taken from the task file on trust.

## The four fixing commits exist and are dated before this session

```
$ for c in e967b91 1a1fbac 87f5e0d 20d085e; do git log -1 --format='%h %ad %s' --date=short $c; done
e967b91 2026-07-21 Job search: harden filtering and expand target coverage
1a1fbac 2026-07-20 evals: give rw-tailor-single-posting an isolated fresh-tailoring scaffold
87f5e0d 2026-07-20 render: kill the silent PDF-skip flake and convert PDFs in parallel
20d085e 2026-07-22 Fix resume skill categorization noise
```

All four landed 11–13 days before this session, which is the point the roadmap paragraph now
makes: nothing noticed.

## Entry 1 — the entry's own reproduction now returns `foreign` / `no_match`

The entry says `classify_location("Hybrid or Remote", policy)` with `us_only: true` "returns
a match; nothing consults the title". Run on 2026-08-02 against
`automation/shared/location.py`:

```
$ .venv/bin/python -c '<import location; call assess_location/classify_location>'
'Senior SRE — Bangalore' -> {'category': 'foreign', 'workplace': 'hybrid',
    'decision': 'no_match', 'confidence': 'high',
    'evidence': ('location_hybrid', 'location_remote', 'foreign_scope'), 'review_reasons': ()}
'Senior SRE'             -> {'category': 'unknown', 'workplace': 'hybrid',
    'decision': 'review', 'confidence': 'unknown',
    'evidence': ('location_hybrid', 'location_remote'),
    'review_reasons': ('unclassified_location',)}
classify_location('Hybrid or Remote'): unknown
is_match(foreign): False | is_match(unknown): False | is_match(us_remote): True
```

The code that does it:

```
$ grep -n 'title=posting.title' skills/job-search/scripts/scoring.py
319:        title=posting.title,
```

read in `assess_location`'s own docstring as "The title is read for geography in the
REJECTING direction only". Note the title-less control also stopped being `us_remote` — a
second, independent reason the entry's symptom cannot recur.

## Entry 2 — the canary now stages its own isolated scaffold

```
$ grep -n 'ISOLATED fresh-tailoring scaffold' evals/canaries/resume-writer.yaml
20:      ISOLATED fresh-tailoring scaffold (NOT the default in-place setup) so this canary
```

The block runs to line 37 and cites GH #16 — this entry's issue — by number, seeds only
`meta.yaml` + `source/JD-*.md`, and closes with "This keeps `rw-duplicate-preflight` the sole
owner of the already-complete-folder stop". That is the entry's Suggested fix, first branch.

## Entry 3 — the flake is handled in code, and LESSONS.md says the opposite of the Source line

```
$ sed -n '7,12p' skills/resume-writer/scripts/pdf_convert.py
Two flake-hardening guarantees (a silent "PDF: skipped" used to hide both):
  * detect + retry: LibreOffice occasionally exits 0 without writing the PDF
    (a transient lock / first-run no-op). We verify a real PDF landed
    (exists AND > MIN_PDF_BYTES); if not, we clear stray lock state, back off,
    and retry ONCE. If a converter was available but still produced no valid
    PDF, we raise PdfConversionError instead of returning a silent None.
```

`skills/resume-writer/LESSONS.md` (Environment section): "The old transient 'PDF: skipped'
flake … is now handled inside `pdf_convert.py`". The entry's `Source:` pointed at
`LESSONS.md:87-88`, which is now that contradicting text — re-pointed at the section.

## Entry 4 — half done, and only half struck

```
$ grep -n '_DEGREE_CHAIN_RE' skills/resume-writer/scripts/skills_diff.py
106:_DEGREE_CHAIN_RE = re.compile(
127:    if _DEGREE_CHAIN_RE.fullmatch(token.replace(".", "")):
```

`Status: open` is left alone: the provenance-header skip, the other half of the Suggested
fix, has not shipped. Only the degree-pattern half is struck.

## Entry 5 — the ADR's Consequences bullet is still false, so the header now says so

```
$ git ls-files 'history/conversations/*/handover.md' | wc -l
      35

$ grep -n 'history/conversations' automation/reconcile/reconcile.py
286:    conversations = REPO_ROOT / "history/conversations"
592:    "handover-present": "history/conversations",
```

**The task says 33 tracked handovers; the count on 2026-08-02 is 35.** Either way the ADR's
"Session handovers move to `private/local/history/` (never committed)" never happened. The
Consequences text is untouched (ADRs are immutable); a dated forward-link block in the header
states the correction and links the still-open
`message-queue/needs-human/decisions/history-untracked-in-phase-5.md`.

## Entry 6 — bare `all` is no longer a scope-limit cue

```
$ grep -n '_SPONSOR_SCOPE_LIMIT_RE\|_SPONSOR_AMBIGUOUS_SCOPE_RE' -A2 automation/shared/job_metadata.py
1526:_SPONSOR_SCOPE_LIMIT_RE = re.compile(
1527-    r"\b(?:every(?:one|body)?|each|guarantee(?:s|d|ing)?)\b",
1528-    re.I,
...
1569:_SPONSOR_AMBIGUOUS_SCOPE_RE = re.compile(r"(?<!\bat\s)\ball\b", re.I)
```

The first ADR's item 1 lists "`every` / `each` / `all`" as universal cues. `all` moved out of
the scope-limit pattern and into the ambiguous one, where it unsettles a denial into
`review`/`unknown`/low rather than removing it. The successor ADR's own header confirms the
scope of the change ("narrows item 1 … every other item of that decision stands unchanged"),
which is why the new `Superseded-by` line says items 2-4 still stand.

## The index is undisturbed

```
$ .venv/bin/python automation/reconcile/reconcile.py --check --fix-index   # EXIT=0
wrote memory/index.md
reconcile: OK (9 checks clean)

$ git status --short memory/index.md
(no output — rewritten byte-identical)
```
