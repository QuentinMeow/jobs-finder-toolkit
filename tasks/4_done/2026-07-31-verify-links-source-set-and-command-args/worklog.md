# Worklog — 2026-07-31-verify-links-source-set-and-command-args

## 2026-08-02 — session 1 (agent)

- Did the measurement the task asks for (`verification.md`), then **closed the task without
  implementing the check**, which is the second branch its own Definition of done offers.
- The measurement answers the open question decisively and in the direction the exclusion was
  written to protect: across all tracked `*.md`, 125 occurrences of
  `-m unittest discover -s <path>` name 17 distinct paths, of which 5 do not exist — 4 are
  literal placeholders (`<dir>`, `<path>`, `<each suite>`, `<scratch>/…`) and 1 is a genuinely
  stale path. **Zero of the five sit in a tier where a break fails a gate**: three are in
  `tasks/4_done/`, the `record` tier (permitted, never fatal), and two are in
  `tasks/0_backlog/`, the `plan` tier (advisory).
- So arming the shape would add ~50 lines of parser and a test suite to produce, today, zero
  failures and one advisory line — about a path inside a dated verification record that must
  not be rewritten to match the present. That is the "cries wolf" outcome the exclusion
  exists to prevent, arriving by a different route.
- The `.py`-docstring decision (part 2) was already **Decided 2026-07-31: out of scope**. Left
  standing; no evidence of a real miss turned up, and this session read
  `check_public.py`/`review_gate.py` docstrings closely without being misled by one.
- No code changed. `automation/gardener/verify_links.py` is untouched, so its
  `_instruction_files()` docstring needs no amendment — the source set is still `*.md` and
  still says so.
