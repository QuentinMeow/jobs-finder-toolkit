# memory/decisions/

One file per **decided** design question — a lightweight ADR log. These record
choices already made (by the owner, or by an agent within its authority) so
future sessions stop re-litigating them. Open questions that still need the
owner's input live in `message-queue/needs-human/decisions/` instead, and move here once
decided.

## Rules

- Filename: `<kebab-slug>.md`.
- **Public tree ⇒ leak-guard rules apply** (no real names/employers/dated
  personal facts; personal-scope decisions go in `private/memory/decisions/`).
- Never rewrite a decision file to say something different — a reversal is a
  new file that links the old one (`Superseded-by:` / `Supersedes:` headers).
- Larger design *proposals* (multi-approach explorations) stay in
  `docs/designs/<topic>/`; the decision file records the outcome and links there.

## File format

Copy `templates/memory/decision.md` and fill the blanks — the template is
the single source of truth for this schema (validated by
`automation/reconcile/reconcile.py`).
