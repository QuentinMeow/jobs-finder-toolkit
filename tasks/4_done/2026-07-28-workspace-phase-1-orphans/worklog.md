# Worklog — 2026-07-28-workspace-phase-1-orphans

## 2026-07-29 — session 1 (agent)

- Pulled both repos. Public `main` picked up the review-gate rebase fix; the overlay was already
  current apart from one unstaged deletion from an earlier session, left alone.
- Read both orphans before touching them, which is what caught the first surprise: the task this
  plan said to file into `0_backlog` was already `Status: done`, with a resolution naming a
  confirmed root cause and a shipped fix. Re-checked all six artifacts it claimed against the
  current tree — all present — and filed it to `private/tasks/4_done/` with a `verification.md`
  instead. One definition-of-done bullet had never been run; it is recorded as not run.
- Refiled the stray review into the overlay's review queue against `templates/queue/review.md`,
  keeping the full body under the template header rather than compressing it away. Its two
  cited reference paths had moved with a skill rename and were updated.
- Swept `tmp/`: 102 files, 18 non-empty folders, 2 empty. **Nothing deleted.** Most of it is
  owner data — complete application folders and interview screenshots — which the never-delete
  guardrail puts out of reach. The output is a classification for the owner to act on.
- The sweep produced the second surprise and the real find of the phase: three durable records
  cite `tmp/` snapshots that no longer exist. So the phase's "public half is empty" assumption
  was false, and the fix is a rule in the scratch section of the file-organization handbook.
- Split the public side into two stacked PRs: the handbook rule at the bottom (it stands alone),
  the phase record on top.
- **What surprised me:** the plan was confidently wrong about a file it named, in a way only
  reading the file could catch. Both of this phase's corrections came from that.
