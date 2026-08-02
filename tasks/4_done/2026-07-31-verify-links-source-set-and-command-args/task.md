# The two surfaces the fenced-command pass deliberately left unread

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: session 2026-07-31, scoped out of
  `2026-07-31-gate-documented-commands` and
  `2026-07-31-verify-links-reads-no-fenced-command` (both in `3_in-review`)
- **Claimed-by**: agent, session 2026-08-02 (branch `docs/26-contract-and-record-corrections`)

## Goal

Decide, with the same measure-first discipline, whether either of the two surfaces
that pass 4 knowingly does not read is worth reading: the ARGUMENTS of a
documented command, and Python docstrings as a source of references.

## Context

`automation/gardener/verify_links.py` pass 4 reads `<python> <script>.py [argv…]`
out of shell fences and checks exactly two things: the script path exists, and
every `--long-flag` is one the script's `add_argument` calls define. Two
exclusions were deliberate and are recorded here so a later session does not have
to rediscover why.

**1. Arguments are not checked, and mostly must not be.** `--update <slug>
applied` names a slug that must not exist; `render.py applications/6_drafted/…`
names a runtime tree. Checking argv wholesale would report both, and a gate that
cries wolf on legitimate documentation gets switched off. But ONE argument shape
is a real path claim and is common in this repo: `-m unittest discover -s <dir>`.
`CONTRIBUTING.md` and two execution plans use it a dozen times, and a moved test
directory kills the line exactly the way a moved script does. Note that pass 4
drops `python -m …` invocations whole (they name no script), so this shape is
currently read by nothing.

Open question: is `-m unittest discover -s <path>` narrow enough to check on its
own, the way `<python> <script>.py` was, or does admitting one argument shape
start the slide the exclusion exists to prevent?

**2. `.py` docstrings are not a source.** `_instruction_files()` enumerates
`git ls-files '*.md'` plus the overlay's, so no Python file is read at all, and
`check_public.py` and `review_gate.py` both name repo paths in their module
docstrings. **Decided 2026-07-31: out of scope, source set stays `*.md`.** A
docstring is not copy-pasteable text a maintainer runs, so it is not the defect
class the command gate exists for; widening the enumeration admits every
`automation/**/*.py` and `skills/**/scripts/*.py` at once, each quoting regexes,
git incantations and sample output that the BACKTICK pass — not the command pass —
would then have to survive. Revisit only if a stale path in a docstring actually
misleads someone; this task exists so that evidence has somewhere to land.

## Definition of done

- [ ] A measured count of `-m unittest discover -s <path>` (and any sibling
      argument shape found) across the tree, with how many name a directory that
      does not exist and which tier each sits in — the same "measure before
      arming" step the parent tasks used.
- [ ] Either the shape is checked, with tests pinning it and the repo run still
      `0 broken`, or a one-paragraph note in this file records why not and the
      task is closed.
- [ ] The `.py`-docstring decision is either left standing (close the item) or
      reversed with evidence of a real miss, and `_instruction_files()`'s
      docstring says which.
