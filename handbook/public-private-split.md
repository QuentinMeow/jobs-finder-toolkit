# Public vs Private (full detail)

Expands `AGENTS.md` → "Public vs Private". The toolkit is layered as two
repos so timeless tooling can be published while everything tied to a real
person or a real job hunt stays private:

- **Public toolkit repo (this repo)** — public-ready: ships only timeless, general
  information — the tooling (`scripts/`, public skills + their scripts), the company registry
  `skills/job-search/companies.yaml` (**identity only** — never specific or dated
  postings), a FAKE example candidate under `examples/` (`examples/profile/…`,
  `examples/templates/…`, `examples/applications/…`), and general instructions/techniques.
  `config.example.yaml` is the tracked placeholder.
- **Private overlay repo** — its **own git repo** synced to a private GitHub remote, mounted
  at a git-ignored **`private/`** directory inside the public checkout. `config.yaml`
  (git-ignored) points the toolkit's `paths.*` into it — real
  identity, profile, baseline, reference DOCX, applications, interviews, and the private
  `coding-interview` skill all live under `private/`. See `handbook/private-overlay.md`.

**Skill visibility** is declared by a `visibility: public|private` key in each `SKILL.md`
frontmatter:

- **PUBLIC skills** (SKILL.md + scripts are published; their generated PRODUCTS stay private):
  `ask-me-anything`, `job-search`, `resume-writer`, `application-tracker`,
  `behavioral-interview-prep`, `company-research`, `email-assistant`, `interview-calendar`, `gardener`,
  `search-recall-audit`, `github-workflow`.
- **PRIVATE skills**: `coding-interview` and `coding-interview-cleanup` — both ENTIRE skills
  (SKILL.md + scripts/assets/evals and products) live only in the private overlay and never ship
  in the public repo.

**PRODUCTS are always private** and mount under `private/`: anything tied to real jobs, the
candidate's background, or dated/time-sensitive info — the real applications
(`config.applications_root()`, e.g. `private/applications/**`, including the discoveries dir
and the real company-level cache), the real interviews (`private/interviews/**` — every real
interview product, from company-info to behavioral/coding prep, belongs here), and the real
profile / baseline / reference DOCX. The overlay is git-ignored in the public checkout and the
exporter excludes it; only fake `examples/**` counterparts are published.

**Personal skill content stays out of `SKILL.md`.** The tracked `SKILL.md` / `LESSONS.md`
of a PUBLIC skill must be personal-free: they defer candidate DATA to `config.yaml` /
the profile and use the generic "Jordan Rivers" examples. Any residual candidate-specific
skill guidance (real lead-project ordering, real metrics, personal anecdotes) goes in the
overlay's per-skill **`references_private/`** folder, reached by
`config.skill_references_dir("<skill>")` (default
`private/skills/references_private/<skill>/`) — the exporter prunes any such folder and
the leak guard fails on any tracked file under one, anywhere in the tree. Each `SKILL.md`
"Before You Start" carries a **Personalization** stanza telling the agent to read that
folder (it overrides the generic examples) when present, and to fall back to the generic
examples otherwise.

**The publish leak guard derives its tokens** (`automation/publish/check_public.py` →
`personal_tokens()`) from the git-ignored `config.yaml` identity, an optional git-ignored
`private/leak_tokens.txt`, and the `JOBHUNT_PERSONAL_TOKENS` env var — it hardcodes NO
real identity and scans both text and document-binary (`.docx`/`.pdf`) content. The
identity-derived half (`identity_tokens()` — a real config plus the env var) is tracked
separately and **arms** the guard: with zero identity tokens it exits 2 rather than
passing, since `leak_tokens.txt` alone keeps the union non-empty while the name, email
and handles are absent. The exporter (`export_public.py`) always runs it against the
copied tree as the final gate.

**Routing**: skills are discovered by listing `skills/` — which is now ENTIRELY public;
the skills table in `handbook/repo-map.md` names exactly what ships. A private skill lives
only at `private/skills/<name>/` and reaches the runtime through a git-ignored entry in
`.claude/skills/<name>` + `.cursor/skills/<name>` that `automation/bootstrap_overlay.py`
creates, pointing straight at the overlay. So it stays discoverable whenever the overlay is
mounted, without any private path ever wearing a public name (workspace-restructure phase 4,
2026-07-28: all eight inbound symlinks deleted). `automation/publish/sync_skill_manifests.py`
owns the public entries in those same host directories and tells the two apart by where a
link points, never by its name.
