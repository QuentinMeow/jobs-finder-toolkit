# Verification — 2026-08-01-the-contract-contradicts-itself-in-eight-places

All eight items were re-verified against this branch before any edit. Line numbers in
`task.md` were written against `fix/43-sponsorship-recall` and have rotted; the evidence
below is what the tree actually held on 2026-08-02.

## Item 4 — the status token now matches the files that carry it

```
$ grep -n 'parked' AGENTS.md
154:   `parked-until-revisit` item unless its revisit condition matches this session's work.

$ grep -rn 'Status.*parked' message-queue/needs-human/decisions/
message-queue/needs-human/decisions/logs-as-store-projections.md:3:- **Status**: parked-until-revisit (owner deferred, 2026-07-21)
```

## Item 2 — both surfaces now agree that a dated reply stays

```
$ grep -n 'Agent reply' AGENTS.md message-queue/needs-agent/requests/README.md
AGENTS.md:144:   `## Agent reply (YYYY-MM-DD)` heading and LEAVE the file, which is deleted only once the owner
message-queue/needs-agent/requests/README.md:17:owner, append it under a dated `## Agent reply (YYYY-MM-DD)` heading and
```

## Item 3 — the five roots that are tracked but not exported

```
$ grep -n 'EXPORT_ABSENT_ROOTS = ' automation/publish/review_gate.py
172:EXPORT_ABSENT_ROOTS = ("tasks", "memory", "message-queue", "history", "docs/roadmap")
```

`export_public.py`'s `ALLOWLIST_FILES`/`ALLOWLIST_DIRS` (read at `:63-118`) name none of the
five, confirming the sentence "tracked ⇒ published" was false for all of them.

## Item 5 — `--file-retries` does not move the exit code

`automation/reconcile/reconcile.py` `main()`: `file_retries(findings, today)` runs, and the
very next block is unconditional —

```
    if findings:
        print(f"reconcile: {len(findings)} finding(s)")
        for f in findings:
            print(f"  {f}")
        return 1
```

so filing a retry leaves the run red and pre-commit still blocks.

## Item 6 — the folder READMEs the old wording forbade

```
$ git ls-files '*README.md' | grep -v '^private/' | grep -E '^(templates|tasks|memory|message-queue|evals)/'
evals/README.md
memory/README.md
memory/decisions/README.md
memory/facts/README.md
memory/known-issues/README.md
memory/lessons/README.md
message-queue/README.md
message-queue/needs-agent/requests/README.md
message-queue/needs-agent/retries/README.md
message-queue/needs-human/clarifications/README.md
message-queue/needs-human/decisions/README.md
message-queue/needs-human/reviews/README.md
tasks/README.md
templates/README.md
```

Every one opens with agent instructions (e.g. `templates/README.md`: "To create any queue
item, task file, memory entry, or handover: **copy the template and fill the blanks**"), and
every one is routed to by this contract.

## Item 7 — ALREADY FIXED before this session, no edit made

The eval-gate guardrail in `AGENTS.md` already carried both halves of the carve-out the task
asks for:

```
$ grep -n 'where a set exists\|no canary set' AGENTS.md
258:  behavioral or large edits must pass canaries before merge where a set exists (no large efficiency
260:  edits — and skills with no canary set — skip **with a recorded one-line rationale**. An
```

Consistent with `evals/README.md`, and with the canary directory holding nine files and
neither `gardener` nor `search-recall-audit`:

```
$ ls evals/canaries | wc -l
       9
```

(Counted 2026-08-02; `evals/canaries/` holds nine `<skill>.yaml` files.)

## Item 8 — NOT decided here

No open item in `message-queue/needs-human/decisions/` covered the scope of the
"agents never delete owner data" guardrail (checked by listing the folder and grepping it for
`interview-calendar`, `Outlook` and `calendar`; the two hits are about doc-style scope and a
phase-7c descope, neither of which is this question). Filed as
`is-never-delete-owner-data-scoped-to-repo-local-products.md`.

## Gates (run from this worktree, redirected — never piped)

```
$ .venv/bin/python automation/metrics/instruction_budget.py --strict   # EXIT=0
AGENTS.md                                        353  28664     7166        500      ok
```

The full gate block for this branch is recorded in the sibling task closures; every gate ran
green at commit time.
