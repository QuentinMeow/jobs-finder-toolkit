# Private overlay

This toolkit is designed to be published **publicly** while everything tied to a
real person or a real job hunt stays **private**. It ships as two layers:

1. **PUBLIC toolkit repo** — timeless, general tooling only: the scripts, the public
   skills, the company registry (identity only), a fake example candidate
   ("Jordan Rivers") under `examples/`, and `config.example.yaml`. Nothing here is
   tied to a real person or a dated posting.
2. **PRIVATE overlay repo** — its **own git repo**, synced to a private GitHub
   remote, holding your real data: profile, resume baseline, reference DOCX,
   applications, interviews, any overlay-only skills, `config.yaml`,
   and your real job-search profile YAML(s).

The overlay **mounts into a git-ignored `private/` directory** inside a public
checkout (**`private/` is the canonical mount**), and `config.yaml`'s `paths.*` point the
toolkit at the overlay's data. Because `private/` (and the other private paths) are
git-ignored in the public repo, your real data is never committed to the public toolkit.

## How the layering works

- **Every private path says `private/`.** Nothing under `skills/` is private: as of
  2026-07-28 the toolkit no longer creates any symlink from the public tree into the
  overlay, so the rule has no exceptions — *if a path does not start with `private/`,
  what you write there is published.* The overlay is reached only through
  `config.*()` accessors and the git-ignored runtime entries described in step 4 below.
- The exported public repo's `.gitignore` ignores `private/`, `config.yaml`, and the
  legacy in-place product folders (`applications/`, `interviews/`, `.agents/inputs/`).
  Exact overlay-only runtime adapter paths live only in the checkout's
  `.git/info/exclude`, which bootstrap maintains from the mounted overlay.
  So you can still work **in place** for those product trees; everything else belongs
  under `private/`. This layered source checkout may carry private products on a
  private branch; the public exporter excludes those paths before publishing.
- **Per-skill private notes.** Any candidate-specific skill guidance that used to be
  baked into a `SKILL.md` (real lead-project ordering, real metrics, personal
  anecdotes) lives in the overlay at `config.skill_references_dir("<skill>")` —
  `private/skills/skill-notes/<skill>/` under the layout below (set
  `paths.skill_references_root`). Each `SKILL.md` reads it
  when present (its "Before You Start" **Personalization** stanza) and otherwise falls
  back to the generic examples. The leak guard fails on any tracked file under a
  `references_private/` folder anywhere in the tree, and the exporter prunes them.
- **Guard tokens are config-derived.** `automation/publish/check_public.py` hardcodes no
  identity; it derives its personal-token set from `config.yaml`, an optional
  `private/leak_tokens.txt`, and the `JOBHUNT_PERSONAL_TOKENS` env var, and scans both
  text and `.docx`/`.pdf` content. Only a real `config.yaml` identity or
  `JOBHUNT_PERSONAL_TOKENS` **arms** it; `leak_tokens.txt` adds tokens but cannot arm it,
  and an unarmed guard exits 2 instead of reporting "safe to publish" (`--allow-unarmed`
  runs the token-independent checks knowingly).
- Skills are discovered through the tracked public adapters plus the Codex, Claude
  Code, and Cursor agent-host trees (see `AGENTS.md`). A private skill lives only
  in the overlay; `automation/bootstrap_overlay.py` gives it a repository-locally
  ignored entry in all three host trees pointing straight at
  `private/skills/<name>`, so it is discoverable **only** when the overlay is
  mounted and its name never enters the tracked public tree.
- `config.yaml`'s `paths.*` are resolved **relative to the config file's
  directory**, so you can point them at `private/…` (or anywhere) and swap the
  fake example candidate for your real one without editing any tooling.

## Suggested overlay layout

Keep the overlay as its own git repo (private). The layout is organised **by lifetime** —
what is permanently true about you (`me/`), what is permanently true about a company
(`companies/<key>/`), what dies with a single req (`applications/`), and what describes
the market you scan (`market/`). Each root maps onto `config.yaml` `paths.*` keys:

```
my-jobhunt-overlay/            # private git repo (mounts at ./private/)
├── config.yaml                # your real identity + paths (copied from config.example.yaml)
├── leak_tokens.txt            # -> private/leak_tokens.txt (extra publish-guard tokens)
├── me/                        # PERMANENT — role-agnostic, this is you
│   ├── profile.md             # -> paths.profile_md
│   ├── baseline.yaml          # -> paths.baseline_yaml
│   ├── tailoring-card.md      # -> paths.tailoring_card
│   ├── resume/
│   │   └── <your-resume>.docx # -> paths.reference_docx
│   └── interviews/
│       ├── calendar.md        # -> paths.calendar_md (upcoming interviews across everything)
│       ├── story-bank/        # -> paths.story_bank_dir (behavioral project stories)
│       ├── question-bank/     # generic behavioral answers
│       └── common-message-replies/   # reusable recruiter-message templates
├── companies/                 # PERMANENT — one folder per company (-> paths.companies_root)
│   └── <key>/
│       ├── research/          # company-research output
│       ├── coding/            # coding problems seen at this company
│       └── product-sense/     # product/design-sense prep for this company
├── applications/              # DISPOSABLE — your real applications (-> paths.applications_root)
│   └── <2_ignored…6_drafted>/<company>-<role>-<date>/
├── market/                    # what the pipeline scans as a whole
│   ├── blacklist.yaml         # -> paths.blacklist_yaml (registry skip rules)
│   ├── universe/              # company universes you sweep
│   ├── searches/              # -> paths.search_profiles_dir (your real search profile YAMLs)
│   ├── scans/                 # dated discovery scans: fresh in current/, aged in archive/
│   │   ├── current/           # -> paths.discoveries_dir
│   │   └── archive/
│   └── logs/                  # -> paths.candidate_dir
│       ├── applications-log.jsonl   # -> paths.applications_jsonl (job-search skip list,
│       │                            #    append-only: nothing rewrites it, so deleting an
│       │                            #    application does not un-skip its posting)
│       ├── applications-log.yaml    # -> paths.applications_log (RETIRED projection; read
│       │                            #    once by --backfill-log, then unread. Remove it
│       │                            #    yourself — no tool deletes owner data)
│       ├── company-search-log.yaml  # -> paths.company_search_log
│       └── company-levels.yaml      # -> paths.company_levels_yaml
├── store/                     # raw-data layer, git-ignored payloads (-> paths.data_root)
└── skills/
    ├── <overlay-skill>/       # zero or more private skills
    └── skill-notes/           # candidate-specific references grouped by public skill
        └── resume-writer/     # -> config.skill_references_dir("resume-writer")
```

The overlay may also carry its own `memory/`, `message-queue/`, and `tasks/` folders —
the private-scope mirror of the toolkit's process layer, for items that cannot be named
in public (see `message-queue/README.md`).

`private/leak_tokens.txt` is one token per line (blank / `#` lines ignored) — put
identity attributes NOT stored in `config.yaml` here (extra handles, school, GPA,
title, current/former employers, internal product and distinctive project names).
`private/market/blacklist.yaml` holds identity-only rows (`name` + optional
`aliases` + a `blacklist:` reason) that `registry.py` merges into the company registry
so personal skip rules never live in the public `companies.yaml`.

## Creating your overlay from scratch

You do not need to be the maintainer to have an overlay — anyone can generate
their own private data set and use the toolkit for a real hunt. From the toolkit
checkout root:

