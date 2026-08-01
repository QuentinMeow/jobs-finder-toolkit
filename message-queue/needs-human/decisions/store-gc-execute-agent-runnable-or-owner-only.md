# May an agent run the store GC's `--execute`, or is deleting payloads owner-only?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31
- **Source**: [raw-data-layer store core, §9 retention + the GC config](../../../docs/designs/raw-data-layer/01-store-core.md)
- **Blocking**: nothing. The store is not near any size limit; a GC that never runs
  costs disk, not correctness.
- **Default path**: agents run `automation/store/gc_store.py` in its dry-run default
  only, never pass `--execute` or `--remove-orphans`, and hand the printed plan to
  you. This is the literal reading of the guardrail and it is what agents do today.

## Background

Two tracked files give an agent opposite instructions about the same command.

**The guardrail**, `AGENTS.md:224-227`:

> - **Agents never delete owner data**: application folders, interview prep, company dossiers,
>   and store payloads are removed by the **user only** — never by an agent, under any
>   condition, including cleanup, migration, or a rejected application. Propose a deletion in
>   `message-queue/needs-human/` and stop; never perform one.

**The tool**, `automation/store/gc_store.py:1-27`, whose whole purpose is to delete
store payloads:

> Prunes payload blobs the domain's ``retention.yaml`` marks disposable …
> ``--dry-run`` is the DEFAULT … ``--execute`` performs it.

**And a third surface routes agents to it.** `skills/gardener/SKILL.md:47` describes the
`store-report` routine's guardrail as *"NEVER prunes — pruning is
`automation/store/gc_store.py`, run deliberately"*, and `:32` repeats it. Neither says
who may run it, so an agent reading only the gardener skill concludes it may.

**What the tool actually deletes, and how carefully.** Read the docstring in full and it
does not read like a command left for a human to run by hand:

- manifests — the observation log — are **never** pruned;
- a blob is deletable only when every manifest referencing it is in a prunable tier and
  past that tier's dates; any keep-class reference vetoes;
- before deleting a blob that feeds a materialized entity, that entity's source-derived
  facts are snapshotted to `state/frozen-facts/`, so a rebuild carries the fact forward
  instead of leaving a hole;
- strict per-blob order frozen-facts → tombstone → delete, so the worst crash window is
  "blob present plus tombstone", which the next sweep repairs;
- it takes the BUILDER lock and fails fast on contention, because a skipped GC costs
  nothing.

That is the engineering of something designed to run unattended and often.

**And the policy it enforces is already yours.** `docs/designs/raw-data-layer/01-store-core.md:503-521`
gives each domain a `retention.yaml` of per-tier prune expressions over posting-date and
last-observed-date, commented *"example shape, owner-editable"* (`:508`), and shipping
conservatively — `boards_and_jds: never`, so the high-value cohort keeps its raw payloads
forever and only aggregator sweeps are ever candidates. You have already drawn the line;
the question is whether an agent may act on the line you drew.

**Where the data lives.** `config.data_root()` has deliberately no default
(`automation/shared/config.py:579-598`) — unset means the store is disabled, which is why
CI and the example config never have one. In your setup it points inside the overlay
(`docs/designs/workspace-restructure/execution-plan.md:407` maps `data/` → `store/`). So
these bytes are under `private/`, which is exactly the territory the guardrail exists to
protect.

**One asymmetry worth naming before you choose.** The guardrail's other three nouns —
application folders, interview prep, company dossiers — are hand-authored and
irreplaceable. Store payloads are fetched, and the GC snapshots the derived facts before
touching them. That argues the fourth noun does not belong in the same sentence as the
first three. The counter-argument is that a posting taken down is gone for good and no
refetch brings it back — which is the whole reason a raw layer exists. Both are true;
`retention.yaml`'s conservative defaults are what reconcile them.

## Options

### Option A — carve blob pruning out of the guardrail; keep `--remove-orphans` owner-only

`AGENTS.md:224-227` gains an exception: *"except `automation/store/gc_store.py`, whose
`retention.yaml` is the deletion policy — an agent may `--execute` it; `--remove-orphans`
stays owner-only."* `gc_store.py`'s docstring and `skills/gardener/SKILL.md:47` say the
same in the same commit.

The split is not arbitrary. `--execute` on its own deletes exactly two things: blobs your
`retention.yaml` marked disposable, and manifest-less debris under `raw/<source>/` older
than 24h (an interrupted fetch's leftovers — garbage by construction). `--remove-orphans`
deletes blobs no manifest references at all, and an orphan is as likely to be the symptom
of a bug as it is to be garbage. Keeping that one flag with you costs nothing, because it
is opt-in already.

*Cost:* the guardrail stops being a flat rule and gains a clause, which is a small tax on
every future reader of it. And you are trusting `retention.yaml` to be right — if you
widen a tier by mistake, an agent acts on the mistake the same day instead of showing you
a plan first.

### Option B — mark `--execute` owner-only (the default path, made explicit)

No exception to the guardrail. Instead `gc_store.py`'s docstring gains a line — *"`--execute`
is owner-only; an agent produces the dry-run plan and stops"* — and
`skills/gardener/SKILL.md:47` gains the same qualifier so the routing line stops reading
like an invitation.

*Cost:* a tool built with a builder lock, crash-safe ordering and frozen-facts
snapshotting can only ever be run by you, by hand, on your machine. In practice that means
it runs rarely or never, the store grows monotonically, and `store-report`'s reclaimable
figure becomes a number nobody is allowed to act on.

### Option C — agents may `--execute` only when the dry-run plan writes no frozen facts

The conditional middle: an agent runs the dry-run, and may proceed only if the plan
touches nothing that feeds a materialized entity.

*Cost:* it makes a hard gate depend on an agent reading a plan correctly, which is the
class of judgment the guardrail exists to remove from agents in the first place. It also
inverts the design — frozen-facts exist precisely so that pruning a fact-bearing blob is
*safe*, so gating on their absence distrusts the mechanism that makes the tool safe.

## Recommendation

**Option A.** The guardrail protects things you wrote; `retention.yaml` is also something
you wrote, and it is a more precise expression of the same intent than a blanket
prohibition is. The GC's design — never touching manifests, refusing on any keep-class
reference, snapshotting facts first, crash-safe ordering — is what an unattended tool
looks like, and Option B leaves that work permanently unused. Splitting `--remove-orphans`
off keeps the one genuinely ambiguous deletion with you at zero cost, since it is a
separate flag already.

If you would rather not open a clause in a guardrail that currently has none, Option B is
entirely defensible — it just means saying so in both files, because the gardener skill
currently reads the other way and an agent will follow it.

**Your answer:** ______
