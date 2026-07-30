# The story bank lands at `me/interviews/story-bank/`, not `me/interviews/stories/` — confirm?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-29
- **Source**: [interview-material ADR](../../../memory/decisions/interview-material-moves-by-company-only.md)
- **Blocking**: nothing. Phase 5 is proceeding on the default path.
- **Default path**: the three non-company interview trees keep their existing
  directory names under their new parent — `me/interviews/story-bank/`,
  `me/interviews/question-bank/`, `me/interviews/common-message-replies/` — rather
  than being renamed to `stories/`, `questions/`, `replies/`. Nothing inside any
  moved file changes.

## Background

You settled the interview tree on 2026-07-29: **move company-specific material into
company folders, reorganise nothing else**, and the 55 non-company files "get
relocated to `me/interviews/…` without being reorganised". The ADR's amendment
records that as *"nothing inside them altered — not a filename, not a heading, not a
directory below the top level."*

The design README and the execution plan both spell the destinations
`me/interviews/{stories,questions,replies}/`. That spelling predates your ruling —
it was written when the phase still expected to reshape this tree.

**Those two things turn out to be incompatible, and a validator is what makes them
incompatible.** All 16 YAML source files in the behavioral question bank carry
`source_stories:` entries written as sibling-relative paths:

```yaml
source_stories:
  - ../../story-bank/<story>.md
```

There are **33 such references**. `skills/behavioral-interview-prep/scripts/answer_bank.py`
resolves each one against the source file's own directory and raises a hard
validation error when it does not exist — and separately requires at least two
distinct resolved story files per answer, so nothing degrades gracefully.

Today `question-bank/sources/` and `story-bank/` are siblings, so `../../story-bank/`
resolves. If the question bank moves to `me/interviews/questions/` and the story bank
to `me/interviews/stories/`, every one of those 33 references resolves to
`me/interviews/story-bank/`, which would not exist. **All 16 sources fail validation
and the answer bank refuses to render.**

Keeping the directory names as they are makes all 33 resolve unchanged, because the
two trees stay siblings under a new parent. That is the whole of the difference.

**The unit test would not have caught this.** `test_answer_bank.py` builds its own
fixture tree containing `behavioral/story-bank/` and `behavioral/question-bank/sources/`
and its own `../../story-bank/example-project.md` reference, so it passes green
against a fixture whose geometry the migration has already changed. The real bank
would be the only thing broken, and only at the moment you next asked for an answer.

## Options

### Option A — keep the existing directory names (default path)
`me/interviews/story-bank/`, `me/interviews/question-bank/`,
`me/interviews/common-message-replies/`. Zero content edits, all 33 references
resolve, your ruling honoured to the letter. Cost: the design README and execution
plan need one word changed in three places, and the names are a little longer than
the ones the plan imagined.

### Option B — use the plan's names and rewrite the 33 references
`sed 's|\.\./\.\./story-bank/|../../stories/|'` across the 16 sources. Cost: it is a
content edit inside files your ruling said would not be altered. Defensible as
"repairing something plainly broken in passing", but the thing being repaired is
only broken *because* of the rename — which makes it a self-inflicted exception to
your own rule, not a pre-existing defect.

### Option C — the plan's names, and teach `answer_bank.py` to resolve story paths
through a config accessor instead of sibling-relative
Cost: real feature work inside a migration, and the acceptance test for this phase is
file-for-file correspondence, which feature work makes uncheckable. It is also a
better idea than either A or B *in the long run* — sibling-relative paths inside data
files are what made this fragile — which is why it is worth its own task rather than
a rider here.

## Recommendation

**Option A**, and it is what phase 5 is doing while this sits here. Your ruling
constrains the *contents*; the leaf directory names came from a plan written before
the ruling, and they are the cheaper thing to change. It also leaves the tree
file-for-file verifiable, which is the property that makes a 764-file migration
reviewable at all.

Option C is the right eventual answer and is filed separately; it should not ride
inside the migration.

**Your answer:** ______
