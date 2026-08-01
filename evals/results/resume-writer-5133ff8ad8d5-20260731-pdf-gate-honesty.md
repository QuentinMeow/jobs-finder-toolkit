<!--
Pre-merge regression gate for the "make the resume gates say when they did not run" change
(eca0c33, ancestor of the run SHA): two new FAIL states in check.py (`PDF NOT INSPECTED`,
`SKILL VOCABULARY NOT INSPECTED`), one shared `## Skills` parser under
automation/shared/profile_skills.py (vendored), + 8 lines in SKILL.md / 4 in LESSONS.md.
The SKILL/LESSONS delta is behavioral (new gate-failure handling), so the eval gate triggers.
DELIBERATE SUBSET: 4 of 8 canaries. Scope + why, and what the subset does NOT cover, in
"Scope and limitations of this run" below — read that before treating this as a full gate.
-->
# Eval result — resume-writer

| Field | Value |
|-------|-------|
| Skill | `resume-writer` — **4 of the 8 canaries** (deliberate subset; see Scope below) |
| Canary set | `evals/canaries/resume-writer.yaml` |
| Run kind | regression pre-merge |
| Git SHA | `5133ff8ad8d5` (all four subject runs). Change under test is `eca0c33` (ancestor). Judged from `ee3aec2ef28b`; the only `skills/resume-writer/` file changed between the two is `scripts/_vendor/location.py`, which no canary here touches — so the runs still bound HEAD's resume-writer surface. |
| Model version | `claude-opus-5` — subject runs and this judgement |
| Config mode | examples fallback (`config.yaml` unset). `rw-tailor-single-posting` used the isolated temp-config scaffold its `setup` mandates (GH #16); the three read-only canaries ran against `config.example.yaml`, pinned via `JOBHUNT_CONFIG`. No private overlay. |
| Date | `2026-07-31` |
| Judge | Claude Opus 5 (this file's author), per `evals/rubrics/judging.md` — strict all-bullets-hold discipline, artifacts inspected rather than records believed. The judge performed none of the runs. |

## Scope and limitations of this run

**Four of eight canaries were run. This is not a full gate, and the subset was chosen before the
runs, not after seeing results.** The change under test adds two FAIL states to the render gate and
unifies the profile `## Skills` parser that `check_never_skills` reads. The four canaries below are
the ones that touch that surface:

| Canary id | Why it was in scope |
|-----------|---------------------|
| `rw-tailor-single-posting` | the only canary that renders, so the only one where the PDF gates fire at all |
| `rw-layout-budget-verdict` | the one-page reasoning the PDF gates back up |
| `rw-skill-gating-weak-never` | the Approved/Weak/Never gate that reads the repaired parser |
| `rw-skill-category-question-batch` | the uncategorized-skill queue built on the same parser |

**Not run — recorded as an untested area, not as a pass:** `rw-multi-experience-baseline`,
`rw-bundled-txt-structure`, `rw-multi-role-one-folder`, `rw-duplicate-preflight`. All four exercise
folder shape, multi-role fan-out, and pre-flight, none of which this change touches.

**The more important gap is that the subset boundary is not where the real hole is.** Neither new
FAIL message was produced in any of the four runs (evidence in the Verdict). Running the other four
canaries would not have produced them either — they render on a machine that has a converter and
read a profile whose `## Skills` section parses. See "Coverage of the change under test" for what
this does and does not license.

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `rw-tailor-single-posting` | 1 \* | 136,739 | 716 | 51 | Pre-flight before any write (tracker folder scan, registry `is_blacklisted` → False, `--check-locations` ok, absent skip-log), `cp` baseline→`tailored.yaml`. **Judge re-ran `check.py` on the surviving artifact: `✓ all checks passed (1 warning(s))`, exit 0**; independently diffed `name`/`contact_line`/`education_line` and the employer `company`/`role`/`dates`/`location` against the baseline — all identical; all 5 project titles match `[draft]`/`[backup]` profile headings; both PDFs re-counted at 1 page; bundled `.txt` carries the three `===` sections. \* **Bullet 5 half not evaluable:** Step 7 ran (`skills_diff.py` → `no uncategorized skills`), so the batched-question format could not be exercised. Efficiency: tokens mid-band (prior runs 113k–160k), tool calls in band, **wall clock 716s is the highest ever recorded for this canary** (prior max 645s) — the record self-reports 4 layout-estimate cycles where 2 would have done. |
| `rw-layout-budget-verdict` | 1 | 76,322 | 214 | 12 | `estimate_layout.py` run before any render; OVERFLOW **739pt / 734pt** (the stable value every prior run of this canary reports); tied to the ~734pt budget and the ≤~715pt one-shot target; trims simulated on a scratch copy (739 → 716 TIGHT → 704 OK) rather than asserted; explicitly kept all five projects and added no filler; stated `check.py`'s post-render page count is the authoritative gate and the estimate a pre-check. Read ~130 lines of `estimate_layout.py` source — permitted (only `check.py`'s source is off-limits) but a step off the routine path. **Efficiency (corrected 2026-07-31):** tokens are **not** the highest for this canary — the real prior band is 53k–**78k** and 76,322 sits below the 78,104 max. The original "prior band 54k–68k, +14% over the max" dropped that row. |
| `rw-skill-gating-weak-never` | 1 | 80,351 | 232 | 18 | Rust declined (Never), Kafka withheld (Weak, and the stored JD names neither term — judge confirmed: `grep -niE "kafka\|rust"` over the JD returns nothing, the closest line is "high-throughput messaging and queueing systems"). Not asserted but proved: a throwaway copy with both terms added returned the three real FAILs, including `Blocklisted skill 'Rust' (profile 'Never' list)`. Weak framed as JD-conditional, not as low proficiency ("Nothing about your Kafka experience is in question"). Zero writes. **Defect outside the rubric — see Verdict:** the run told the user "LibreOffice isn't installed in this checkout"; it is installed and the toolkit's own resolver finds it. **Efficiency (corrected 2026-07-31):** tokens **+7.6%** over this canary's real prior max (43k–**75k**), wall clock 232s against a prior **94–231s**. The original "+21% over prior max (43k–66k) … 97–142s" dropped one tracked prior row; see § Efficiency. |
| `rw-skill-category-question-batch` | 1 | 77,742 | 173 | 13 | Both terms confirmed uncategorized by running the real queue tool (`skills_diff.py` on a scratch probe JD → `OpenTelemetry` / `WebAssembly`), so no alias silently folded OTel into Approved `observability`. ONE interaction, exactly two one-skill questions, no serial turns, no combining; the three consequence labels verbatim in the mandated Never → Weak or Selective → Approved order with **Other** last; "Weak or Selective" used as the user-facing alias with an explicit refusal to rename the stored `### Weak` subsection; neither term categorized. **No interactive question tool existed** (ToolSearch for `AskUserQuestion` → no match), so the questions were written out per SKILL.md Step 7 item 5 — judged to satisfy the bullet; see "Checks that could not be evaluated". Tokens above the prior band (52k–69k). |

Pass rate: `4/4` of the canaries run; `4/8` of the canary set exercised.

## Checks that could not be evaluated

Recorded rather than passed, because a check nobody could exercise is not evidence:

1. **`rw-tailor-single-posting`, bullet 5, second half** — "asks one single-select question per skill
   in ONE batched interaction, and uses this option order in every question". `skills_diff.py`
   returned `no uncategorized skills`, so there was no question to ask. The first half (ends by
   running Step 7 and gathering the complete queue) **is** met, with the tool's own output behind it.
   This is not a run defect: with the shipped example JD and profile, every JD term is already
   categorized, so this bullet's format half is structurally unexercisable on this fixture and has
   been "legitimately empty" in every prior recorded run of this canary too. **Canary-set finding:**
   the batched-question format in this canary is dead weight — `rw-skill-category-question-batch` is
   its only real coverage. Either give this canary a JD carrying one uncategorized term, or delete
   the clause and stop implying coverage that does not exist.
2. **`rw-skill-category-question-batch`, bullet 1, the "question objects" mechanism** — no
   interactive question tool exists in this environment, confirmed by the run's own ToolSearch
   probes. **Judged MET on the substitute**, deliberately and not generously: every property the
   bullet guards (one batched interaction, exactly two questions, one skill each, not serial, not
   combined, not multi-select) is observable in the written batch and holds, the failure modes are
   all absent, SKILL.md Step 7 item 5 prescribes exactly this fallback for a non-interactive run,
   and the rubric's own bullet 3 already contemplates a non-tool path. The single property genuinely
   lost — machine-enforced single-select — is presentational, not the regression this canary guards.
   The run flagged the substitution itself.
3. **`rw-skill-gating-weak-never`'s converter claim** — the run reported LibreOffice absent and used
   that as a reason not to edit. It is not a rubric bullet either way (no bullet in this canary
   involves rendering), and it is **factually wrong** — see Verdict.

## Verdict

- **Regression: PASS on the four canaries run. Does not block the merge.** Every
  `expected_behavior` bullet that could be evaluated held, on evidence the judge reproduced rather
  than read: `check.py` re-run to exit 0 on the surviving `rw-tailor-single-posting` artifact,
  locked fields and project titles diffed against the baseline and the profile, both PDFs re-counted
  at 1 page, the bundled `.txt` sections listed, and the JD independently grepped for the Rust/Kafka
  false premise. No listed `failure_mode` was observed in any run. Two checks are recorded as not
  evaluable above and are not counted as passes.

- **Coverage of the change under test — the honest limit of this evidence.** `eca0c33` has two
  halves. Its **code** half is well covered: `check.py` exits 0 with no `PDF NOT INSPECTED` and no
  `SKILL VOCABULARY NOT INSPECTED` on a healthy render (`rw-tailor-single-posting`, reproduced), and
  the unified parser resolves the three lists correctly in two independent runs — `rw-skill-gating-weak-never`
  read Approved/Weak/Never off the example profile and `check.py` enforced all three, and
  `skills_diff.py` (same matcher) returned exactly the two uncategorized terms in
  `rw-skill-category-question-batch`. A parser that regressed to the empty-vocabulary bug would have
  surfaced as a bogus pass in the first or a wrong queue in the second. That is real regression
  evidence and it is clean.
  Its **instruction** half is not covered at all. The 8 added SKILL.md lines tell an agent what to do
  *when it sees* the two new FAIL messages, and **neither message was produced in any of the four
  runs**. `PDF NOT INSPECTED` was reasoned about but never seen (`rw-skill-gating-weak-never` argued
  from a converter it wrongly believed absent, and never rendered); the `SKILL VOCABULARY NOT
  INSPECTED` guidance — notably "do NOT start asking the user to categorize skills", which
  deliberately cuts against Step 7 — was never exercised in any form.

- **Is a four-canary subset adequate evidence for this change?** For the merge, yes: the subset is
  correctly targeted, it is the only subset that touches the changed surface, and it shows no
  regression on the paths a user actually walks. But **the four canaries not run are not the missing
  evidence, and running them would not add any** — they would render on the same converter-equipped
  machine and read the same parseable profile, producing neither new message. The gap is in the
  canary *set*, not in this run's scope: nothing in `evals/canaries/resume-writer.yaml`, all eight
  included, can produce either FAIL state. Closing it needs a new canary (a render with the converter
  hidden via `JOBHUNT_SOFFICE`, and a profile whose `## Skills` section does not parse), or an
  explicit, recorded decision that the shipped unit tests — `skills/resume-writer/scripts/tests/test_pdf_gate_reporting.py`
  and `automation/shared/tests/test_profile_skills.py` — are the accepted coverage for the failure
  paths. Judge's recommendation: file the new canary; the SKILL.md text being gated is precisely
  agent-behavioral, which unit tests cannot reach.

- **A false environment claim was delivered to the user (`rw-skill-gating-weak-never`).** The run
  probed `which soffice libreoffice` plus `/Applications/LibreOffice.app/...`, got nothing, and told
  the user "LibreOffice isn't installed in this checkout, so I can't re-render". `pdf_convert.LO_PATHS`
  checks `~/Applications/LibreOffice.app/Contents/MacOS/soffice` **before** the system path the run
  tested; the judge resolved `pdf_convert._find_soffice()` on the same machine and it returns that
  path, and `rw-tailor-single-posting` converted two DOCX files to PDF on that machine within the
  same hour. The conclusion was a probe artifact stated as fact, and it was one of two reasons the
  run gave for withholding a gate-legal Approved-term edit. No `expected_behavior` bullet in this
  canary covers rendering, so `rubric_pass` stands at 1 under the all-bullets rule — but this is the
  kind of confident-and-wrong environment claim no canary currently penalizes, and it is worth an
  owner decision (add an "environment claims must use the toolkit's own resolver" line, or a rubric
  bullet, or neither).

- **Content judgement call (`rw-tailor-single-posting`), judged against the bullets, not taste.**
  The run swapped one project 1-for-1 — dropped `[draft] Customer onboarding automation service`,
  added `[backup] CI/CD pipeline modernization` — and asked the user to confirm. Bullet 2 requires
  project titles to match `[draft]`/`[backup]` profile projects; both do (judge-verified against the
  profile headings), the count stayed at 5, and no failure mode covers a swap. The profile's own rule
  allows a `[backup]` project when it is a significantly better fit, and the JD lists "Experience with
  Terraform, CI/CD, and Git-based workflows" under required qualifications, so the swap has a
  documented basis. **Not a fail.** Surfacing it for confirmation is neither credited nor penalized.

- **Efficiency vs baseline:** recorded, not scored, and **not merge-blocking**. **Corrected
  2026-07-31: the two middle rows were wrong, and both overstated the deviation.** The prior
  ranges were re-derived by extracting every tracked numeric row for each canary id from
  `evals/results/*.md`; two of the four ranges silently dropped their own highest-token row while
  still using that row's call count and wall clock for the other two bounds. Corrected, **one**
  canary came in above its historical token max, not three.

  | Canary id | This run | Prior recorded range | Read |
  |-----------|----------|----------------------|------|
  | `rw-tailor-single-posting` | 136,739 tok / 51 calls / 716s | 113k–160k / 32–59 / 465–645s | tokens and calls mid-band; **wall clock a new max** (+11% over the prior worst), consistent with the record's self-reported 2 wasted layout cycles. Verified — this row was right |
  | `rw-layout-budget-verdict` | 76,322 / 12 / 214 | **53k–78k** / 6–27 / 67–313s | **below the prior token max** (78,104, in `…-19c3ff8-20260720.md`). The stated band "54k–68k" excluded that row while its own 27 calls and 313s set the other two bounds. The claim "+14% over prior max" is false, and false in the wrong direction |
  | `rw-skill-gating-weak-never` | 80,351 / 18 / 232 | **43k–75k** / 11–**22** / **94**–**231s** | **+7.6% over prior max** (74,643 tok, in `…-8d4c06c-20260720.md`), **+0.4% wall clock** (232s vs 231s), calls in band. "+34% over median" is correct — median of the 8 prior rows is 60,050 — which is the tell: two statistics in the original sentence were computed over different row sets |
  | `rw-skill-category-question-batch` | 77,742 / 13 / 173 | 52k–69k / 6–10 / 64–113s | **tokens +12% over prior max**; explained by the ToolSearch probes and the probe-JD queue run. Verified — this row was right |

  Prior token rows, for anyone re-deriving these: `rw-skill-gating-weak-never` 42,954 · 57,660 ·
  59,650 · 60,046 · 60,054 · 66,136 · 66,464 · **74,643**; `rw-layout-budget-verdict` 53,150 ·
  54,394 · 62,989 · 65,141 · 67,187 · 67,363 · 67,552 · 67,950 · 72,381 · **78,104**.

  **The comparison is confounded and should not be read as a harness regression.** These four
  subjects were each instructed to author a detailed evidence record inside the measured session;
  the prior rows were not. That authoring, plus the probes it motivated (the `check.py` FAIL probe,
  the probe JD, the artifact re-listing), sits inside `total_tokens` and `tool_calls` here. The
  numbers are directionally up across the board by a similar margin, which is what a fixed per-run
  overhead looks like — not what a skill-instruction regression looks like (that would concentrate
  in the canaries touching the edit). No single canary shows a blow-up of the order the README's
  eval-gated-merge rule treats as failing on its own. **Re-measure without the record-writing
  instruction before treating any of these as a baseline**, and do not use this table as the
  comparison row for the next gate.

## A/B section (only for run kind = A/B)

Not applicable — this is a regression pre-merge run, not a matched-pair A/B. No variant B was run,
no primary metric was pre-registered, and no blind pairwise quality read was taken. The efficiency
table above is a historical comparison against previously recorded rows, not a paired A/B, and
carries no significance claim.

## Stage row (only for run kind = stage A/B)

Not applicable — no stage fixture was pinned and no matched pairs were run.
