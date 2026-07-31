# Worklog — 2026-07-30-company-research-read-completely-defeats-its-own-pointers

## 2026-07-31 — session 1 (agent, fix/10-company-research-correctness)

- Verified the claim and found it understated. The task names two conflicting instructions;
  there were three. `reference.md`'s own header line said "Read this reference before live
  research and again before writing company-research outputs" — a second copy of the
  blanket read, inside the file the pointers point into. The task does not mention it.
- Re-measured before choosing, as the task asked: `reference.md` was 13,220 bytes (~3.3k
  tokens), matching the task's estimate.
- Chose option 1, **scope the blanket read**. Option 2 (drop the triggers) leaves the whole
  file read every run and gives up the headroom the retiering bought; option 3 (split the
  file) is churn for the same effect. Scoping makes the pointers real at the lowest cost.
- The deciding argument is not the tokens. 3.3k out of runs costing 125k-1.2M is 0.3-2.6%.
  It is that a self-contradicting instruction file is non-deterministic: an agent that
  resolves it one way this run and the other way next run is the actual defect.
- Measured the result: always-read drops from 15,071 bytes (~3.8k tokens, whole file) to
  6,374 (~1.6k) across the three named sections — a ~58% cut in the always-read portion,
  even though the file itself grew by the new "Maturity fetches" section.
- Added the sentence that stops the contradiction from being re-derived: the per-file
  pointers "are the complete list — nothing here asks you to read `reference.md` end to
  end." Left the two "read ONLY §" pointers as they are; they now agree with the header
  instead of fighting it.

### After the canary run (same session)

Two corrections to the first draft, both reported by runs without being asked:

- **A sixth pointer was hiding in `09`'s prose** and conflicted with `09`'s own Trigger. A run
  followed the narrower one and wrote `09`'s required pitch without ever seeing the template
  that defines its shape. The `09` Trigger now names both sections it needs.
- **"Nothing asks you to read `reference.md` end to end" was an overclaim.** A full-folder run
  fires every per-file pointer and the union is the rest of the file. The honest statement —
  now in both files — is that the tiering buys `SKILL.md` budget headroom and saves tokens on
  a single-file request only.
