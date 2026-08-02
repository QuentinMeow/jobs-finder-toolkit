# Worklog — 2026-08-01-the-contract-contradicts-itself-in-eight-places

## 2026-08-02 — session 1 (agent)

- Re-verified all eight items against this branch's HEAD before editing; the filed line
  numbers had rotted (the task was written against `fix/43-sponsorship-recall`), so every
  item was re-located by content, not by coordinate.
- **Item 7 was already fixed** before this session. The eval-gate bullet already reads
  "must pass canaries before merge **where a set exists** … mechanical or small edits —
  **and skills with no canary set** — skip with a recorded one-line rationale". No edit made;
  recorded in `verification.md` so a later reader does not re-open it.
- Items 1-6 corrected in `AGENTS.md` as wording changes only — no behaviour, no new section:
  1. Read Hygiene now carves out the two-way-file safety re-read explicitly.
  2. Boot ritual step 1 now says a dated agent reply LEAVES the request file, matching
     `message-queue/needs-agent/requests/README.md`.
  3. "tracked ⇒ published" replaced with "tracked ⇒ must be PUBLISHABLE", naming the five
     export-absent roots so an agent knows where in-flight prose may live.
  4. `parked` → `parked-until-revisit`, the value the files actually carry.
  5. `--file-retries` no longer reads as an alternative to passing the reconciler.
  6. Doc ownership now distinguishes the ROOT `README.md` from a FOLDER's `README.md`.
- **Item 8 filed, not decided**: no existing decision item covered it, so
  `message-queue/needs-human/decisions/is-never-delete-owner-data-scoped-to-repo-local-products.md`
  was written from `templates/queue/decision.md` with a default path that is the intersection
  of the two surfaces (nothing an agent does today changes while it is pending).
- Nothing was touched near Read Order step 2, where a sibling branch is adding a GitHub
  routing invariant.
