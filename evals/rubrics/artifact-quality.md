# Artifact-quality rubric — tailored-application audit

Purpose: a **self-contained, cheaply re-applicable** rubric for scoring one drafted application
folder (0/1/2 per dimension). Usable on the public "Jordan Rivers" example and on any private overlay
alike — all candidate-specific ground truth is reached through config accessors, never hardcoded
paths. A fresh grader needs only:

1. this file,
2. the application folder (`<slug>/` with `meta.yaml`, `notes.md`, `source/tailored.yaml`,
   `source/JD-*.md`, the bundled `..._Application_<role>.txt`, resume PDF),
3. the ground-truth sources (paths via config, so this rubric is identity-free):
   - profile (source of truth): `config.profile_md_path()`
   - baseline resume: `config.baseline_path()`
   - supporting library (traceability): the story bank and answer bank under the overlay's
     `interviews/`, plus any role-description reference kept beside the profile
     (see `docs/AGENTS-ANNEX.md` §12 "supporting library")
   - tailoring card: `<applications_root>/0_profile/tailoring-card.md`

Grounded in the repo's own gates: `evals/rubrics/judging.md` (strict pass/fail, judge the artifact
not the prose), `AGENTS.md` "Guardrails", `.agents/skills/resume-writer/SKILL.md` (three-list skill
gate, no-fabrication, cover-letter structure), and the machine checks in
`.agents/skills/resume-writer/scripts/check.py` + `.../application-tracker/scripts/status.py`.

## Scoring discipline (read first)

- **0 = fail, 1 = partial, 2 = good.** Borderline → round DOWN and write one line why
  (a false pass hides a regression; a false fail just prompts a re-run — `judging.md`).
- **Judge the artifact, not the claim.** A tailoring-note comment that *says* "no fabrication"
  earns nothing; trace the actual bullet. Inspect files, run the scripts.
- **Any Never-list token on the resume, or any fabricated metric/technology, caps the app's
  overall verdict at "regenerate"** regardless of other scores (these are hard guardrail breaches).
- Record per-dimension score + 1–2 lines of `file:line` evidence. Note whether a defect is
  **SYSTEMIC** (same pattern in ≥2 apps) or **one-off**.

## Mechanical pre-checks (run once per app, read-only — NEVER run render.py)

```bash
# Resume + cover-letter validity (resolves baseline/profile from config; no rendering):
.venv/bin/python .agents/skills/resume-writer/scripts/check.py <app_folder>/
# Metadata schema v4 + location policy (a private overlay tree needs its JOBHUNT_CONFIG;
# the benchmark tree needs the benchmark config):
JOBHUNT_CONFIG=<config> \
  .venv/bin/python .agents/skills/application-tracker/scripts/status.py --check-metadata
JOBHUNT_CONFIG=<config> \
  .venv/bin/python .agents/skills/application-tracker/scripts/status.py --check-locations
```
`check.py` also prints a bullet-drift ratio (`N/M bullets differ from baseline`) and
bottom-of-page fill warnings — capture both, they feed D2 and D6.

> Drift caveat (critical): `check.py` validates against the **current** profile/baseline.
> If the profile/baseline changed after a draft was made, the draft can fail for a token
> that was valid when written (e.g. a later baseline edit canonicalized `Distributed System`→
> `Distributed Systems` and `codex`→`ChatGPT Codex`; another reworded a phrase to clear a
> `Harness` Never-list false positive). Before blaming the draft, `git log` the profile/baseline
> and label such failures **DRIFT** vs **DRAFTING**.

---

## Dimension 1 — JD requirement / keyword coverage (tailored resume)

Extract the JD's explicit requirements (`source/JD-*.md`: "required"/"must have", core
responsibilities, named technologies). Count how many the resume **honestly** surfaces
(mirrored keyword in a skill line, summary, or bullet the candidate can truthfully claim).
Do NOT penalize for honest gaps on off-profile requirements — that is D5.

- **2** — resume surfaces (near-)all *addressable* JD requirements; projects reordered to
  JD relevance; JD-relevant Approved/Weak terms present in the skills line.
- **1** — surfaces some, but omits clearly-coverable JD terms, OR the JD's core is largely
  off-profile so genuine coverage is thin even after honest tailoring.
- **0** — little JD alignment; generic baseline with no meaningful tailoring to this JD.

## Dimension 2 — Traceability / no fabrication (sample 8–10 bullets)

Sample 8–10 tailored bullets (summary + project). Trace each to real content: profile,
baseline, story bank, answer bank, role-description reference. Enrichment with a real,
documented detail is allowed; inventing metrics/tech/scope is not.

