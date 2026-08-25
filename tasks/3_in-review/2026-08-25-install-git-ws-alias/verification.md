# Verification — 2026-08-25-install-git-ws-alias

## Bootstrap behavior

```text
$ .venv/bin/python -m unittest discover -s automation/hooks/tests -t automation/hooks/tests
............................................................
----------------------------------------------------------------------
Ran 60 tests in 8.910s

OK
```

```text
$ .venv/bin/python automation/bootstrap_overlay.py --check
[    ok] repository-local git ws alias already correct
check complete.
```

```text
$ git ws --no-color
GIT WORKSPACE  2 repositories · 2 worktrees · 1 dirty · 3 local + 2 cached remote branches
```

## CI-equivalent gates on the published implementation commit

Run in a clean detached checkout with no private overlay at `28b8e6f`:

```text
$ .venv/bin/python automation/gates/run_gates.py --impact-from origin/main --jobs 8
coverage: 32 of 37 gates in the table executed (0 skipped, 5 not selected, selector: impact from: origin/main)
ALL GREEN (32 of 37 gates ran)
```

## Public push guard and PR

```text
$ git push -u origin codex/install-git-ws-alias
pre-push: scanning outgoing ref 'refs/heads/codex/install-git-ws-alias' at 28b8e6fc3323a3c25c60a9bdd987bf61e76d2e25
OK: no public-repo leaks detected. Safe to publish.
pre-push: leak guard PASSED for 'refs/heads/codex/install-git-ws-alias'.
pre-push: OK
```

```text
$ gh pr create --base main --head codex/install-git-ws-alias ...
PR #368 created against main.
```
