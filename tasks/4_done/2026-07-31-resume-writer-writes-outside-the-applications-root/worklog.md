# Worklog — resume-writer writes outside the applications root

## 2026-07-31 — session 1 (agent)

- Rewrote resume-writer step 5's `mkdir`/`cp` to take `<apps>` = `config.applications_root()`.
- Swept every other bare `applications/` literal and classified each as instruction or
  shorthand (table in `verification.md`); added a one-line definition in the five documents
  a reader meets the shorthand in.
- Left the three remaining shorthand sites alone deliberately — they are reached only from a
  document that now defines the term.
- Next: none. Shipped in the PR stacked on `fix/02-ci-runs-the-promised-gates`.
