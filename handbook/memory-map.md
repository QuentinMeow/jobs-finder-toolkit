# Memory Map

Expands `AGENTS.md` → "Memory Map". Every place an agent reads context from
or appends learnings to, by lifecycle **zone** (maintainer-only design doc
`private/docs/harness-engineering-and-repo-evolution/03-folder-structure-and-memory.md` §3 —
overlay-mounted, absent in contributor checkouts) with its retention +
writer. Promotion (MEMORY→LESSONS→SKILL) exists; **forgetting**
(TTL/prune/demotion) is enforced by the `gardener`
(`skills/gardener/`, dry-run by default).

| Location | Zone | Retention | Who writes |
|----------|------|-----------|-----------|
| `AGENTS.md` | (b) harness | permanent, versioned | human + agent (PR) |
| `SKILL.md` / `reference.md` | (b) instructions | permanent, versioned; size-budgeted | human + agent (PR) |
| `LESSONS.md` | (c) durable memory | `last_confirmed` >180d → gardener flags demotion; universalized entries promote into SKILL.md (separate human commit) | agent proposes, human ratifies |
| `memory/decisions/` | (c) durable memory | permanent, append-only ADR log; a reversal is a new file (`Supersedes`/`Superseded-by`) | agent (after owner decision or within standing policy) |
| `memory/known-issues/` | (c) durable memory | until fixed + one PR cycle, then deleted (git is the archive) | agent |
| `memory/facts/` | (c) durable memory | until falsified or superseded; gardener re-verifies stale entries | agent |
| `memory/lessons/` | (c) durable memory | same policy as skill `LESSONS.md`, scoped to non-skill areas | agent proposes, human ratifies |
| `.agents/MEMORY.md` | (d) scratch (gitignored) | ephemeral; entries >14d promote to LESSONS or drop | agent |
| `<applications_root>/0_profile/applications-log.yaml` | (d) derived index | regenerable — never hand-edit; `status.py --sync-log` rebuilds it | `status.py` |
| `<applications_root>/0_profile/company-search-log.yaml` | (d) TTL state | read-side skip `skip_within_days: 7`; rows >90d pruned | `status.py` / gardener |
| `config.company_levels_path()` | (d) TTL cache | comp facts 365d (`last_verified`); level maps re-verified, not expired | agent / `import_company_levels.py` |
| `config.discoveries_dir()` `current/` + `archive/` | (d) working memory | 30d hard TTL; raw scans >14d → `archive/` (move, never delete) | job-search; gardener |
| `private/` overlay (real products; `examples/` is the public mirror) | (e)/(f) products | user-owned, kept; never auto-deleted | human (private) |

The queues (`message-queue/`, `tasks/`) are coordination state, not memory —
their lifecycle is defined in their own READMEs and they hold only live
items.
