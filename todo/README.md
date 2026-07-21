# todo/ — the AI↔human async work queue

One folder, four queues. This is how the owner and agents hand work to each
other **across sessions, without a live conversation**: each side writes
files; the other side picks them up on its next visit. The full behavioral
contract agents follow is `AGENTS.md` → "Async collaboration"; this README
is the map.

| Queue | Direction | Contains | Emptied by |
|-------|-----------|----------|------------|
| `inbox/` | **human → AI** | Free-form asks the owner drops in (any format, even one line) | An agent converts each item into a proper task/decision/answer, acts or files it, then deletes the inbox item in the same commit |
| `tasks/` | AI ⇄ AI (owner may add too) | Actionable, self-contained work items (format in `tasks/README.md`) | Whoever does the work; `Status: done` for one PR cycle, then deleted |
| `decisions/` | **AI → human** | Questions only the owner can answer, fully self-contained with options + recommendation + a default path (format in `decisions/README.md`) | The owner answers (inline edit or told in chat) → an agent records it in `design-decisions/` and deletes the file here |
| `reviews/` | **AI → human** | Things a human may want to eyeball: docs awaiting a read, data-quality queues worth a look, "I did X, sanity-check me" notes (format in `reviews/README.md`) | The owner looks (or explicitly declines to); the filing agent removes it once acknowledged or stale |

## Rules that apply to every queue

- One self-contained file per item, `<kebab-slug>.md`. A reader must be able
  to act from the file alone — no chat-history archaeology.
- **Public tree ⇒ leak-guard rules apply.** Items about the owner's real
  pipeline/identity go in the same-shape private mirror `private/todo/`.
- Nothing here blocks: every `decisions/` item states a default path agents
  follow while it's pending; every `reviews/` item is optional to act on.
- Resolved/handled files are **deleted** (after at most one PR cycle) — git
  history is the archive. No done/ subfolders.
- Agents check this folder at session start (the boot ritual in
  `AGENTS.md`): `inbox/` first, then whether any `decisions/` item got an
  answer, then `tasks/` relevant to the session's work.

## History

`tasks/` and `decisions/` moved here from repo-root `tasks/` and
`unresolved-decisions/` (owner decision, 2026-07-21 — recorded in
`design-decisions/process-folders-v2-todo-queue.md`). `known-issues/` and
`design-decisions/` remain at root: they are *records*, not queues.
