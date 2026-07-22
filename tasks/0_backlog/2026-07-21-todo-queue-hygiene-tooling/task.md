# message-queue/ queue hygiene tooling (lint + leak scan + gardener routine)

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: adversarial review of the async-collaboration model
  (2026-07-21) — the model is convention-only in a repo that mechanically
  enforces everything else. The planned reconciler
  (memory/decisions/agentfold-restructure.md, item 5) is the natural
  implementation vehicle for gaps 1 and 3.

## Goal

Give the `message-queue/` queue family the same mechanical backing as the rest of
the repo: a format lint, a leak scan, and a gardener hygiene routine.

## Context

Three gaps the review demonstrated:

1. **No format lint.** Queue files have mandated front-matter (Status/
   Priority/Area/Source for tasks; Status/Filed/Blocking/default-path +
   `**Your answer:**` line for decisions; Filed/Look-at/Resolution for
   reviews) but nothing checks it — the launch seeds themselves shipped
   with violations. Add a small linter over `message-queue/**` front-matter +
   required sections, wired into pre-commit.
2. **No leak scan on message-queue/ content.** The queue READMEs say "leak-guard
   rules apply" but no automated scan runs on public-tree queue items
   (applied-to company names + dates aren't the owner's identity tokens, so
   the identity guard alone can't catch them). Extend the pre-commit check
   to run the structural screens over `message-queue/**`, and add a reviews/-specific
   rule: flag real-company-plus-date shapes.
3. **No gardener routine.** Add `todo-hygiene` to the gardener (dry-run
   like everything): reviews/ items past 30 days, tasks stuck `done` past
   one PR cycle, decisions/ items pending longer than N weeks (surface a
   reminder line for the owner), parked items whose revisit condition
   references a shipped stage.

## Definition of done

- [ ] Lint green on the current tree; a planted malformed queue file fails
      pre-commit with a message naming the missing field.
- [ ] Leak scan over `message-queue/**` runs in pre-commit; a planted
      real-company+date line in `message-queue/needs-human/reviews/` is flagged.
- [ ] `gardener` offers `todo-hygiene` (dry-run), reporting the three aging
      dimensions above.
