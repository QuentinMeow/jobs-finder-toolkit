# Verification — 2026-07-28-workspace-phase-3-review-gate

<Only commands actually run and their real output. Never fabricated, never
paraphrased into "all tests pass" without the evidence. Required before a
task enters 3_in-review or 4_done.>

All commands run 2026-07-29 on `chore/workspace-phase-bookkeeping`, which is
based on `phase-4/remove-inbound-symlinks` and carries the phase-3 commits
(`92abe36`, `ef2d0a3`, `97a7303`).

## Gate is silent when the ledger is current (DoD: "silent when nothing
changed" / "gate command clean")

```
$ .venv/bin/python automation/publish/review_gate.py
$ echo "exit: $?"
exit: 0
```

No output, exit 0 — the working tree's ledger is current for this branch's
history.

## Gate is wired into CI

```
$ grep -n "review_gate" .github/workflows/ci.yml
19:# Step 2d is the public REVIEW gate (automation/publish/review_gate.py) — the other
114:            python automation/publish/review_gate.py --verify-all --head "$PR_HEAD"
116:            python automation/publish/review_gate.py --verify-all
```

## Gate is wired into pre-commit

```
$ grep -n "review_gate" automation/hooks/pre-commit
9:#      automation/publish/review_ledger.yaml (automation/publish/review_gate.py), or
98:"$PY" automation/publish/review_gate.py
```

(This repo's hooks are hand-rolled scripts at `automation/hooks/`, installed
by `bootstrap_overlay.py` — there is no `.pre-commit-config.yaml`.)

## Gate test suite (fail-with-file-list, valid-row passes, wrong-digest
fails, shallow-clone / out-of-sync / not-applicable modes — all in
`automation/publish/tests/test_review_gate.py`, included in the publish
suite)

```
$ .venv/bin/python -m unittest discover -s automation/publish/tests -t .
----------------------------------------------------------------------
Ran 137 tests in 32.788s

OK
```

## Not independently re-derived

I did not hand-construct a throwaway repo to manually reproduce "a public
commit fails the gate with the file list and the instruction" or "a row
with a wrong digest still fails" — the commit message for `92abe36` states
39 dedicated gate tests do exactly this (each building a throwaway repo and
running the real CLI), and they are included and passing in the 137-test
publish suite run above. Re-deriving them by hand would just be restating
that same test suite.
