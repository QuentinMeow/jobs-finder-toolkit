# May the behavioral canary send a public-only fixture to GPT-5.6 Sol?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-04
- **Source**: required model-pinned eval for the behavioral skill policy change
- **Blocks**: merging the policy change; deterministic tests pass, but the behavioral canary gate has not run
- **Default path**: do not invoke an external model and leave the policy PR unmerged
- **Cost if wrong**: high
- **Safe to merge because**: the default transmits nothing and does not bypass the required eval gate

## Background

The attempted fresh GPT-5.6 Sol high canary was rejected before execution because a runner launched
from this checkout could read the mounted private overlay and transmit private profile or interview
content. Nothing was sent. The canary only needs public policy, skill, and fictional Jordan Rivers
fixtures, so it can run from a temporary public-only copy that contains no private overlay.

## Options

### Option A — approve a public-only external canary (recommended)

Create a temporary copy containing only public `AGENTS.md`, the behavioral skill, its canary rubric,
and fictional Jordan Rivers example data; run GPT-5.6 Sol high against that copy; inspect and record
the outputs; then discard the temporary copy. This sends those public files and prompts to the
external OpenAI model service, but no private overlay data.

### Option B — do not approve external evaluation

Keep the deterministic test results only. Because the repository requires model-pinned canaries for
this behavioral skill change, the branch remains unmerged until the gate is changed or an approved
equivalent is available.

**Your answer:** ______
