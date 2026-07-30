# Give the human-read trees one docs/ parent

- **Status**: decided
- **Date**: 2026-07-29
- **Decided by**: owner (workspace-restructure phase 2; the consolidation question was answered 2026-07-28)
- **Supersedes**: item 3 of [`memory/decisions/agentfold-restructure.md`](agentfold-restructure.md) — "`docs/` dissolves into `handbook/` (operating docs) and top-level `design/` (design programs)"

## Context

The AgentFold restructure dissolved a generic top-level `docs/` folder, on the
rule that a folder name must announce what its contents are *for*. `docs/` said
only "these are files", so its contents were re-homed into `handbook/`
(reference prose) and `design/` (design programs), and `roadmap/` was added
beside them later.

That left three top-level folders — `handbook/`, `design/`, `roadmap/` — sitting
at the same level as the machinery a reader actually runs (`automation/`,
`skills/`, `evals/`, `templates/`) and the process layer (`tasks/`, `memory/`,
`message-queue/`, `history/`). Twelve top-level entries compete for a newcomer's
attention, and three of them turn out to be the same kind of thing.

## Decision

Reinstate `docs/` as a parent, with purpose-named children:

| Was | Now |
|-----|-----|
| `handbook/` | `docs/handbook/` |
| `design/` | `docs/designs/` (plural — it holds a collection of design programs) |
| `roadmap/` | `docs/roadmap/` |

The rule from the superseded decision is unchanged and still binding: no file
may land directly in `docs/`. Every file lives in a purpose-named child, and a
new child needs a name that says what it is for.

`docs/` is not restored as a general destination. It is a category with a
boundary — prose a human reads — and the boundary is testable: if an agent or a
script reads a file to do its job, that file does not belong here.
`AGENTS.md`, `templates/`, `evals/` and the process folders all stay at the
root for that reason.

## Alternatives considered

- **Leave the three roots at the top level.** Loses nothing mechanically, but
  keeps three sibling entries that a reader has to learn are one category, and
  keeps the top level at twelve entries.
- **One flat `docs/` with no children.** This is exactly what the superseded
  decision correctly rejected: the folder name would stop announcing purpose,
  and design programs, reference prose and the roadmap would mix.
- **`docs/design/` (singular).** Reads as a verb or an attribute of the
  toolkit; `designs/` reads as the collection of design programs it actually is.

## Consequences

- The earlier reasoning was right about what it was judging. The counter-argument
  is not that generic buckets became acceptable, but that `handbook/` + `design/`
  + `roadmap/` are three roots of *one* kind. `docs/` with purpose-named children
  is not a generic bucket; it is a category with a real boundary.
- **Every literal in the repo naming those roots had to change in the same
  change as the move** — the agent contract, the README, CONTRIBUTING, the
  handbook itself, the skills, live task files, and the checkers. Renaming a root
  whose name is baked into a checker *disarms* the checker rather than breaking
  it: `verify_links.py` makes a prefix strict only in a tree that has that root,
  and the reconciler's `CHECK_ROOTS` no-ops on a root it cannot find. Both keep
  reporting success while checking nothing.
- **Any external bookmark or link into `handbook/…`, `design/…` or `roadmap/…`
  breaks.** GitHub will not redirect them; there is no compatibility shim, and
  none is planned — a shim would be a second name for one thing, which is the
  problem this decision exists to remove.
- `export_public.py`'s `ALLOWLIST_DIRS` names `docs/handbook` and `docs/designs`
  individually, never a bare `docs`. A bare parent would newly publish
  `docs/roadmap/`, which has never shipped, and that is a separate decision
  nobody has made.
- Records are deliberately left stale. Dated handovers, `evals/results/` runs,
  immutable ADRs and `tasks/4_done/` items still name the old paths, because
  rewriting a record falsifies it. `verify_links.py` classifies those sources as
  plan-or-record, so their now-unresolved refs are advisory, not failures.
- Revisit if `docs/` ever accumulates a child whose contents an agent or script
  reads to do its job — that would mean the boundary has stopped holding.
