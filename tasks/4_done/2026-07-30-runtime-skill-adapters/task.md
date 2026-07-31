# Make overlay-only skills discoverable without publishing their names

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: Owner request in the 2026-07-30 Codex session
- **Claimed-by**: Codex

## Goal

Make public and overlay-only skills discoverable in Codex, Claude Code, and
Cursor while ensuring the public repository's current tracked tree and PR
metadata contain no overlay-only skill names.

## Context

The overlay keeps each private skill at `private/skills/<name>/`. Runtime
adapters must be generated from those directories without hardcoded names.
Public adapters remain tracked and derived from public `SKILL.md` frontmatter;
overlay adapters are local-only and excluded through repository-local Git
metadata. Historical Git objects are out of scope because rewriting published
history is destructive and was not requested.

## Definition of done

- `.agents/skills/`, `.claude/skills/`, and `.cursor/skills/` expose the same
  tracked public adapters and locally generated overlay adapters.
- Bootstrap derives overlay adapter names at runtime and maintains a private,
  repository-local exclude block without writing those names to tracked files.
- The tracked current tree contains no names derived from
  `private/skills/*/SKILL.md`.
- Focused adapter, manifest, leak-guard, link-checker, reconciler, and
  config-less checkout checks pass.
- A public pull request is open with privacy-safe branch, commit, and PR text.
