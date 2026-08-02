# Four gates that report clean when they inspected nothing

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: repo contradiction audit, 2026-07-30 — findings 12, 13 and 16 (fail-open
  gates) plus the untested `roadmap-fresh` invariant. Fourth PR of the hygiene stack,
  on top of `fix/03-owner-data-paths`.
- **Claimed-by**: agent, 2026-07-31 — see [verification.md](verification.md) and
  [worklog.md](worklog.md)

## Goal

Four gates could pass without having inspected anything. Each one now treats
"I verified nothing" as a finding, following the precedent already set in
`automation/gardener/verify_links.py`'s `check_symlinks()`.

## Context

`check_symlinks()` was fixed earlier with the right shape: all link roots absent, a
root present but empty, and a root tracked-but-missing are each their own finding,
because reporting "all resolve" after checking nothing is worse than reporting a
break. Four gates still had that shape:

1. **`automation/shared/mail/check_mail_safety.py`** — a MISSING `providers/` was a
   finding; a present-but-empty one yielded zero providers, zero errors and
   `mail safety policy: PASS`. Directories beginning `_` or `.` were filtered out of
   the walk unscanned, so a send path in `providers/_outlook/` was invisible. This is
   the guardrail behind AGENTS.md's draft-only invariant, and PR 02 of this stack put
   it in CI — so the fail-open was a fail-open at merge.
2. **`automation/gardener/verify_links.py`** — printed `references: all resolve` after
   counting 729 refs it never resolved (133 naming a file) and listing 89 advisory /
   permitted findings above the line. A run that verified nothing printed the same
   line. The in-review task `2026-07-29-verify-links-misses-markdown-and-nonstrict-roots`
   had already made markdown links checkable and given the unrecognised-root bucket a
   counter; the summary line was what remained.
3. **`automation/publish/review_gate.py`** — `NotApplicable` → exit 0 whenever no
   ledger row named a commit this checkout has. That is the published mirror's normal
   state and a wholesale ledger rewrite's normal state, and the second passed on the
   first's licence in pre-commit and in CI.
4. **`automation/reconcile/reconcile.py`** — `check_roadmap_fresh` tested that the
   string `Last-updated` appeared in `docs/roadmap/current-state.md`. It never read the
   date, so a roadmap a year stale passed. `docs/roadmap/README.md` claimed the check
   "keeps it dated".

Constraints honoured: `reconcile.py` is stdlib-only (`datetime` is stdlib, so the
import stays at the top); `review_gate.py` must keep the exported public mirror green,
and the mirror runs this repo's OWN tracked `automation/hooks/pre-commit` and
`.github/workflows/ci.yml`, so a flag those files passed would disarm the maintainer
checkout too.

## Definition of done

- [x] Each of the four fails on a planted no-coverage tree and passes on the real one,
      proved in both directions in [verification.md](verification.md)
- [x] `automation/shared/mail/check_mail_safety.py` reports an empty providers tree, a
      `_`/`.` directory carrying Python, and a consumer dir with nothing scannable; the
      pass line names the provider folders and consumer-file count
- [x] `verify_links.py` never prints "all resolve": the summary carries the verified
      count next to the not-verified count, and zero coverage exits 1. Widening
      coverage over the retired roots was measured and rejected — the one reference-tier
      hit is `docs/roadmap/current-state.md` naming `tmp/` in the sentence that says it
      was renamed
- [x] `review_gate.py` exits 2 when no row resolves in a tree carrying the
      maintainer-only roots; the published-export shape stays exit 0 and says why;
      `--allow-not-applicable` is the explicit override; a test pins
      `EXPORT_ABSENT_ROOTS` against `export_public.ALLOWLIST_DIRS`
- [x] `check_roadmap_fresh` parses the date and fails on missing / unparseable / future
      / older than `ROADMAP_MAX_AGE_DAYS` (30), and checks `desired-state.md` exists
      *(Amended 2026-07-31, later in the same stack: the AGE half was removed from the
      gate and the check renamed `roadmap-dated`. An age limit in a check that runs in
      pre-commit AND CI fails every commit in the repo once the clock runs out — with
      a 30-day window and a roadmap dated 2026-07-31, from 2026-08-31 onward. Age is
      now the gardener's report-only `roadmap-staleness` routine; missing, unparseable
      and future dates plus the `desired-state.md` check still gate, unchanged.)*
- [x] Full gate script ALL GREEN, including a detached config-less worktree run
