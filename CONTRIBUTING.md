# Contributing

Thanks for helping improve the job-hunting toolkit. This is the **public**
`jobs-finder-toolkit` repository, Apache-2.0. It ships timeless tooling and a
fictional "Jordan Rivers" example candidate under `examples/` — never anyone's
real data.

## Dev setup

```bash
python3 automation/check_python.py   # refuses to continue below Python 3.11
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**Python 3.11+ required.** Bare `python3` can resolve to an ancient interpreter
(macOS boxes still ship 3.7-era pythons). `python3 -m venv` on one of those exits
0 and installs an obsolete pip, so the only symptom is a misleading
`No matching distribution found for python-jobspy` from the requirements install
— run `automation/check_python.py` first (it is written to stay parseable by
Python 3.7, so it reports instead of crashing), then create the venv with a
modern interpreter: `python3.13 -m venv .venv` or `uv venv --python 3.13`.

No `config.yaml` is needed to contribute: with none present, every tool falls
back to the tracked `config.example.yaml` and the `examples/` Jordan Rivers
fixture. (For PDF rendering, install LibreOffice — see `README.md`.)

Optionally wire the tracked git hooks in one idempotent, stdlib-only step. The
pre-commit hook runs nine gates — a staged-`private/` reject, the leak guard over
the staged index, the public review gate over the staged index, the vendored-copy
drift check, the mail send-less policy, `compileall`, the instruction-file budget,
the reconciler, and the reference/markdown link check — and
`automation/hooks/pre-commit` is the list:

```bash
.venv/bin/python automation/bootstrap_overlay.py        # installs automation/hooks/pre-commit + automation/hooks/pre-push
.venv/bin/python automation/bootstrap_overlay.py --check  # exits 1 if a hook is not wired to its source
```

## Running the checks

This is the **contributor** list — the commands worth running locally before opening
a PR, which the pull-request template points at instead of repeating. All of it must
pass. It is a **subset**, not a mirror: `.github/workflows/ci.yml` is the authoritative
gate list and runs strictly more (see the note under the block).

```bash
# Resume-writer schema/extraction/render tests (includes one fake multi-experience E2E)
.venv/bin/python -m unittest discover -s skills/resume-writer/scripts/tests

# Canonical shared-module tests
.venv/bin/python -m unittest discover -s automation/shared/tests

# Job-search pipeline tests + deterministic high-stakes filter corpus
.venv/bin/python -m unittest discover \
  -s skills/job-search/scripts/tests \
  -t skills/job-search/scripts/tests
.venv/bin/python skills/job-search/scripts/validate_filter_variants.py --check

# The remaining skill suites (application-tracker reads config; the other three do not)
JOBHUNT_CONFIG="$PWD/config.example.yaml" \
  .venv/bin/python -m unittest discover -s skills/application-tracker/scripts/tests
.venv/bin/python -m unittest discover -s skills/email-assistant/scripts/tests
.venv/bin/python -m unittest discover -s skills/behavioral-interview-prep/scripts/tests
.venv/bin/python -m unittest discover -s skills/github-workflow/scripts/tests

# Publish leak-guard + exporter unit tests
.venv/bin/python -m unittest discover -s automation/publish/tests

# Mail send-less policy — the email path must never expose send capability
.venv/bin/python automation/shared/mail/check_mail_safety.py \
  --consumer skills/email-assistant/scripts

# Instruction-file size budget (strict)
.venv/bin/python automation/metrics/instruction_budget.py --strict

# Public leak guard — must be COMPLETELY CLEAN (exit 0, zero findings).
# Without a real config.yaml it has no identity tokens and refuses to run
# (exit 2); add --allow-unarmed to run its token-independent checks.
.venv/bin/python automation/publish/check_public.py

