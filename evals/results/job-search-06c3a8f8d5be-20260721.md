# Eval result — job-search

| Field | Value |
|-------|-------|
| Skill | `job-search` |
| Canary set | `evals/job-search/canaries.yaml` |
| Run kind | regression pre-merge (final audit-hardened filtering-variant safeguards) |
| Git SHA | `06c3a8f8d5be` (public main; working-tree changes under evaluation — the filtering-variant-safeguards work from `tmp/handoffs/filtering-variant-safeguards-20260721.md`) |
| Model version | Claude Sonnet 5 (resumed verification after strict-audit hardening) |
| Config mode | examples fallback (`JOBHUNT_CONFIG=$PWD/config.example.yaml`) |
| Date | `2026-07-21` |
| Judge | manual, against the frozen rubric, resumed single continuous session (see limitation below) |

## Limitation — no fresh-session isolation

All five canaries were re-run manually in **one resumed continuous agent session** against the final
working tree, not five independent fresh sessions per `evals/README.md` method (b) step 1. This
is a deviation from the ideal isolation protocol; results should be read as "the pipeline commands
the routine path prescribes produce rubric-compliant output," not as "five independently-primed
agents each discovered and executed the right routine unaided." No cross-canary state leaked
between runs other than the shared Stage-1 snapshot reused via `--refilter` (as the routine path
itself prescribes — see SKILL.md "To widen the freshness window... re-filter, never re-fetch").

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|-------------------|--------------|--------------|------------|-------|
| `js-core-shortlist` | 1 | unavailable | 40.6 (+22.3 restore) | 1 | Fresh exact default-profile Stage 1 scheduled 109 tasks: 105 company boards + 4 aggregator task groups `[jobicy, remoteok, themuse, jobspy:indeed,google]`. It fetched 11,426 postings with 0 source errors -> 40 matches + 75 review. Two accepted rows carried `source=jobspy:indeed`, proving the dependency ran; Google was scheduled in the same successful JobSpy task group. All 40 rows have real source+URL and the discoveries artifact carries level, YOE, salary, visa, why, and unknowns without fabrication. |
| `js-visa-require-positive` | 1 | unavailable | 21.9 | 1 | Refiltered the exact fresh snapshot with `--visa-policy require_positive`: 40 kept rows, every `visa_label=yes` / sponsorship `likely`; 804 uncertain rows preserved for review and no silent widening. Direct classifier probe: generic "must be authorized to work in the United States" -> `unclear`, explicit H-1B offer -> `yes`, explicit inability to sponsor -> `no`. Labels remain heuristic and require employer confirmation. |
| `js-mts-not-staff` | 1 | 0 additional | included in js-core-shortlist | 0 additional | Same fresh default-profile result kept Perplexity "Member of Technical Staff (Software Engineer, API Platform)" as `senior` (score 40), not staff. Every accepted true Staff/Staff+ title carried the explicit `level over-leveled (-1.2)` demotion; the bare word in MTS was not treated as staff level. |
| `js-recency-vs-research-window` | 1 | unavailable | 1.8 | 1 | Refiltered the same snapshot with `--max-age-days 3`: 30 matches, maximum computed age 2.6610 days. Posting age remained an explicit opt-in filter independent of the unchanged 7-day company re-search window. |
| `js-single-company-location-verdict` | 1 | unavailable | 2.2 | 1 | `company_roles.py --name Cloudflare --match-only` resolved through the registry and fetched 263 roles -> 3 policy matches, explicitly labeled heuristic. It listed all role families without applying role/seniority/visa gates, so the user must judge role fit and confirm remote/workplace claims in the JD. No Canada/India role leaked through a two-letter abbreviation. |

Pass rate: `5/5`.

## Verdict

- **Regression:** PASS. All five canaries passed, including the documented default JobSpy Indeed/Google source path, and the strict audit is clean after labeling one intentional review family.
- **Deterministic gates:** shared tests 124/124, job-search tests independently re-run 129/129, application-tracker tests 28/28, resume-writer tests 86/86, vendored-copy drift check clean, `compileall` clean, filter-variant corpus clean (25 cases), strict instruction budget OK, links/symlinks clean, and public leak guard clean (0 findings, 13 active tokens scanned).
- **Final strict snapshot audit:** the first audit of `tmp/search_cache/example-stage1-20260721T155148Z.json` correctly blocked on one unlabeled family: three JobSpy rows carried an untrusted `remote` hint with no corroborating JD wording and were quarantined as `review`, never accepted. A fictional corpus case now labels that intentional `uncorroborated_ats_workplace_hint` family without weakening the production verdict. Rerunning the same audit exited 0: `snapshot audit clean: 11426 postings, no new variants` after confirming the 25-case corpus.
- **Fixed-defect verification on all 40 accepted matches:** every row's production `title` and `location` assessment was `match`; there were zero foreign-only accepted locations/titles and zero finance/business titles admitted only through a broad infrastructure/platform/compute term. The accepted set retained legitimate engineering titles including MTS, infrastructure/platform engineers, distributed-systems engineers, and normal software/backend roles.
- **Efficiency vs baseline (2026-07-20 record):** no session token metrics were available. The one required network fetch took 40.6s; the visa refilter took 21.9s, recency refilter 1.8s, and Cloudflare check 2.2s. All filter canaries reused the exact fresh snapshot; the final default refilter only restored the canonical public artifact.
