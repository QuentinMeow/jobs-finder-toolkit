# handbook/ — the extended reference behind AGENTS.md

`AGENTS.md` carries the boot-critical core every agent reads before acting;
this folder holds the full detail — one named document per concern. Read the
doc a contract section points you to; you never need to read the whole
folder. Active design programs live in `design/`, not here.

| Document | Contents |
|----------|----------|
| `handbook/configuration.md` | The config system: discovery order, path functions, output stems |
| `handbook/public-private-split.md` | The two-repo model: what ships, skill visibility, products, leak guard |
| `handbook/repo-map.md` | The complete per-path directory table |
| `handbook/command-cookbook.md` | Every toolkit command, copy-paste ready |
| `handbook/memory-map.md` | Agent-memory zones, retention windows, writers |
| `handbook/skills-and-vendoring.md` | Skill directory layout + how code is shared across self-contained skills |
| `handbook/file-organization.md` | Purpose-named folders, tree-first file placement, scratch/tmp rules |
| `handbook/subagent-budget.md` | The repo-wide subagent cap |
| `handbook/application-folders.md` | The full application-folder convention: statuses, files, splits |
| `handbook/tailoring-guardrails.md` | Extended tailoring guardrails: traceability, keywords, skill lists |
| `handbook/architecture.md` | Human-facing design doc: render pipeline, config, vendoring, CI gates |
| `handbook/private-overlay.md` | Setting up and maintaining the private overlay repo |
| `handbook/metrics.md` | Opt-in local metrics collection |
| `handbook/doc-style.md` | Style contract for human-read documents (decision blocks, async fields) |
| `handbook/comparisons/` | Research comparing this toolkit to external tools |
