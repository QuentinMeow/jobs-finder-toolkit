# Anchoring `/logs/` in .gitignore turned a green CI gate red

- **Priority**: P0 (blocks work)
- **Area**: harness
- **Source**: found running `automation/publish/tests` while renaming
  `examples/data` → `examples/store` (branch `feat/19-examples-store`); the
  failure is inherited from that branch's base and is unrelated to the rename
- **Claimed-by**:

## Goal

`python -m unittest discover automation/publish/tests` passes again, with
`/logs/` covered by whichever of the two sanctioned mechanisms is correct for
it — and the reason written down, so the next root-anchored ignore rule does
not re-open this.

## Context

Commit `e91f6cb` ("Anchor two gitignore rules that failed on trailing-slash
semantics") changed the `.gitignore` rule `logs/` to `/logs/`. That was the
right fix for its own bug: unanchored, the rule matched a `logs/` directory at
ANY depth and silently made `examples/market/logs/**` untrackable.

But `test_leak_guard.RealTreeStructuralTests.test_every_root_anchored_gitignore_product_rule_is_denied`
enumerates every `.gitignore` line that both starts and ends with `/`, and
asserts each one is also covered by `check_public._DENY_TREES` or
`PERSONAL_OVERLAY_PREFIXES`. Its premise: a private root named in `.gitignore`
must ALSO be path-denied, because `git add -f` overrides a glob but not the
guard. Anchoring `logs/` made it match that "root-anchored product rule"
shape for the first time, and nothing covers it:

    AssertionError: False is not true : .gitignore rule '/logs/' is not
    covered by _DENY_TREES / PERSONAL_OVERLAY_PREFIXES

CI runs this suite (`.github/workflows/ci.yml:280`), so `main` — and every
branch based on `e91f6cb` — is red until this is fixed. Pre-commit does NOT
run the publish suite, which is why the commit that caused it went in green.

There are exactly two sanctioned fixes and the choice needs judgement, which
is why this is a task and not a `needs-agent/retries/` item:

1. **`NON_PRODUCT_ROOTS`** (`test_leak_guard.py:780`) — the escape hatch the
   test's own author built, documented as "root-anchored ignore rules that are
   scratch/build output rather than a private PRODUCT tree. Add here (with a
   reason) only after checking the tree is genuinely not personal data." The
   set is currently empty; `/logs/` would be its first entry.
2. **`_DENY_TREES`** (`check_public.py:179`) — append `(re.compile(r"^logs/"),
   "logs/")`. The list is append-only, so this is additive and permanent.

Which is right turns on one question nobody has answered in writing: **can the
metrics log contain personal data?** `/logs/` is written only by
`automation/metrics/hook_collect.py` (its `LOG_PATH` is `REPO_ROOT/"logs"`).
If those records can carry file paths or arguments reaching into `private/`,
then it is closer to a product tree and option 2 is correct and strictly safer.
If they are pure counters and timings, option 1 is correct and option 2 would
permanently deny a generic root name that is not actually private. Read what
`hook_collect.py` writes before choosing; do not guess.

Do NOT make the test pass by weakening it — deleting the test, loosening the
rule pattern, or reverting `/logs/` back to `logs/` all re-open the
`examples/market/logs/**` untrackable bug that `e91f6cb` fixed.

## Definition of done

- [ ] `hook_collect.py`'s record shape is inspected and the verdict (personal
      data: yes/no) is recorded in the fix's commit body
- [ ] `/logs/` is covered by option 1 or option 2, with the reason written at
      the code site
- [ ] `.venv/bin/python -m unittest discover automation/publish/tests` exits 0
- [ ] `.gitignore` still carries the anchored `/logs/`; `git check-ignore -v
      examples/market/logs/probe.md` still exits 1 (the negative control from
      `e91f6cb` still holds)
