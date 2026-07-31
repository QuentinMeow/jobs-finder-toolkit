# Build the email provider contract and relocate Outlook safely

- **Priority**: P1 (next email round)
- **Area**: email
- **Source**: `docs/designs/application-progress-calendar/execution-plan.md` Stage 1
- **Claimed-by**: claude (subagent session 2026-07-22, branch `email/stage-1-provider-contract`)

## Goal

Ship the provider boundary and conformance harness without changing the
current Outlook assistant's behavior or draft-only safety guarantees.

## Context

Implement `docs/designs/raw-data-layer/03-provider-interfaces.md`: one
send-less `MailProvider` contract, audited raw-HTTP transport, provider
route allowlists, isolated provider folders, and folder-walking safety
checks. Relocate the current Outlook implementation, update pre-commit
paths, and rename the skill to `email-assistant` with no alias. Gmail is
read-only and does not land in this task.

This is a prerequisite for email-store sync but independent of the tracker
schema/calendar task. Preserve every existing Sent/Drafts duplicate-reply
preflight and `isDraft: true` assertion.

## Definition of done

- Synthetic conformance and every existing Outlook draft-only test pass.
- The folder-walking checker fails a planted send-capable provider fixture
  and forbids SDK imports and cross-provider imports.
- Pre-commit paths and public instructions point only to the renamed skill;
  there is no compatibility alias.
- One explicitly requested read-only `--live` conformance run succeeds;
  no mailbox mutation occurs.
- Behavioral instruction edits pass the email-assistant canaries and record
  the result.

## Held in `3_in-review`, 2026-07-31 — what is missing

A bookkeeping pass promoted six finished in-review folders to `4_done` and deliberately left this
one behind. PR #60 is merged; the gap is in the definition of done, not in the code:

- **The read-only `--live` conformance run has never happened.** It needs the real keyring login
  and is the documented owner action. The folder says so; nothing here can close it.
- **The recorded canary result the last bullet asks for does not exist.** No `email-assistant`
  eval record exists for this task's date. The worklog records a deliberate skip under the
  risk-based eval gate, which is defensible — but the bullet as written asks for a record, and a
  reader cannot tell "skipped with rationale" from "run and passed" without one.

Promoting this folder would assert both. Either satisfy them, or amend the two bullets to say what
was actually decided.
