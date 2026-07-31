# Verification — 2026-07-30-company-research-no-application-record-fallback

Real output, captured 2026-07-31 on `fix/10-company-research-correctness`. Absolute paths
are redacted to `<repo-root>`.

## The gap, confirmed in the pre-change file

```
$ git show b7227ae97:skills/company-research/SKILL.md | sed -n '71,72p'
3. Find the application record under `config.applications_root()/<status>/<slug>/`: its
   `meta.yaml`, the JD file(s) `source/JD-*.md`, and `notes.md` if present.
```

No branch for the record's absence, anywhere in the file:

```
$ git show b7227ae97:skills/company-research/SKILL.md | grep -c -iE "no application record|without a posting|company[- ]scope|JD-dependent"
0
```

The second instance holds too — `09` was required to link a file that a `09`-only run never
produces:

```
$ git show b7227ae97:skills/company-research/SKILL.md | sed -n '350,351p'
candidate will be *asked*: summarize the prepared, personalized answer and link to the
fuller `10-why-this-company.md` (at least two angles, grounded in the candidate's real
```

## This is the common case, not an edge case

Under the example config there is exactly one application, and it is not the company the
canary set researches — so 4 of the 6 canaries take this path on every run:

```
$ .venv/bin/python skills/application-tracker/scripts/status.py --check-metadata
ok      example-corp-senior-software-engineer
Checked 1 applications; 0 invalid.
```

## The three questions, answered in one place

```
$ sed -n '/No application record is the ordinary case/,/deliverable, and the link is only a pointer/p' \
      skills/company-research/SKILL.md
   **No application record is the ordinary case** — research usually runs before an
   application exists. Do not improvise an accommodation; switch to **company scope**:
   - Produce the **whole folder anyway**. Only the three outputs below are specified in
     terms of a posting; everything else is company-level and unchanged.
   - The subject of `08`, of `10`'s angles, and of `09`'s level/scope questions becomes the
     **role family named in the request** (e.g. "Senior SWE, Platform"), sourced from the
     company's own open postings on its ATS board — real, fetchable evidence that needs no
     application. Put `Scope: company-level — no saved posting; grounded in the ATS board as
     of <date>` under the title of each of those three.
   - Tag every line a real posting would change `[JD-dependent]`, so a later run *with* the
     application re-targets those lines instead of rewriting the file.
   - A required cross-file link whose target this run did not produce (`09` → `10`, when only
     `09` was asked for) **stays a link**, marked `(not yet written)`. Never inline another
     file's template to avoid a dangling reference: the summary `09` already owes is the
     deliverable, and the link is only a pointer.
```

It is in the routine section (`Before You Start` step 3), not `reference.md`, which is what
the task's definition of done required.

## Canary evidence

`evals/results/company-research-48f9b46a366e-20260731-correctness.md`. Four canaries run,
**4/4 rubric_pass**. Three of the four took the company-scope path.

The full-research canary followed every stated mechanic and grep-verified it: the scope line
verbatim under the title of `08`, `09` and `10`; `[JD-dependent]` tags 5/5/3 in those files;
all 17 files plus README produced; `08`'s subject sourced entirely from currently-open reqs
with **no posting invented** — the file states outright that no req carries the requested
title. The question-bank canary linked forward with `(not yet written)` rather than inlining,
which is the third question this task asked.

It also surfaced the one case the first draft did not cover: the requested role family may
not exist on the ATS board at all. That is now instructed (enumerate the closest real reqs,
name the ambiguity, never invent a posting) — see the worklog.
