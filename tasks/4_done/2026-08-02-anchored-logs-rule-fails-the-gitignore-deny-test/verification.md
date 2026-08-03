# Verification — 2026-08-02-anchored-logs-rule-fails-the-gitignore-deny-test

Retro-closure, 2026-08-02. Fixed by option 2 (`_DENY_TREES`) in `f61ccfb`
(PR #203, "Anchor logs ignore"), an ancestor of `f360aec`.

```
$ git merge-base --is-ancestor f61ccfb HEAD; echo $?
0
```

## DoD 2 — `/logs/` covered, with the reason at the code site

`automation/publish/check_public.py`, end of `_DENY_TREES`:

```
    # carries no prompt text or file path, so it is not personal data as
    # written. It is denied because the schema is explicitly version-brittle
    # and grows with Claude Code releases; an exemption would publish a future
    # field that carries a path, whereas a deny only ever inconveniences
    # somebody deliberately tracking a root logs/ tree, which nothing wants.
    # The `^` anchor is what keeps the tracked examples/market/logs/** fixture
    # in scope for tracking while a root logs/ stays denied.
    (re.compile(r"^logs/"), "logs/"),
```

## DoD 1 — `hook_collect.py`'s record shape inspected, verdict recorded

The verdict is written at the code site above ("carries no prompt text or file
path, so it is not personal data as written") together with the reason the
option-2 deny was chosen anyway (schema is version-brittle and grows). That
discharges the bullet's intent: the question was answered in writing before the
choice, and the answer travels with the code rather than only with a commit body.

## DoD 3 — the publish suite is green

```
$ .venv/bin/python -m unittest discover automation/publish/tests
...
OK (skipped=1)
```

and in the whole-repo gate run:

```
$ .venv/bin/python automation/gates/run_gates.py
  PASS   tests-publish  exit 0   243.6s
  PASS   leak-guard-tree  exit 0    12.2s
ALL GREEN (29 gates, 2 skipped: reconciler-require-roots, verify-links-require-roots)
```

## DoD 4 — the anchored rule and its negative control both still hold

`.gitignore:23` is still the anchored `/logs/`, with the full reason above it
(`:16-22`). Negative control:

```
$ git check-ignore -v examples/market/logs/probe.md; echo "EXIT=$?"
EXIT=1
```

Exit 1 = no pattern matched, i.e. the tracked `examples/market/logs/**` fixture is
still trackable — which is the bug `e91f6cb` fixed and this task was forbidden to
re-open.