# Link / symlink / vendor-drift check
.venv/bin/python automation/gardener/gardener.py verify-links
```

CI additionally runs the maintenance-tooling suites
(`automation/{reconcile,gardener,hooks,search-recall-audit,metrics}/tests`), the
reconciler, the public review gate, the example render, the vendored-copy drift
check, `compileall`, and the example-store validation — see
`.github/workflows/ci.yml` for the authoritative set and order. The tracked
pre-commit hook runs the cheap gates on every commit; three of them (the public
review gate, the reconciler, `compileall`) are **not** in the block above, so a
green local run of this list is not proof the hook will pass — read
`automation/hooks/pre-commit` for what it actually runs.

Vendored copies must stay in sync; after editing a canonical `automation/shared/`
module, regenerate with `.venv/bin/python automation/vendoring/sync_vendored.py` (the
pre-commit hook and CI both fail on drift).

## Commits & pull requests

**Who this section binds.** It is written for **outside contributors** working
from a fork. The maintainer branches directly in this repo and follows
`skills/github-workflow/SKILL.md`, which allows practices this list rules out
for forks — stacking above all (see rule 6). Where the two disagree, the
audience decides: fork → this file, maintainer branch → the skill.

1. **Fork** the repo on GitHub (maintainer: branch directly), then create a topic
   branch off `main` named `<type>/<short-slug>` where `<type>` is one of
   `feature`, `fix`, `docs`, `chore` — e.g. `fix/guard-comment-tokens`.
2. **Keep each PR to one focused change.** Small PRs get reviewed fast; unrelated
   fixes belong in their own PRs.
3. **Commit messages**: imperative subject line (≤72 chars) saying *what* changed;
   a short body saying *why* — especially for anything behavioral. Run the checks
   above before committing; the tracked pre-commit hook (installed by
   `automation/bootstrap_overlay.py`) re-runs the cheap ones.
4. **Open the PR against `main`** and fill in the pull-request template — it
   mirrors the gates: checks pass, the eval gate discharged in the body (ran,
   skipped-with-a-written-rationale, deferred to a named stack tip, or tracked
   debt) if you touched skill instruction files, no personal data. **Report gate results as exit codes plus the deltas your PR
   caused — never an absolute tree-wide count** ("2669 references", "43
   records"): a count measured on your branch is wrong the moment anything else
   lands under it, so totals come from the post-merge canonical counts job that
   measures `main` after the merge.
5. **CI must be green.** Fork PRs run the leak guard tokenless (structural + path
   checks) — a clean tree passes; if the guard fires on your PR, it found
   something that looks personal and it must come out, not be excepted.
6. **Avoid stacked PRs from a fork** (a PR based on another PR's branch). If two
   changes must land in order, say so in the descriptions; the maintainer merges
   base-first. A fork's branches are not in this repo, so a stack built there is
   one the maintainer cannot rebase or retarget for you when the bottom merges.
   **This rule does not bind the maintainer**, who stacks branches inside this
   repo — the procedure is `skills/github-workflow/SKILL.md` §2 and the runbook in
   `skills/github-workflow/reference.md`, and `AGENTS.md` routes "stacked PRs"
   there. (Either way, stacked PRs merge bottom-up with a merge commit, one at a
   time. Which *command* does the merge depends on whether the PRs were converted
   into one of GitHub's native stacks: a stack member refuses `gh pr merge` with
   HTTP 403 and merges through the repository's `merge-async` endpoint, where one
   entry lands every entry below it in a single commit and GitHub retargets the
   next entry itself; an ordinary PR merges with `gh pr merge <n> --merge` and is
   never retargeted by anything, so the next PR up needs an explicit
   `gh pr edit <n+1> --base main` *after* its base has merged. Checking which case
   you are in is the first step, not a detail — the two are indistinguishable in
   `gh pr view` and on the web page, and merging an unretargeted PR lands it on a
   dead branch with green checks and no warning anywhere.
   Head branches are **not** deleted on merge and `delete_branch_on_merge` stays
   off: deleting a base branch closes the stacked PR above it instead of
   retargeting it, and it makes the rewritten commits unreachable, which turns the
   review-ledger rows written on that branch into unknown objects in a fresh
   clone. Merging out of order strands content.)
7. The maintainer reviews every PR; merged work arrives in the next
   `git pull` — there is no mirror or sync step.

## Eval gate for skill-instruction changes

The eval gate on a skill's instruction files — `skills/*/SKILL.md`,
`LESSONS.md`, or `reference.md` — is **risk-based**: the editing agent decides
whether to run that skill's canaries in `evals/canaries/<skill>.yaml` by judging the edit's
**intention** (does it change what an agent does?) and **size**. Behavioral or
large edits must run the canaries and report results in the PR description;
mechanical or small edits (typos, path/flag fixes, semantics-preserving
rewording) may skip with a **one-line skip rationale recorded in the PR**. See
`evals/README.md` for the full run/skip criteria and how to record either
outcome. Instruction edits are delta-only, and consolidation must not drop a
domain edge case.

**CI blocks on this, and takes four forms.** The `pr-body` job runs
`skills/github-workflow/scripts/check_pr_body.py --eval-gate-only` over your
description and the diff; a PR touching those files fails unless the body says
one of:

1. **Ran** — pasted canary results, or the recorded run under `evals/results/`,
   or `Eval gate: ran — <what ran, how it went>`.
2. **Skipped** — `Eval gate: skipped — <intention + size>` with the rationale
   filled in. The bare placeholder, `N/A`, and `TBD` all fail: quoting the form
   is not discharging the gate.
3. **Stack** — `Eval gate: stack — <why this one is intermediate>; tip: <#PR or
   branch>`, for an intermediate PR of a stack that runs its canaries once at the
   named tip. The name is the commitment: no tip named (or a file path in its
   place) fails. Nothing verifies the tip's run at this PR's CI time — see
   `evals/README.md` → "Stacked PRs". Maintainer-facing: contributors are asked
   above to avoid stacks from a fork.
4. **Debt** — `Eval gate: debt — <why not now>` **plus** a `tasks/0_backlog/`
   item, named in the body and added by the same diff. Running a skill's canaries
   costs about a session, so tracked debt is a real option; untracked debt is a
   skip with no rationale and fails.

## No personal data — ever

This tree is PUBLIC. Never add real names, emails, phone numbers, employer or
school names, home paths, or any other personal identity — in code, docs,
comments, tests, or example data. Use the fictional Jordan Rivers fixture.

The CI **leak guard (`automation/publish/check_public.py`) is blocking**: it scans
tracked files (text and `.docx`/`.pdf` content) for structural PII and private
paths, and any finding fails the build. It also **fails closed when it is unarmed**
— with no identity tokens its token scan inspects nothing, so it exits 2 rather
than reporting "safe to publish". Fork PRs (which receive no secrets) and
contributor clones run it with `--allow-unarmed`: structural + path checks only,
which a clean tree passes by design. The `pre-commit` hook scans the **staged
index** the same way and rejects any staged `private/` path.

## Contributing while running your own job hunt

You can use this toolkit with your **own real data** and still contribute — that
is exactly what the private-overlay design is for (see
[`docs/handbook/private-overlay.md`](docs/handbook/private-overlay.md), including how to create
your own overlay from scratch):

- Your data lives in the git-ignored `private/` mount (optionally your **own**
  private repo — never this one) plus a git-ignored `config.yaml`. None of it is
  ever tracked here, so it cannot enter a commit or PR by accident.
- With an overlay mounted, the leak guard runs **armed with your identity
  tokens** (from `config.yaml` + `private/leak_tokens.txt`), and the pre-push
  hook scans every exact outgoing Git tree before anything reaches a public
  remote — including non-HEAD branches and refs owned by other worktrees.
- Keep the two commit streams separate: toolkit improvements → branch + PR here;
  your data → commits in your own overlay repo. A PR should never reference your
  overlay's contents, filenames, or real employers/companies from your hunt.

## Extra-careful review areas

Changes under **`automation/publish/`**, **`.github/`**, and **`automation/hooks/`** are the
repo's leak defenses (the guard, the exporter, CI, and the pre-push gate). PRs
touching them get extra-careful review — keep those changes small, well-explained,
and covered by the tests in `automation/publish/tests/`.

This is a single-maintainer repo, so there is no `CODEOWNERS` file; the maintainer
reviews every PR.
