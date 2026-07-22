# Configuration (full detail)

Expands `AGENTS.md` → "Configuration". Candidate identity, paths, and output
filename stems are never hardcoded — they come from a config file loaded by
`scripts/shared/config.py` (vendored into each consuming skill's
`scripts/_vendor/config.py`):

- `config.yaml` (git-ignored) holds the real values. `config.example.yaml` (tracked) is a
  neutral **"Jordan Rivers"** placeholder that doubles as the fallback when no `config.yaml`
  is found. Discovery order: `$JOBHUNT_CONFIG` → nearest `config.yaml` walking up from cwd
  then from the loader's directory → `config.example.yaml`. Paths in the config are resolved
  relative to the config file's directory.
- **Paths** come from config, not literals — always accessed via the `config.py` functions:
  the candidate profile is `config.profile_md_path()` (example:
  `examples/profile/profile.example.md`), the baseline is `config.baseline_path()`, the
  rendering reference DOCX is `config.reference_docx_path()`, the reusable sourced company
  leveling/compensation cache is `config.company_levels_path()` (default: beside the profile;
  compensation bands are age-gated while level/YOE mappings retain provenance), the
  applications root is `config.applications_root()` (`applications/` by default), and the
  discoveries dir is `config.discoveries_dir()`. Real data mounts under `private/` and the
  public example under `examples/`; the function always returns the configured absolute path.
- **Output filename stems** come from `config.resume_stem()` / `config.cover_stem()` /
  `config.application_stem()` — each built from `name_slug` + `title_slug` (plus an optional
  target-position label via `layout.compose_stem`). Never hardcode a concrete person's filename
  stem anywhere; refer to `<RESUME_STEM>` / "the configured stem". With the example config the
  resume stem is `Jordan_Rivers_Software_Engineer_Resume`.
