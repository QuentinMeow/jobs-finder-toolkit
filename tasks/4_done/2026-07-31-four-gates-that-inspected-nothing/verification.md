# Verification — 2026-07-31-four-gates-that-inspected-nothing

Real output only. Absolute home paths are redacted to `<repo-root>` and throwaway
temp directories to `<tmp>`; nothing else is edited. Each "OLD" transcript runs the
pre-change module (`git show HEAD:<file>` loaded side by side with the new one)
against the SAME fixture, so the before/after is behavioural, not an import error.

## 1. Mail safety — an empty providers tree, and a directory hidden from the walk

```
$ .venv/bin/python <tmp>/prove_mail.py     # old checker vs new, same two fixtures
--- fixture A: present-but-EMPTY providers/
    OLD -> []
    NEW -> ['providers root <tmp>/pkg_a/providers contains no provider folder — nothing
            was verified (an EMPTY tree used to print PASS)']
--- fixture B: only provider is providers/_outlook/ with a send path
    OLD -> []
    NEW -> ["_outlook/: directory skipped by the '_'/'.' rule carries 1 python file(s) and
            was NEVER scanned — rename it to a provider name or move the code out of
            providers/",
            'providers root <tmp>/pkg_b/providers contains no provider folder — nothing was
            verified (an EMPTY tree used to print PASS)']
```

Fixture B's hidden file is `def send_mail(msg): return post("/sendMail", msg)` — the
old checker returned zero errors for it and `main()` printed `mail safety policy: PASS`.

New unit tests, both directions:

```
$ git stash push automation/shared/mail/check_mail_safety.py
$ .venv/bin/python -m unittest discover -s automation/shared/tests -k NothingWasVerified
ImportError: cannot import name 'consumer_files' from 'mail.check_mail_safety'
FAILED (errors=1)
$ git stash pop
$ .venv/bin/python -m unittest discover -s automation/shared/tests -k NothingWasVerified
.....
Ran 5 tests in 0.062s
OK
```

Live tree still passes, and now says what it read:

```
$ .venv/bin/python automation/shared/mail/check_mail_safety.py \
      --consumer skills/email-assistant/scripts
mail safety policy: PASS — 1 provider folder(s) [outlook_graph], 2 consumer file(s)
exit=0
```

## 2. Link checker — the summary stops claiming what it did not verify

Before, on this repository (`--no-overlay`, the pre-commit and CI form):

```
  skipped refs — no recognised root prefix (...): 729, of which 133 name a file
  ...
  advisory (plans name targets that do not exist yet): 33
  permitted (dated records — rewriting them would falsify the record): 56
  references: all resolve
  OK: links, symlinks, and vendored copies verified.
exit=0
```

After, same tree, same flags:

```
$ .venv/bin/python automation/gardener/verify_links.py --no-overlay
  skipped refs — no recognised root prefix (...): 729, of which 133 name a file
  ...
  references: 0 broken of 1540 verified · 33 advisory · 56 permitted · 1045 refs NOT
  verified in this tree (classes above)
  OK: 1540 references, the skill symlinks and the vendored copies verified.
exit=0
```

Unit tests, both directions. The BEFORE quotes the old line verbatim:

```
$ git stash push automation/gardener/verify_links.py
$ .venv/bin/python -m unittest discover -s automation/gardener/tests \
      -t automation/gardener/tests -k TestReferenceCoverageIsReported
ERROR: test_a_resolving_ref_is_enough_coverage_to_pass
ERROR: test_the_verified_count_travels_in_a_baseline_snapshot
ERROR: test_zero_verified_references_is_a_finding
FAIL: test_summary_names_what_was_not_verified
    self.assertNotIn("references: all resolve", out)
AssertionError: 'references: all resolve' unexpectedly found in
  '... refs + markdown links checked across 3 tracked .md files
   skipped refs — no recognised root prefix (...): 1, of which 1 name a file
   references: all resolve
   ...  OK: links, symlinks, and vendored copies verified.'
Ran 4 tests in 0.976s
FAILED (failures=1, errors=3)
$ git stash pop
$ .venv/bin/python -m unittest discover -s automation/gardener/tests \
      -t automation/gardener/tests -k TestReferenceCoverageIsReported
Ran 4 tests in 1.067s
OK
```