```bash
# 1. Scaffold the overlay tree (directly at the git-ignored ./private/ mount):
mkdir -p private/me/{resume,interviews/{story-bank,question-bank,common-message-replies}}
mkdir -p private/companies
mkdir -p private/applications/{2_ignored,3_rejected,4_in_progress,5_applied,6_drafted}
mkdir -p private/market/{universe,searches,logs,scans/{current,archive}}
mkdir -p private/skills/skill-notes

# 2. Seed the data files from the tracked fixtures, then edit them to be YOU:
cp examples/profile/profile.example.md        private/me/profile.md
cp examples/profile/baseline.example.yaml     private/me/baseline.yaml
cp examples/profile/company-levels.example.yaml private/market/logs/company-levels.yaml
cp examples/templates/reference.example.docx  private/me/resume/reference.docx
cp skills/job-search/profiles/_TEMPLATE.yaml  private/market/searches/my-default.yaml

# 3. Arm the leak guard with your identity (one token per line: name variants,
#    email localpart, phone, school, employers, distinctive project names):
$EDITOR private/leak_tokens.txt

# 4. Make it a git repo of its own — local-only is fine; a PRIVATE GitHub remote
#    adds multi-machine sync. NEVER make this repo public.
cd private && git init && git add -A && git commit -m "My private overlay"
gh repo create <you>/my-jobhunt-overlay --private --source . --push   # optional
cd ..

# 5. Point the toolkit at it and wire everything up (see "Setup steps" below):
cp config.example.yaml config.yaml     # edit candidate + paths.* to private/…
python automation/bootstrap_overlay.py
```

Git does not track empty directories, so the status folders under
`applications/` materialize in a fresh clone only as the tools write into them —
that is normal. The `companies/`, `me/interviews/`, and `skills/` trees are optional;
leave them empty until you have content (e.g. your own private interview-prep skill).

## Setup steps

