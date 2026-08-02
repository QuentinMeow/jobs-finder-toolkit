# Worklog — 2026-07-31-remote-role-bound-to-a-single-metro

## 2026-07-31 — session 1 (agent)

- Implemented the design sketch in `task.md` as `_JD_RESIDENCY_RE` +
  `_residency_category()` in `automation/shared/location.py`, hooked into the
  `workplace == "remote"` branch of `assess_location`.
- Kept the asymmetry the task asked for: the rule narrows an already-remote
  posting and cannot grant one. A preferred residency metro lands `metro`
  (already a match before), a non-preferred one `other_us`, a foreign one
  `foreign`, and an unparseable place `review` — never `us_remote`.
- The requirement word is mandatory in the pattern, so "many of our engineers
  live in Austin" cannot rewrite a posting's geography.
- Shipped alongside the sibling bare-`remote`-without-US-scope fix in the same
  branch; both share the `workplace == "remote"` branch and one set of
  regressions.
- Next: review/merge. Nothing outstanding.