### The widening that was measured and rejected

The 729 invisible refs, bucketed by first path segment:

```
$ .venv/bin/python automation/gardener/verify_links.py --no-overlay --list-unrecognised \
    | sed -n '/unrecognised-root refs/,$p' | awk '{print $2}' | awk -F/ '{print $1}' \
    | sort | uniq -c | sort -rn | head
  40 scripts     39 me       30 (bare)   24 interviews  23 fix
  22 tmp         22 source   22 market   21 design      20 handbook
```

`fix/`, `feat/`, `chore/`, `phase-4/` are branch names; `me/`, `market/`,
`companies/`, `interviews/` are overlay-relative shorthand; `scripts/`, `source/`,
`_vendor/` are skill-relative fragments. The only class that looks like a genuine
rename hazard is the four roots workspace phase 2 retired — `handbook/`, `design/`,
`roadmap/`, `tmp/`, about 72 refs:

```
$ ... | grep -E '  (handbook|design|roadmap|tmp)/' | awk '{split($1,a,":"); print a[1]}' \
      | sort | uniq -c | sort -rn
   7 tasks/3_in-review/...   5 docs/designs/...   3 memory/decisions/...
   ... every hit is under tasks/, memory/decisions/, history/, evals/results/ or
   docs/designs/ — plan or record tier — EXCEPT one:
   1 docs/roadmap/current-state.md
```

That one reads: "the gitignored scratch root is renamed `tmp/` → `local/`". It is a
reference document naming a retired root **because** it is retired. Hard-failing that
class buys exactly one false positive and no true ones, so coverage was not widened;
the summary was made honest instead, and the earlier task's decision ("making them
visible is the requirement; making them fatal is a separate decision") stands with
numbers behind it.

### A real failure the stricter gate surfaced

Two fixtures in `TestRootDisappearance` planted a tree whose ONLY reference was the
deliberately unresolvable one, so the run verified nothing and the new finding fired
(`AssertionError: 1 != 0` on both). Fixed by giving `plant()` a second reference that
resolves — those tests are about a missing ROOT, not about a corpus with no coverage.
The gate was not weakened.

## 3. Review gate — no resolvable row is only tolerated for the export mirror

A sandbox carrying the maintainer-only roots plus a ledger whose single row names a
commit nobody has (a wholesale ledger rewrite):

```
$ .venv/bin/python <tmp>/old_review_gate.py --repo <tmp>/rewrite-demo
public review gate: NOT APPLICABLE in this checkout.
None of the 1 ledger row(s) names a commit that exists here, so this is
not the repository whose review history the ledger records — an exported public
mirror (export_public.py --git-init) or a re-initialised tree. There is nothing
to review against. The gate is a no-op here and exits 0.
exit=0

$ .venv/bin/python automation/publish/review_gate.py --repo <tmp>/rewrite-demo
PUBLIC REVIEW GATE — the ledger describes a history this checkout does not have.
None of the 1 ledger row(s) names a commit that exists here, and yet this
tree carries the maintainer-only roots (tasks/, memory/, message-queue/, history/,
docs/roadmap/), so it IS the repository whose review history the ledger records. ...
The ledger is APPEND-ONLY — recover the rows rather than writing new ones:
    git log -p -- automation/publish/review_ledger.yaml
If this genuinely is a mirror that ships the process roots, say so explicitly:
    review_gate.py --allow-not-applicable
exit=2
```

**The export mirror is unbroken** — verified against a real export rather than argued.
The mirror runs this repo's own tracked `automation/hooks/pre-commit` and
`.github/workflows/ci.yml`, so both invocation forms were run inside it:

```
$ .venv/bin/python automation/publish/export_public.py --dest <tmp>/export-mirror \
      --git-init --force
... create mode 100644 templates/task/worklog.md
$ for r in tasks memory message-queue history docs/roadmap; do ...; done
absent  tasks      absent  memory      absent  message-queue
absent  history    absent  docs/roadmap

$ cd <tmp>/export-mirror && review_gate.py            # the pre-commit form
public review gate: NOT APPLICABLE in this checkout.
None of the 67 ledger row(s) names a commit that exists here, ...
Tolerated because: this tree ships none of tasks/, memory/, message-queue/, history/,
docs/roadmap/ — the published-export shape
exit=0
$ review_gate.py --verify-all                         # the CI form
... same, exit=0
```

