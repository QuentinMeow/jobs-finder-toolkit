# Raw data layer — filesystem-as-database for every internet-facing fetch

**Status:** accepted and partially implemented. Jobs-store stages 0–4
shipped in PRs #49–#53; the email track is the remaining major stage.
Every design decision is resolved, including the follow-up jobs-derived and
email git policies. See [the current implementation map](#implementation-state).
Produced by: web research pass → first draft → five independent design
reviews (three angle reviews, two adversarial) → owner answers → this
regeneration. Remaining implementation tasks live in `tasks/0_backlog/`. All docs follow
the writing rules in [docs/design/STYLE.md](../STYLE.md): every section
self-contained, every reference clickable, every concept diagram in both
Mermaid and plain-text form, every decision a self-contained block.

## Problem (why this family of designs exists)

Every internet-facing skill treats fetched data as disposable. The only
cache (`tmp/search_cache/` snapshots) is deliberately a within-session
artifact with a 6-hour lifetime. Three costs follow:

1. **No memory.** A posting rejected last week returns every run; a mailbox
   review re-reads and re-classifies the same messages; nothing can be
   filtered by code against stored metadata when a new need appears.
2. **No bug recovery.** When a classifier is wrong (the known visa
   false-negative bug; the unreliable scraper remote-flag), everything it
   mislabeled is gone — fixed code can never re-run over what we saw.
3. **No timeline.** "What's new since Tuesday", "what did this company post
   this month", "which rejection email closed this application" are
   unanswerable.

**Honesty note from the token-economics review:** the earlier token-usage
program already banked the big single-session token savings. On the
job-search path this layer is roughly **token-neutral** (the arithmetic is
in [the job-postings doc](02-job-postings-pipeline.md#9-honest-token-accounting));
its justification there is bug recovery, durable memory, and code-based
filtering. The genuinely large token savings live in the **email** half
(mailbox re-reads become local queries), which this store core unlocks.

## Design stance

> **We definitely have bugs. The design must make bugs cheap:** keep the raw
> data, make everything else deterministically re-derivable from it, and a
> bug becomes "fix code, rebuild" instead of "data lost".

The principles every document shares:

- **Raw is sacred; derived is disposable.** The raw zone is append-only and
  immutable; everything else can be deleted and rebuilt from it by
  deterministic code.
- **The filesystem is the database.** Partitioned directories, one-line-per-
  record JSONL, per-entity YAML, manifests. A person can `ls` and `cat`
  their way to any answer.
- **Append, never mutate.** History is an event log; "current state" files
  are rebuilt projections, never hand-edited.
- **Versioning is built in; breaking changes rebuild instead of migrate.**
  Matches this repo's no-backward-compatibility stance — and is only
  possible because raw is kept.
- **Facts, opinions, and judgments live in separate channels.** What the
  source said; what our code concluded (stamped with the code version); what
  a human verified (protected from rebuilds).
- **Code filters; AI reads only deltas.** Compact indexes make routine
  questions one script call; AI attention is spent on new information only.
- **All real data lives in the private overlay**, and identifiers in paths
  and manifests are neutral slugs — no real name or address anywhere.
- **The store never blocks and never vouches.** Store failures degrade to
  cold behavior; acting on anything still requires fresh fetches and the
  same verification gates as today. Memory is not freshness.
- **Claims are bounded, not aspirational.** Capture scope, retention's limit
  on rebuildability, lifecycle preconditions, and privacy exposure are
  stated as contracts with limits.

## The documents

| Doc | What it covers | Post-review verdict |
|-----|----------------|---------------------|
| [01 — Store core](01-store-core.md) | The generic contract: five zones, write discipline, the determinism contract, identity pinning, retention with reference counting, agent ergonomics, content-egress rules | **Implemented for jobs.** Shared store and retention shipped; the email domain will reuse it |
| [02 — Job postings](02-job-postings-pipeline.md) | Capture, stable posting identity, gap-tolerant observation history, code-only queries, JD reuse, application linkage, and the suppressed-row review queue | **Implemented.** Stages 1–3 shipped; the multi-day capture measurement and O(new) optimization remain follow-ups |
| [03 — Provider interfaces](03-provider-interfaces.md) | One abstract mail contract; isolated Outlook/Gmail implementations; conformance testing; Gmail read-only by default | **Accepted, not implemented.** This is the first remaining email implementation slice |
| [04 — Email download & categorization](04-email-download-categorization.md) | Incremental mail sync, categorization, guarded application linkage, and triage | **Accepted, not implemented.** Git policy is resolved |
| [Application progress and calendar](../application-progress-calendar/README.md) | Structured hiring phases, booking/waiting/scheduled/reschedule states, and one private calendar todo file | **Designed, not implemented.** Required before email-driven scheduling reconciliation |
| [Execution plan](execution-plan.md) | Staged delivery with acceptance gates | Jobs stages 0–4 shipped; remaining email work is split into focused tasks |

Suggested cold-read order: this page → each doc's "For the human reviewer"
section (~5 minutes each) → the compact decision tables and linked records.

## What it will look like (one picture)

```
private/data/                        # config.data_root() — never in the public repo
├── jobs/
│   ├── raw/greenhouse/2026/07/21/<fetch_id>/manifest.json → _blobs/<sha>.json.zst
│   ├── derived/postings/examplecorp/gh-1234567/{posting.yaml, jd.md, events.jsonl}
│   ├── index/{postings.jsonl, by-day/…}
│   ├── annotations/gh-1234567.yaml        # human-verified facts — survive every rebuild
│   └── state/{cursors/, build-ledger.jsonl, key-registry.yaml, frozen-facts/}
└── email/                                 # same pattern, partitioned per account,
    └── …                                  #   stricter git policy (see the email doc)
```

Every example in this family uses the fictional Jordan-Rivers universe
(`examplecorp`, `profile-01`, `acct-01`) — and the *real* store also uses
neutral slugs in paths and manifests, so nothing identifying ever appears in
a path, manifest, or query output.

## Implementation state

| Stage | State | Evidence / remaining work |
| --- | --- | --- |
| 0 — store library | Shipped | PR #49 |
| 1 — jobs capture | Shipped; measurement open | PR #50; multi-day growth/overhead/dedup soak remains |
| 2 — builder and queries | Shipped | PR #51 |
| 3 — pipeline integration | Shipped | PR #52; O(new) incremental-build optimization remains queued |
| 4 — retention and gardener | Shipped | PR #53 |
| 5 — email | Planned | Provider contract, tracker/calendar foundation, sync, categorization, reconciliation, and cutover |

## Decisions: all resolved

The owner answered the full decision set on 2026-07-21. The authoritative
ADR record is
[memory/decisions/raw-data-layer-decisions.md](../../../memory/decisions/raw-data-layer-decisions.md);
each design doc carries a "Decisions (resolved)" table showing where every
answer landed in its text.

The owner resolved the two follow-up git-policy questions on 2026-07-22:

- The jobs store does not track `derived/`; it remains rebuildable and is
  too large and churn-heavy for git. `index/`, `annotations/`, and `state/`
  remain tracked. See
  [the decision record](../../../memory/decisions/derived-zone-git-tracking.md).
- The email store tracks only content-free index headers and safe
  annotations. Raw, derived, message rows, and quoted evidence remain out
  of git. See
  [the decision record](../../../memory/decisions/email-git-policy.md).

**Answers that changed the design** (beyond accepting recommendations):

- Multi-laptop reality: everything tolerates locally missing raw
  (`not-synced-here` is a normal state) — new store-wide rule in
  [the store core](01-store-core.md#1-zones-and-their-contracts).
- Retention became a **GC expression config** over posting-date and
  last-observed-date filters (AND default, OR/single supported) —
  [the GC config](01-store-core.md#the-gc-config-decided-2026-07-21).
- Suppressed sweep rows get a **review queue** (partial info + raw path;
  optional manual review; never blocks the pipeline) —
  [the suppressed review queue](02-job-postings-pipeline.md#7-capture-policy-what-counts-as-useful-raw).
- Closure inference is **not built at all** (on-demand polling,
  gap-tolerant timelines) —
  [the lifecycle note](02-job-postings-pipeline.md#4b-lifecycle-not-built-decided-2026-07-21).
- The fixture size cap is a **soft threshold** (warn → human may raise a
  configurable limit); neutral identifier slugs gained **mechanical
  AI-error safeguards** (library-allocated only, write-time pattern
  validation); attachments are **metadata-only**; the cutover criterion is
  **dual** (5 clean runs AND ≥300 job-related messages); at-rest protection
  is the private-machines assumption, documented.
- Process folders were restructured by the same sign-off: open decisions
  now live in `message-queue/needs-human/decisions/` (the todo-queue convention in `AGENTS.md`).

## How this was produced

1. **Research pass** (web-research agent): Anthropic's agent/context
   engineering guidance; small-scale data-lake architecture critiques;
   event-sourcing versioning literature (rebuild over migrate); Microsoft
   Graph delta-sync and immutable-ID documentation; job-board lifecycle and
   deduplication practice. The non-obvious gotchas it surfaced (same-
   filesystem renames, torn JSONL tails, failed-fetch lifecycle guards,
   HTML-entity normalization before hashing, sync-token expiry as a routine
   path) are inlined where they bind.
2. **First draft** of all six documents.
3. **Five independent reviews:** data-engineering, token-economics/agent
   behavior, human-ergonomics/privacy, and two adversarial reviews (jobs
   layer, email layer) that attacked the drafts against the real fetcher
   and mailbox code. Roughly 60 findings, 14 at blocker severity.
4. **Review revision.** Every finding is either incorporated or explicitly
   deferred; each document ends with a plain-language "What the reviews
   changed" table linking findings to their fixes. The largest changes: a
   fifth storage zone for non-regenerable state; builder-only locking and
   degrade-on-read; a tested determinism contract; stable native-ID
   identity with pinned keys; lifecycle detection gated on preconditions
   instead of shipped broken; the snapshot cache retained; the Gmail
   read-only default; transition-time re-verification for email evidence;
   and the flipped email git policy.
5. **Owner sign-off (2026-07-21), plus follow-up decisions
   (2026-07-22).** Answers were folded back into the docs and compact
   decision records; no raw-data-layer question remains open.

## Relationship to existing work

- **Complements the token-usage-modes program** (`docs/design/token-usage-modes/`):
  that program cut instruction and iteration waste; this adds durable
  memory. They overlap on the search path (hence token-neutral there) and
  compose on the email path (where the next real savings live).
- **The snapshot cache stays.** Within-session refiltering and the
  filter-variant audit are its job; cross-run memory is the store's.
- **The shipped jobs-store integration changed the application pipeline
  only additively:** `meta.yaml` may carry the posting's store key. The
  planned [application-progress and calendar design](../application-progress-calendar/README.md)
  is a separate schema-v5 change for the email scheduling track.
- **Every hard guardrail survives:** draft-only email (structurally
  strengthened), the leak guard (plus new content-egress rules for store
  data), no fabricated postings, the location gate, blacklist/log
  preflights. Several review fixes exist precisely to keep these intact
  through the refactors.

## Human questions / additional tasks

*Owner space — anything written here is picked up by the next agent session
(see the async-collaboration contract in `AGENTS.md`). Questions get
answered in place; tasks get filed into `message-queue/` and linked back here.*

- (none right now)
