---
name: coding-interview-cleanup
visibility: public
description: Back up, deduplicate, crop, rename, and organize coding-interview screenshots and problem folders, then create or improve a coaching README that reconstructs the full question, required functions, solution approach, examples, pseudocode, complexity, and likely follow-up questions. Use when screenshots or interview-practice folders are messy, use temporary level-based names, contain duplicate or intermediate captures, need prompt-only or starter-code crops, lack an understandable problem guide, or need another cleanup pass after a partially completed earlier run.
---

# Coding Interview Cleanup

Turn raw interview captures and a partially organized problem folder into a stable, recoverable study package. Preserve exact prompt evidence while making the active files concise, purpose-specific, and useful for interview coaching.

## Non-negotiable outcomes

- Preserve every unique source image byte-for-byte in `originals_backup/` before renaming, cropping, moving, or deleting a working copy.
- Use a stable problem slug based on the complete question, never the currently unlocked stage. Rename `in_memory_database_level_1` to `in_memory_database` once the full problem is known.
- Keep each active image for one purpose only. Separate question descriptions from optional code setup.
- Deduplicate by both hash and visible meaning. Two different photos of the same prompt region are semantic duplicates.
- Crop from an untouched backup, never from an earlier crop.
- Preserve screenshot text exactly. Do not regenerate, retype, beautify, perspective-correct, or hallucinate prompt text.
- Create or update a human-readable `README.md` that teaches the full problem and answers realistic follow-ups.
- Make repeated invocations safe: continue the current state, retain correct prior work, and add or replace only what new evidence requires.

## 1. Resume the current cleanup state

Inspect, in this order:

1. `private/interviews/company-specific/TODO/` for newly arrived images.
2. The target problem folder, including loose images, `README.md`, `question_description/`, `code_setup/`, and `originals_backup/`.
3. Existing solution files and any nearby handover that names the folder.

Group images by problem before acting. Do not merge unrelated questions because they share a company or interview session.

Treat an existing organized folder as a continuation, not a fresh run:

- Keep verified backups and curated images.
- Reuse the established stable slug unless the reconstructed question proves it wrong.
- Update the README in place; preserve accurate explanations and any user-written notes.
- Compare new images by hash and visible content before adding anything.
- Do not recreate a crop that already covers the same region clearly.

## 2. Back up before editing

Run the deterministic helper before modifying images:

```bash
python <skill-dir>/scripts/cleanup_images.py backup <problem-dir>
```

Use `--input-dir <dir>` for source images outside the problem root, such as the TODO inbox. The helper copies unique images, verifies each copy, avoids hash duplicates, never overwrites different content, and refreshes `originals_backup/SHA256SUMS.txt`.

After the helper succeeds:

- Confirm the backup count and checksums.
- Rename backup files descriptively when useful, retaining the original capture ID at the end.
- Refresh the checksum manifest after any backup rename by running the backup command again.
- Never delete, crop, recompress, or overwrite a backup image.

If the source images are already backed up and there are no new loose images, treat the backup step as a verified no-op.

## 3. Reconstruct and name the complete problem

Read prompt-bearing regions in capture order. Extract the title, stages, required signatures, constraints, examples, and visible starter code.

Choose a readable snake-case problem slug that describes the complete task:

- Good: `in_memory_database`, `multithreaded_web_crawler`, `integer_container`.
- Bad: `level_1`, `question_2`, `todo`, `latest`.

When renaming an existing problem:

1. Rename the problem directory.
2. Rename a same-stem solution file to the stable slug.
3. Update README links, manifests, handovers, and direct references.
4. Verify that the old directory no longer exists and no second copy was created.

Do not rename function signatures supplied by the platform.

## 4. Build the curated image set

Create these folders only when they have content:

```text
<problem>/
├── question_description/
├── code_setup/
└── originals_backup/
```

### Question descriptions

Crop exact pixels around only the useful prompt content:

- overview and global constraints;
- required operations or tasks;
- trusted examples and expected results;
- stage-specific requirements that add new behavior.

Use numeric reading-order prefixes and semantic names:

```text
00_problem_overview_and_constraints.jpg
01_basic_operations_and_example.jpg
02_filtered_scans_and_example.jpg
03_ttl_operations.jpg
04_ttl_example.jpg
05_historical_lookup_and_example.jpg
```

Split a stage into operations and example only when one image would be crowded or unreadable. Avoid repeated headers or overlapping paragraphs across adjacent crops when a tighter crop can remove them.

### Code setup

Keep only initial scaffolds that help reconstruct the task:

- required class or function signature;
- supplied models or interfaces;
- imports or restrictions;
- pre-follow-up implementation state when it materially explains what the next stage builds on.

Do not retain every debugging scroll position or final implementation screenshot in the active set. Those belong only in the backup unless a specific failure is part of the question.

### Visual QA

Use the available image-viewing tool to inspect every original and every final crop. Follow runtime image-editing policy, but require pixel-faithful evidence. Reject any generative edit that redraws or changes prompt text; use deterministic crop-only processing when permitted.

Before removing loose working copies, verify:

- every unique source is in the backup;
- every active image has one stated purpose;
- no active hashes duplicate;
- no active images are semantic duplicates;
- all prompt text remains legible and uncropped.

Remove redundant loose copies only after those checks. State that removal is recoverable from the backup.

## 5. Write the coaching README

Copy the structure from `assets/problem-readme-template.md` and replace every placeholder. The README must stand alone for someone who has not seen the screenshots.

Include:

1. A plain-English problem summary and the stable problem name.
2. A requirements table listing every required function/task, parameters, return value, and behavior.
3. The core data model and important invariants.
4. A high-level solution that explains data flow and why the design fits later follow-ups.
5. Two or more step-by-step examples using trusted screenshot examples where available.
6. Language-neutral pseudocode for each major operation family.
7. Time and space complexity, including the historical or concurrency tradeoff when relevant.
8. Common pitfalls and exact boundary rules.
9. Likely interviewer follow-up questions with direct, technically grounded answers.
10. A file map and backup recovery note.

Coach rather than merely restate:

- Explain what to say before coding.
- Show how later stages extend earlier state without breaking previous behavior.
- Connect each data structure to the operation it makes efficient.
- Distinguish source-backed facts from inferred design advice.
- Keep examples concrete enough to simulate by hand.

Do not claim an optimization, complexity, or behavior that the visible contract or implementation does not support.

## 6. Validate the finished package

Run:

```bash
python <skill-dir>/scripts/cleanup_images.py audit <problem-dir>
```

The audit must pass:

- backup checksums;
- no duplicate backup content;
- no duplicate active hashes;
- no loose root images;
- stable non-level-based problem naming;
- README, question-description images, and optional code setup.

Then visually review the curated images once more and run any repository reconciliation required by the workspace.

Report the stable problem path, curated image count, backup count, README coverage, and verification result. Do not foreground intermediate tooling.

## Resources

- `scripts/cleanup_images.py`: idempotent backup and structural audit helper.
- `assets/problem-readme-template.md`: required coaching README structure.
