# Approach 3 — Explicit generation modes: `token_saving` (default) vs `full`

**Strategy:** Make the cost/quality dial explicit and user-controlled. One config
switch selects between two documented behaviors: a **token-saving mode** that is the
default for routine search + drafting, and a **full generation mode** for deep
research and final polish.

## How it works

**Plumbing.** `config.yaml`:

```yaml
generation:
  mode: token_saving   # token_saving | full
```

Overridable per run (`--mode full`, or the user simply asks for "full mode"). Each
SKILL.md states what each mode does differently; scripts that behave differently
(e.g. output verbosity) read the same config key.

**`token_saving` (default) semantics:**

| Step | token_saving | full |
|---|---|---|
| Job search execution | Main session runs `search_jobs.py` directly — no subagent for a routine run (the pipeline is deterministic Python; an agent adds ~20k+ tokens of boot tax to relay a table) | Search subagent that iterates on windows/filters, investigates anomalies, reads pipeline source when results look wrong |
| Search output | Compact top-15 table; JSON to file | Full table + per-row reasons, agent commentary |
| Instruction reading | Quickstart header + hard gates only; LESSONS/reference on demand | Full SKILL.md + LESSONS.md + reference.md |
| Candidate context | Tailoring card (~2k tokens) | Full profile + baseline + entire story bank + prior applications |
| Company/JD research for prose | JD text + company registry/cache facts only | Deep per-JD company research (product, launches, team) incl. web fetches |
| Render loop | `estimate_layout.py` then **one** render + check; a second cycle only on FAIL | Iterate until polished (est → render → check → refine) |
| Step 7 skill categorization | Queue new skills to a pending file; ask later in one interactive session | Full one-at-a-time interactive protocol in-run |
| Cover letter | Standard template depth, one pass | Individually researched, iterated per JD |

**`full` semantics:** today's documented behavior, unchanged, plus explicit
permission to research deeply.

**What never changes with mode (the quality floor):** every hard gate stays on in
both modes — blacklist/log/duplicate pre-flight, location gate, `meta.yaml` schema
validation, `check.py` (locked fields, real projects, three skill lists, one-page,
cover-letter checks), no-fabrication rules. Modes change how much *context and
iteration* is spent, never which *validations* run.

## Pros

- **Directly matches real usage.** Bulk pipeline runs (daily searches, first drafts
  of many applications) don't need deep research; the one application the user is
  about to submit does. The dial puts the expensive behavior exactly where it pays.
- **Biggest savings of the three approaches** on the common path — it compounds
  Approaches 1+2 and additionally cuts research fetches, iteration loops, and
  full-library reads.
- **Explicit and auditable.** The mode is recorded per run (e.g. a `notes`/log line in
  the draft), so "this was a cheap draft" is visible when reviewing before submission,
  and an under-researched cover letter is explainable and upgradeable (`--mode full`
  re-run on the same folder).
- **A natural place for model tiering** (cheaper models in token_saving drafting,
  strongest model for full-mode judgment) without hardcoding model names into skills.

## Cons

- **Two behaviors to maintain and eval.** Canary evals must cover both modes or the
  default (cheap) path silently rots — this roughly doubles instruction-eval surface
  for the affected skills.
- **The overhead paradox:** documenting two modes makes SKILL.md *longer*, which
  raises the boot tax that Approach 1 tries to cut. Mitigation: the mode table lives
  in the quickstart; only `full` extras live in the body.
- **Quality drift risk at the default.** Users review drafts less carefully than they
  think; if token_saving cover letters are noticeably weaker and the default is
  token_saving, weaker artifacts can get submitted. Mitigation: the quality floor
  (all validators) is mode-independent, and drafts carry their mode marker so the
  review skill can prompt "re-run in full mode before submitting?".
- **Combinatorics with future features.** Every new pipeline feature must now answer
  "what does it do in each mode?"
