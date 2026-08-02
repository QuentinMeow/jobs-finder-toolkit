# Verification — four config defaults named the retired layout

Run from the repo root on branch `fix/03-owner-data-paths`. Absolute home paths are redacted to
`<repo-root>`.

## Live-data hazard, checked FIRST

All four keys are set explicitly in the working `config.yaml`, so a default change cannot move
a resolved path for the current owner (values elided; only the key names matter here):

```
$ grep -nE '^\s*(blacklist_yaml|story_bank_dir|search_profiles_dir|skill_references_root):' config.yaml
18:  story_bank_dir:        <set>
26:  blacklist_yaml:        <set>
27:  search_profiles_dir:   <set>
35:  skill_references_root: <set>
```

Proved rather than argued — the pre-change and post-change modules resolved side by side against
the same live config:

```
before  <repo-root>/private/market/blacklist.yaml
before  <repo-root>/private/me/interviews/story-bank
before  <repo-root>/private/market/searches
before  <repo-root>/private/skills/skill-notes/resume-writer
after   <repo-root>/private/market/blacklist.yaml
after   <repo-root>/private/me/interviews/story-bank
after   <repo-root>/private/market/searches
after   <repo-root>/private/skills/skill-notes/resume-writer
```

Identical. **No resolved path moved for the current owner.**

## What actually changes: an overlay built from the handbook that omits the four keys

Scaffolded exactly as `docs/handbook/private-overlay.md` says, with a `config.yaml` that sets
only `applications_root`:

```
before  blacklist    private/job-search/blacklist.yaml        -> exists: False
before  story-bank   private/interviews/behavioral/story-bank -> exists: False
before  searches     private/job-search-profiles              -> exists: False
before  skill-notes  private/skills/references_private        -> exists: False
after   blacklist    private/market/blacklist.yaml            -> exists: True
after   story-bank   private/me/interviews/story-bank         -> exists: True
after   searches     private/market/searches                  -> exists: True
after   skill-notes  private/skills/skill-notes               -> exists: True
```

Four misses became four hits. Every one of them failed soft before — a stderr notice from
`registry.py`, a story-bank digest that reports "no story bank found", a search-profile
directory that resolves to nothing — so none of it surfaced as an error.

## Under the example config: unchanged, and still not resolving

`overlay_root()` under `config.example.yaml` is `examples/`, whose shape is workspace phase 8's
job. All four defaults resolved to non-existent directories before this change and still do; the
change neither fixes nor worsens that. The task's DoD item "`examples/` has the shape that makes
them resolve" is therefore **left open for phase 8** — it requires reshaping tracked example
data, which is not this branch's scope. The related DoD item "a smoke assertion that every
`config.*()` path exists under the example config" is blocked on the same thing and is likewise
not done here.

## Tests

`automation/shared/tests/test_config_accessors.py` pins each new default, and the story-bank
test now pins the accessor against the layout both hashers record in `STORY_BANK_REL` rather
than against the retired derivation it used to encode.

```
$ .venv/bin/python -m unittest discover automation/shared/tests
Ran 425 tests in 52.221s

OK
```

The three job-search sites and the resume-writer docstrings/fixtures named in the task moved
with the defaults. One of them was a real (not cosmetic) dependency:
`skills/job-search/scripts/tests/test_overlay_blacklist.py` plants its fixture blacklist at the
DEFAULT location, so it failed until the fixture moved to `private/market/` — which makes that
test a second pin on `blacklist_path()`'s default.

```
$ JOBHUNT_CONFIG=$PWD/config.example.yaml .venv/bin/python -m unittest discover \
      -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests
Ran 333 tests in 18.571s

OK

$ JOBHUNT_CONFIG=$PWD/config.example.yaml .venv/bin/python -m unittest discover \
      -s skills/resume-writer/scripts/tests
Ran 92 tests in 31.161s

OK
```

## Re-vendored

```
$ .venv/bin/python automation/vendoring/sync_vendored.py --check
(clean — reported PASS by the gate below)
```

## Full gate

```
$ zsh <scratch>/gate.sh
ALL GREEN
```
