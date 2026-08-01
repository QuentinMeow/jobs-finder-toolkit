# Two skill-token expansion rules still mirror each other by hand

- **Priority**: P2 (someday)
- **Area**: resume-writer
- **Source**: the PR that hoisted the `## Skills` section parser into `automation/shared/profile_skills.py` (branch `wip/09-resume-validation-gates`)

## Goal

Decide whether `check.py`'s `_skill_keys` and `profile_skills.expand_keys` should
become one function, and either merge them or record why they must stay apart —
so the pair cannot repeat the drift that emptied the Never blocklist.

## Context

That PR fixed a real drift: the profile's `## Skills` **section boundary** was
parsed by two private regexes that had diverged, so a profile whose `## Skills`
was the last `##` section yielded an empty vocabulary in the render gate while
the gardener read it fine. The boundary now lives once, in
`automation/shared/profile_skills.py`.

One near-duplicate pair survives that hoist, deliberately. Both expand a nested
`Base (a, b)` skill token into the spellings it should match:

- `automation/shared/profile_skills.expand_keys` — used to build the gardener's
  canonical-spelling set. Adds the bare base (`aws`), each member, and
  `base member`; normalizes with whitespace-collapse + lowercase only.
- `skills/resume-writer/scripts/check.py::_skill_keys` — used by the render
  gate's Approved/Weak membership test and its JD-mention search.
  Deliberately does **not** make bare `AWS` selective, applies `_SKILL_ALIASES`,
  and normalizes with `check._norm` (which also strips `**bold**` markers and
  unifies dashes/quotes).

They are not the same function today and merging them naively would change what
the gate accepts, so this PR left them alone. But the old `skill_drift.py`
comment literally read "mirroring check.py's `_skill_keys`", which is exactly the
hand-maintained-mirror shape that produced the original defect.

Constraint: any merge is a change to a hard gate, so it needs the resume-writer
canaries per `evals/README.md`, plus a test that pins the accepted/rejected token
set on both sides before and after.

## Definition of done

- [ ] A decision recorded (in `memory/decisions/` if the answer is "they stay
      separate", with the behavioural reason stated).
- [ ] If merged: one implementation in `automation/shared/profile_skills.py`,
      vendored (`automation/vendoring/sync_vendored.py --check` clean), with a
      test asserting the pre-merge accept/reject behaviour of both callers is
      unchanged.
- [ ] If not merged: a test that fails when the two expansions disagree on the
      cases they are *supposed* to share, so future drift is caught.
- [ ] `automation/shared/tests/test_profile_skills.py` still passes.
