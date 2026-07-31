# Worklog — 2026-07-30-company-research-shipped-vs-beta-needs-a-maturity-check

## 2026-07-31 — session 1 (agent, fix/10-company-research-correctness)

- Verified the task's claims. The headline holds; one detail is overstated. The task says
  the skill's guidance for establishing shipped "is only 'cite the artifact'", but the AI
  Strategy Template already said "with dates and evidence (changelog, blog, release)". The
  real gap is not that the skill names no evidence class — it is that it names no
  *counter*-evidence (what does NOT establish GA), no rule for ambiguity, and no way to
  mark the maturity call in the output.
- Independently reproduced the failure shape live: the docs pricing page of one product
  says "During the open beta, <product> is free within these limits" in its BODY, while
  neither the product-directory entry nor a maturity badge carries that. Same day, the
  product's docs landing page did carry a "Beta" badge — so the reference wording was
  corrected from "a landing page cannot answer it" to "its silence proves nothing", which
  is the claim that actually holds.
- Rejected the task's proposed one-sentence fix. One sentence cannot tell an agent what to
  do when the evidence is ambiguous, and ambiguity is the case that produced the wrong
  calls. Wrote a four-rung ladder with an explicit not-evidence list, a required
  `Maturity unverified` bucket, and per-product inline stage tags with beta duration.
- Took the two "consider also" items: `reference.md` gains a "Maturity fetches" section
  with a tested grep recipe, and `05`'s Evidence bullet now carries the maturity tag
  through, since a beta capability is weaker evidence for a moat.
- Strengthened the `cr-ai-strategy` rubric so a confident wrong answer fails: two new
  expected_behavior bullets (evidence class + the unverified bucket, with a spot-check
  instruction) and two new failure_modes.

### After the canary run (same session)

The runs found the gate's own tooling was broken and fixed six things about the ladder:

- **The `llms-full.txt` grep recipe returned zero hits on a file containing the answer three
  times.** `.` does not match a newline in `grep -E` and those mirrors are hard-wrapped at
  ~31k lines. Under the gate's own rule a zero-hit grep is `Ambiguous`, so the documented
  command manufactured a false hedge on a 16-month open-beta product — the mirror image of
  the failure this task is about. Reproduced by hand, fixed with `tr '\n' ' '`, and given a
  self-check (`grep -c` non-zero + windowed grep empty = the command is wrong).
- The gate did not cover `09`, which is where the candidate says "you've shipped X" out loud
  to X's own engineer. Now in scope.
- A sub-feature needs its own classification: one run found a 27.9-month open beta inside a
  GA product.
- A docs body refreshed after the last beta statement and silent on stage is now its own
  `Ambiguous` case, rather than pinning a product to a stale beta claim.
- A stage word must sit in a sentence about the product — a bare "Beta" in a nav list or a
  blog tag cloud is not a statement (the judge's own spot-check hit a tag cloud first).
- A docs GA banner establishes the stage but often not the date; a dated changelog entry is
  promoted from tiebreaker to a first-class fetch.
