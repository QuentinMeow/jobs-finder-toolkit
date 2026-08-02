# The words a search filters on live in the profile, never in code

- **Status**: decided
- **Date**: 2026-08-02
- **Decided by**: owner

## Context

Before a big-tech board posting can be scored it has to survive a coarse **title prefilter** in
`skills/job-search/scripts/sources.py`. The prefilter runs on the title alone, before the
per-posting detail fetch, so a title it drops is never fetched at all — and its list is a tuple of
literal words compiled into the shared toolkit.

Five of those words are seniority or discipline judgements that the candidate's profile already
owns one gate later, in `scoring.assess_title` (`titles.include` / `titles.exclude`). Where the two
disagree the code wins, silently: a profile that deliberately targets Principal-and-above or
applied-scientist roles receives none of them from those employers, no matter what its include
list says, with no filtered row and no count.

The question was filed as a binary — keep the five hardcoded words, or delegate them to
`titles.exclude`. The owner rejected the framing. The defect is not which five words are in the
tuple; it is that one person's filter vocabulary is compiled into tooling several people run.

## Decision

**The words a search filters on come from the candidate's search profile, never from a constant in
a script.** Different people run this toolkit and each one's filter logic is their own.

The vocabulary carries **at least three classes**, and they do not behave alike:

1. **hard-exclude** — example: `intern`. Always drop. The posting is not fetched and not reasoned
   about.
2. **soft-exclude** — example: `manager`. **Never drop on the title alone.** A hit is a reason to
   read the JD, not to discard it: the role may be a genuine software-engineering role, or the
   title may name a *product* that is literally called a manager. The AI reads the JD and judges.
3. **inclusion** — a hit means the role **must** be examined and reasoned about, rather than
   quietly kept or dropped along with everything else.

In the owner's words: *"We should make this filter words profile based. I.e. multiple different
people should have their own filter logic. So definitely not hardcoded in code. We should include
at least several logic: 1. hard excluded word, for example intern; 2. soft excluded word, for
example, manager (which could be a software engineer role, might just be some software called
manager), so that we let AI read JD and decide whether or not it looks like something interesting
3. inclusion word, when we hit such word, we must check it out and let AI reason about it."*

## Alternatives considered

- **Keep the hardcoded list** (the default path while the question was open) — leaves a seniority
  policy in code that the profile is supposed to own, with the code winning invisibly.
- **Remove only the five disputed words and let `titles.exclude` decide** — fixes five words and
  leaves the rest of the tuple as a second, code-side policy owner; it is also still a binary
  keep/drop with no room for "read the JD and judge".
- **Remove the five and raise the per-board candidate budgets** — treats the displacement symptom
  without moving ownership of the rule.
- **Pass the profile's exclude list into the fetcher** — the structurally correct version of the
  two above and the closest to this decision, but still a two-class in/out vocabulary; the answer
  asks for three classes and for soft-exclude to defer to a JD read.

## Consequences

- The hardcoded skip tuple stops being a policy owner, and the test that froze its five seniority
  words while this question was open goes with it. What replaces that test is an assertion that a
  person's filter words are not re-introduced in code.
- The search-profile schema grows the three classes. The shipped template and
  `skills/job-search/profiles/README.md` are the public statement of what each class means; the
  actual vocabulary is per-candidate data and lives in the overlay.
- **Soft-exclude costs fetch budget by construction.** A title that used to be dropped before the
  detail fetch is now fetched so its JD can be read. Per-board candidate caps are applied in the
  order the search pages returned, so a wider candidate set can push wanted roles past the cap
  invisibly — the same silent-loss shape this decision exists to remove. Whoever implements it
  owns that trade explicitly rather than discovering it.
- **This is a design direction, not a finished spec.** A first implementation is judged against the
  three classes above and the owner's words, not against detail this decision does not contain.
  The conformance checklist is `tasks/0_backlog/2026-08-02-profile-owned-search-filter-vocabulary/`.
- **Revisit if** three classes turn out not to be enough — the answer says "at least" — not
  because one of them is awkward to implement.