- **2** — every sampled bullet traces to a real source; any enrichment is documented;
  no invented metric/technology/title.
- **1** — one borderline unverifiable embellishment (e.g. an unstated scale figure such as
  "thousands of nodes") but no hard fabrication.
- **0** — any fabricated metric, technology, title, or scope not in the profile/library.

Flags to check explicitly: quantified claims ("cut X by N%", "in half", "$NNNk"),
named technologies not in the profile, and heavy full-rewrites (drift ≥ ~80%) — a 100%
rewrite is not itself a fail but raises fabrication risk, so trace those apps hardest.

## Dimension 3 — Skill-list compliance (three-list gate)

Parse the profile's Approved / Weak / Never lists (`## Skills`). For every skill token on
the resume (skills lines, summary, bullets):

- **2** — no Never-list token anywhere on the resume; every Weak token has a matcher-verifiable
  JD mention; every skill token matches a canonical Approved/Weak form. `check.py` reports 0
  skill FAILs.
- **1** — no Never token, but a Weak skill lacks a JD mention, OR an Approved/Weak token is a
  non-canonical surface form that fails the exact-match gate (e.g. `autoscaling` vs profile
  `autoscaling (Kubernetes)`; `codex` vs `ChatGPT Codex`).
- **0** — a **Never-list token appears on the resume** (real leak OR false positive such as
  `harness` matching `Harness`). This is the highest-severity skill breach.

## Dimension 4 — Cover-letter specificity (bundled `.txt`, COVER LETTER + WHY sections)

Count concrete, verifiable, company/JD-specific claims (named team, product, architecture
fact, scale figure, quoted value) vs. boilerplate flattery.

- **2** — ≥3 concrete, verifiable company/JD specifics; no generic filler; claims about the
  candidate are traceable. (Company-fact mentions of Never-list tech — e.g. correctly describing
  a target company's own observability or storage stack — are fine; the Never list gates the
  *resume's skill claims*, not factual research about the target company.)
- **1** — some specificity but leans on generic language, or specifics are thin/unverifiable.
- **0** — boilerplate; interchangeable with any company; placeholder text (`check.py`
  `COVER_PLACEHOLDER_RE`).

## Dimension 5 — Honest-fit framing (stretch roles)

For a stretch/partial-fit JD, is the gap named honestly (one clause, reframed as fast-ramp)
rather than oversold? (`AGENTS.md`: "Honesty over optimization".)

- **2** — real gaps named plainly in the cover letter/notes; no invented experience to close
  them; strong-fit roles simply not oversold.
- **1** — gap acknowledged weakly or buried; mild overreach in framing.
- **0** — a genuine gap is papered over or the letter claims fit the candidate does not have.

## Dimension 6 — Structural validity (machine gates)

- **2** — `check.py` passes (0 FAIL; warnings OK); `status.py --check-metadata` = ok;
  `--check-locations` = match; PDF is 1 page with text.
- **1** — metadata + location pass, but `check.py` has FAILs that are token-form / DRIFT
  in nature (not fabrication, not Never-list).
- **0** — `check.py` fails on a Never-list token or fabrication, OR metadata/location fails,
  OR PDF is not 1 page / not extractable.

## Dimension 7 — Bundled `.txt` packet completeness

Required (`SKILL.md` "Bundled .txt structure"): one `..._Application_<role>.txt` **per JD**,
each with the three canonical sections in order — `COVER LETTER`, `WHY THIS COMPANY & ROLE`,
`PAST EXPERIENCE` (title line + `===` underline), plain text only, cover letter has
name+contact → salutation → ≥2 developed paragraphs (60–180 words each, 200–450 total) →
`Sincerely,` + name. Add `APPLICATION QUESTIONS` only when the posting shows questions.

- **2** — every JD has its packet; all three sections present & ordered; cover-letter passes
  `check.py`'s `check_cover_letter`; plain text (no markdown/bold/bullets).
- **1** — packet present but one section thin/misordered, or a cover-letter word-count warn.
- **0** — a JD is missing its packet, a canonical section is absent, or markdown/placeholder leaks.

---

## Overall verdict per app (roll-up)

- **SHIP-CLEAN** — all dims ≥1 and D2=2, D3=2, D6=2 (passes every hard gate).
- **FIX** — no Never token, no fabrication; ≥1 dimension at 1 from token-form/DRIFT/Weak-JD.
- **REGENERATE** — D2=0 (fabrication) or D3=0 (Never-list token) or D6=0.

Report per app: 7 scores, overall verdict, and every defect with `file:line` + SYSTEMIC/one-off.
