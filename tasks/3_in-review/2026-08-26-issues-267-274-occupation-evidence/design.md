# Design — primary occupation evidence

## Decision

Add an optional `titles.primary` list to a search profile. `titles.include` remains the broad title-retrieval surface: it decides which titles are plausible candidates. When `titles.primary` is non-empty, a title can enter the main shortlist only when it also matches at least one primary phrase. A title that matches `include` but not `primary` is kept in the existing bounded occupation-review lane with explicit rule and evidence identifiers. `primary` never rescues a title that failed `include`, never overrides `titles.exclude`, and never creates a hard drop.

This is opt-in. A profile with no `titles.primary` has byte-for-byte-compatible title decisions. A candidate-authored exact include therefore remains a kept candidate; adding that exact target-family phrase to `primary` preserves its main-list disposition.

## Why this is needed

The current title gate has one binary concept: an include term either matches or does not. That makes a broad supporting word indistinguishable from primary occupation evidence. A mobile profile can therefore treat `application` as proof that an application-security role is mobile engineering; an SDET profile can treat `automation`, `performance`, or `quality` as proof that business automation, backend performance, customer-quality, or manufacturing-quality work is software testing.

The new list expresses the distinction the classifier cannot safely infer: which title phrases establish this profile's occupation. The deterministic gate then enforces that declaration without guessing candidate intent.

## Rejected alternatives

### Expand `_BROAD_DOMAIN_TOKENS`

Rejected. A blacklist fixes only words already observed. The existing closed set covers infrastructure, platform, and similar software domains, but missed application, automation, performance, and quality. The same design would miss the next collision, and several of those words are valid primary evidence for other profiles. A generic tool cannot declare `quality` broad for every candidate without breaking a quality-engineering search.

### Infer primary terms from spelling

Rejected. Word count, presence of `engineer`, or title length cannot distinguish `Mobile Engineer` from `Manufacturing Quality Engineer`, or `Software Engineer, iOS` from `Software Engineer, Storage`, without embedding an occupation taxonomy in code. That taxonomy would be another blacklist in disguise and would overrule the profile owner.

### Require JD keyword hits

Rejected for this change. One incidental mention already caused the mobile and game false positives, and generic language lists caused the C++ storage collision. Requiring a count would turn repetition into truth. It would also make results depend on whether a source supplied a complete description before the title gate. Body-level occupation evidence needs a separately designed, negation-aware model.

### Hard-reject titles without primary evidence

Rejected. Missing title evidence is uncertainty, not proof of a mismatch. Direct-fit jobs can use general titles. Review preserves those rows, and the existing occupation-review cap bounds what is shown while retaining overflow evidence.

## Frozen public matrix

The matrix is fictional and contains no private profile or posting text. The same profile dictionaries include `titles.primary` in both measurements: before this change the unknown key is ignored; after it is enforced.

| Family | Target-family controls that must remain `match` | Broad or adjacent controls that must become/remain `review` |
|---|---|---|
| Mobile / app platform | Senior iOS Engineer; Mobile Platform Engineer | Application Security; generic Notifications SWE; Web Experience SWE |
| SDET / QA | QA Automation SDET; Test Infrastructure SWE | manual QA; IT/business automation; backend scalability/performance; customer quality; manufacturing quality; Core AI automation |
| Gameplay / graphics | Senior Gameplay Engineer | generic storage SWE |
| Robotics / autonomy | Senior Robotics Engineer | full-stack deployment tooling |
| Developer documentation | Developer Documentation Writer | Technical Writer, Life Sciences |
| Compiler / toolchain | GPU Compiler Engineer | generic build-tools SWE |
| Database / storage | Postgres Product Engineer | Database Administrator |
| Software engineering management | Software Engineering Manager | power-generation Engineering Manager |

Baseline at branch commit `07ee313`: 25 inputs produced 24 `match`, 1 `review`, and 0 `no_match`. The only baseline review was manual QA. Fourteen broad or adjacent controls were incorrectly in the main lane.

## Acceptance and rollback

- Target-family recall: 10 of 10 positive controls must remain `match`.
- Precision routing: all 15 broad or adjacent controls must be `review`; none may become `no_match`.
- Compatibility: every pre-existing corpus case and the shipped example profile must retain its verdict when `titles.primary` is absent.
- Auditability: a primary-evidence review must name the matched include terms and the expected primary phrases in structured evidence.

Rollback is two-layered. A profile can remove `titles.primary` to restore the old behavior immediately without changing code. If any frozen target-family control loses its main-list verdict or any profile without the key changes, revert the implementation commit; the review-only design means there is no persisted destructive state to migrate.

## Consequences

- Specialized profiles gain a deterministic main-list precision boundary without a public occupation taxonomy.
- Profiles must explicitly maintain the small primary phrase list; an omitted target synonym routes that title to review. This is intentional friction and the main recall risk.
- Generic profiles remain unchanged because the key is optional.
- Review volume can rise for a specialized profile, but the existing per-run occupation-review cap and durable overflow evidence bound and expose that cost.
- This change does not solve body-only semantic conflicts such as a `Database Engineer` description that is actually database administration. Those remain review/negative-keyword work for a future body-evidence model; this change does not pretend title evidence proves the JD.

## Human questions / additional tasks

None.
