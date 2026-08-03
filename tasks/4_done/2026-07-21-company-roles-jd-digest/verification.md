# Verification — 2026-07-21-company-roles-jd-digest

Retro-closure, 2026-08-02. The work landed in an earlier PR without this task
being moved. Every Definition-of-done bullet was re-checked against the tree at
`f360aec` before the move; only commands actually run are below.

## DoD 1 — `--jd --digest` prints the `fetch_jd.py --digest` format; no-flag behavior unchanged

```
$ grep -n '\-\-digest' skills/job-search/scripts/company_roles.py
39:    # ~2 KB gate digest (the same locator fetch_jd.py --digest prints)
42:        --out applications/6_drafted/<slug>/source/JD-Control-Plane.md --digest
70:# ``--digest`` prints a locator only when the locator is actually SMALLER than the
205:    that drafting and the honesty gates need — so pair ``--digest`` with ``--out``
291:              f"was {dumped_bytes} bytes. `--digest` prints a ~2 KB gate locator "
320:    ap.add_argument("--digest", action="store_true",
332:        print("ERROR: --out and --digest apply to --jd only.", file=sys.stderr)
```

`company_roles.build_digest` is the same builder `fetch_jd.py` uses — the test
below asserts the two agree byte-for-byte on the same JD text.

## DoD 2 — unit tests beside the existing company_roles tests; job-search suite green

Tests live at `skills/job-search/scripts/tests/test_company_roles.py` (NOT
`tests/test_company_roles.py`, which does not exist — the earlier audit's path
was wrong). Relevant classes:

```
$ grep -n "digest" skills/job-search/scripts/tests/test_company_roles.py
185:    """Without --digest/--out, stdout is byte-identical to the pre-flag behavior."""
227:    """Every field the pipeline parses out of a JD body survives the digest."""
286:    def test_digest_matches_fetch_jd_for_the_same_text(self):
298:    """A consumer can always tell a digested dump from a complete one."""
317:    """A JD under the digest threshold is passed through untouched."""
389:    def test_a_broken_digest_never_costs_the_recovery(self):
432:    def test_digest_is_materially_smaller_than_the_full_dump(self):
```

Suite green as part of the whole-repo gate run:

```
$ .venv/bin/python automation/gates/run_gates.py
  PASS   tests-job-search  exit 0    78.0s
```

## DoD 3 — reference/SKILL fallback lines carry the flag

```
$ grep -n "company_roles.py --jd" skills/job-search/SKILL.md skills/job-search/reference.md
skills/job-search/SKILL.md:198:JD from the ATS API via `company_roles.py --jd` instead of accepting a partial scrape
skills/job-search/reference.md:68:`company_roles.py --jd`:
skills/job-search/reference.md:121:`company_roles.py --jd --digest` (ATS API) — from the same builder, so the two print one format.
```

## Eval gate

No skill-instruction change is being made by this closure — it is a task-folder
move plus this record. The instruction edits the DoD asked for shipped in the
original PR and are recorded there.
