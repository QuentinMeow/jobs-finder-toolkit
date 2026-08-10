# Should global rules ban backward compatibility and temporary bridges?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-09
- **Source**: [agent-instruction and harness research](../../../docs/handbook/comparisons/agent-instruction-harnesses.md)
- **Blocks**: only the final wording of two global engineering defaults. The five non-conflicting image rules and two evidence-backed harness rules can operate independently.
- **Default path**: omit a global compatibility rule; permit a temporary bridge only when it is isolated, verified, and carries an explicit exit condition.
- **Cost if wrong**: ratify
- **Safe to merge because**: these defaults change instruction prose only. Removing the relevant bullet from `~/.codex/AGENTS.md` restores the prior behavior; no repository data, API, or schema is migrated.

## Background

The image proposes two absolutes: remove backward compatibility instead of adding migrations or
fallbacks, and reject any architecture intended to be replaced later. Those statements conflict with
real product obligations. This repository preserves append-only application history, owner data, and
explicit migrations, while its async workflow sometimes ships a reversible default before the owner
answers. OpenAI's own Codex protocol also treats backward compatibility as a requirement, while
long-running-agent research supports incremental delivery from a working state.

The question is not whether obsolete code and accidental stopgaps are desirable. It is whether one
global file may decide compatibility and transition policy for every repository before the product
contract is known.

## Options

The tradeoff is aggressive cleanup and short-term simplicity against product compatibility and safe
incremental migration.

### Option A — adopt both absolutes

Globally remove obsolete paths and refuse temporary bridges unless the user explicitly overrides the
rule. This produces the smallest steady-state code but makes breaking changes the default.

***Example consequence:*** an agent removes a deprecated configuration key even though a deployed
client still sends it, because no repository-local sentence explicitly restated compatibility.

### Option B — preserve compatibility and avoid interim designs by default

Require compatibility unless the repository or user explicitly authorizes a break, and require the
final architecture in every change. This is conservative but accumulates shims and can force large,
risky migrations.

***Example consequence:*** a small feature gains another permanent fallback, or waits for a broad
rewrite, even when every caller could have been updated safely in one change.

### Option C — make both contract-sensitive (recommended)

Do not set a global compatibility outcome. Follow the user and repository contract; when breaking
change is authorized, update callers, tests, and docs together instead of adding silent fallbacks.
Permit an interim bridge only when the final design cannot safely ship in the same increment, and
require isolation, verification, an owner, and a concrete exit condition.

***Example consequence:*** a public API keeps an explicit, tested migration path, while an internal
helper with no consumers is removed cleanly; a two-phase migration can ship without turning its bridge
into anonymous permanent debt.

## Recommendation

Choose Option C. Compatibility is externally observable behavior, so only the product contract can
decide it. Temporary architecture is sometimes the safest route to the long-term design, but the
bridge must be visible and removable rather than an undocumented promise to fix it later.

**Strongest case against this:** Option C depends on agents correctly recognizing what counts as a
contract and consistently recording exit conditions. Option A is simpler to apply and leaves less
dead code when most repositories are early-stage internal tools.

**Confidence:** high — I compared the supplied rules with the active global and repository contracts,
the current Codex instruction-loading documentation, and primary OpenAI, Anthropic, Vercel, and
AGENTS.md guidance. I did not verify the image's 60-billion-token attribution.

Answer in plain words; for example, "C", or choose different treatment for compatibility and
temporary bridges.

**Your answer:** ______
