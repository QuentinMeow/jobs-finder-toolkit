# Worklog — 2026-07-31-gate-documented-commands

## 2026-07-31 — session 1 (agent)

- Measured before designing. 284 documented `<python> <script>.py` commands live
  in fenced blocks across 384 tracked `.md`. 7 name a script that does not exist,
  and **none of the 7 is in the reference tier** — so the check could be armed at
  full strength with no backlog to clean and no grandfathering. That answered the
  gating question with data rather than a guess.
- Scope held to ONE shape, `<python interpreter> <script>.py [argv…]`, and to two
  claims about it: the script path exists, and every `--long-flag` is one the
  script's own `add_argument` calls define. **Arguments are not checked at all.**
  `--update <slug> applied` names a slug that must not exist and
  `render.py applications/…` names a runtime tree; checking argv would report both
  and the gate would be switched off inside a week.
- Fence policy is "shell tags plus untagged, minus every explicit non-shell tag".
  Untagged is IN because this repo's own verification records fence transcripts
  with no info string and 12 documented commands live in one. Admitting all 311
  untagged fences cost nothing measurable: no directory tree, YAML sample or prose
  fragment matches the command shape, which is the filter doing the real work.
- **Flag checking: static `ast`, not `--help` in a subprocess.** The subprocess
  route executes ~40 repo scripts inside a pre-commit hook, needs one call per
  SUBCOMMAND (43 pairs here) because a subparser's options are absent from the
  top-level help, and converts any import-time failure in a config-less checkout —
  which is exactly what CI is — into a phantom "that flag does not exist". Static
  parsing costs nothing and cannot have a side effect. Measured cost of the whole
  pass: the repo run went 1.9 s → 2.2 s.
- Attribution is best-effort, so the pass fails open in a defined way: a flag is
  reported when it appears in NO `add_argument` in the file, and only when EVERY
  `add_argument` receiver in that file traced to a named parser does it also get
  checked against the subcommand the doc names. One unattributable call drops the
  whole file back to the loose question. Two of this repo's scripts build
  subparsers in a loop and land there; neither produces a finding.
- Whole-tree run: 8 findings, all true positives, 0 broken. Two are deliberately
  wrong by design — a verification transcript demonstrating `--bogus`, and a
  design doc proposing a CLI that does not exist yet — and the EXISTING tier rule
  already routes both to non-fatal without a special case. That was the constraint
  the task set, and it held without touching any tier list.
- Surprise worth recording: `_is_checkable` (pass 2's filter) rejects any token
  containing `config.`, `layout.` or `check.`, so it would refuse to verify
  `automation/shared/config.py`. Commands got their own narrower predicate —
  slash AND `.py` suffix — rather than inheriting that.
