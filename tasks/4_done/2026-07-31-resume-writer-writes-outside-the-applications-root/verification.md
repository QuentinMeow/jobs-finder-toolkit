# Verification — resume-writer writes outside the applications root

Every command below was run from the repo root on branch `fix/03-owner-data-paths`.
Absolute home paths are redacted to `<repo-root>`.

## No skill command creates an application folder at a literal path

```
$ grep -rn 'mkdir' --include='*.md' skills/ AGENTS.md docs/handbook/ | grep -i applications
skills/resume-writer/reference.md:470:   Preflight (blacklist + applications log + existing status folders). Do not `mkdir` until checks pass;
docs/handbook/private-overlay.md:133:mkdir -p private/applications/{2_ignored,3_rejected,4_in_progress,5_applied,6_drafted}
```

Two hits, neither a defect: the first is prose forbidding a premature `mkdir`, the second is the
overlay scaffold command, which is deliberately literal — it is what creates the tree the
accessor later resolves to.

The rewritten step-5 block:

```
$ grep -n 'apps>' skills/resume-writer/SKILL.md
206:# <apps> = config.applications_root(), <baseline> = config.baseline_path()
208:mkdir -p <apps>/6_drafted/<slug>/source
209:cp <baseline> <apps>/6_drafted/<slug>/source/tailored.yaml
```

## Where the shorthand is defined now

```
$ grep -rln 'shorthand for `config.applications_root()`' AGENTS.md \
    docs/handbook/command-cookbook.md docs/handbook/application-folders.md \
    skills/resume-writer/SKILL.md skills/application-tracker/SKILL.md
AGENTS.md
docs/handbook/application-folders.md
skills/application-tracker/SKILL.md
skills/resume-writer/SKILL.md
docs/handbook/command-cookbook.md

$ grep -rn 'here `applications/` means' skills/ask-me-anything/SKILL.md
skills/ask-me-anything/SKILL.md:141:The `resume-writer` skill creates `applications/6_drafted/<slug>/` (here `applications/` means
```

`ask-me-anything` carried the only pre-existing definition; the five above are new.

## Judgment recorded: real instruction vs documentation shorthand

| Site | Verdict | Action |
|---|---|---|
| `skills/resume-writer/SKILL.md` step 5 (`mkdir` + `cp`) | real instruction — creates owner data | rewritten to `<apps>` |
| `AGENTS.md` Application Folder Convention + tree | shorthand | definition added |
| `docs/handbook/command-cookbook.md` (every command) | shorthand — the reader substitutes a real folder | definition added |
| `docs/handbook/application-folders.md` (status table + tree) | shorthand | definition added |
| `skills/application-tracker/SKILL.md` (13 uses) | shorthand — a wrong read fails loudly, never silently | definition added |
| `skills/job-search/SKILL.md` (3), `skills/search-recall-audit/SKILL.md` (1), `skills/resume-writer/reference.md` (4) | shorthand, already covered by the definitions above | none |

One real instruction. Eight shorthand sites, five of which now carry a definition; the other
three are reached only from a document that defines the term.

## Instruction budget still clear after the additions

```
$ .venv/bin/python automation/metrics/instruction_budget.py --strict
FILE                                                 LINES  BYTES  ~TOKENS     BUDGET  STATUS
AGENTS.md                                              318  25167     6291        500      ok
skills/application-tracker/SKILL.md                    530  29793     7448        600      ok
skills/resume-writer/SKILL.md                          456  31559     7889        600      ok
```

## Full gate

```
$ zsh <scratch>/gate.sh
ALL GREEN
```
