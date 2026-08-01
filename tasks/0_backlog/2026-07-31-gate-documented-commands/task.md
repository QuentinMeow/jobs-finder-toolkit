# Gate the commands docs tell agents to run

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: contradiction audit 2026-07-31 (findings A2, A3; the mechanism is diagnosed in the audit's §C hole 3), and the PR that repaired those two commands by hand
- **Claimed-by**:

## Goal

A copy-pasteable command in a fenced block should not be able to name a deleted
directory or a flag that does not exist without some gate saying so. Today
nothing checks either, and both classes shipped.

## Context

Two documented commands were broken on `main` and invisible to every gate:

- `skills/search-recall-audit/SKILL.md` documented
  `field_fidelity.py check --source lever --id <native_id>`; the `check`
  subparser takes only `--key` (`automation/search-recall-audit/field_fidelity.py:625-627`),
  so the line died at argparse with two separate errors.
- `docs/designs/filtering-variant-safeguards/execution-plan.md` calls
  `automation/maintenance/gardener/gardener.py` in two Stage-gate blocks; that
  root was retired in the workspace restructure.

Both were repaired by hand. Neither would have been caught, for two independent
reasons documented in `automation/gardener/verify_links.py`:

1. **Fenced blocks are in no tier.** Pass 2 scans `BACKTICK_RE` (`:617`) and
   pass 3 scans markdown links over fence-masked text (`:661`), so a bare path
   inside a ```` ```bash ```` block is read by neither — not broken, not
   advisory, not counted. (Proof that this is the gap and not the tiering: the
   dated note added to `execution-plan.md:11` puts the same retired path in a
   backtick, and it immediately appears in the advisory tier with a correct
   "did you mean" hint. The two in-fence copies eight lines below still do not.)
2. **Nothing compares a documented flag to its `add_argument`.** `--source` is
   defined only on `sample`; `--id` exists nowhere in the file. A doc may
   invent any flag it likes.

Prior art for the shape of the fix, both in the audit: scan fenced blocks for
the `.venv/bin/python <path>` and `python <path>` shapes only — that one shape
covers the whole copy-pasteable-command class at negligible false-positive
cost. Flag checking can reuse the same extraction: once a `<script>.py` and its
argv are parsed out of the fence, `argparse` can be asked whether the flags
resolve without running the command.

Constraints:

- `verify_links.py` runs in pre-commit (`automation/hooks/pre-commit:151-157`)
  and CI (`.github/workflows/ci.yml:124-125`), both blocking, so a new check
  must be tiered deliberately, not defaulted to `broken`. Historical design
  records legitimately name retired paths — `docs/designs/AGENTS.md` says
  historical families are records — so the record/plan/reference tiering at
  `verify_links.py:440-448` has to apply to fenced commands too, or the first
  run turns every dated verification block into a build failure.
- Do not weaken an existing check to make this one fit.

## Definition of done

- [ ] A planted defect is caught: a fenced `.venv/bin/python does/not/exist.py`
      in a non-record source is reported (tier argued in the PR body), and the
      same line in a `tasks/4_done/` or `history/` record is not a failure.
- [ ] A planted bad flag on a real script is reported, and every command
      currently in the tree still passes — run the checker over `main` first and
      triage the backlog it finds before arming it.
- [ ] `automation/gardener/verify_links.py --help` documents the new pass, and
      its tests pin both the catch and the record exemption.
- [ ] `.venv/bin/python automation/gardener/verify_links.py`,
      `automation/reconcile/reconcile.py --check` and the gardener suite stay green.
