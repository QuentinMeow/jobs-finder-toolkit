# Build the email provider contract and relocate Outlook safely

- **Priority**: P1 (next email round)
- **Area**: email
- **Source**: `design/application-progress-calendar/execution-plan.md` Stage 1
- **Claimed-by**: claude (subagent session 2026-07-22, branch `email/stage-1-provider-contract`)

## Goal

Ship the provider boundary and conformance harness without changing the
current Outlook assistant's behavior or draft-only safety guarantees.

## Context

Implement `design/raw-data-layer/03-provider-interfaces.md`: one
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
