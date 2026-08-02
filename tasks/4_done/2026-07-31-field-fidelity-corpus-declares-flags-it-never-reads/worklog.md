# Worklog — 2026-07-31-field-fidelity-corpus-declares-flags-it-never-reads

## 2026-08-02 — session 1 (agent)

- Took the task's recommended option — drop `--limit`/`--seed` from the `corpus`
  subparser — after checking it breaks nobody. Grepped every tracked `.md`, `.py`
  and `.yaml` for `corpus`: no caller passes either flag, the skill's documented
  command shows `corpus` bare, and the only in-repo caller is the test helper,
  which passed them into an `argparse.Namespace` that `cmd_corpus` never read.
  Implementing them instead would have meant inventing a sampling contract for a
  command whose whole value is that it reads everything.
- Fixed the docstring's "each **sampled** entity" claim, and two adjacent claims
  in the same paragraph that were also untrue: `corpus` walks manifests, not the
  derived store index, and it reads no `jd.md` lines (that is `check`). Left the
  `sample` paragraph alone.
- Pinned three things, not one: the flags are rejected by argparse (exit 2,
  "unrecognized arguments"), `sample` still accepts `--n`/`--seed` so a later
  cleanup cannot over-remove the real levers, and the docstring no longer
  advertises sampling.
- The `_StoreCase._corpus()` helper stopped passing `limit=600, seed=42` into the
  Namespace. It was harmless — nothing read them — but it read as though the
  command took them.
