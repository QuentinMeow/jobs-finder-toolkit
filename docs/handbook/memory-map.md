# Memory Map

Expands `AGENTS.md` → "Memory Map". Every place an agent reads context from
or appends learnings to, by lifecycle **zone** (maintainer-only design doc
`private/docs/03-folder-structure-and-memory.md` §3 —
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
| `config.applications_jsonl_path()` | (c) durable memory | permanent, append-only; **not regenerable** — nothing rewrites it, so a deleted application keeps its row and recovery is overlay git history, never a rebuild. Repair a wrong row by appending a tombstone (`status.py --forget-log`), never by hand-editing | `status.py` |
| `config.company_search_log_path()` | (d) TTL state | read-side skip `skip_within_days: 7`; rows >90d pruned | `status.py` / gardener |
| `config.company_levels_path()` | (d) TTL cache | comp facts 365d (`last_verified`); level maps re-verified, not expired | agent / `import_company_levels.py` |
| `config.discoveries_dir()` `current/` + `archive/` | (d) working memory | 30d hard TTL → moved to `archive/` on `--apply` (move, never delete); raw scans >14d but inside the TTL are only FLAGGED for human review — `expire_discoveries.py` never auto-moves them, and neither should you | job-search; gardener |
| `private/` overlay (real products; `examples/` is the public mirror) | (e)/(f) products | user-owned, kept; never auto-deleted | human (private) |

The queues (`message-queue/`, `tasks/`) are coordination state, not memory —
their lifecycle is defined in their own READMEs and they hold only live
items. Nothing expires them, so the gardener's report-only `queue-hygiene`
routine flags the aging ones (old reviews, long-pending decisions, dwelling
tasks, parked items whose revisit condition already shipped); acting on a
finding is always a human judgement, so it exits 0 and moves nothing.
