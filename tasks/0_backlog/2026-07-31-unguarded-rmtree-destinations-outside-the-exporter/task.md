# The other rmtree call sites still take a caller-supplied root with no destination guard

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: session 2026-07-31, filed alongside the `export_public.py --force` destination guard (audit finding 6); the adversarial audit's coverage section flags `build_postings.py` as never reviewed
- **Claimed-by**:

## Goal

Give every remaining `shutil.rmtree` whose target comes from a caller/CLI argument the same
"where may this delete?" rule the exporter now has, or record why each one does not need it.

## Context

`automation/publish/export_public.py` used to `rmtree` whatever `--dest` named as long as it was
not the checkout root or an ancestor, so `--dest private --force` would have deleted the mounted
private overlay. That is fixed: `forbidden_destination()` (blocklist — the checkout, anything
inside it, the private overlay and configured owner-data roots, `$HOME`, another git checkout)
plus `overwrite_refusal()` (allowlist — `--force` deletes only an empty directory or one carrying
`.jobhunt-export-marker`). Tests: `automation/publish/tests/test_export_destination.py`.

The same shape exists elsewhere and was NOT touched:

- `automation/store/generate_fixture_store.py:217` — `generate(root)` does
  `if root.exists(): shutil.rmtree(root)` on whatever path the caller passes, with no guard at
  all. It is a developer tool, but a mistyped `--root` deletes that directory outright, and
  AGENTS.md puts store payloads in the never-delete-by-agent set.
- `skills/job-search/scripts/build_postings.py:1097,1122,1171,1176` — four calls around the
  snapshot swap. The audit **excluded this file** (it was being edited) and explicitly says the
  swap was not reviewed. Someone should read the swap end to end and decide whether a crash
  between the renames can leave the real snapshot deleted.
- `automation/shared/store/retention.py:634` — already carries a belt-and-braces guard
  (`never state/, never _blobs/`) and deletes only planned debris; likely fine, worth confirming
  the plan's paths cannot escape the domain layout.
- `skills/resume-writer/scripts/pdf_convert.py:95,147` — a private LibreOffice profile dir this
  process created; almost certainly fine, confirm and move on.

The exporter's rule is deliberately not shared code: it knows about `--dest`, the overlay, and an
export marker, none of which the store tools have. What should be shared is the *decision* — a
caller-supplied deletion target is either an allowlisted shape or a refusal that names the rule.

**Verify-with**:

```bash
grep -rn "shutil.rmtree" --include='*.py' automation skills | grep -v _vendor/
```

## Definition of done

- [ ] `generate_fixture_store.generate()` refuses a root that is the checkout, inside it, the
      private overlay, `$HOME`, or a non-empty directory it did not create — with a message that
      names the path and the rule
- [ ] The `build_postings.py` snapshot swap is read end to end and either guarded or documented as
      safe (with the crash-window argument written down)
- [ ] `retention.py` and `pdf_convert.py` are confirmed and recorded as needing no change
- [ ] A test per changed call site proves the refusal (exit code + message) and that a legitimate
      target still works
</content>
