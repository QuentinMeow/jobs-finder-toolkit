# Workspace layout — public working root, private overlay, detection after the fact

**Status (corrected 2026-08-02):** owner-approved topology (2026-07-28), **largely
implemented**. Phases 0-6 are merged into `main` and phase 7 is done — see
[the execution plan](execution-plan.md) and `docs/roadmap/current-state.md`, which are the
status board; this README is the topology. Both layers of the defense run today: Layer 2 is
`automation/publish/review_gate.py`, executed by the pre-commit hook and by CI (its own
sibling [review-gate.md](review-gate.md) already said "Implemented in
`automation/publish/review_gate.py`"). Phases 7b, 7c and 8 are not started.

~~**Status:** design, owner-approved topology (2026-07-28). Not implemented.~~ — true when
written, false for weeks afterwards. Struck rather than deleted: every phase task links this
file as `[design]`, so a reader arriving from one needs to see which claim was corrected.

## The principle

An agent must be able to see and edit public files — it uses public skills and develops the
toolkit. Hiding the public repo was never the goal. The goal is:

> Make a mistake structurally hard to make, and easy to catch when it is made.

Two layers, neither of which tries to prevent a write:

1. **Naming carries the instruction.** Every private path contains `private/`. There is no
   private byte reachable through a path that looks public — which is not true today, and
   fixing it is the main structural change.
2. **Detection after the fact.** Every commit touching the public tree trips a test that
   prints the changed files and asks for a personal-data read. It stays red until someone
   records the review in a tracked ledger.

## Topology — unchanged

The public repo is the working root. `.venv`, `rg`, `git status`, `git worktree`, config
discovery, and the git hooks all keep working exactly as today.

```text
jobs-finder-toolkit/          ← the working root. Agents cd here. Nothing is hidden.
└── private/                  ← git-ignored mount; its own repo and remote
```

Instructions route agents into `private/` when they need real data — which is already how
`config.*_path()` works. Nothing is concealed; the path just says which zone you are in.

## Layer 1 — every private path says `private/`

This is broken today in six places. A private file is reachable at a path that looks
entirely public, and the only thing stopping it from being committed is a `.gitignore` glob
with two negations:

| Path in the public tree | What it really is |
|---|---|
| `skills/job-search/profiles/<personal-name>.yaml` ×4 | symlinks into the overlay — **the filename itself is a personal token, sitting in the public tree** |
| `skills/<skill>/references_private/` ×2 | symlinks into the overlay |
| `skills/<overlay-only-name>/` ×2 | symlinks into the overlay |

All eight are deleted and replaced by `config.search_profiles_dir()`,
`config.skill_references_dir()`, and runtime adapter entries pointing straight at
`private/skills/`. Verified removable: `search_jobs.resolve_profile()` already
accepts an absolute path first and documents the case;
`bootstrap_overlay._overlay_links()` is the only writer of all three families.

After this, the rule an agent follows is one sentence with no exceptions: **if the path does
not start with `private/`, what you write there is published.**

## Layer 2 — the review gate

Specified in [review-gate.md](review-gate.md). A test that fails whenever the public tree has
commits not yet acknowledged, printing the commit range and the changed files. Acknowledging
means appending a row — commit, file count, a digest of the actual diff, and a finding — to
`automation/publish/review_ledger.yaml`. The digest is recomputed, so a row cannot be
guessed; it forces the diff into the reviewer's context, which is where the judgment happens.
Runs in `pre-commit` and in CI, so `--no-verify` does not dodge it.

Alongside it, the existing `check_public.py` token scan, plus a narrowed private-company
cross-reference. **Measured warning:** the obvious version of that detector is unusable as a
blocker — flagging any public file naming a company in the private tree matches **51 of 177**
private company tokens across the current public tree, led by `canonical` (114 files),
`writer` (103), `render` (85), `lambda` (59), `customer`, `iterable` — ordinary English words
— plus Google, Microsoft, Amazon and Anthropic appearing legitimately as ATS providers and
model vendors. So it runs on the diff only, subtracts the pre-change baseline, matches
display names from `companies/_index.yaml`, and feeds the gate as a *hint*, never a block.

## The public tree

```text
jobs-finder-toolkit/
├── AGENTS.md  CLAUDE.md  README.md  CONTRIBUTING.md  LICENSE  requirements.txt
├── config.example.yaml                    # tracked placeholder (Jordan Rivers)
├── config.yaml                            # git-ignored; paths.* point into private/
├── .venv/                                 # git-ignored, unchanged
├── skills/                                # 11 public skills, each self-contained
│   ├── application-tracker/  ask-me-anything/  behavioral-interview-prep/
│   ├── company-research/  email-assistant/  gardener/  github-workflow/
│   ├── interview-calendar/
│   ├── job-search/                        #   keeps companies.yaml, profiles/, filter_variants/
│   ├── resume-writer/  search-recall-audit/
│   └── (no overlay-only symlinks — runtimes find them in private/skills/)
├── automation/
│   ├── shared/  vendoring/  hooks/  reconcile/  metrics/  store/  bootstrap/
│   ├── gardener/                          # was maintenance/gardener/
│   ├── search-recall-audit/               # was maintenance/search_recall_audit/
│   ├── company-levels/                    # was maintenance/import_company_levels.py
│   └── publish/
│       ├── check_public.py  export_public.py
│       ├── review_gate.py                 # ← NEW
│       ├── review_ledger.yaml             # ← NEW (tracked)
│       └── tests/
├── docs/
│   ├── handbook/                          # was handbook/
│   ├── designs/                           # was design/
│   └── roadmap/                           # was roadmap/
├── evals/
│   ├── protocols/                         # ab-protocol + stage-benchmark protocol
│   ├── rubrics/  canaries/<skill>.yaml  results/
├── examples/                              # the fake candidate, mirroring private/'s shape
│   ├── me/  companies/  applications/  store/  fixtures/  screenshots/
├── templates/                             # process-file schemas
├── memory/  message-queue/  tasks/        # toolkit-scope process layer
├── local/                                 # git-ignored scratch (was tmp/)
├── .github/  .claude/  .cursor/  .agents/  .claude-plugin/
└── private/                               # git-ignored mount → the private repo
```

## The private overlay

```text
private/
├── README.md  .gitignore  leak_tokens.txt  email-company-domains.yaml
│
├── me/                                    # ══ PERMANENT · role-agnostic ══
│   ├── profile.md  baseline.yaml  tailoring-card.md
│   ├── resume/                            #   master.docx  master.pdf  reference.docx
│   └── interviews/
│       ├── story-bank/                    #   behavioral story bank
│       ├── question-bank/                 #   generic answers (_general_*) + sources/
│       ├── common-message-replies/        #   reusable message templates
│       ├── practice/                      #   coding practice tied to no company
│       └── calendar.md                    #   upcoming interviews across everything
│
├── companies/                             # ══ PERMANENT · per company ══
│   ├── _index.yaml                        #   key → {display, aliases[], parent, kind}
│   └── <key>/                             #   THE single alias registry
│       ├── company.yaml                   #   ATS, sponsorship, levels + comp (last_verified),
│       │                                  #     relationship: stub|researched|applied|interviewed|offer
│       ├── loop.md                        #   HOW THEY INTERVIEW — rounds, format, vendor, timing
│       ├── people.yaml                    #   recruiters, hiring managers
│       ├── research/                      #   company-research output
│       ├── coding/<problem>/              #   problems seen here
│       ├── derived/                       #   their-values answers, ONE FILE PER principle
│       └── decision.md                    #   offer, comp, would-I-work-here
│
│                                          #   (a firm that RUNS interviews on a client's
│                                          #    behalf is a company too — its own loop, its
│                                          #    own question set. No separate vendors/ root.)
│
├── applications/                          # ══ DISPOSABLE ══ status folders unchanged
│   └── <2_ignored…6_drafted>/<company>-<role>-<date>/
│       ├── meta.yaml                      #   + company_key, validated against _index.yaml
│       ├── <RESUME_STEM>.pdf  <COVER_STEM>_<Role>.pdf  <APPLICATION_STEM>_<Role>.txt
│       ├── timeline.md                    #   this req's log; entries carry durable: true|false
│       └── source/                        #   JD-<title>.md, tailored.yaml, *.docx
│
├── market/                                # ══ what the pipeline scans as a whole ══
│   ├── blacklist.yaml  manual-check.yaml
│   ├── universe/  searches/
│   ├── scans/{current,archive}/           #   dated, 30-day TTL
│   └── logs/
│       ├── applications.jsonl             #   APPEND-ONLY, URL-keyed, never regenerated
│       ├── company-search-log.yaml
│       └── company-levels.yaml            #   stays whole — 27 YAML anchors don't shard
│
├── store/                                 # ══ raw-data layer ══ (rename of data/)
│   ├── jobs/{raw,derived,index,state}/
│   └── email/{raw,derived,index,state,annotations}/
│
├── skills/
│   ├── <overlay-skill>/                   #   zero or more private skills
│   └── skill-notes/<skill>/               #   was skills/references_private/<skill>/
│
├── memory/  message-queue/  tasks/        # ══ private-scope process layer ══
├── evals/{canaries,fixtures,runs}/        #   private canaries + benchmark (+ config.benchmark.yaml)
├── docs/                                  #   maintainer-only harness-engineering docs
└── local/                                 # ══ NEVER COMMIT ══
    ├── tmp/  cache/  logs/
    └── history/<date>-<slug>/handover.md  #   session handovers
```

Handovers live under `private/local/` rather than the public `local/` so that even a forced
add lands in the private repo. Consequence, stated once: the reconciler's `handover-present`
check becomes local-only — it fires on the machine doing the work and is vacuous in CI.

## Company ≠ application ≠ prep

| Survives the application | Where |
|---|---|
| Their loop — rounds, format, vendor, timing | `companies/<key>/loop.md` |
| Research, moat, competitors, culture | `companies/<key>/research/` |
| Levels, comp (values carry `last_verified`) | `companies/<key>/company.yaml` |
| Recruiter identity | `companies/<key>/people.yaml` |
| Problems they asked | `companies/<key>/coding/` |
| Would I work here | `companies/<key>/decision.md` |

| Dies with the application | Where |
|---|---|
| JD, tailored resume, cover letters, packet | `applications/<status>/<slug>/` |
| This req's narrative — dates, reschedules, outcome | `applications/<status>/<slug>/timeline.md` |

An application folder is deletable **by the user only**. Agents never delete owner data under
any condition — the guardrail is in `AGENTS.md`. The taxonomy's job is to make the user's
`rm -rf` safe, not to let an agent perform it.

An interview vendor is a company. A firm that runs the loop on a client's behalf has its own
format and its own question set, so it gets a `companies/<key>/` like any employer;
`companies/<key>/loop.md` names it where a loop is run by one.

Three requirements, each with the evidence that forced it:

1. **The company key must be owner-owned.** 242 application folders carry **213 distinct
   free-text company strings**; the registry resolves only 119 — 44% unresolvable, including
   several household-name employers it has no row for. Bare-name-versus-legal-suffix and
   bare-name-versus-parenthesised-entity splits are already live in the data (not named
   here — that list *is* the owner's application history). Hence one
   `companies/_index.yaml`, `company_key` in `meta.yaml`, and a reconciler check that every
   key resolves and no two share an alias.

2. **The skip-log must stop being derived.** `--sync-log` regenerates `applications-log.yaml`
   from a scan of the folders, so deleting a rejected application and re-syncing makes the
   posting look fresh. It becomes `market/logs/applications.jsonl` — append-only, URL-keyed,
   **not** per-company markdown, because the existing skip check is deliberately URL-first
   and key-independent, so sharding by key would turn every alias split into a re-drafted
   application.

3. **Durable vs disposable splits at write time.** A single real sentence in a recruiter
   email routinely carries both: *"<recruiter> confirmed the 60-minute video coding
   interview for <date> … with <video tool> and <coding platform>"* — the format is
   permanent, the date dies with the application, and they arrive in one sentence. The email assistant rewrites these files every run, so it
   emits a `durable:` flag per entry and a `promote` command moves the flagged ones.

`companies/` is not fed only by applications — four entries under today's
`interviews/company-specific/` have no application at all. It is a first-class root that
recruiter outreach and research write to directly.

## Sharp edges that become handbook rules

- `git clean -ffdx` in the public repo **deletes the entire private repo** (verified: plain
  `-fdx` skips it, `-ffdx` removes it).
- `git add -f private/` — with the trailing slash — stages private files with exit 0 and no
  output. The slash-less form warns.
- Renaming `data/` → `store/` without simultaneously rewriting all **9** ignore patterns
  unignores **82,318 files / 432 MB**, including 36,465 raw email files the ignore file's own
  comment says must never enter history.

## Human questions / additional tasks

<!-- Free space: write here any time. -->
