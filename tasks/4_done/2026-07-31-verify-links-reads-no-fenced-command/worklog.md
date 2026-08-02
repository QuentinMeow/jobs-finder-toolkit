# Worklog — 2026-07-31-verify-links-reads-no-fenced-command

## 2026-07-31 — session 1 (agent)

- Done together with `2026-07-31-gate-documented-commands`, which is the same
  hole seen from the other side (that one adds the flag half). One pass, one
  branch; the design notes live in that task's worklog.
- The three reasons this was split out of the retired-roots PR all resolved:
  - **"It needs real shell tokenization, not a regex."** It needs `shlex` plus one
    rule: only the interpreter's SCRIPT argument is a path claim. Flags, `--flag=path`,
    `$VAR`, quoted paths and pipes stop being hard the moment argv is out of scope.
    `python -m module` and `python -c '…'` name no script and are dropped whole.
  - **"It needs a fence-language policy."** Shell tags plus untagged, minus every
    explicit non-shell tag. Measured rather than argued: 311 untagged fences in the
    tree, 12 of them holding a command, and not one directory tree or YAML sample
    matches `<python> <path>.py`. A test pins the `templates/` tree case.
  - **"It changes what `_mask_fences` is for."** It does not. The mask stays exactly
    as it was and keeps its docstring; the new pass reads fences on its own terms
    and the module docstring now says so in one sentence ("masked for LINKS and
    READ for COMMANDS"). Un-masking would have dragged every tree back into the
    link passes, which is what the mask exists to prevent.
- **Decision on `.py` docstrings (DoD item 5): NOT in scope, and not a third task
  in this round.** The source enumeration stays `git ls-files '*.md'` (plus the
  overlay's). Reasons: a docstring is not copy-pasteable text a maintainer runs,
  so it is not the defect class this gate exists for; widening the enumeration
  brings in every `automation/**/*.py` and `skills/**/scripts/*.py` at once, each
  with its own false-positive surface (module docstrings quote regexes, git
  incantations and example output); and the two docstrings the task named —
  `check_public.py` and `review_gate.py` — name paths in prose, which the
  BACKTICK pass would handle if `.py` joined the source set, not this pass. If it
  is ever wanted it is a source-enumeration change, independent of everything
  here. Filed as `tasks/0_backlog/2026-07-31-verify-links-source-set-and-command-args/`
  together with the other deliberate gap (arguments to `-m unittest discover -s`).
