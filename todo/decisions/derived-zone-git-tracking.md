# Should the store's `derived/` zone be git-tracked in the overlay repo?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-21
- **Blocking?**: Nothing. The default path (A) is already in force via
  `private/.gitignore` (`data/*/derived/` is ignored). This decision only
  confirms or overrides that.
- **Default path**: Option A — do NOT git-track `derived/`. `index/`,
  `annotations/`, and `state/` stay tracked.

## Background

At raw-data-layer sign-off (2026-07-21) you accepted the tracked-zones split:
*"track `derived/`, `index/`, `annotations/`, `state/`; gitignore `raw/`"* — on
the rationale that those four zones are **small** (git is right for small zones;
content-addressed raw blobs are what balloon a repo).

Building the real jobs store (Stage 2, then Stage 3's bigtech capture) made the
actual sizes measurable, and `derived/` contradicts the small-zones premise:

- `derived/` measured **~225 MB across ~44,106 files** (~15,200 posting entities,
  each a folder of `posting.yaml` + `jd.md` + `events.jsonl`), **dominated by the
  verbatim JD text** in `jd.md`.
- It is also **fully rebuildable from `raw/` by design** (the whole point of the
  regenerable zone) and it **churns wholesale on every rebuild** (a builder-code
  or classifier change re-stamps every entity), so tracking it would add ~225 MB
  plus large per-rebuild diffs to the overlay repo's history forever.
- `index/`, `annotations/`, and `state/` are genuinely small (a few MB of JSONL
  and YAML) and NOT rebuildable-from-nothing (annotations/state are human/operational),
  so tracking those still matches the original rationale.

## Options

| Option | What it means | Pros | Cons / cost |
| --- | --- | --- | --- |
| **A — don't track `derived/`** (DEFAULT; already in force) | Gitignore `data/*/derived/`; keep `index/`, `annotations/`, `state/` tracked. | Repo stays small; no per-rebuild churn; matches the "regenerable, rebuild-don't-migrate" design; `annotations`/`state` (the non-recomputable zones) still versioned. | `derived/` is not in git history — but it is a pure function of `raw/` + code, reproducible with one `build_postings.py --rebuild`. |
| **B — track everything** (the letter of the sign-off) | Track `derived/` too. | Literal fidelity to the decision as worded; `derived/` browsable in git. | Overlay repo grows ~225 MB immediately and diffs wholesale on every rebuild; weaponizes git against a cache the design explicitly says to rebuild, not version. |
| **C — track `derived/` minus `jd.md`** | Track `posting.yaml` + `events.jsonl`; gitignore the `jd.md` (and `jd-*.md`) files that dominate the size. | Keeps the structured facts/opinions/events in git at a fraction of the size; drops only the bulky verbatim text (which is anyway re-derivable from raw and re-fetched fresh at draft time). | A partially-tracked zone is a subtle contract (mixed tracked/ignored inside one regenerable zone); still churns `posting.yaml` wholesale on every rebuild; more `.gitignore` surface to get right. |

## Recommendation

**Option A.** The size measurement invalidates the small-zones premise the original
"track derived/" answer rested on, and `derived/` is exactly the regenerable cache
the design says to rebuild rather than version — tracking it fights the architecture
for no durable benefit. The zones that carry non-recomputable decisions
(`annotations/`, `state/`) and the compact code-filter index (`index/`) remain
tracked, so nothing irreplaceable is untracked. A is already the operative behavior;
this decision just ratifies it (or picks B/C if you want `derived/` in history).

**Your answer:** ______
