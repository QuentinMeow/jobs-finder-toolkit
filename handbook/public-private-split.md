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
  `behavioral-interview-prep`, `company-research`, `email-assistant`, `gardener`.
- **PRIVATE skill**: `coding-interview` — the ENTIRE skill (SKILL.md + product) lives only in
  the private overlay and never ships in the public repo.

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
skill guidance (real lead-project ordering, real metrics, personal anecdotes) goes in a
git-ignored, per-skill **`references_private/`** folder — the exporter prunes it, the leak
guard fails on any tracked file under it, and `.gitignore` ignores it. Each `SKILL.md`
"Before You Start" carries a **Personalization** stanza telling the agent to read
`references_private/` (overrides the generic examples) when present, and to fall back to
the generic examples otherwise.

**The publish leak guard derives its tokens** (`automation/publish/check_public.py` →
`personal_tokens()`) from the git-ignored `config.yaml` identity, an optional git-ignored
`private/leak_tokens.txt`, and the `JOBHUNT_PERSONAL_TOKENS` env var — it hardcodes NO
real identity and scans both text and document-binary (`.docx`/`.pdf`) content. The
exporter (`export_public.py`) always runs it against the copied tree as the final gate.

**Routing**: skills are discovered by listing `skills/` — the skills table in
`handbook/repo-map.md` names only the PUBLIC ones that ship in the repo. The private
`coding-interview` skill appears in `skills/` via a git-ignored symlink that
`automation/bootstrap_overlay.py` creates, so it stays discoverable whenever the overlay is
mounted.
