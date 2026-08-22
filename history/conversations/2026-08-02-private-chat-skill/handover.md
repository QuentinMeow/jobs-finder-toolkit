# Handover — private-chat-skill

- **Date**: 2026-08-02
- **Task(s)**: none

## What happened

- Nothing is in flight or blocked.
- A private chat-only skill now returns the shortest sufficient answer for general problems from chat, attachments, or the shared screenshot inbox; before this, only the coding-specific workflow covered that inbox.
- A follow-up now routes the screenshots used for that answer into company-scoped, one-problem-per-folder storage only after the answer is visible; before it, screenshots stayed in the inbox.
- Runtime adapters now expose the skill to Codex, Claude, and Cursor.

## Where things stand

- The private skill and its post-chat routing follow-up are committed on the overlay's local `main`; this handover records the matching public-toolkit session.
- The new private skill has no canary set, so the eval gate was skipped with this recorded rationale; static frontmatter, metadata, discovery, and repository checks are the verification path.

## Decisions made for you

- The skill checks a complete chat prompt before attachments and TODO, then reads newest evidence first; this minimizes latency and is cheap to reverse in one instruction file.
- The skill still creates no answer, note, code, test, or summary files; screenshot movement is the only durable post-chat action, matching the owner's follow-up and remaining cheap to reverse in two instruction files.
- Newly routed screenshots use one folder per distinct question under the resolved company, while unrelated inbox images and existing company material remain untouched; changing the new-content layout later is a local move rather than a migration of old material.
- The generic skill validator is not the verdict because it rejects this repository's required `visibility: private` extension; repository-native YAML and runtime checks remain authoritative.

## If X then Y

- If two plausible readings would change the answer, the skill asks one narrow question instead of guessing.
- If current, high-stakes, or explicitly requested evidence requires a lookup, the skill makes the minimum targeted call and answers immediately afterward.
- If one screenshot contains several independent questions, the unchanged image is preserved in each question folder and verified by hash before the inbox original moves.

## Dead ends

- The generic validator accepted the generated structure but rejected the required custom `visibility` key; this is the repository's documented validator incompatibility, not malformed skill metadata.
- The first runtime-bootstrap pass could not update repository-local Git metadata inside the sandbox; the approved rerun registered all three runtime links successfully.
- The public leak guard rejected the first handover draft because it named an overlay-only skill; this generic handover preserves the session record without leaking the private skill name.

## Needs your attention

- Nothing from this task. Existing queues remain unchanged.
- 42 pending · top: [job-search-us-only-default-asymmetry](../../../message-queue/needs-human/decisions/job-search-us-only-default-asymmetry.md) — inconsistent search and draft defaults can repeatedly admit roles that later cannot be drafted.
