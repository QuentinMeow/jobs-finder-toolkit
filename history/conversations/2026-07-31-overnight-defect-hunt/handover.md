# Handover — 2026-07-31 overnight defect hunt

- **Date**: 2026-07-31
- **Task(s)**: fifteen backlog items closed or advanced; see each PR's "What was filed"
  section for the mapping

An overnight session that went looking for defects rather than building features. Three
adversarial audits read the code, five live job searches ran against real boards as canary
runs, and one agent spent its whole run trying to break the largest change in the stack.
Between them they found more than sixty confirmed defects. Forty PRs fix or record them. Nothing is merged.

## What happened

- **A 40-PR public stack, `#135`–`#174`**, each branch on the one below, bottom PR on `main`.
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

*Counts below are true of this file's own commit. This handover sits inside the stack it
describes, so any PR added above it makes its numbers stale — which happened three times
tonight. `gh pr list --state open` is the authority; this is orientation.*

- **All 40 PRs are open and green, none merged.** Merge bottom-up, `#135` first, one at a
  time. Expect `main`'s CI to go red after each merge until a reconciliation row is
  appended — that is the documented cost of stacking here, not a regression, and
  `skills/github-workflow/SKILL.md` has the recovery.
- **The eval gate is discharged for the job-search PRs below `#163`** — the full canary set
  was run at that head and recorded. **Two PRs still owe a run and say so:** `#161`, which
  needs the behavioural-prep canaries, and `#165`, which changed job-search instruction files
  *after* the run. Neither records a skip it could not justify.
- **`#161` must not merge until `examples-reshape-seven-calls.md` D5 is answered.** It
  implements D5's own recommendation, whose default path is "this piece is dropped". If the
  answer is no, close it. `#161` is the PR whose own title ends "(BLOCKED on D5)" and whose
  commit `ac34371` changes five `.py` files; `#162` (`9d31abe`) changes one markdown file —
  this handover — and gates nothing. **Corrected 2026-08-01:** all three D5 references in
  this file said `#162`, which would have put the decision gate and the owed canary run on a
  documentation-only PR and merged the actually-blocked one unexamined.
- **The PR bodies for `#135`–`#159` were re-measured and rewritten**, and so were eight
  tracked records. Each was originally measured in its authoring agent's isolated worktree and
  never re-run after integration; **all 25 were wrong, and seven of eight tracked
  `verification.md` files carried a figure that was false at the commit that published it.**
  The mechanical fix is filed as
  `tasks/0_backlog/2026-07-31-pr-verification-blocks-are-measured-off-the-stack/`.
- **That corrections pass did not hold, and a third pass on 2026-08-01 was needed.** Two
  things went wrong. The pass **published new false numbers of its own** — `#164`'s
  Verification block pairs `#163`'s reference count with `#162`'s "refs NOT verified" figure,
  so the line it published matches no commit in this history, and it wrote a reference count
  into `tasks/3_in-review/2026-07-31-gate-documented-commands/verification.md` that no commit
  reports. And it **did not cover the thirteen PRs above it**: re-measured at each PR's own
  substantive commit in a config-less clone, **nine of `#160`–`#172` publish a false
  `verify_links` count** and only `#167` is right, with four more carrying stale suite counts.
  All are corrected in the bodies as of 2026-08-01. Why this recurs, and the one rule that
  ends it, is written once in `skills/github-workflow/SKILL.md` §1 — not repeated here.
- Three findings were **accepted rather than fixed**, each with the reason in the code and a
  task filed. One of them, sweeping the blob store, would have re-added exactly the
  unattended delete path the PR below it had just hardened against.
- **The canaries were run twice — before the stack and at its head — and the second run is why
  `#165` exists.** It caught a regression the stack itself introduced: the sponsorship fix
  over-corrected and made the strict `require_positive` filter return zero roles where it had
  returned dozens. Fixed, then re-run: 59 roles, all 59 labels verified against their own JD
  text. That loop is the single best argument for running canaries at head rather than trusting
  unit tests. **Corrected 2026-08-01:** this bullet credited `#171`. `#165` (`bfd3e11`) is the
  only commit in the range that touches `job_metadata.py`, `scoring.py` and the sponsorship
  corpus; `#171` (`c416c2d`) changes `build_postings.py` and its test and contains no
  sponsorship code.
- **The store's byte-identity contract was unproven.** Its equivalence test rebuilt in place, so
  for every carried entity it compared a value to itself. Repaired, it catches nothing on its
  own — because no fixture ever built the class it had stopped covering — so a fixture where the
  paths genuinely diverge was added alongside it.

## Needs your attention

Twenty-five decision items are open, twelve of them filed tonight (one of those
arrived already answered — the sponsorship fix settled it, and it is marked
`resolved-by-implementation` with an ADR). All carry a default path,
so nothing is blocked. (**Corrected 2026-08-01** — this read 24 / 11 / nineteen. Counted at
`d1fdba6`: `git ls-tree` gives 26 entries under
`message-queue/needs-human/decisions/`, of which one is the folder `README.md`, so **25**
items; `git diff --diff-filter=A origin/main d1fdba6` over that folder gives **12** filed
this session. `#171` added the twelfth after the count was taken and it was never re-run.)
The ones that actually change what happens next:

- [`examples-reshape-seven-calls.md`](../../../message-queue/needs-human/decisions/examples-reshape-seven-calls.md)
  — D5 gates `#161` specifically. Seven calls, answer all or none.
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

The remaining twenty are lower stakes and each states its own default.
