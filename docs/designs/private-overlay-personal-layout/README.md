# Private overlay — group personal work by purpose

**Status:** owner-directed design, implementation in progress (2026-08-06).

This design replaces the private overlay's lifetime-first layout with a person-first
layout. The practical rule is simple: artifacts created for the owner's career, job
applications, and interviews live below `me/`; repository controls and machine-operated
systems remain at the overlay root.

## Why the old grouping no longer fits

The previous layout treated permanence as the top-level distinction: reusable personal
material lived in `me/`, company material in `companies/`, and per-requisition products in
`applications/`. That made deletion boundaries explicit, but it scattered one person's job
hunt across three peer roots and left profile source files loose directly under `me/`.

The new layout optimizes for navigation by purpose. `me/` is the parent for everything the
owner reads or submits; `market/`, `store/`, `skills/`, `evals/`, and the process roots stay
separate because they are operating systems for the toolkit rather than personal artifacts.

## Target tree

The target keeps only directories immediately below `me/` and separates career source,
application records, and interview preparation.

```text
private/
├── README.md  .gitignore  leak_tokens.txt  leak_safe_words.txt
├── me/
│   ├── applications/
│   │   └── <2_ignored…6_drafted>/<application>/
│   ├── career/
│   │   ├── profile.md
│   │   ├── tailoring-card.md
│   │   ├── resume/
│   │   │   ├── baseline.yaml
│   │   │   └── <resume DOCX/PDF files>
│   │   └── communications/
│   │       ├── <shared application and outreach copy>
│   │       └── companies/<key>/<company-specific reply>
│   └── interviews/
│       ├── calendar.md  calendar.html
│       ├── companies/<key>/
│       ├── practice/
│       ├── question-bank/
│       └── story-bank/
├── market/
│   ├── company-index.yaml
│   ├── blacklist.yaml  manual-check.yaml
│   ├── scans/  searches/  universe/
│   └── logs/
├── store/
├── data/                         # temporary split-brain exception; see below
├── docs/  evals/  skills/
└── memory/  message-queue/  tasks/  history/
```

## Complete routing decisions

This map states what moves and what deliberately does not. A path absent from the move
column remains where it is.

| Before | After | Reason |
|---|---|---|
| `applications/<status>/` | `me/applications/<status>/` | Submitted and tracked applications are the owner's artifacts. |
| `applications/1_discoveries/current/*` | `market/scans/current/` | Search scans describe the market, not an application. |
| `companies/<key>/` | `me/interviews/companies/<key>/` | The audited folders contain interview research, questions, and assessment practice. |
| `companies/_index.yaml` | `market/company-index.yaml` | The identity registry serves applications, search, review checks, and interviews; it is not interview prep. |
| one company outreach draft | `me/career/communications/companies/<key>/` | Recruiter/application copy is career communication, not interview material. |
| `me/profile.md` | `me/career/profile.md` | Candidate source material belongs together under career. |
| `me/tailoring-card.md` | `me/career/tailoring-card.md` | The distilled candidate source is part of the same career context. |
| `me/baseline.yaml` | `me/career/resume/baseline.yaml` | The baseline is the structured source for the resume set. |
| `me/resume/*` | `me/career/resume/*` | Resume source and rendered artifacts stay together; no duplicate is deleted. |
| `me/interviews/common-message-replies/*` | `me/career/communications/*` | The audited files are outreach, role-targeting, and application-form copy. |

`market/`, `store/`, `docs/`, `evals/`, and `skills/` remain top-level cohesive systems.
`memory/`, `message-queue/`, `tasks/`, and `history/` remain top-level because the public
reconciler and agent contract intentionally mirror those process roots. Repository control
files and leak-guard token files remain at the root because exact-path security consumers
read them there.

## The legacy `data/` exception

The old `data/` store root cannot move safely in this refactor. It was renamed to `store/`,
then a later write recreated `data/` with newer index and state rows that are absent from
`store/jobs/`. Calling it an archive or nesting it below `store/` before reconciling those
rows would hide an active split-brain problem rather than solve it.

The default is therefore lossless: leave `data/` at the root, file a separate reconciliation
task, merge its unique state into the canonical store with store-aware verification, and only
then propose retirement of the old root. Agents still may not delete it; owner-data deletion
remains owner-only.

## Path contract and compatibility

Moving applications one level deeper breaks the old inference that the overlay root is the
applications directory's parent. Real configurations must set `paths.overlay_root` explicitly
to the overlay root and set the new applications, company-index, company-prep, profile,
resume, and communication paths. Benchmark configurations keep their current derived overlay
root because that derivation is what isolates benchmark writes.

Public defaults and fictional examples adopt the same person-first shape. Historical ADRs,
completed tasks, results, and handovers keep their dated old paths as testimony; active docs,
code, tests, skills, and artifacts move. The link checker retains old application paths only
for record trees and treats old active company paths as retired.

## Two-repository rollout

The public toolkit and private overlay are different repositories, so this is two ordinary
PRs rather than a stack:

1. The public PR teaches config accessors, company-index consumers, examples, tests, and
   current documentation the new shape. It remains compatible with a mounted old overlay
   through explicit real-config paths during review.
2. The private PR performs exact moves in batches below the private hook's file and byte
   limits, then updates live private references. It declares the public PR as a dependency.
3. At cutover, the ignored real `config.yaml` changes atomically after the new private tree
   is present. The currently dirty private checkout must first preserve and reconcile its
   unrelated application and calendar edits; the migration branch does not touch them.

There is no permanent compatibility symlink. A shim would keep two apparently valid homes
and make future writes split again.

## Verification

The migration is accepted only when all of these hold:

- a precomputed map proves every tracked source path has exactly one destination with the
  same Git mode and blob OID;
- pure move commits contain only `R100` entries, while reference edits are separate;
- before/after manifests cover ignored recovery files and symlink targets as well as tracked
  files, without dereferencing links;
- no tracked or ignored file remains directly under `me/`, and old active roots are absent;
- config accessors resolve the new personal roots while market, store, skill-note, and
  benchmark-isolation roots remain unchanged;
- strict company-index, application-status, reconciler, link, vendoring, leak, and impacted
  gate suites pass, followed by a config-less public checkout and both PRs' CI.

## Decisions (resolved)

| Decision | Resolution | Record |
|---|---|---|
| What owns applications and company interview prep? | `me/` owns both; company prep nests below `me/interviews/`. | [Person-first private layout](../../../memory/decisions/private-overlay-person-first-layout.md) |
| Where does the company identity registry live? | `market/company-index.yaml`, because it is cross-workflow market identity. | [Person-first private layout](../../../memory/decisions/private-overlay-person-first-layout.md) |
| What happens to divergent `data/` state? | Preserve in place and reconcile separately before any retirement. | [Legacy data-root reconciliation task](../../../tasks/0_backlog/2026-08-06-reconcile-recreated-legacy-data-root/task.md) |

## Human questions / additional tasks

<!-- Free space for the owner. -->
