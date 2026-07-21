# Contributing

Thanks for helping improve the job-hunting toolkit. This is the **public**
`jobs-finder-toolkit` repository, Apache-2.0. It ships timeless tooling and a
fictional "Jordan Rivers" example candidate under `examples/` — never anyone's
real data.

## Dev setup

```bash
python3 -m venv .venv        # Python 3.11+ (see below)
.venv/bin/pip install -r requirements.txt
```

**Python 3.11+ required.** Bare `python3` can resolve to an ancient interpreter
(macOS boxes still ship 3.7-era pythons) where the requirements install fails —
create the venv with a modern one if needed: `python3.13 -m venv .venv` or
`uv venv --python 3.13`.

No `config.yaml` is needed to contribute: with none present, every tool falls
back to the tracked `config.example.yaml` and the `examples/` Jordan Rivers
fixture. (For PDF rendering, install LibreOffice — see `README.md`.)

Optionally wire the tracked git hooks (drift check + compile on commit) in one
idempotent, stdlib-only step:

```bash
python scripts/bootstrap_overlay.py        # installs hooks/pre-commit + hooks/pre-push
```

## Running the checks

Run these before opening a PR (all must pass; CI runs them too):

```bash
# Resume-writer schema/extraction/render tests (includes one fake multi-experience E2E)
.venv/bin/python -m unittest discover -s .agents/skills/resume-writer/scripts/tests

# Canonical shared-module tests
.venv/bin/python -m unittest discover -s scripts/shared/tests

# Publish leak-guard + exporter unit tests
.venv/bin/python -m unittest discover -s scripts/publish/tests

# Instruction-file size budget (strict)
.venv/bin/python scripts/metrics/instruction_budget.py --strict

# Public leak guard — must be COMPLETELY CLEAN (exit 0, zero findings)
.venv/bin/python scripts/publish/check_public.py

# Link / symlink / vendor-drift check
.venv/bin/python scripts/maintenance/gardener/gardener.py verify-links
```

Vendored copies must stay in sync; after editing a canonical `scripts/shared/`
module, regenerate with `.venv/bin/python scripts/vendoring/sync_vendored.py` (the
pre-commit hook and CI both fail on drift).

## Commits & pull requests

1. **Fork** the repo on GitHub (maintainer: branch directly), then create a topic
   branch off `main` named `<type>/<short-slug>` where `<type>` is one of
   `feature`, `fix`, `docs`, `chore` — e.g. `fix/guard-comment-tokens`.
2. **Keep each PR to one focused change.** Small PRs get reviewed fast; unrelated
   fixes belong in their own PRs.
3. **Commit messages**: imperative subject line (≤72 chars) saying *what* changed;
   a short body saying *why* — especially for anything behavioral. Run the checks
   above before committing; the tracked pre-commit hook (installed by
   `scripts/bootstrap_overlay.py`) re-runs the cheap ones.
4. **Open the PR against `main`** and fill in the pull-request template — it
   mirrors the gates: checks pass, eval canaries run or a recorded skip
   rationale per the risk-based gate if you touched skill instruction files,
   no personal data.
5. **CI must be green.** Fork PRs run the leak guard tokenless (structural + path
   checks) — a clean tree passes; if the guard fires on your PR, it found
   something that looks personal and it must come out, not be excepted.
6. **Avoid stacked PRs** (a PR based on another PR's branch). If two changes must
   land in order, say so in the descriptions; the maintainer merges base-first.
   (When stacked PRs are merged, each head branch must be deleted on merge so
   GitHub retargets the next one — merging out of order strands content.)
7. The maintainer reviews every PR; merged work arrives in the next
   `git pull` — there is no mirror or sync step.

## Eval gate for skill-instruction changes

The eval gate on a skill's instruction files — `.agents/skills/*/SKILL.md`,
`LESSONS.md`, or `reference.md` — is **risk-based**: the editing agent decides
whether to run that skill's canaries in `evals/<skill>/` by judging the edit's
**intention** (does it change what an agent does?) and **size**. Behavioral or
large edits must run the canaries and report results in the PR description;
mechanical or small edits (typos, path/flag fixes, semantics-preserving
rewording) may skip with a **one-line skip rationale recorded in the PR**. See
`evals/README.md` for the full run/skip criteria and how to record either
outcome. Instruction edits are delta-only, and consolidation must not drop a
domain edge case.

## No personal data — ever

This tree is PUBLIC. Never add real names, emails, phone numbers, employer or
school names, home paths, or any other personal identity — in code, docs,
comments, tests, or example data. Use the fictional Jordan Rivers fixture.

The CI **leak guard (`scripts/publish/check_public.py`) is blocking**: it scans
tracked files (text and `.docx`/`.pdf` content) for structural PII and private
paths, and any finding fails the build. Fork PRs run it tokenless (structural +
path checks only), which a clean tree passes by design.

## Contributing while running your own job hunt

You can use this toolkit with your **own real data** and still contribute — that
is exactly what the private-overlay design is for (see
[`docs/PRIVATE_OVERLAY.md`](docs/PRIVATE_OVERLAY.md), including how to create
your own overlay from scratch):

- Your data lives in the git-ignored `private/` mount (optionally your **own**
  private repo — never this one) plus a git-ignored `config.yaml`. None of it is
  ever tracked here, so it cannot enter a commit or PR by accident.
- With an overlay mounted, the leak guard runs **armed with your identity
  tokens** (from `config.yaml` + `private/leak_tokens.txt`), and the pre-push
  hook re-runs it before anything reaches a public remote — screen your own
  identity locally before CI ever sees the PR.
- Keep the two commit streams separate: toolkit improvements → branch + PR here;
  your data → commits in your own overlay repo. A PR should never reference your
  overlay's contents, filenames, or real employers/companies from your hunt.

## Extra-careful review areas

Changes under **`scripts/publish/`**, **`.github/`**, and **`hooks/`** are the
repo's leak defenses (the guard, the exporter, CI, and the pre-push gate). PRs
touching them get extra-careful review — keep those changes small, well-explained,
and covered by the tests in `scripts/publish/tests/`.

This is a single-maintainer repo, so there is no `CODEOWNERS` file; the maintainer
reviews every PR.
