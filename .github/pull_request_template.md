<!-- See CONTRIBUTING.md for details on each item. Keep this section first: the body
     opens with what changes for the person who uses the thing, before any technical
     detail. Validate with:
     .venv/bin/python skills/github-workflow/scripts/check_pr_body.py <file> -->

## What changes for you

### <name the change in user terms, not module terms — one `###` per change>

**Before.** <what happened, or what was broken, in concrete terms>

**After.** <what happens now>

**What you'll notice.** <the practical day-to-day effect, including friction, extra
steps, or slowdown — a PR that lists only benefits is under-reported>

## What & why

<!-- Briefly describe the change and the motivation. -->

## Checklist

- [ ] Ran every command under **Running the checks** in `CONTRIBUTING.md` — unit
      suites, instruction budget, mail send-less policy, leak guard, links. That
      list is the contributor subset; `.github/workflows/ci.yml` is the
      authoritative gate list and runs strictly more.
- [ ] Reported those runs as **exit codes plus this PR's deltas**, each beside the
      SHA it was run on — **no absolute tree-wide counts** ("2669 references", "43
      records"); totals come from the post-merge canonical counts job on `main`
- [ ] If any `skills/*/SKILL.md` / `LESSONS.md` / `reference.md` changed: per the risk-based gate, either ran that skill's canaries in `evals/canaries/<skill>.yaml` and pasted results below, or recorded a one-line skip rationale (`Eval gate: skipped — <intention + size>`) — see `evals/README.md`
- [ ] **No personal data** (no real names, emails, phones, employer/school names, or home paths) — this repo is PUBLIC

## Canary results / skip rationale (only if skill-instruction files changed)

<!-- Paste eval results per evals/README.md, or a one-line skip rationale, or write "N/A". -->
