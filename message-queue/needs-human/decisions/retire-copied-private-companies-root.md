# May the retired private company root be deleted after its ignored files were copied?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-07
- **Source**: [Person-first private-overlay task](../../../tasks/4_done/2026-08-06-private-overlay-personal-taxonomy/task.md)
- **Blocks**: only removal of the now-redundant ignored files from the retired private company root
- **Default path**: keep the retired root in place and use only `private/me/interviews/companies/` for future work
- **Cost if wrong**: data
- **Safe to merge because**: the default deletes nothing; all ignored source files were copied with `rsync --ignore-existing` and a checksum dry run now reports no content differences

## Background

Git moved every tracked company-interview file into the person-first tree, but ignored files cannot
participate in a Git rename. The retired `private/companies/` root retained 21 ignored files (about
46 MiB): original screenshot backups, their checksum manifests, and generated Python bytecode.

The reconciliation copied those files without overwriting anything into the corresponding paths
under `private/me/interviews/companies/`. A checksum-enabled `rsync` dry run after the copy produced
no output, which means each source file has identical content at the destination. The old copies
remain because agents do not delete owner data, including during migrations.

## Options

This trades a tidier single-root layout against keeping an extra recovery copy.

### Option A — Delete the retired root

After inspecting the destination if desired, the owner removes `private/companies/`. Future tooling
already resolves only the new person-first location.

***Example consequence:*** File browsing shows only `private/me/interviews/companies/`, and roughly
46 MiB of duplicate local data is reclaimed.

### Option B — Keep the recovery copy

Leave the retired root untouched. It remains ignored by Git and unused by configured tooling, but it
can confuse manual browsing and occupies duplicate disk space.

***Example consequence:*** Both the retired and current company trees remain visible locally even
though only the current tree receives future updates.

## Recommendation

Choose Option A after a quick manual spot-check. The checksum comparison proves the destination
contains the same ignored bytes, and retaining a second inactive tree makes future path mistakes
more likely.

**Strongest case against this:** The old root is a cheap extra recovery copy of original screenshots,
and keeping it avoids relying on one local copy even though the repository itself does not track them.

**Confidence:** high — every ignored source file was included in the checksum-enabled comparison;
the source was not deleted and no destination file was overwritten.

Say whether to delete the retired `private/companies/` root or keep it as a local recovery copy.

**Your answer:** ______
