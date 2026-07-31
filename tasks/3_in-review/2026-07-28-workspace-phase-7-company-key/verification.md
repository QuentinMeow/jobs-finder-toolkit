# Verification — 2026-07-28-workspace-phase-7-company-key

Run on 2026-07-30 against `feat/02-company-index-module`. No command here resolved a path under
`private/` except where the point of the command was to exercise the overlay; nothing under
`private/` appears in any public file, commit message or PR description.

## The result the phase exists for

```
$ .venv/bin/python -c "<resolve every meta.yaml company string through both resolvers>"
distinct company strings: 214  folders: 243
public registry resolves : 119/214 = 55.6%
company index resolves   : 214/214 = 100.0%
unresolved by the index  : 0
```

The 44% gap the design was written around is closed: **every** company string an application
carries now resolves to exactly one key. The public registry's 55.6% is unchanged and was never
the thing to fix — it is a *polling* registry and structurally cannot hold an employer without a
supported ATS token.

## Unit suites

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests
Ran 405 tests in 17.655s          OK          (368 before this phase)

$ .venv/bin/python -m unittest discover -s automation/reconcile/tests
Ran 26 tests in 0.092s            OK

$ JOBHUNT_CONFIG=config.example.yaml .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests
Ran 333 tests in 14.640s          OK          (329 before this phase)

$ .venv/bin/python -m unittest discover -s automation/publish/tests
Ran 145 tests in 48.783s          OK
```

Full CI-equivalent gate (8 gates, 11 suites, strict export dry-run): **ALL GREEN**.

## The safety property: the public half cannot affect a tree without the overlay

Proved in a detached worktree with no `private/` and no `config.yaml` — the shape CI actually runs:

```
$ git worktree add --detach <scratch>/ci_wt HEAD
$ test -d <scratch>/ci_wt/private   -> absent
$ test -f <scratch>/ci_wt/config.yaml -> absent

$ .venv/bin/python <scratch>/ci_wt/automation/reconcile/reconcile.py --check
reconcile: OK (8 checks clean)        exit 0     <- company-index no-ops

