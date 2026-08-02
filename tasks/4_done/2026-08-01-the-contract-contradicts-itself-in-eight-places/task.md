# The contract contradicts itself in eight places

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: instruction-conflict audit, 2026-08-01 (a sweep for contradictory instructions across
  `AGENTS.md`, `docs/handbook/`, every public `SKILL.md`/`LESSONS.md`/`reference.md`, the process
  READMEs and the code that enforces them)
- **Claimed-by**: agent, session 2026-08-02 (branch `docs/26-contract-and-record-corrections`)

## Goal

`AGENTS.md` can be followed literally without hitting a rule that another line of the same file, a
folder README it routes to, or the code contradicts. Eight independent items, each a sentence of
wording; none needs a behaviour change.

## Context

Line numbers are as of `fix/43-sponsorship-recall`. Each item names both sides and which one the
audit believes is right; the reasoning is in the bullet, so this task is self-contained.

1. **`:302` forbids the re-read `:170` requires.** `:302` — "**Read Hygiene** — never re-Read a
   file already in context (duplicate reads are pure token waste)". `:170` — "**re-read any two-way
   file immediately before writing it; if it changed since your last read, merge — never clobber**".
   Within one session an agent that read a decision file at turn 5 and writes it at turn 40 has it
   "already in context", so the general rule tells it to skip the specific safety re-read whose
   stated failure mode is clobbering owner text. `:170` is right; Read Hygiene needs the carve-out.
   (`:187`'s post-compaction re-read is NOT a conflict — after a compaction the file is by
   definition no longer in context.)

2. **The boot ritual deletes a reply the owner has not read.** `:133-135` — "For each item: act, or
   convert it (task / decision / **dated reply appended to the item**), then delete the request file
   in the same commit." vs `message-queue/needs-agent/requests/README.md:16-19` — "If the right
   response is an *answer* to the owner, append it under a dated `## Agent reply (YYYY-MM-DD)`
   heading and **LEAVE the file** … deleted only after the owner acknowledges." The README is right
   and thought the case through; the contract's grammar puts the dated-reply branch inside the list
   that "then delete" governs, and the README itself calls `AGENTS.md` the canonical version of this
   ritual, so an agent that reads only the contract deletes the answer.

3. **"Tracked ⇒ published" is false for five roots, and the same file says so.** `:50-51` — "**If a
   path does not start with `private/`, tracked content written there is published.**" vs `:132` —
   "skip entirely if `message-queue/` is absent (public exports omit it)", and
   `automation/publish/export_public.py:63-101`, whose `ALLOWLIST_FILES`/`ALLOWLIST_DIRS` name none
   of `tasks/`, `memory/`, `message-queue/`, `history/`, `docs/roadmap/`
   (`automation/publish/review_gate.py:129` spells the same five as `EXPORT_ABSENT_ROOTS`). The
   leak-guard framing is the true one — `check_public.py` scans `git ls-files` wholesale, so tracked
   content must be *publishable* — but as written the sentence is factually wrong about publication
   and an agent deciding where a doc naming in-flight work may live gets no usable rule.

4. **`:141` names a status value that does not exist.** "skip `parked` items unless their revisit
   condition matches" vs the real value, `parked-until-revisit`, used by
   `message-queue/needs-human/decisions/logs-as-store-projections.md:3` and named correctly in
   `message-queue/needs-human/decisions/README.md:24`. An agent grepping for the backticked token
   finds nothing and processes a parked item.

5. **`--file-retries` reads as a way past a gate it does not move.** `:238-241` — "must pass — fix
   the finding or let `--file-retries` queue it" vs `automation/reconcile/reconcile.py:704-714`,
   where `file_retries()` runs and the function then still `return 1` on any finding. Filing a retry
   changes nothing about the exit code, so pre-commit still blocks — which is also what `:212-213`
   says ("You may **not** commit, push, or open a PR over a red gate that pre-commit or CI runs").
   The two lines can only be reconciled by reading "queue it" as *the filing step*, not an
   alternative to passing.

6. **The doc-ownership guardrail forbids what six tracked files do.** `:236-237` — "`README.md` is
   human-facing (no agent instructions)" vs `templates/README.md`, `tasks/README.md`,
   `message-queue/README.md` (+ its four sub-READMEs), `memory/README.md` and `evals/README.md`,
   every one of them agent-facing, and every one of them routed to by this contract (`:89`, `:94`,
   `:123`, `:193-194`, `:247`). The bullet plainly means the ROOT `README.md` (its Repo Map row at
   `:96` pairs root `README.md` with root `AGENTS.md`); as written it invites an agent doing doc
   hygiene to strip the schema instructions out of `templates/README.md`.

7. **The eval gate's absolute has a hole its own pointer fills.** `:242-246` — "behavioral or large
   edits **must pass canaries** before merge" vs `evals/README.md:193-196`, which records that
   `gardener` and `search-recall-audit` deliberately have no canary set, so an edit to either is
   "always a skip with a recorded one-line rationale". Confirmed on disk: `evals/canaries/` holds
   nine files and neither of those two. An agent that stops at the contract concludes a behavioral
   gardener edit cannot merge at all.

8. **The deletion guardrail's "under any condition" vs an approved remote deletion.** `:232-235` —
   "**Agents never delete owner data**: application folders, interview prep, company dossiers, and
   store payloads are removed by the **user only** — never by an agent, under any condition …
   Propose a deletion in `message-queue/needs-human/` and stop; never perform one." vs
   `skills/interview-calendar/SKILL.md:130` — "Never delete an existing duplicate without the user's
   explicit approval", i.e. deletion IS permitted with approval. The guardrail's enumeration is
   repo-local owner data and its remedy is repo-shaped (file a queue item), so a live Outlook event
   the user just approved deleting is arguably outside it — but nothing says so, and the heading is
   the broad form. Decide whether the guardrail is scoped to repo-local products or whether
   interview-calendar must also route through the queue.

Constraint: `AGENTS.md` is 335 of its 500-line budget
(`automation/metrics/instruction_budget.py`), so there is room, but prefer replacing words to
adding sentences. Items 1-7 are wording; item 8 may need an owner call — if it does, file it in
`message-queue/needs-human/decisions/` rather than picking a side here.

## Definition of done

- [ ] Each of the eight items is either corrected in `AGENTS.md` (or the leaf, where the leaf is the
      wrong side) or has a `message-queue/needs-human/decisions/` item explaining why it needs the owner.
- [ ] `grep -n 'parked' AGENTS.md` shows the real status value; `grep -rn 'Agent reply' AGENTS.md
      message-queue/needs-agent/requests/README.md` shows the two surfaces agreeing.
- [ ] `.venv/bin/python automation/metrics/instruction_budget.py --strict` clean, and the full
      pre-commit chain green.
