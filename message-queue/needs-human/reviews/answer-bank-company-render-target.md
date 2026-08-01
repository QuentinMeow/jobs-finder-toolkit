# Company answers now render into the company tree, not the question bank

- **Filed**: 2026-07-31
- **Look at**: `message-queue/needs-human/decisions/examples-reshape-seven-calls.md` § D5, then
  `.venv/bin/python skills/behavioral-interview-prep/scripts/answer_bank.py check <your sources dir>`
  before the next `render`.
- **Why you might care**: two things. (1) **D5 is still unanswered, and this change is D5's
  recommendation** — a company-prefixed alias now renders to
  `config.companies_root()/<key>/derived/<slug>.md` instead of back into the question bank. If you
  decline D5, this PR is what gets reverted. (2) It is a generator that now writes into your
  private company tree: `render` overwrites the generated file at that path, so any of those files
  you hand-edited after phase 5 moved them loses those edits on the next render. `check` is
  read-only and tells you which ones differ from their YAML source first. D5's own measurement also
  notes one company-prefixed file still sitting in the question bank — a render now creates the
  company-tree copy and leaves that one behind. Agents never delete your files; removing the stale
  copy is yours to do.
- **If you do nothing**: nothing moves and nothing is written. The routing only takes effect the
  next time someone runs `render`, and a missing company folder is a loud FAIL naming the key
  rather than an invented folder.
- **Resolution**:
