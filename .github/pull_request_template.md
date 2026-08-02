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
- [ ] If any `skills/*/SKILL.md` / `LESSONS.md` / `reference.md` changed: discharge the risk-based eval gate in this body — CI's `pr-body` job blocks on it. Exactly one of: that skill's canary results from `evals/canaries/<skill>.yaml` pasted below (or the `evals/results/` record named); `Eval gate: skipped — <intention + size>` with the rationale actually written out; `Eval gate: debt — <why not now>` plus a `tasks/0_backlog/` item named here and added by this same diff. The bracketed placeholders are not rationales — see `evals/README.md`
- [ ] **No personal data** (no real names, emails, phones, employer/school names, or home paths) — this repo is PUBLIC

## Canary results / skip rationale / eval-gate debt (only if skill-instruction files changed)

<!-- Paste eval results per evals/README.md, or an `Eval gate: skipped — <…>` line
     with the rationale spelled out, or an `Eval gate: debt — <…>` line plus the
     tasks/0_backlog/ item this diff adds. "N/A" and "TBD" fail the gate; if the
     diff touches no skill instruction file, delete this section. -->
