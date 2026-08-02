# Broken links inside the overlay are invisible to both gates, and there are some

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: records-hygiene pass, 2026-08-02 — a prior run of the same pass reported five
  broken link targets under the mounted overlay; this task exists because that finding has
  nowhere else to live and neither gate would surface it again on its own
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

The overlay's own markdown links are swept for breaks on a stated cadence, and the result is
recorded somewhere a later session can find — so "no gate covers this" stops meaning "nobody
ever looks".

## Context

`automation/gardener/verify_links.py` has three modes and only one of them reads the overlay:

| Where it runs | Invocation | Reads the overlay? |
|---|---|---|
| pre-commit, overlay mounted | `verify_links.py --require-roots --no-overlay` (`automation/hooks/pre-commit:181`) | **no** |
| pre-commit, no overlay | `verify_links.py` (`:184`) | nothing to read |
| CI | `verify_links.py` (`.github/workflows/ci.yml:152`) | **no** — CI has no overlay |

That is deliberate and the hook says why at `:175-178`: a maintainer whose overlay carries a
break would otherwise be unable to commit anything, and the routine's output *"can name
`private/` paths and must never be pasted into public text"*. So overlay coverage is assigned
to a manual gardener run — which nothing schedules and nothing records.

The consequence is not theoretical. A run of the routine with the overlay mounted reported
**five broken targets inside the overlay** on 2026-08-02. Their paths are deliberately not
reproduced here: this file is in the public tree, and the hook's own comment is the rule.

Two things make this worth a task rather than a shrug:

- The public tree runs `verify_links` on every commit and in CI, so the public half never
  accumulates breaks. The overlay half accumulates them silently and indefinitely — the two
  halves have opposite failure curves for no reason a reader would guess.
- A reference from the overlay into a public path is exactly what breaks when the public tree
  is reorganised, which it has been repeatedly (`docs/` consolidation, the `examples/`
  reshape, `automation/maintenance/` dissolution). The overlay never gets the "the PR that
  moves a path updates every literal naming it" treatment because the mover cannot see it.

Do **not** solve this by making pre-commit read the overlay. That re-opens the exact failure
the hook comment documents, and it would put private paths into an error stream agents paste
into public places.

Plausible shapes, in increasing cost:

1. **A cadence, written down.** Add the overlay-reading `verify_links.py` run to the
   gardener's documented weekly upkeep (`skills/gardener/`), with the standing instruction
   that the finding is repaired in the overlay and only a COUNT is ever reported publicly.
2. **A private-scope record.** File the findings each sweep into `private/tasks/0_backlog/`,
   where naming the paths is legal. Note that `message-queue/needs-human/decisions/private-scope-reconciler.md`
   already asked a neighbouring question and the owner said to leave it undecided — read it
   before proposing anything that runs a checker over the private tree on a schedule.
3. **A counts-only public signal.** Have the routine print `N broken in the overlay` with no
   paths when `--no-overlay` is off, so a maintainer sees the number without the leak risk.
   `automation/gardener/queue_hygiene.py` already does exactly this for the `private/`
   queue mirrors and is the model to copy.

## Definition of done

- [ ] The overlay link sweep has a stated owner and cadence, written in the gardener skill or
      `docs/handbook/memory-map.md`, not only in a session's head
- [ ] The five breaks found on 2026-08-02 are either repaired in the overlay or recorded in a
      private-scope item; either way a later session can tell which
- [ ] Whatever is added prints **counts only** for `private/` paths in any output an agent
      might paste publicly — checked the same way `queue_hygiene.py` is
- [ ] `automation/gardener/verify_links.py --require-roots --no-overlay` still exits 0 and the
      pre-commit hook is unchanged in the overlay-mounted branch
