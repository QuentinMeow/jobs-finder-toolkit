# Verification — 2026-07-28-workspace-phase-1-orphans

Commands actually run on 2026-07-29 and their real output. The overlay half is described by
shape rather than pasted, because its paths carry the owner's name and real employers and this
file is published.

## Both orphan trees are gone

The two refiles were staged in the overlay as deletions of the old paths plus new files at the
queue and task destinations. After the move, both source trees are absent:

```
$ ls -d private/todo private/email-assistant
ls: private/todo: No such file or directory
ls: private/email-assistant: No such file or directory
```

The overlay's working tree shows exactly two deletions and two additions from this task, plus one
unrelated deletion that predates this session and was deliberately left unstaged.

## The refiled task's claims still hold in this tree

The orphaned task said it was done. Rather than take that at face value, every artifact its
resolution named was looked for in the current tree — the fix itself, the three regressions it
added, and the two corpus cases:

```
$ git grep -n -e "test_general_requirement_not_contaminated_by_adjacent_clause" \
    -e "test_high_general_requirement_hard_gates_over_cap" \
    -e "test_adjacent_tool_clauses_stay_contextual_review" \
    -e "yoe-general-then-adjacent-leadership-clause" \
    -e "yoe-adjacent-tool-clauses-stay-contextual" \
    -e "_NEXT_YOE_CLAUSE_RE" -- automation/shared skills/job-search
automation/shared/job_metadata.py:429:_NEXT_YOE_CLAUSE_RE = re.compile(
automation/shared/job_metadata.py:800:    next_clause = _NEXT_YOE_CLAUSE_RE.search(after)
automation/shared/tests/test_job_metadata.py:119:    def test_general_requirement_not_contaminated_by_adjacent_clause(self):
automation/shared/tests/test_job_metadata.py:132:    def test_high_general_requirement_hard_gates_over_cap(self):
automation/shared/tests/test_job_metadata.py:142:    def test_adjacent_tool_clauses_stay_contextual_review(self):
skills/job-search/filter_variants/corpus.yaml:402:  - id: yoe-general-then-adjacent-leadership-clause
skills/job-search/filter_variants/corpus.yaml:421:  - id: yoe-adjacent-tool-clauses-stay-contextual
skills/job-search/scripts/_vendor/job_metadata.py:429:_NEXT_YOE_CLAUSE_RE = re.compile(
skills/job-search/scripts/_vendor/job_metadata.py:800:    next_clause = _NEXT_YOE_CLAUSE_RE.search(after)
```

All six present; the canonical module and its vendored copy carry the fix at identical line
numbers, consistent with the byte-identical vendoring the original session reported. The task's
fourth definition-of-done bullet was never run and is recorded as not run.

The four paths it cited (`scripts/shared/…`, `.agents/skills/job-search/…`) no longer exist. They
were rewritten to the current roots shown above; no technical claim was altered.

## The `tmp/` inventory

```
$ git status --porcelain --ignored -uall -- tmp/ | wc -l
102
```

102 files, matching the count this plan recorded. They sit in 18 non-empty folders plus one loose
file at the scratch root; two further folders are empty, giving the 20 the plan names. Git does
not track empty directories, which is why they do not appear in the listing above and had to be
counted separately.

Nothing was deleted. The breakdown by disposability is an owner decision item in the overlay's
review queue, because naming the folders here would publish employer names — one folder holds
complete application folders, another holds interview screenshots.

## Three durable records cite scratch that is already gone

The finding that produced the new handbook rule. Each of these paths is cited as evidence by a
record that is still read as current, and none of the three resolves:

| Citing record | Cited path | Present? |
|---|---|---|
| `evals/results/job-search-06c3a8f8d5be-20260721.md:40` | `tmp/search_cache/example-stage1-20260721T155148Z.json` | no |
| `evals/results/job-search-06c3a8f8d5be-20260721.md:8` | `tmp/handoffs/filtering-variant-safeguards-20260721.md` | no — the folder does not exist |
| the refiled overlay task | a `search_cache` snapshot from 2026-07-22 | no — ten sibling snapshots from that day survive, not this one |

Checked against the 102-file listing above, which is the complete contents of `tmp/`.

## Gates

The full pre-commit chain ran on each commit of this branch and its parent:

```
leak guard over the staged index    OK: no public-repo leaks detected
public review gate                  pass (4 of 13 rows reported off-chain, by design)
vendored copies                     in sync
mail send-less policy               PASS
byte-compile                        OK
instruction budget --strict         OK: all instruction files within budget
reconciler --check --require-roots  OK (8 checks clean)
```

The four off-chain rows are the orphans left by the earlier stack merge. Reporting them is the
gate behaving as designed, not a failure.
