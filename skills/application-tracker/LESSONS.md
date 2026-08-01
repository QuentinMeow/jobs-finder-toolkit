# Lessons — Application Tracker

Curated operational lessons from real usage. The `meta.yaml` schema itself lives in SKILL.md.

Last reviewed: 2026-07-19

Lifecycle tags: each `##` section carries `<!-- added: <first-seen> · last_confirmed: <date> · status: active -->`
(gardener `lessons_report` parses these; `added` = the section's first git appearance, `last_confirmed` = last review date).

## Status Management
<!-- added: 2026-04-16 · last_confirmed: 2026-07-19 · status: active -->
- Each `jobs:` entry has a per-job `status` (`drafted` / `applied` / `in_progress` / `rejected` /
  `ignored`); the folder is the DERIVED overall status, rolled up by precedence
  `in_progress > applied > drafted > rejected > ignored`. Change status only on explicit request —
  `status.py --update <slug> <status>` (whole app: stamps every job + moves the folder) or
  `--update-job <slug> <role-match> <status>` (one posting: recomputes the rollup + moves if it
  changed). A hand-moved folder must be re-synced via `--update`, else `--check-metadata` flags the
  folder↔rollup mismatch. Move promptly (a stale folder makes pipeline reviews useless).

## Metadata
<!-- added: 2026-04-16 · last_confirmed: 2026-07-19 · status: active -->
- Always record `channel` (referral/cold/recruiter/linkedin) — it predicts conversion rates;
  `next_action` with a date keeps momentum (review weekly).
- Job facts are per posting and live inside each `jobs:` entry: `job_level` (incl. approximate
  float-bounded Google equivalent), `required_yoe`, and `salary_range` — schema **v5** (per-job
  `status` + structured `progress`; no `total_compensation_range`, no `stage`). Live JD values win;
  the dated, sourced company-level cache (`config.company_levels_path()`, its own schema-v2 file —
  the company-levels cache format, a different file from `meta.yaml`, whose only supported schema
  is v5) is level/YOE fallback only.
- Never round-trip application `meta.yaml` through `safe_dump`. Use the node-anchored metadata
  editor/backfill so comments, quoting, blank lines, and CRLF survive; multi-role enrichment
  requires an exact `jd_file` for each job.

## Process
<!-- added: 2026-04-16 · last_confirmed: 2026-07-19 · status: active -->
- Referrals convert significantly better than cold applications — track and optimize for this.
- Follow up ~1 week after applying if no response; save recruiter contact info early (needed
  at the negotiation stage).

## Layout & application log
<!-- added: 2026-04-16 · last_confirmed: 2026-07-19 · status: active -->
- Each folder keeps only the final PDFs, the bundled `..._Application_<job title>.txt`,
  `meta.yaml`, and optional `notes.md` at its root; JD files (`source/JD-<job title>.md`),
  `tailored.yaml`, and the DOCX live in `source/`. `status.py`'s files column shows
  `docx+pdf+cl+txt` (txt = the bundled application file).
- The applications skip-log (`config.applications_jsonl_path()`) is **append-only** —
  `--update`/`--update-job` record the event as it happens and `--sync-log` is the backstop.
  Nothing rewrites it, so deleting an application no longer un-skips its posting; a wrong row
  is repaired by appending a tombstone (`--forget-log`), never by editing the file. The blacklist of
  employers job-search must never surface is the MERGED registry, not `companies.yaml` alone:
  `registry.load_registry()` merges the public `skills/job-search/companies.yaml` with the
  git-ignored overlay at `config.blacklist_path()` (`private/market/blacklist.yaml`) at load time.
  Every `blacklist:` reason lives in that overlay — the public registry ships none, and writing one
  there would publish a personal skip rule (the reconciler's `public-registry-blacklist` check
  fails the commit).
