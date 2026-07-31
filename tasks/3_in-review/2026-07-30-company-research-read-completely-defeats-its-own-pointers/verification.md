# Verification — 2026-07-30-company-research-read-completely-defeats-its-own-pointers

Real output, captured 2026-07-31 on `fix/10-company-research-correctness`. Absolute paths
are redacted to `<repo-root>`.

## The contradiction, before — and there were THREE copies, not two

```
$ git grep -n -E "read \`reference\.md\` completely|read ONLY \`reference\.md\`|read \`reference\.md\` §|Read this reference before" \
      b7227ae97 -- skills/company-research/SKILL.md skills/company-research/reference.md
SKILL.md:109:Before live research and before writing outputs, read `reference.md` completely. ...
SKILL.md:160:  product/competitive strength (before writing it, read `reference.md` § "Competitor
SKILL.md:197:  least two angles**. Before writing it, read `reference.md` § "Why-This-Company Template".
SKILL.md:291:"network effects"):** read ONLY `reference.md` § "5 Whys, worked example".
SKILL.md:385:**Trigger — drafting the questions themselves:** read ONLY `reference.md` §
reference.md:3:Read this reference before live research and again before writing company-research outputs. ...
```

`SKILL.md:109` and `reference.md:3` are both blanket-read instructions; the task names only
the first. Five per-file pointers sit under them.

## After

```
$ git grep -n -E "read \`reference\.md\` completely|end to end|read ONLY \`reference\.md\`|read \`reference\.md\` §|read by section" \
      -- skills/company-research/SKILL.md skills/company-research/reference.md
SKILL.md:126:The rest of the file is per-file templates: **each file's entry below names the one
             section to read before writing that file, and those pointers are the complete
             list — nothing here asks you to read `reference.md` end to end.**
SKILL.md:177:  product/competitive strength (before writing it, read `reference.md` § "Competitor
SKILL.md:216:  least two angles**. Before writing it, read `reference.md` § "Why-This-Company Template".
SKILL.md:312:"network effects"):** read ONLY `reference.md` § "5 Whys, worked example".
SKILL.md:447:**Trigger — drafting the questions themselves:** read ONLY `reference.md` §
reference.md:3:**This file is read by section, never end to end.** Before live research read
               §§ "Handy Fetches", "Maturity fetches" and "Output Location and Structure"; ...
```

Zero blanket-read instructions remain. The five pointers are unchanged and now agree with
both headers.

## The measurement the task asked for

Before (`b7227ae97`): `reference.md` = 206 lines, 13,220 bytes (~3.3k tokens) — matching the
task's estimate, and all of it read every run.

After, per-section, with the three always-read sections marked:

```
$ .venv/bin/python - <<'PY'   # split reference.md on H2 and size each section
ALWAYS   2350  Handy Fetches
ALWAYS   1914  Maturity fetches
ALWAYS   2110  Output Location and Structure
         5259  Per-File Rubrics and Templates
          690  Angle 1 — <role type / framing>
           97  Angle 2 — <different role type / framing>
         2283  Curveballs

always-read bytes: 6374  (~1593 tok)   whole file: 15071 (~3767 tok)
PY
```

So the always-read portion drops **~3.8k tokens -> ~1.6k tokens (-58%)**, even though the
file itself grew from 13,220 to 15,071 bytes by adding the "Maturity fetches" section this
branch introduces. Against runs that cost 125k-1.2M tokens, the saving is 0.2-1.8% — the
change is justified by determinism, not by the tokens, and the eval record says so.

## Budget still clean after the edit

```
$ .venv/bin/python automation/metrics/instruction_budget.py --strict
FILE                                                 LINES  BYTES  ~TOKENS     BUDGET  STATUS
skills/company-research/SKILL.md                       535  36022     9005        600      ok
skills/company-research/LESSONS.md                      52   3512      878        160      ok
skills/company-research/reference.md                   229  15323     3830          -     n/a
OK: all instruction files within budget.
```

## Canary evidence

`evals/results/company-research-48f9b46a366e-20260731-correctness.md`. Four canaries run,
**4/4 rubric_pass**. Every run reported which sections of `reference.md` it read and quoted
the instruction line it followed; none read the file end to end on its own initiative, and
the three single-file runs read 3-5 sections of 8.

Two findings corrected the first draft, both recorded in the eval record:

- a **sixth** pointer was hiding in `09`'s prose and conflicted with its own Trigger. One run
  followed the narrower instruction and wrote `09`'s required pitch **without ever seeing the
  template that defines its shape** - a real cost of the ambiguity, not a hypothetical one;
- "nothing asks you to read `reference.md` end to end" was an overclaim. A full-folder run
  fires every per-file pointer, and the union of those pointers is the rest of the file. The
  tiering buys `SKILL.md` budget headroom and saves tokens only on a single-file request. Both
  files now say that rather than implying otherwise.
