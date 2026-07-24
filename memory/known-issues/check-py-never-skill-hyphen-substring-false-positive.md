# `check_never_skills()` flags a blocklisted word inside a hyphenated compound as a false positive

- **Status**: open
- **Severity**: medium (blocks a render with a spurious FAIL; the workaround is manual and
  affects any resume whose text happens to contain a hyphenated compound built from a
  blocklisted single word)
- **Area**: resume-writer
- **Source**: found live while drafting an application whose baseline bullet contained the phrase
  "on-node debugging agent" — the same false positive reproduces against any already-drafted
  application when `check.py` is re-run today if its resume text carries such a hyphenated compound,
  so it is not new to that run, just newly noticed.

## Symptom

`check.py` fails a render with `Blocklisted skill 'Node' (profile 'Never' list) appears in the
resume` even though the resume text never mentions the Node.js/Node runtime — the profile's own
baseline bullet text contains the substring "node" only as part of an unrelated hyphenated
compound word (e.g. "on-node debugging agent", describing a per-machine/per-host agent, nothing
to do with the Node.js runtime the blocklist entry is meant to catch).

## Reproduction

```bash
.venv/bin/python -c "
import re
never_tok = 'node'                                  # a bare 'Never'-list token, e.g. from 'Node.js, Node'
text = 'introduced an on-node debugging agent'.lower()  # resume text using 'node' only inside a compound
bare = re.sub(r'\s*\(.*?\)', '', never_tok).strip()
m = re.search(rf'(?<![a-z0-9]){re.escape(bare)}(?![a-z0-9])', text)
print(bool(m))   # True -- false positive: hyphen is not in [a-z0-9], so it satisfies both boundaries
"
```

Any existing drafted application whose tailored resume still carries a baseline bullet with this
phrasing reproduces the same `FAIL` if `check.py` is re-run against it today.

## Impact

Blocks an otherwise-clean render with a FAIL the agent cannot silently bypass (`--skip-checks` is
disallowed by policy), forcing a manual reword of resume text that never actually violated the
Never-list intent. Low frequency (depends on the baseline/profile's specific wording colliding
with a blocklisted single word), but when it hits, it costs a full extra render cycle and,
without this note, could tempt an agent to mis-diagnose it as a real fabrication/blocklist issue.

## Root cause

`check_never_skills()` (`skills/resume-writer/scripts/check.py`, function around line 448) scans
all resume text with the boundary regex `(?<![a-z0-9]){escaped_term}(?![a-z0-9])`. This regex
treats any non-alphanumeric character — including a hyphen — as a valid word boundary. A
hyphenated compound word such as "on-node" or "node-local" therefore satisfies both lookaround
boundaries around the inner word "node", even though a human reader would never parse "on-node"
as containing the standalone term "Node" (the Node.js runtime). The same class of false positive
can trigger for any other single-word Never-list entry that happens to be a substring of a
hyphenated compound used elsewhere in the resume (e.g. a blocklisted "Go" matching inside
"go-to-market" if that phrase ever appeared, though bullet text is unlikely to contain it).

## Suggested fix

Tighten the boundary regex in `check_never_skills()` to also treat a hyphen adjacent to the match
as part of the same word (i.e. require the pattern to fail on `-` immediately touching the match,
not just `[a-z0-9]`) — e.g. change the lookaround boundary classes from `[a-z0-9]` to
`[a-z0-9-]` so "on-node" and "node-local" no longer match a bare "node" token, while a real
standalone mention ("Node", "Node.js") still matches correctly. Add a regression case with a
synthetic Never-list token and a hyphenated compound containing it as a substring (mirroring the
reproduction above) to whatever test coverage `check.py`'s skill-gate logic already has, so a
future edit to this regex doesn't silently reintroduce the false positive.
