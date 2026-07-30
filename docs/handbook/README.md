# docs/handbook/ — the extended reference behind AGENTS.md

`AGENTS.md` carries the boot-critical core every agent reads before acting;
this folder holds the full detail — one named document per concern. Read the
doc a contract section points you to; you never need to read the whole
folder. Active design programs live in `docs/designs/`, not here.

| Document | Contents |
|----------|----------|
| `docs/handbook/configuration.md` | The config system: discovery order, path functions, output stems |
| `docs/handbook/public-private-split.md` | The two-repo model: what ships, skill visibility, products, leak guard |
| `docs/handbook/repo-map.md` | The complete per-path directory table |
| `docs/handbook/command-cookbook.md` | Every toolkit command, copy-paste ready |
| `docs/handbook/memory-map.md` | Agent-memory zones, retention windows, writers |
| `docs/handbook/skills-and-vendoring.md` | Skill directory layout + how code is shared across self-contained skills |
| `docs/handbook/file-organization.md` | Purpose-named folders, tree-first file placement, scratch/tmp rules |
| `docs/handbook/subagent-budget.md` | The repo-wide subagent cap |
| `docs/handbook/collaboration-modes.md` | The human dial: `autonomous` / `async` / `pair`, and what "expensive to reverse" means |
| `docs/handbook/application-folders.md` | The full application-folder convention: statuses, files, splits |
| `docs/handbook/tailoring-guardrails.md` | Extended tailoring guardrails: traceability, keywords, skill lists |
| `docs/handbook/architecture.md` | Human-facing design doc: render pipeline, config, vendoring, CI gates |
| `docs/handbook/private-overlay.md` | Setting up and maintaining the private overlay repo |
| `docs/handbook/metrics.md` | Opt-in local metrics collection |
| `docs/handbook/doc-style.md` | Style contract for human-read documents (decision blocks, async fields) |
| `docs/handbook/comparisons/` | Research comparing this toolkit to external tools |
