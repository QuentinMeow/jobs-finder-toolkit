# Worklog — 2026-07-31-sponsorship-negation-defeats-require-positive

## 2026-07-31 — session 1 (agent, branch `wip/22-sponsorship-negation`)

- Reproduced all three defects against `automation/shared/job_metadata.py` at
  `HEAD` before touching anything; captured the baseline in `verification.md`.
- Sponsorship: replaced "denial list wins" with a **negation scope**. Phrase lists
  still detect evidence; polarity is decided structurally, so an offer phrase
  inside a negated clause becomes a denial of that offer regardless of wording.
  Scope = NegEx-style look-back, ≤8 tokens, cut at the nearest clause boundary.
- Chose `unknown` (kept + flagged) as the fallback everywhere the reading is
  ambiguous, because `unlikely` hides a job and `likely` sends someone who needs
  sponsorship to an employer that said no. Double negation therefore returns
  `unknown` rather than guessing which way it flips.
- Two more defects arrived mid-task from the same audit; folded in rather than
  split, since all three live in one file and would have collided:
  third-party YOE attribution, and export-control "sponsorship" read as an
  immigration denial.
- Deliberately NOT fixed: denials that match no phrase at all, and the un-gated
  generic denial phrase ("we do not sponsor community events" -> `unlikely`).
  Both are recorded with a concrete suggested fix in
  `memory/known-issues/visa-sponsorship-negation-phrase-gap.md`; a second
  heuristic in a hard gate needs its own measurement pass.
- Next: review + merge. Nothing is blocked.