1. **Clone the public toolkit + create the venv.**

   ```bash
   git clone https://github.com/<owner>/jobs-finder-toolkit.git   # or your fork
   cd jobs-finder-toolkit
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

2. **Mount your overlay.** Clone (or symlink) your **own** private overlay repo
   into the git-ignored `private/` path (replace `<you>/<your-private-overlay>`
   with your private remote):

   ```bash
   git clone git@github.com:<you>/<your-private-overlay>.git private
   # or, if the overlay already lives elsewhere:
   ln -s /abs/path/to/your-overlay private
   ```

3. **Create `config.yaml`.** Copy the example and edit the `paths.*` to point at
   your overlay data (paths resolve relative to the config file's directory):

   ```bash
   cp config.example.yaml config.yaml
   ```

   ```yaml
   # config.yaml (illustrative — real values live only in your overlay)
   candidate:
     name: "Jordan Rivers"
     contact_line: "City, ST • jordan.rivers@example.com • linkedin.com/in/jordanrivers"
     name_slug: "Jordan_Rivers"
     title_slug: "Software_Engineer"
   paths:
     profile_md: "private/me/profile.md"
     baseline_yaml: "private/me/baseline.yaml"
     tailoring_card: "private/me/tailoring-card.md"
     reference_docx: "private/me/resume/<your-resume>.docx"
     calendar_md: "private/me/interviews/calendar.md"
     story_bank_dir: "private/me/interviews/story-bank"
     applications_root: "private/applications"
     discoveries_dir: "private/market/scans/current"
     applications_log: "private/market/logs/applications-log.yaml"
     applications_jsonl: "private/market/logs/applications-log.jsonl"
     company_search_log: "private/market/logs/company-search-log.yaml"
     company_levels_yaml: "private/market/logs/company-levels.yaml"
     blacklist_yaml: "private/market/blacklist.yaml"
     search_profiles_dir: "private/market/searches"
     candidate_dir: "private/market/logs"
     skill_references_root: "private/skills/skill-notes"
     data_root: "private/store"
   job_search:
     default_profile: "my-default"
   ```

   Every key after `applications_root` is optional — each has a default derived from
   the roots above it — but a lifetime-organised overlay like this one overrides most
   of them, because the defaults assume the flat "everything under
   `<applications_root>/0_profile/`" layout the example candidate uses.

   `config.yaml` is git-ignored in the public repo, so your real identity never
   gets committed. (If you prefer, point `paths.*` at in-place folders like
   `applications/` — those are git-ignored too.)

4. **Wire the private skills + git hooks.** One idempotent, stdlib-only step:

   ```bash
   python automation/bootstrap_overlay.py          # add --check to preview, make no changes
   ```

   It writes **nothing tracked** into the public tree. With `private/` mounted it
   links each private skill — any `private/skills/<name>/` holding a `SKILL.md` —
   into the Codex, Claude Code, and Cursor host trees, pointing straight at
   `private/skills/<name>`. Before creating those adapters, bootstrap writes their
   exact paths into a managed block in `.git/info/exclude`. That file is local Git
   metadata: it is never committed or exported, so every runtime sees the skill
   while the public repository never learns its name. Adding or renaming a private
   skill requires only re-running bootstrap. Removing one also removes its stale
   generated adapters and local exclude rows; foreign runtime entries are never
   touched.

   Your other overlay content needs no wiring at all — the toolkit reaches it through
   config accessors: personal search profiles via `config.search_profiles_dir()`
   (`search_jobs.py --profile <label>` resolves there first, then the public
   `skills/job-search/profiles/`; point `config.job_search.default_profile` at one), and
   per-skill private notes via `config.skill_references_dir("<skill>")`.

   It **always** installs `automation/hooks/pre-commit` and `automation/hooks/pre-push` into `.git/hooks`
   (never clobbering a foreign hook — it warns instead), and re-running is a safe
   no-op. When `private/` is mounted it also installs the OVERLAY's own hooks into
   `private/.git/hooks/`, as symlinks to `automation/hooks/overlay-pre-commit` and
   `automation/hooks/overlay-pre-push`. Both scripts are tracked **here**, in the public
   repo, so they stay reviewed and versioned and the overlay needs no tracked code of its
   own. `overlay-pre-commit` rejects a staged raw-data-layer store payload
   (`<data_root>/*/{raw,derived,state}`, resolved from `config.data_root()`) and a staged
   set larger than any commit in that repo's history (500 files / 128 MiB);
   `overlay-pre-push` refuses any destination that is not the private remote the repo
   configures (`jobhunt.privateRemote`, else `remote.origin.url`) and fails closed when it
   cannot determine one. Private skills, per-skill private notes, and personal search
   profiles now live **only** under `private/` (plus the git-ignored host entries above),
   so they stay out of public history while remaining reachable whenever the overlay is
   mounted. The `skills/job-search/profiles/` folder holds nothing but the public
   `example.yaml`, `_TEMPLATE.yaml`, and `README.md`.

**Maintainer note.** The maintainer keeps the canonical overlay as its own private
GitHub repo, mounted at `private/` exactly as above. Strangers do not need
(or get) access to it — the `<you>/<your-private-overlay>` placeholder is your own.

## How the public repo stays clean

This public repo is **canonical** — toolkit development happens here directly;
there is no export/mirror step between a maintainer checkout and what you see.
(The allowlist exporter, `automation/publish/export_public.py`, seeded this repo's
fresh history from the maintainer's pre-split combined repo, and lives on as the
end-to-end harness for the leak-guard test suite and as a sanitized-copy tool.)

The gate is the leak guard (`automation/publish/check_public.py`). It derives
overlay-only skill names from mounted `private/skills/*/SKILL.md` at runtime and
fails if any appears in the tracked public tree. It also fails on any private
skill tree, `private/` path, tracked `references_private/` file, or
personal-identity token (in a path, text content, or extracted `.docx`/`.pdf`
content) is tracked. Its tokens are derived at runtime from `config.yaml` +
`private/leak_tokens.txt` + `JOBHUNT_PERSONAL_TOKENS` (nothing hardcoded), so
with your overlay mounted it screens for **your** identity — and it refuses to
run (exit 2) when no identity token resolved at all, because a guard that cannot
see your name cannot certify a tree. It runs four times over: in the pre-commit
hook over the **staged index** (with `--allow-unarmed`, alongside a hard reject of
any staged `private/` path), blocking in CI, in the pre-push hook before anything
reaches a public remote (armed — no escape hatch but `JOBHUNT_ALLOW_PUSH=1`), and
by hand any time:

```bash
.venv/bin/python automation/publish/check_public.py
```

The steady state is **zero findings**; any finding is a regression to fix, never
to except.
