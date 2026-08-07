# behavioral-interview-prep hardcodes `private/me/interviews/`, which the accessors do not resolve to

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: instruction-conflict audit, 2026-08-01
- **Claimed-by**:

## Goal

Every output path in `skills/behavioral-interview-prep/SKILL.md` comes from a `config.*()` accessor,
so the skill writes where the toolkit reads in a public checkout and in any overlay that is not
mounted at `private/`.

## Context

`AGENTS.md:69-70`: "**Paths** always come from `config.*_path()` functions … never literals — real
data under `private/`, the public example under `examples/`."

The skill states bare literals in four places:

- `:18-19` — "work in `private/me/interviews/story-bank/` or `private/me/interviews/question-bank/`"
- `:180` — "All real behavioral products live under `private/me/interviews/`"
- `:182` — "Use `private/me/interviews/question-bank/` for question-based answers"
- `:448` — "change `private/me/interviews/story-bank/` only when the user explicitly asks"

`:187` is the one that does it right ("`private/me/interviews/story-bank/`
(`config.story_bank_path()`)"), which shows the accessor exists and was known.

The literals are wrong wherever the overlay is not at `private/`. `automation/shared/config.py:507-517`:

```python
def story_bank_path() -> Path:
    return _resolve_configured(
        "story_bank_dir", overlay_root() / "me" / "interviews" / "story-bank")
```

and `config.py:427-437` derives `overlay_root()` from `applications_root().parent`. The shipped
`config.example.yaml` now sets `applications_root: "examples/me/applications"` and explicitly
pins `overlay_root: "examples"`, which resolves to
`examples/me/interviews/story-bank` — so an agent following `:18-19` in a public checkout creates a
git-ignored `private/` directory nothing ever reads, and the gardener's card-staleness hash and the
tailoring-card builder (both of which read the accessor, per the docstring at `config.py:511-514`)
never see the file. `memory/facts/overlay-root-follows-the-active-config.md` records the same
principle.

The sibling skill shows the shape to copy: `skills/company-research/reference.md` spells out
both branches (`private/me/interviews/companies/…` with the overlay mounted and
`examples/me/interviews/companies/…` in a public checkout), and `company-research` uses
accessors throughout.

Counter-argument considered and rejected: "'All *real* products' scopes `:180` to a real
deployment." That rescues `:180` only; `:18-19` and `:182` are unhedged literals in the section an
agent reads first, and neither names an accessor.

This is a `SKILL.md` edit in the skill's routine path — behavioral, so
`evals/canaries/behavioral-interview-prep.yaml` must run and be recorded per `evals/README.md`.

## Definition of done

- [ ] Every output path in `skills/behavioral-interview-prep/SKILL.md` names its `config.*()`
      accessor (`config.story_bank_path()` and the question-bank equivalent), with the literal shown
      only as "…which is `private/…` with the overlay mounted, `examples/…` without" if it is shown
      at all.
- [ ] `grep -n 'private/me/interviews' skills/behavioral-interview-prep/SKILL.md` returns only
      accessor-qualified lines.
- [ ] behavioral-interview-prep canaries run and recorded per `evals/README.md`.
