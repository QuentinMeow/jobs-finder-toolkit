# Refresh calendar identity after an application correction

- **Priority**: P1 (this round)
- **Area**: tracker
- **Source**: 2026-08-07 application-tracker session
- **Claimed-by**: Codex

## Goal

When a tracked application's slug or role title is corrected, a subsequent progress update must refresh both the hidden calendar identity and the tool-generated visible row without changing owner-authored wording.

## Context

The progress updater previously refreshed phase, state, label, and links while preserving the calendar occurrence's original application slug and role. The consistency check then failed after an otherwise valid application correction. The renderer also compared generated text against the new role instead of the occurrence's prior role, so it could mistake old tool-generated wording for an owner customization.

## Definition of done

- A regression test begins with a fictional calendar occurrence carrying an obsolete slug and role, updates progress against corrected metadata, and verifies both machine and visible identities.
- The application-tracker calendar suite passes.
- The vendored calendar helper remains byte-identical to its canonical source.
