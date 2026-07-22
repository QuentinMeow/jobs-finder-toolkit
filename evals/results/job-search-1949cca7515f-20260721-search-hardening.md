<!--
One-page result-recording template. Results are per-machine (network/board state + local model
dependent). Tracked for now; may be gitignored later. Per-SHA token metrics from
automation/metrics/report.py --by-sha are NOT available here: canaries were run as fresh subject
subagents, whose usage is not captured by the metrics hook. Efficiency below is taken from each
subagent's own usage telemetry (subagent_tokens / tool_uses / duration_ms).
-->
# Eval result — job-search

| Field | Value |
|-------|-------|
| Skill | `job-search` |
| Canary set | `evals/job-search/canaries.yaml` |
| Run kind | regression pre-merge (branch `fix/search-hardening`) |
| Git SHA | `1949cca7515f` |
| Model version | `claude-sonnet-5` (spawned via Agent tool, model=`sonnet`) |
| Config mode | examples fallback — fictional "Jordan Rivers" persona + `example` profile. Outputs redirected to per-canary `tmp/evals/<id>/` for run isolation; persona/profile/location-policy identical to `config.example.yaml`. `JOBHUNT_CONFIG` set explicitly to the per-canary config because this branch runs inside a git worktree nested under the main checkout, where default discovery would otherwise walk up to the real `config.yaml`. |
| Date | 2026-07-21 (runs executed 2026-07-21T06:44–06:51Z) |
| Judge | manual (this session), per `evals/rubrics/judging.md` — every `expected_behavior` bullet a pass/fail check; all must hold |

## Why this run (eval gate trigger)

Branch changes job-search behavior and instruction files: `handoff.py` now auto-runs the
location-policy gate (a behavioral reroute of a hard gate), and `SKILL.md` + `reference.md`
were edited (new JD-fetch fallback section + pointer). Per AGENTS.md "risk-based eval gate" and
`evals/README.md`, this MUST run the job-search canaries on branch head. Method (b): one fresh
subject subagent per canary, verbatim prompt, judged against `expected_behavior`.

Note: no canary directly exercises `handoff.py` (the canary set is search/verdict-shaped, not
handoff-shaped), so the location-gate reroute is covered by its unit tests
(`test_handoff.py`, 6 new cases) rather than a canary. The canaries confirm the SKILL.md /
reference.md edits did not regress the core search + single-company workflows.

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `js-core-shortlist` | 1 | ~81,765 (subagent) | ~286 | 21 | Ran `search_jobs.py --profile example` Stage 1 (11,381 fetched → 40 kept); wrote discoveries md + presented top matches w/ company/title/score/level+Google-eq/YOE/salary/visa/WHY; '?' for unstated facts; flagged `yes`/`unclear` as confirm-with-employer (even fetched 3 JDs to verify the `yes` rows); handed off to resume-writer/application-tracker without tailoring. No failure modes. |
| `js-visa-require-positive` | 1 | ~75,211 (subagent) | ~297 | 21 | Applied `--visa-policy require_positive`; warned the filter is very narrow (55 matches, all Anthropic) and explained "unclear ≠ no"; did NOT count work-auth boilerplate as a denial; labels heuristic + confirm-with-employer; did NOT revert to `exclude_negative` (an uncapped refilter kept require_positive and was fully disclosed — investigative, not padding). No failure modes. |
| `js-mts-not-staff` | 1 | ~95,533 (subagent) | ~391 | 29 | KEPT the Perplexity "Member of Technical Staff" role and verified `exclude_neutralize` preserved 150 raw MTS postings with 0 false drops; EXCLUDED 7 true Staff/Staff+ titles (Anthropic ×3, Twilio, Okta, Harvey, Pinecone); explained the MTS-vs-staff-level distinction; even caught 1 staff-by-required-YOE role (OpenAI, 9+y → L6) the title gate alone missed and flagged it. No failure modes. Note: achieved the hard exclude by editing `profiles/example.yaml` (the SKILL-sanctioned scope mechanism) — that tracked-file edit was reverted after the run (out of this branch's scope); it does not affect the behavioral PASS. |
| `js-recency-vs-research-window` | 1 | ~58,667 (subagent) | ~113 | 12 | Ran `--max-age-days 3` (27 matches, ages 0.2–2.3d); cleanly separated the posting-age filter from the 7-day company re-search window (`company_search_log.skip_within_days`); noted age filtering is off by default and this is the explicit "last N days" case. No failure modes. |
| `js-single-company-location-verdict` | 1 | ~56,794 (subagent) | ~103 | 13 | Used `company_roles.py --name Cloudflare --match-only` (NOT the full pipeline), resolved via registry; applied the vendored location verdict; stated it does NOT apply the role/seniority/visa title gate + gave the remote-heuristic caveat; caught a foreign (Bangalore) role the ATS `location` field mislabeled "Hybrid or Remote" by fetching the verbatim JD, and did NOT leak it as a US match. No failure modes. |

Pass rate: `5/5`.

## Verdict

- **Regression:** PASS. All 5 canaries `rubric_pass = 1`; no listed `failure_mode` observed in any
  run. The SKILL.md / reference.md edits did not regress the core shortlist, the strict-visa
  filter, the mid/senior-vs-staff seniority handling (incl. MTS preservation), the
  recency-vs-research-window distinction, or the single-company location verdict. Merge is not
  blocked by the eval gate.
- **Efficiency:** no blow-up. Runs spanned ~12–21 tool calls and ~57k–82k subagent tokens (the
  higher counts came from the agents proactively fetching JDs to verify `yes` visa labels — the
  LESSONS-driven verification step, expected). There is no committed prior baseline SHA for
  job-search to diff against these numbers; recorded here as the pre-merge baseline for
  `1949cca7515f` + `claude-sonnet-5`. Precise `total_tokens` via `report.py --by-sha` is
  unavailable for subagent-run canaries (metrics hook not wired to subagents).

## Notes / caveats

- All runs were fully public: fictional "Jordan Rivers" fixture + real-public companies with real
  live postings. Leak guard is clean on this branch (`check_public.py` → 0 findings).
- The `js-single-company-location-verdict` run surfaced a real-world limitation of the location
  heuristic (a foreign role whose foreign city is only in the title, with a generic
  "Hybrid or Remote" `location` field, classifies as `us_remote`). The subject agent handled it
  correctly by JD verification; this is pre-existing `location.py` behavior, not introduced by
  this branch, and is out of scope for the four hardening items.
- The `js-mts-not-staff` subject agent edited the tracked `profiles/example.yaml` (adding
  `staff`/`principal`/`distinguished engineer` to `titles.exclude`) to satisfy the "keep me out of
  staff" ask via a hard exclude rather than the shipped soft demotion. This is a legitimate,
  SKILL-sanctioned scope change and the run is judged on behavior (PASS). The edit was **reverted**
  after the run — it is not part of the `fix/search-hardening` branch; the branch head
  `1949cca7515f` carries only the four hardening items.