Unit tests, both directions:

```
$ git stash push automation/publish/review_gate.py
$ .venv/bin/python -m unittest discover -s automation/publish/tests \
      -k NotApplicableIsConditionalTests
FAIL: test_one_surviving_process_root_is_enough_to_fail
AssertionError: 0 != 2
FAIL: test_the_export_shape_is_still_tolerated_and_says_why
AssertionError: 'published-export shape' not found in 'public review gate: NOT
  APPLICABLE in this checkout. ...'
ERROR: test_a_maintainer_shaped_tree_with_no_resolvable_row_fails
ERROR: test_a_resolvable_row_never_reaches_the_tolerance_branch
ERROR: test_the_explicit_flag_overrides_the_shape_test
Ran 5 tests in 0.786s
FAILED (failures=2, errors=3)
$ git stash pop
$ .venv/bin/python -m unittest discover -s automation/publish/tests -k NotApplicable -v
test_a_maintainer_shaped_tree_with_no_resolvable_row_fails ... ok
test_a_resolvable_row_never_reaches_the_tolerance_branch ... ok
test_one_surviving_process_root_is_enough_to_fail ... ok
test_the_explicit_flag_overrides_the_shape_test ... ok
test_the_export_shape_is_still_tolerated_and_says_why ... ok
Ran 5 tests in 1.408s
OK
```

`AssertionError: 0 != 2` on the rewritten-ledger sandbox is the fail-open itself.

## 4. Roadmap freshness — the check now reads the date

```
$ .venv/bin/python <tmp>/prove_roadmap.py    # old check vs new, same four fixtures
--- a roadmap 366 days stale
    OLD -> PASS (no findings)
    NEW -> ['Last-updated: 2025-07-30 is 366 days old (limit 30) — describe what is true
            today, then re-date it']
--- Last-updated: whenever
    OLD -> PASS (no findings)
    NEW -> ["Last-updated: 'whenever' is not an ISO date (YYYY-MM-DD)"]
--- dated in the future
    OLD -> PASS (no findings)
    NEW -> ['Last-updated: 2027-01-01 is in the future — a date nobody can go stale past
            is not a freshness claim']
--- dated yesterday
    OLD -> PASS (no findings)
    NEW -> PASS (no findings)
```

```
$ .venv/bin/python -m unittest discover -s automation/reconcile/tests \
      -t automation/reconcile/tests -k TestRoadmapFreshness
Ran 9 tests in 0.018s
OK
```

Blast radius, checked before committing: this repo's roadmap is dated 2026-07-30, one
day old, so the stricter check passes. `test_the_real_roadmap_is_fresh_today` pins it
against the real file, so a stale roadmap fails a unit test as well as the gate.

```
$ .venv/bin/python automation/reconcile/reconcile.py --check --require-roots
reconcile: OK (9 checks clean)
exit=0
```

## 5. CI shape — a detached, config-less, overlay-less worktree

```
$ git worktree add --detach <tmp>/ci_wt HEAD
Preparing worktree (detached HEAD ef5cbc7)
$ [ -e private ] ; [ -e config.yaml ]
private/ absent
config.yaml absent

$ automation/shared/mail/check_mail_safety.py --consumer skills/email-assistant/scripts
mail safety policy: PASS — 1 provider folder(s) [outlook_graph], 2 consumer file(s)   exit=0
$ automation/reconcile/reconcile.py --check
reconcile: OK (8 checks clean)                                                        exit=0
$ automation/gardener/verify_links.py
  references: 0 broken of 1538 verified · 33 advisory · 56 permitted · 1047 refs NOT
  verified in this tree (classes above)
  OK: 1538 references, the skill symlinks and the vendored copies verified.           exit=0

$ python -m unittest discover -s <each suite>
automation/shared/tests:     Ran 430 tests   OK
automation/gardener/tests:   Ran  90 tests   OK (expected failures=1)
automation/publish/tests:    Ran 155 tests   OK (skipped=1)
automation/reconcile/tests:  Ran  35 tests   OK
```

The one expected failure in the gardener suite is the pre-existing
`test_link_inside_an_indented_code_block_is_not_a_link`, unrelated to this change;
the one skip in the publish suite is the leak guard's own probe-token file.
