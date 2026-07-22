# Approach 3 — CLI / service boundary ("scripts are tools, not libraries")

**Strategy:** Decoupling-first. Shared functionality is never *imported* across a
boundary — it is *invoked*. Each unit of shared logic is exposed as a small
command-line tool with a documented, stable input/output contract. Skills and toolkit
scripts that need it run it as a subprocess (or the agent runs it directly) and read
its output. This is the "execute the script" model the Agent Skills best-practices
guide explicitly prefers for deterministic operations.

## How it works

1. Every shared capability gets a CLI with a **stable name, stable flags, and
   structured output** (JSON on stdout). Example: a `location` classifier tool.
2. Consumers depend only on the **contract** (the command name + its JSON schema),
   never on Python internals. A refactor behind the CLI is invisible to callers.
3. Skills invoke via `subprocess` (for script-to-script use) or the agent invokes the
   documented command directly from `SKILL.md` (for agent-driven steps).

### The location tool, as a CLI

```python
# jobsfinder_tools/location_cli.py
"""Classify a posting location against the configured metro / US-remote policy.

Usage:
  python location_cli.py --classify "Remote - US"      # -> {"category": "us_remote", "match": true}
  python location_cli.py --classify "Berlin, Germany"  # -> {"category": "foreign", "match": false}
"""
import argparse, json, sys
# ... single implementation of the rule lives here ...

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--classify", required=True)
    args = ap.parse_args()
    cat = classify_location(args.classify)
    json.dump({"category": cat, "match": is_match(cat)}, sys.stdout)
    return 0
```

Consumer (a skill script), depending only on the contract:

```python
import json, subprocess
out = subprocess.run(
    [sys.executable, LOCATION_TOOL, "--classify", loc],
    capture_output=True, text=True, check=True,
).stdout
verdict = json.loads(out)          # {"category": ..., "match": ...}
```

`SKILL.md` (agent-driven), documenting the stable command:

```bash
# Classify a posting location (configured metro / US-remote policy)
.venv/bin/python scripts/tools/location_cli.py --classify "Remote (US)"
```

### Two flavors of "boundary"

- **Fine-grained tools** — one CLI per shared capability (`location_cli.py`,
  `naming_cli.py`). Simple, but chatty (a subprocess per call is slow for hot loops).
- **One umbrella CLI** — a single `jf` entrypoint with subcommands
  (`jf location classify ...`, `jf status`, `jf render ...`). Fewer moving parts, one
  contract surface, easy to document. Recommended if you go this route.

## Pros

- **G1 ✅ No imports across boundaries at all.** A move/rename behind the CLI cannot
  break a caller as long as the command contract holds. Structurally eliminates
  README §2.1/§2.2.
- **G2 ✅ Single source of truth.** The logic lives once, behind the tool; callers
  can't fork it.
- **G4 ✅ Clear ownership + clean seams.** "If it's shared, it's a tool with a
  contract." Language-agnostic: a future non-Python skill can still call the CLI.
- **Matches the standard's guidance** ("prefer scripts for deterministic operations,"
  "make execution intent clear," "solve don't defer" — the tool handles its own
  errors and returns structured results).
- Easy to test the contract (golden input → expected JSON) independent of callers.

## Cons

- **G3 ⚠️ Partial portability.** A skill that shells out to `scripts/tools/jf` still
  *requires that tool to exist on the path/repo*. It is decoupled at the code level
  but still coupled to "the CLI is installed here." Not fully self-contained unless
  the tool is also vendored into the skill (→ Approach 2).
- **G5 ⚠️ Contract/versioning overhead.** You now maintain a CLI surface and its JSON
  schema as an API. Changing output shape is a breaking change across all callers —
  more discipline than editing a function signature with a type checker to catch
  fallout.
- **Performance.** A subprocess per call has real overhead. Fine for agent-driven,
  once-per-task steps; bad for tight loops (e.g. classifying 500 postings — you'd
  need a batch/`--stdin-jsonl` mode). Provide batch endpoints for hot paths.
- **Ergonomics.** Parsing stdout/handling non-zero exits/quoting is clumsier than
  `import`; loses IDE autocomplete, types, and stack traces across the boundary.
- More runtime failure modes (tool missing, wrong Python, malformed output) than a
  static import.

## When to choose this

Choose Approach 3 when the shared capability is naturally a **coarse, deterministic
operation invoked occasionally** (render a resume, run status, classify one posting on
demand), when you want **language independence** or a hard decoupling seam, or when
the shared thing is really a *service* (needs its own heavy deps you don't want every
caller to install). It is a strong fit for the toolkit's existing top-level scripts
(`render.py`, `status.py` already *are* CLIs) but a poor fit for fine-grained,
hot-loop pure functions like per-posting location classification unless batched.

## Migration steps

1. Define the shared surface as CLIs: keep `render.py`/`status.py` as-is (already
   CLIs); add `location` and `naming` as subcommands of a single `jf` umbrella CLI
   with JSON output + a documented schema, plus a batch `--stdin-jsonl` mode for hot
   loops.
2. Replace cross-boundary *imports* with subprocess calls to the CLI (fixing
   `company_roles.py`); replace `scoring.location_ok` with a batch CLI call or (for
   perf) keep an in-skill copy fed by the same golden tests.
3. Write contract tests (golden input → expected JSON) for each tool.
4. Update `SKILL.md`/`AGENTS.md` to reference the stable `jf ...` commands (also fixes
   the stale-path problem, README §2.4).
5. Document the output schema + a deprecation policy for contract changes.

**Effort:** Medium–High (design + maintain the contract, add batch modes). The
top-level toolkit is already CLI-shaped, so partial adoption is cheap; full adoption
for fine-grained logic is the expensive part.
