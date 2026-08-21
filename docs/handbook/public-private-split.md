# Public vs Private (full detail)

Expands `AGENTS.md` → "Public vs Private". The toolkit is layered as two
repos so timeless tooling can be published while everything tied to a real
person or a real job hunt stays private:

- **Public toolkit repo (this repo)** — public-ready: ships only timeless, general
  information — the tooling (`automation/`, public skills + their scripts), the company registry
  `skills/job-search/companies.yaml` (**identity only** — never specific or dated
  postings), a FAKE example candidate under `examples/` (`examples/me/…`,
  `examples/market/…`), and general instructions/techniques.
  `config.example.yaml` is the tracked placeholder.
- **Private overlay repo** — its **own git repo** synced to a private GitHub remote, mounted
  at a git-ignored **`private/`** directory inside the public checkout. `config.yaml`
  (git-ignored) points the toolkit's `paths.*` into it — real
  identity, profile, baseline, reference DOCX, applications, interviews, and any
  overlay-only skills all live under `private/`. See `docs/handbook/private-overlay.md`.

**Skill visibility** is declared by a `visibility: public|private` key in each `SKILL.md`
frontmatter:

- **PUBLIC skills** (SKILL.md + scripts are published; their generated PRODUCTS stay private):
  `ask-me-anything`, `job-search`, `resume-writer`, `application-tracker`,
  `behavioral-interview-prep`, `company-research`, `email-assistant`, `interview-calendar`, `gardener`,
  `search-recall-audit`, `github-workflow`.
- **PRIVATE skills** are intentionally not named in this repository. Each entire
  skill (SKILL.md + scripts/assets/evals and products) lives only in the private
  overlay and never ships in the public repo.

**PRODUCTS are always private** and mount under `private/`: anything tied to real jobs, the
candidate's background, or dated/time-sensitive info — the real applications
(`config.applications_root()`, e.g. `private/me/applications/**`), the real interview material
(`private/me/interviews/companies/**` for everything tied to one employer — research, their
loop, and the problems they ask — plus the role-agnostic story/question banks), and the real
profile / baseline / reference DOCX. The overlay is git-ignored in the public checkout and the
exporter excludes it; only fake `examples/**` counterparts are published.

**Personal skill content stays out of `SKILL.md`.** The tracked `SKILL.md` / `LESSONS.md`
of a PUBLIC skill must be personal-free: they defer candidate DATA to `config.yaml` /
the profile and use the generic "Jordan Rivers" examples. Any residual candidate-specific
skill guidance (real lead-project ordering, real metrics, personal anecdotes) goes in the
overlay's per-skill **skill-notes** folder, reached by
`config.skill_references_dir("<skill>")` (`private/skills/skill-notes/<skill>/` under the
current overlay layout; set `paths.skill_references_root`) — the exporter prunes any such
folder and the leak guard fails on any tracked file under a `skill-notes/` folder —
or under its retired name `references_private/`, which stays denied — anywhere in the
public tree. Each `SKILL.md`
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

**When your own name blocks the guard.** Matching is hybrid. A bare word — a name part,
a one-word employer — hits only at a word, identifier or case-hump **edge**, so `making`
does not flag a three-letter surname buried in it. High-specificity tokens (the email
address, the linkedin/github handles, the home-directory basename, and the name
*compounds* the guard derives — `jordanrivers`, `jrivers`, `jordan-rivers`) keep plain
containment, which is what still catches `linkedin.com/in/jordanrivers`.

Edges cannot help a name that **is** an ordinary word — a colour, a length, a place name.
Nothing distinguishes a town from a person there, so the repo's own timeless prose flags
as a leak. For that, and only that, the owner may declare the word in the git-ignored
`config.yaml`:

```yaml
leak_guard:
  english_word_tokens: ["<word>"]      # or $JOBHUNT_LEAK_GUARD_WORD_TOKENS for CI
```

It is **opt-in** (never inferred from a dictionary, never written by an agent, never
tracked), **narrow** (it reaches boundary-matched tokens only — the address, the handles,
the home basename and every full-name compound keep full containment, so the whole name
written any way at all is still caught), **loud** (every run prints the word and the
number of occurrences it skipped, clean or failing), and **still arming** (the token
still counts, so declaring one can never drop the guard into its unarmed exit-2 state).
The guard names this mechanism in its own check-6 output whenever a boundary token is
what blocked you.

The alternative an operator reaches for instead — deleting the identity out of
`config.yaml` — is the one thing to never do: a guard with zero identity tokens is the
state in which a tree full of the owner's real name reports "Safe to publish".

**Routing**: skills are discovered by listing `skills/` — which is now ENTIRELY public;
the skills table in `docs/handbook/repo-map.md` names exactly what ships. A private skill lives
only at `private/skills/<name>/` and reaches the runtime through a git-ignored entry in
each runtime's `<host>/skills/<name>` adapter tree that
`automation/bootstrap_overlay.py` creates, pointing straight at the overlay. The
exact adapter paths are stored only in repository-local Git metadata. The skill
therefore stays discoverable whenever the overlay is mounted without its name
appearing in the tracked public tree. `automation/publish/sync_skill_manifests.py`
owns the public entries in those same host directories and tells the two apart by
where a link points, never by its name.