$ .venv/bin/python <scratch>/ci_wt/automation/reconcile/reconcile.py --check --require-roots
reconcile: OK (9 checks clean)        exit 0     <- and the private root is NOT asserted
```

With the overlay mounted the same command reports **9 checks clean**. So the check runs where the
data is and disappears where it is not, which is what keeps the exported repo's CI green.

## The index passes its own linter

```
$ .venv/bin/python -c "company_index.lint(read_raw('private/companies/_index.yaml'))"
lint findings on the SHIPPED index: 0
keys loaded: 223
```

223 keys · 265 distinct names, no two keys sharing one · 31 keys with aliases · 222 `employer`,
1 `interview_vendor` · 2 `parent` edges · all 25 pre-existing company folder names reproduced
exactly, so **no folder was renamed**.

## The alias rule, which took three drafts and two measurements

The rule was exercised against all five real offenders and both real abbreviations. **All five
offenders are CAUGHT and both abbreviations are KEPT.** The inputs are not reproduced here — they
are the owner's employers, and this file is public; see the leak note at the end of this section.
By shape:

```
<ordinary-word>  under <Ordinary-Word>.<tld>   -> CAUGHT   (x4)
<ordinary-word>  under <Ordinary-Word> <Noun>  -> CAUGHT   (x1)
<ABBREV>         under <Parent Name>           -> kept     (3-letter division acronym)
<A&B>            under <A> & <B>               -> kept     (ampersand initialism)
```

Two wrong versions were withdrawn, each killed by running it against real data rather than by
argument:

1. **A minimum alias length.** It caught the five offenders but also deleted a three-letter
   division acronym and an ampersand initialism — both legitimate, both from the highest-quality
   alias source in the tree. Withdrawn.
2. **A ~620-word English stop-list.** 149 of its tokens did not occur anywhere in this repo, and
   the detector permanently subtracts any name already in the public tree — so publishing those
   149 words would have **blinded the detector** to any employer of that name, to suppress false
   positives this repo's diffs cannot produce. Withdrawn; the list is now 152 tokens, every one
   verified already present, pinned by `test_stop_list_holds_no_vocabulary_new_to_this_repo`.

The surviving rule is narrow: an **all-lowercase single-token** shortening of an entry's own
display. The lowercase condition is load-bearing — a display-cased short form is the spelling a
human actually writes, and rejecting it would leave that application unkeyable. That narrowing
came from running the linter against the real index and getting a finding on a legitimate alias.

### The detector caught this file leaking, on its first armed commit

The first version of this section pasted the linter's actual output, naming **seven real
employers** from the owner's tree into a public file. The advisory company detector — inert for its
entire existence until this phase created the index it reads — fired on exactly those seven names
and forced this commit to `reviewed_by: human`.

Worth recording precisely because of who made the mistake: the leak was written by the agent that
had just spent the session arguing that this phase is the highest-leak-risk one in the plan, into
the file whose own opening line promises no company names appear in it. The mechanism that caught
it is the one this phase switched on. **The staged-index leak guard would not have caught it** —
company names are not identity tokens, which is why the review gate reads diffs at all.

## Mutation checks — 10 planted defects

Nine went red on the first attempt: dropping the non-string-key rule, the shared-alias rule, the
stop-list rule, the `is_dir()` no-op guard, the private-root skip, the unresolvable-key report,
the `DEFAULT_REL` pin, the retries filter, and reinstating the length floor.

**The tenth stayed green, and that is the useful one.** `test_an_unkeyed_application_is_not_a_finding`
used a `meta.yaml` with no `company_key` text at all, which a cheap substring prefilter discards
*before* the branch under test — so the test passed while coverage was gated, which is exactly
what it was written to forbid. Rewritten with an explicit-null shape; the mutation now goes red.
Recorded because the pattern generalises: **a prefilter upstream of the code under test can make a
negative test vacuous.**

## A leak vector found and closed that was not in the design

`reconcile.py --file-retries` writes a file per finding into
`message-queue/needs-agent/retries/` — a **tracked** directory (`git ls-files` confirms
`.gitkeep` and `README.md`) — whose filename is the slugified subject and whose body repeats the
subject and message verbatim. The new check's subjects are application paths and company keys, and
`AGENTS.md` explicitly tells agents to "let `--file-retries` queue it".

The staged-index leak guard would **not** have caught it: company names are not identity tokens,
which is why the review gate reads diffs rather than relying on the token scan. One such run would
have committed an application slug and a company key into the public tree. Findings from private
checks are now dropped before anything is written, with two tests.

## Verified plan corrections

- `CHECK_ROOTS` gates nothing at runtime; and because `automation/hooks/pre-commit` runs
  `--require-roots` whenever `private/` is merely mounted, declaring a private root without an
  exemption would have made the overlay's shape a gate on public commits. Verified by reading the
  hook, and pinned by a test so it cannot be argued away later.
- Routing `review_gate.py`'s index literal through `config.companies_root()` would **silently
  disarm** the detector: under `config.example.yaml`, `companies_root()` resolves into `examples/`
  and `overlay_mounted()` returns True, so once phase 8 creates `examples/companies/` the gate
  would read the example index in every public clone and print a clean bill of health instead of
  `NOT INSPECTED`. The literal is kept, single-sourced, and pinned by a test.
- The advisory detector was **inert** before this phase — the file it reads never existed. It now
  loads 265 names. Measured cost: 0.21–0.56s per commit.

## Definition of done — what is and is not covered here

Ticked: the index exists and is the only owner-owned alias registry; the reconciler check is in
`CHECKS`, gated so it no-ops in the published tree; review-ledger rows on every commit; zero
company names in public files, commit messages or PR descriptions; gate clean.

**Not ticked, and split out rather than dropped:** `company_key` on the 243 `meta.yaml` files
(7b — held for seven owner judgements), the email assistant's `durable:`/`promote` and the 126
`notes.md` renames (7c). The three other alias registries were **not** retired; each is kept for a
recorded reason and the plan section records why "retire them" was not implementable.
