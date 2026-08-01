# Handover — 2026-07-31 overnight defect hunt

- **Date**: 2026-07-31
- **Task(s)**: fifteen backlog items closed or advanced; see each PR's "What was filed"
  section for the mapping

An overnight session that went looking for defects rather than building features. Three
adversarial audits read the code, five live job searches ran against real boards as canary
runs, and one agent spent its whole run trying to break the largest change in the stack.
Between them they found more than sixty confirmed defects. Twenty-six PRs fix or record
them. Nothing is merged.

## What happened

- **A 26-PR public stack, `#135`–`#160`**, each branch on the one below, bottom PR on `main`.
  Roughly a third are gates that reported success without inspecting anything; a third are
  silent false negatives in the job pipeline — a registered company board that had been
  returning 404, a location gate printing confident rejections for postings it had actually
  marked "review", a sponsorship classifier reading "we do not offer visa sponsorship" as an
  explicit offer; the rest is a store rewrite, the eval records, and the questions only the
  owner can answer.
- **The canary runs paid for themselves twice over.** Nine live runs across two skills were
  executed for the eval gate, judged by agents that performed none of them. They came back
  4/5 and 4/4 — and along the way found five product defects that no amount of reading would
  have surfaced, because they only appear against real job boards.
- **An attack on the store rewrite broke it.** The incremental build's contract is
  byte-identical output versus a full rebuild. Annotating one half of a duplicate pair
  silently deleted its duplicate link — no crash, no refusal, from a documented workflow,
  and only `--rebuild` restored it. The fix went **inside** that PR rather than above it, so
  merging bottom-up never lands a known corruption on `main`. Six branches were rebased for
  that, and they say so in a comment.
- **An independent verification of the whole stack found the stack's own records wrong.**
  The leak cross-reference was clean — 266 tokens including 243 private application slugs,
  against the full 28k-line diff, every PR body and every commit message, zero hits. But
  roughly twenty verification claims in the PR descriptions were false, nearly all from one
  mechanical cause: each was measured in its authoring agent's isolated worktree and never
  re-run after integration. That is the integrator's error, not the authors'. It is being
  corrected across every PR, and the root-cause fix is filed.

## Where things stand

- **All 26 PRs are open and green, none merged.** Merge bottom-up, `#135` first, one at a
  time. Expect `main`'s CI to go red after each merge until a reconciliation row is
  appended — that is the documented cost of stacking here, not a regression, and
  `skills/github-workflow/SKILL.md` has the recovery.
- **Three PRs have an unmet eval gate and say so in their bodies.** The job-search canaries
  need one run at the final stack head, which covers all three at once — `evals/README.md`
  says a run at head covers the accumulated state.
- **`#160` must not merge until `examples-reshape-seven-calls.md` D5 is answered.** It
  implements D5's own recommendation, whose default path is "this piece is dropped".
- Three findings were **accepted rather than fixed**, each with the reason in the code and a
  task filed. One of them, sweeping the blob store, would have re-added exactly the
  unattended delete path the PR below it had just hardened against.

## Needs your attention

Twenty-three decision items are open, ten of them filed tonight. All carry a default path,
so nothing is blocked. The ones that actually change what happens next:

- [`examples-reshape-seven-calls.md`](../../../message-queue/needs-human/decisions/examples-reshape-seven-calls.md)
  — D5 gates `#160` specifically. Seven calls, answer all or none.
- [`title-prefilter-hardcoded-seniority-words.md`](../../../message-queue/needs-human/decisions/title-prefilter-hardcoded-seniority-words.md)
  — needs you to open your overlay search profile; no agent here could read it. If
  `titles.exclude` already covers Principal/Distinguished/Fellow/scientist titles, the
  fetcher's hardcoded list can go. If not, removing it would let those titles consume the
  per-board fetch budget and push wanted roles out entirely.
- [`re-enrich-yoe-after-attribution-fix.md`](../../../message-queue/needs-human/decisions/re-enrich-yoe-after-attribution-fix.md)
  — applications enriched before tonight may carry a required-YOE figure lifted from the
  company's own history ("our founders bring 25 years"). Re-running `--enrich-metadata`
  fixes it but recomputes every other field, so it is your call on your data.
- [`store-gc-execute-agent-runnable-or-owner-only.md`](../../../message-queue/needs-human/decisions/store-gc-execute-agent-runnable-or-owner-only.md)
  — the contract forbids agents deleting store payloads; a command exists to do exactly
  that and a skill routes agents to it.
- [`2026-07-31-builder-lock-stale-window-vs-liveness.md`](../../../message-queue/needs-human/decisions/2026-07-31-builder-lock-stale-window-vs-liveness.md)
  — the lock-identity fix closed the third-writer case; the stale window itself is a
  liveness-versus-safety trade nobody has measured.

The remaining eighteen are lower stakes and each states its own default.
