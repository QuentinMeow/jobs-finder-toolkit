# memory/ — what this project must not forget

Long-term project memory, split by kind. Everything here states *current*
truth (git remembers the past) — except `decisions/`, whose records are
immutable.

| Zone | Contains |
|------|----------|
| `decisions/` | ADRs — decided design questions: what was chosen, alternatives, consequences. **Immutable**: a reversal is a new file linking the old one (`Supersedes` / `Superseded-by`). Format: `decisions/README.md` |
| `known-issues/` | Reproducible, accepted-or-unfixed bugs, one self-contained file each. Format: `known-issues/README.md` |
| `facts/` | Durable constraints not derivable from code or git history (environment quirks, external-service behavior, owner-stated invariants) |
| `lessons/` | What failure taught, **scoped by area**. Skill-specific lessons stay in each skill's `LESSONS.md` (the per-skill lessons zone); this folder holds lessons for non-skill areas |

Open questions that still need the owner live in
`../message-queue/needs-human/decisions/` and move into `decisions/` once
decided. Retention and pruning are the `gardener` skill's job (see
`AGENTS.md` → "Memory Map").

**Public tree ⇒ leak-guard rules apply**: personal-scope records go in the
same-shape private mirror `private/memory/`.
