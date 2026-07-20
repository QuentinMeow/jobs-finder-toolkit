# Private overlay

This toolkit is designed to be published **publicly** while everything tied to a
real person or a real job hunt stays **private**. It ships as two layers:

1. **PUBLIC toolkit repo** — timeless, general tooling only: the scripts, the five
   public skills, the company registry (identity only), a fake example candidate
   ("Jordan Rivers") under `examples/`, and `config.example.yaml`. Nothing here is
   tied to a real person or a dated posting.
2. **PRIVATE overlay repo** — its **own git repo**, synced to a private GitHub
   remote, holding your real data: profile, resume baseline, reference DOCX,
   applications, interviews, the private `coding-interview` skill, `config.yaml`,
   `.cursor/rules/private-skills.mdc`, and your real job-search profile YAML(s).

The overlay **mounts into a git-ignored `private/` directory** inside a public
checkout (**`private/` is the canonical mount; `personal/` is kept as a legacy
alias** — `.gitignore` ignores both), and `config.yaml`'s `paths.*` point the
toolkit at the overlay's data. Because `private/` (and the other private paths) are
git-ignored in the public repo, your real data is never committed to the public toolkit.

## How the layering works

- The exported public repo's `.gitignore` ignores `private/`, `config.yaml`,
  `.cursor/rules/private-skills.mdc`, every per-skill
  `.agents/skills/*/references_private/` folder, and the private product folders
  (`applications/`, `interviews/`, `templates/`, `.agents/inputs/`,
  `.agents/skills/coding-interview/`). So you can work **in place** in a public
  checkout: drop your private files at those paths (or under `private/` and point
  `config.yaml` at them) and git will refuse to track them. This layered source
  checkout may carry private products on a private branch; the public exporter
  excludes those paths before publishing.
- **Per-skill private notes.** Any candidate-specific skill guidance that used to be
  baked into a `SKILL.md` (real lead-project ordering, real metrics, personal
  anecdotes) lives in a git-ignored `references_private/` folder inside that skill
  (e.g. `.agents/skills/resume-writer/references_private/`). Each `SKILL.md` reads it
  when present (its "Before You Start" **Personalization** stanza) and otherwise falls
  back to the generic examples. The exporter prunes these folders and the leak guard
  fails on any tracked file under one.
- **Guard tokens are config-derived.** `scripts/publish/check_public.py` hardcodes no
  identity; it derives its personal-token set from `config.yaml`, an optional
  `private/leak_tokens.txt`, and the `JOBHUNT_PERSONAL_TOKENS` env var, and scans both
  text and `.docx`/`.pdf` content.
- The public skill router `.cursor/rules/shared-skills.mdc` (tracked) lists only
  the public skills. The private `coding-interview` skill is registered by
  `.cursor/rules/private-skills.mdc`, which the overlay supplies (see the template
  at `examples/templates/private-skills.mdc`) and which is git-ignored in the
  public repo — so it is discoverable **only** when the overlay is mounted.
- `config.yaml`'s `paths.*` are resolved **relative to the config file's
  directory**, so you can point them at `private/…` (or anywhere) and swap the
  fake example candidate for your real one without editing any tooling.

## Suggested overlay layout

Keep the overlay as its own git repo (private). A clean layout that maps onto the
`config.yaml` `paths.*` keys:

```
my-jobhunt-overlay/            # private git repo (mounts at ./private/)
├── config.yaml                # your real identity + paths (copied from config.example.yaml)
├── leak_tokens.txt            # -> private/leak_tokens.txt (extra publish-guard tokens)
├── job-search/
│   └── blacklist.yaml         # -> private/job-search/blacklist.yaml (registry skip rules)
├── profile/
│   ├── profile.md             # -> paths.profile_md
│   ├── baseline.yaml          # -> paths.baseline_yaml
│   ├── company-levels.yaml    # -> paths.company_levels_yaml (optional; defaults here)
│   ├── applications-log.yaml  # auto-generated (job-search skip list)
│   └── company-search-log.yaml
├── templates/
│   └── reference.docx         # -> paths.reference_docx
├── applications/              # your real applications (-> paths.applications_root)
│   └── 1_discoveries/         # discoveries dir; keep fresh scans in current/, aged ones in archive/
│       ├── current/           # -> paths.discoveries_dir
│       └── archive/
├── interviews/                # your real interview prep
├── skills/
│   ├── coding-interview/      # the PRIVATE skill (SKILL.md + products)
│   └── references_private/    # per public skill: candidate-specific notes/examples,
│                              # symlinked/copied into .agents/skills/<skill>/references_private/
├── job-search-profiles/
│   ├── my-default.yaml        # your real search profile(s)
│   └── my-smb.yaml
└── cursor-rules/
    └── private-skills.mdc     # copied from examples/templates/private-skills.mdc
```

