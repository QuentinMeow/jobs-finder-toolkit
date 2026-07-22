# message-queue/ — async human↔agent messages, one file each

All human↔agent coordination goes through this folder: each side writes
files; the other side picks them up on its next visit, **across sessions,
without a live conversation**. Queues are split by **who acts next** — a
stable property — never by topic or urgency (urgency lives in each item's
`Blocking` field; files never move between queues, so links never break).
The full behavioral contract agents follow is `AGENTS.md` → "Async
Collaboration"; this README is the map. Work items themselves live in
`tasks/`, not here — this folder holds *messages about* work.

| Queue | Who acts next | Contains |
|-------|---------------|----------|
| `needs-human/decisions/` | **owner** | Choices only the owner may make — options, recommendation, and a default path agents follow while pending (format: `needs-human/decisions/README.md`) |
| `needs-human/clarifications/` | **owner** | Questions that will matter soon; the filing agent states an assumption and proceeds on it meanwhile (format: `needs-human/clarifications/README.md`) |
| `needs-human/reviews/` | **owner** | Optional human-eyes items — doing nothing must be safe (format: `needs-human/reviews/README.md`) |
| `needs-agent/requests/` | **any agent** | The owner's free-form drop box — any shape, even one line; the only queue with no required format |
| `needs-agent/retries/` | **any agent** | Repair work filed by automated checks or a failed job, one finding per file |

## Rules that apply to every queue

- One self-contained item per file, `<kebab-slug>.md` (no dates or numbers
  in filenames — the filing date lives in the item's `Filed` field). A
  reader must be able to act from the file alone — no chat-history
  archaeology.
- **Public tree ⇒ leak-guard rules apply.** Items about the owner's real
  pipeline/identity go in the same-shape private mirror
  `private/message-queue/`.
- Nothing here blocks by default: every `decisions/` item states a default
  path, every `clarifications/` item states an assumption, every `reviews/`
  item is safe to ignore. Only an explicit `Blocking: yes` stops work.
- **Claim before resolving**: commit a one-line `Status` edit
  (e.g. `folding`) before folding an answer, so parallel sessions don't
  collide.
- Resolved/handled items are **deleted in the resolving commit** — git
  history is the archive. No done/ subfolders.
- An answer the owner gives in chat is written into the queue file in the
  same turn — chat is the only channel with no file trace of its own.
- Agents sweep this folder at session start (the boot ritual in
  `AGENTS.md`): `needs-agent/requests/` first, then `needs-agent/retries/`,
  then `needs-human/decisions/` for newly filled answers.

## History

Restructured from the former `todo/` queue family (owner decision,
2026-07-22 — recorded in `../memory/decisions/agentfold-restructure.md`);
`todo/tasks/` became the sibling `tasks/` tree at the same time. Earlier
lineage: `../memory/decisions/process-folders-v2-todo-queue.md`.
