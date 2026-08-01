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

**Rewritten 2026-07-31: two of the three gaps this task was filed for have since shipped.** They
are recorded below rather than deleted, because a task that describes work already done sends the
next reader to build it twice. What remains is real and is stated first.

**Updated 2026-07-31 (second pass): gap B has now shipped too.** Only gap A is left, and it is
waiting on an owner answer — see the new
[company-plus-date screen decision](../../../message-queue/needs-human/decisions/company-plus-date-structural-screen.md).
Do not start gap A before that is answered; its default path is "no screen is added".

**Verify-with**:

```bash
grep -n 'def check_queue_schema\|def check_task_structure' automation/reconcile/reconcile.py
grep -n 'reconcile.py --check' automation/hooks/pre-commit
grep -n 'def _structural_hits' -A 14 automation/publish/check_public.py
grep -n 'ROUTINES = {' -A 12 automation/gardener/gardener.py
```

### Gap A — no company-plus-date structural screen (the surviving half of old gap 2)

`check_public.py --staged` runs in pre-commit with **no exclusion for `message-queue/`** — the
tree is explicitly named in the module as legitimately scanned — so queue items *are* scanned. But
`_structural_hits` screens exactly four shapes: email, phone, home path and LinkedIn. There is no
real-company-plus-date rule, which is the one shape the identity guard structurally cannot see
(company names are not identity tokens — that is why the review gate exists). So the DoD's planted
`message-queue/needs-human/reviews/` defect would still walk through today.

**This one needs a narrow owner decision before it is built.** A company-plus-date regex over a
*public* tree is a false-positive generator: this repo's own docs and ADRs name ATS vendors and
dates constantly. Decide the shape (allowlist of vendor names? advisory-only hint like the review
gate's detector, rather than a blocker?) before writing the regex.

**Filed 2026-07-31** as
`message-queue/needs-human/decisions/company-plus-date-structural-screen.md` — four options
(do nothing / advisory hint off the existing `companies.yaml` registry / blocking regex with a
vendor allowlist / blocking but scoped to `message-queue/` + `tasks/` only), recommending the
advisory hint. It notes the overlap with `process-weight-what-to-cut.md` D6, also unanswered.

### Gap B — ~~no gardener routine~~ SHIPPED 2026-07-31 (old gap 3)

The gardener has 8 routines — `expire-discoveries`, `compact-logs`, `lessons-report`,
`card-staleness`, `skill-drift`, `store-report`, `verify-links`, `self-measure` — and **none of
them touches `message-queue/`, `tasks/`, or `memory/known-issues/`**. Add `queue-hygiene`
(dry-run, exit 0 always, like everything there): `reviews/` items past 30 days, tasks dwelling in
`1_in-progress`/`3_in-review`, `decisions/` items pending longer than N weeks, and parked items
whose revisit condition references a shipped stage.

**Name (2026-07-31, owner call): the routine shipped as `queue-hygiene`, not the `todo-hygiene`
this task asked for** — this task was written on 2026-07-21, when the folder family was still
`todo/`; `message-queue/README.md` records the rename, so the old name pointed at a folder that no
longer exists. This task's title is stale for the same reason; its id never changes.

Note that this overlaps a proposal now in front of the owner
([process-weight](../../../message-queue/needs-human/decisions/process-weight-what-to-cut.md),
D6b) — check the answer before building, so the routine is not built twice under two names.

**It did overlap: D6b proposes this exact routine under the name "the age flag".** They were
reconciled into ONE routine rather than two — `queue-hygiene`
(`automation/gardener/queue_hygiene.py`, tests in
`automation/gardener/tests/test_queue_hygiene.py`), registered in `gardener.py`'s `ROUTINES` and
`ALL_ORDER`. A dated note in D6b records that its gardener half is built and narrows what is still
open there to the reconciler-`ADVISORY`-tier fallback. Two departures from D6b's sketch: it
excludes `0_backlog` (D3 of that same document argues an old backlog item is not a defect) and it
prefers the newest dated `worklog.md` heading over the id's filed date, which is only an upper
bound on dwell. It also adds the two dimensions D6b did not name — `reviews/` past 30 days and
parked items whose revisit condition has shipped — and prints **counts only** for the `private/`
mirrors, so a run is safe to paste into a public PR.

### Shipped since filing — do NOT rebuild

- ~~**No format lint.**~~ `reconcile.py::check_queue_schema` validates required keys per queue
  subfolder against `templates/`, and `check_task_structure` enforces `Priority`/`Area`/`Source`,
  the folder-name regex, `Claimed-by` outside backlog, and `verification.md` in
  `3_in-review`/`4_done`. Both are wired into `automation/hooks/pre-commit`. (The *reviews* key set
  drifted from this task's original claim — the templates won.)
- ~~**No leak scan on `message-queue/` content.**~~ It is scanned, in pre-commit, with no
  exclusion. Only the company-plus-date screen is missing; that is gap A.

## Definition of done

- [ ] The company-plus-date screen exists in whatever shape the owner's decision settles, and a
      planted real-company+date line in `message-queue/needs-human/reviews/` is caught by it
      — **blocked on `company-plus-date-structural-screen.md`**; note that under the recommended
      advisory option "caught" means *surfaced as a hint*, not *fails the commit*, so this line
      needs re-wording once the shape is settled
- [x] `gardener` offers `queue-hygiene` (dry-run, never gating), reporting the aging dimensions
      above, and no-opping cleanly when `message-queue/` and `tasks/` are absent (the exported
      public tree ships neither)