`private/leak_tokens.txt` is one token per line (blank / `#` lines ignored) — put
identity attributes NOT stored in `config.yaml` here (extra handles, school, GPA,
title, current/former employers, internal product and distinctive project names).
`private/job-search/blacklist.yaml` holds identity-only rows (`name` + optional
`aliases` + a `blacklist:` reason) that `registry.py` merges into the company registry
so personal skip rules never live in the public `companies.yaml`.

## Creating your overlay from scratch

You do not need to be the maintainer to have an overlay — anyone can generate
their own private data set and use the toolkit for a real hunt. From the toolkit
checkout root:

```bash
# 1. Scaffold the overlay tree (directly at the git-ignored ./private/ mount):
mkdir -p private/{profile,templates,job-search,job-search-profiles,cursor-rules,interviews}
mkdir -p private/applications/{1_discoveries/{current,archive},2_ignored,3_rejected,4_in_progress,5_applied,6_drafted}
mkdir -p private/skills

# 2. Seed the data files from the tracked fixtures, then edit them to be YOU:
cp examples/profile/profile.example.md        private/profile/profile.md
cp examples/profile/baseline.example.yaml     private/profile/baseline.yaml
cp examples/templates/reference.example.docx  private/templates/reference.docx
cp examples/templates/private-skills.mdc      private/cursor-rules/private-skills.mdc
cp .agents/skills/job-search/profiles/_TEMPLATE.yaml private/job-search-profiles/my-default.yaml

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
python scripts/bootstrap_overlay.py
```

Git does not track empty directories, so the status folders under
`applications/` materialize in a fresh clone only as the tools write into them —
that is normal. The `interviews/` and `skills/` trees are optional; leave them
empty until you have content (e.g. your own private interview-prep skill).

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
     profile_md: "private/profile/profile.md"
     baseline_yaml: "private/profile/baseline.yaml"
     company_levels_yaml: "private/profile/company-levels.yaml"
     reference_docx: "private/templates/reference.docx"
     applications_root: "private/applications"
     discoveries_dir: "private/applications/1_discoveries/current"
   job_search:
     default_profile: "my-default"
   ```

   `config.yaml` is git-ignored in the public repo, so your real identity never
   gets committed. (If you prefer, point `paths.*` at in-place folders like
   `applications/` — those are git-ignored too.)

4. **Wire the overlay + git hooks.** One idempotent, stdlib-only step creates every
   overlay symlink and installs the tracked git hooks:

   ```bash
   python scripts/bootstrap_overlay.py          # add --check to preview, make no changes
   ```

   With `private/` mounted it symlinks (skipping any that already point correctly):

   - `.agents/skills/coding-interview` → `private/skills/coding-interview` — the private skill;
   - `.cursor/rules/private-skills.mdc` → `private/cursor-rules/private-skills.mdc` — its router,
     which the overlay seeds from `examples/templates/private-skills.mdc`;
   - one link per `private/job-search-profiles/*.yaml` into
     `.agents/skills/job-search/profiles/` — then point `config.job_search.default_profile` at one.

   It **always** installs `hooks/pre-commit` and `hooks/pre-push` into `.git/hooks`
   (never clobbering a foreign hook — it warns instead), and re-running is a safe
   no-op. All of `.agents/skills/coding-interview/`, `.cursor/rules/private-skills.mdc`,
   and any personal `*.yaml` profiles are git-ignored in the public repo, so the private
   skill and your profiles stay out of public history while remaining discoverable
   whenever the overlay is mounted. (The `.agents/skills/job-search/profiles/` folder keeps
   only `example.yaml`, `_TEMPLATE.yaml`, and `README.md` public.)

**Maintainer note.** The maintainer keeps the canonical overlay as its own private
GitHub repo, mounted at `private/` exactly as above. Strangers do not need
(or get) access to it — the `<you>/<your-private-overlay>` placeholder is your own.

## How the public repo stays clean

This public repo is **canonical** — toolkit development happens here directly;
there is no export/mirror step between a maintainer checkout and what you see.
(The allowlist exporter, `scripts/publish/export_public.py`, seeded this repo's
fresh history from the maintainer's pre-split combined repo, and lives on as the
end-to-end harness for the leak-guard test suite and as a sanitized-copy tool.)

The gate is the leak guard (`scripts/publish/check_public.py`). It fails if any
private skill, `private/` path, tracked `references_private/` file, or
personal-identity token (in a path, text content, or extracted `.docx`/`.pdf`
content) is tracked. Its tokens are derived at runtime from `config.yaml` +
`private/leak_tokens.txt` + `JOBHUNT_PERSONAL_TOKENS` (nothing hardcoded), so
with your overlay mounted it screens for **your** identity. It runs three times
over: blocking in CI, in the pre-push hook before anything reaches a public
remote, and by hand any time:

```bash
.venv/bin/python scripts/publish/check_public.py
```

The steady state is **zero findings**; any finding is a regression to fix, never
to except.
