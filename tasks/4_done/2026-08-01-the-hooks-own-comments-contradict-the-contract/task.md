# The hooks' own comments list six of nine gates and advertise the bypasses the contract forbids

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: instruction-conflict audit, 2026-08-01
- **Claimed-by**: agent, session 2026-08-02 (branch `docs/26-contract-and-record-corrections`)

## Goal

The tracked hooks are safe to read as documentation, because `CONTRIBUTING.md` sends agents there to
learn what blocks a commit.

## Context

`CONTRIBUTING.md:88` tells the reader to "read `automation/hooks/pre-commit` for what it actually
runs". Two things they find there are wrong for an agent.

1. **The header enumerates six blocking conditions; the file runs nine.**
   `automation/hooks/pre-commit:4-14` lists (1) staged `private/` paths, (2) the leak guard over the
   staged index, (3) the public review gate, (4) vendored-copy drift, (5) the mail send-less policy,
   (6) `compileall`. The body then also runs `automation/metrics/instruction_budget.py --strict`
   (`:114-116`), `automation/reconcile/reconcile.py --check [--require-roots]` (`:127-133`) and
   `automation/gardener/verify_links.py [--require-roots --no-overlay]` (`:150-156`).
   `docs/handbook/repo-map.md:57` has the correct nine and says "The hook file itself is the list —
   read it rather than trusting this row", which is exactly the wrong advice while the list in the
   file is short by three. The instruction-budget gate in particular appears in no contract surface,
   and it is the one most likely to block an agent that is *adding* documentation.

2. **The comments offer the escape hatches `AGENTS.md` forbids.**
   `automation/hooks/pre-commit:23` — "`# Bypass in an emergency with:  git commit --no-verify`" —
   and `automation/hooks/pre-push:32` for push, against `AGENTS.md:238-241` ("never bypass with
   `--no-verify`") and `skills/github-workflow/SKILL.md:338-344` ("Never `--no-verify`"). Worse,
   `pre-commit:18` reasons five lines earlier that checks 1-3 "have NO env-var escape hatch by
   design (see AGENTS.md)" — so the file both argues against hatches and hands one over.
   `automation/hooks/pre-push:26` documents `JOBHUNT_ALLOW_PUSH=1`, which skips the content leak
   guard entirely and appears in no document in the repo, while
   `skills/github-workflow/SKILL.md:254` describes that gate as an unconditional refusal.

Neither is a behaviour change: the hatches exist for the human installing the hooks and should stay.
What is missing is the audience marker — "for the repo owner, never for an agent" — which is the
same fix `CONTRIBUTING.md:94-101` already applied to the stacked-PR disagreement.

## Definition of done

- [ ] `automation/hooks/pre-commit`'s header lists every gate the file runs, in order, with the two
      `[ -d private ]` branches noted; no behaviour line is touched.
- [ ] The `--no-verify` and `JOBHUNT_ALLOW_PUSH` comments name their audience (owner, not agent) and
      point at the contract line that forbids agent use.
- [ ] `skills/github-workflow/SKILL.md`'s gate description mentions `JOBHUNT_ALLOW_PUSH` exists and
      is owner-only, or explains why an agent will never see it.
- [ ] The full pre-commit chain is green after the edit (the hook must still run).
