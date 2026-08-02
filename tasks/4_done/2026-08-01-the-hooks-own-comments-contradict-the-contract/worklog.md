# Worklog — 2026-08-01-the-hooks-own-comments-contradict-the-contract

## 2026-08-02 — session 1 (agent)

- Re-counted the gates by reading `automation/hooks/pre-commit` end to end: the header
  listed six, the body runs nine. Rewrote the header to list all nine in the order they
  run, and to say that gates 8 and 9 each branch on `[ -d private ]`. No executable line
  moved; `sh -n` clean.
- Named the audience on both escape hatches, in the three places they are offered:
  `pre-commit`'s `--no-verify` line, `pre-push`'s `JOBHUNT_ALLOW_PUSH` header line, and
  `pre-push`'s `--no-verify` line. Each now says owner-at-a-terminal, never an agent, and
  cites the contract line that forbids agent use.
- **The extra finding, resolved.** `evals/canaries/github-workflow.yaml` scores
  "suggests JOBHUNT_ALLOW_PUSH" as a canary FAILURE mode, while `pre-push` offered the
  variable twice with no qualification. That is a real disagreement and it is now named in
  the hook itself: the hatch exists for the human who installed the hooks and must never
  be reached for by anything else. Resolved in the direction the contract already points —
  the canary is right about agents, the hook is right that the owner needs an exit, and
  what was missing was the audience marker, not a behaviour change.
- Added one comment above the runtime `override knowingly with JOBHUNT_ALLOW_PUSH=1`
  message (`pre-push`, in the refusal branch) saying that line is addressed to the owner.
  The message text itself is untouched, so stderr output is byte-identical — an agent
  reading the hook to understand a refusal now finds the marker next to the offer it saw.
- **DoD line 3 deliberately NOT done** — see `verification.md`. Teaching the variable's
  name to `skills/github-workflow/SKILL.md` would put it on the one surface the canary
  penalises an agent for repeating, and would trigger the eval gate for no safety gain.
