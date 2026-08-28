# Design — primary occupation evidence

## Decision

Add an optional `titles.primary` list to a search profile. `titles.include` remains the broad title-retrieval surface: it decides which titles are plausible candidates. When `titles.primary` is non-empty, a title can enter the main shortlist only when it also matches at least one profile-owned, occupation-bearing phrase. Use `ios engineer`, `mobile platform engineer`, or `qa automation sdet`, not a raw domain word such as `mobile`, `application`, or `quality`. A title that matches `include` but not `primary` is kept in the existing bounded occupation-review lane with explicit rule and evidence identifiers.

Primary phrases use the title gate's existing word-bounded, separator-insensitive, short-inflection matching; they are not literal-string equality. Every main-list match records the decisive matched primary phrase as both `title.primary_occupation.<phrase>` and `primary:<phrase>`. This makes an acceptance auditable instead of recording only its retrieval include and seniority.

This is opt-in. An absent or empty `titles.primary` produces the same title assessment as before. A broad candidate-authored include remains recoverable in review unless an existing harder assessor rule rejects it; an occupation-bearing include copied to `primary` preserves its main-list disposition.

At the canonical assessor, `primary` never rescues a title that failed `include`, never overrides `titles.exclude`, and never creates a hard drop. The full pipeline has one pre-existing, explicitly configured exception: `titles.word_filter.include` or `soft_exclude` may rescue an assessor `no_match` to review, never to the main list; `word_filter.hard_exclude` still drops before the assessor. Focused tests pin both boundaries.

The frozen profiles keep two mobile intents separate. The broad mobile profile declares iOS,
Android, and React Native occupation phrases and must retain all three families as matches. The
iOS-only profile keeps the same broad retrieval includes but explicitly excludes Android and
React Native; those two negative policy decisions must remain `no_match`. This pins recall for
the broad profile without weakening a narrower candidate-authored exclusion.

## Why this is needed

The current title gate has one binary concept: an include term either matches or does not. That makes a broad supporting word indistinguishable from primary occupation evidence. A mobile profile can therefore treat `application` as proof that an application-security role is mobile engineering; an SDET profile can treat `automation`, `performance`, or `quality` as proof that business automation, backend performance, customer-quality, or manufacturing-quality work is software testing.

The new list expresses the distinction the classifier cannot safely infer: which title phrases establish this profile's occupation. The deterministic gate then enforces that declaration without guessing candidate intent. The first implementation proved why the declaration itself must be occupation-bearing: `primary: [ios, mobile]` still admitted `Mobile Mechanic` and `Mobile Sales Representative`. Replacing those raw domain tokens with complete profile-owned phrases closes that gap without a public occupation taxonomy.

## Rejected alternatives

### Expand `_BROAD_DOMAIN_TOKENS`

Rejected. A blacklist fixes only words already observed. The existing closed set covers infrastructure, platform, and similar software domains, but missed application, automation, performance, and quality. The same design would miss the next collision, and several of those words are valid primary evidence for other profiles. A generic tool cannot declare `quality` broad for every candidate without breaking a quality-engineering search.

### Infer primary terms from spelling

Rejected. Word count, presence of `engineer`, or title length cannot distinguish `Mobile Engineer` from `Manufacturing Quality Engineer`, or `Software Engineer, iOS` from `Software Engineer, Storage`, without embedding an occupation taxonomy in code. That taxonomy would be another blacklist in disguise and would overrule the profile owner.

### Reject every one-word primary term

Rejected. Some one-word titles, such as `SDET`, are themselves occupations, while multiword phrases can still be broad. A generic word-count validator would reject valid profiles without proving that the remaining phrases are safe. The profile therefore owns the semantic boundary; the template, field reference, corpus, and frozen controls show occupation-bearing phrases and make the remaining misconfiguration risk explicit.

### Require JD keyword hits

Rejected for this change. One incidental mention already caused the mobile and game false positives, and generic language lists caused the C++ storage collision. Requiring a count would turn repetition into truth. It would also make results depend on whether a source supplied a complete description before the title gate. Body-level occupation evidence needs a separately designed, negation-aware model.

### Hard-reject titles without primary evidence

Rejected. Missing title evidence is uncertainty, not proof of a mismatch. Direct-fit jobs can use general titles. Review preserves those rows, and the existing occupation-review cap bounds what is shown while retaining overflow evidence.

## Frozen public matrix

The matrix is fictional and contains no private profile or posting text. All three measurements use the same 31 titles and retrieval includes. The pre-feature measurement has no effective primary boundary, the first implementation uses the reproduced broad mobile declaration, and the repaired measurement replaces it with occupation-bearing phrases. The two added iOS-only negative-policy rows are hard exclusions in every variant; they isolate candidate policy from the primary-evidence delta.

| Family | Target-family controls that must remain `match` | Broad or adjacent controls that must become/remain `review` |
|---|---|---|
| Mobile / app platform | Senior iOS Engineer; Mobile Platform Engineer; Senior Android Engineer; React Native Developer | Mobile Mechanic; Mobile Sales Representative; Application Security; generic Notifications SWE; Web Experience SWE; Android and React Native under the iOS-only profile are explicit `no_match` controls |
| SDET / QA | QA Automation SDET; Test Infrastructure SWE | manual QA; IT/business automation; backend scalability/performance; customer quality; manufacturing quality; Core AI automation |
| Gameplay / graphics | Senior Gameplay Engineer | generic storage SWE |
| Robotics / autonomy | Senior Robotics Engineer | full-stack deployment tooling |
| Developer documentation | Developer Documentation Writer | Technical Writer, Life Sciences |
| Compiler / toolchain | GPU Compiler Engineer | generic build-tools SWE |
| Database / storage | Postgres Product Engineer | Database Administrator |
| Software engineering management | Software Engineering Manager | power-generation Engineering Manager |

The repaired matrix has 31 inputs. With primary evidence absent (equivalent to pre-feature commit `07ee313`), it produces 28 `match`, 1 `review`, and 2 `no_match`; 16 adjacent controls are incorrectly in the main lane. The first implementation at `4a1fdb2`, measured with the expanded but still broad mobile declaration `primary: [ios, mobile, android, react native]`, produces 14 `match`, 15 `review`, and 2 `no_match`: `Mobile Mechanic` and `Mobile Sales Representative` are the two remaining false main-list matches. With occupation-bearing primary phrases, the repaired result is 12 `match`, 17 `review`, and 2 `no_match`. The two hard drops are only the iOS-only profile's explicit Android and React Native exclusions.

## Stack dependency

This change was built on `codex/issue-234-manager-product-corpus` at
`67a0375f012e7ef579482de5b0272d4ec13bb0b2`, published as PR #371. While PR #371
is open, publication uses that branch as the PR base. Rebase onto `main` only after PR #371
merges; rebasing earlier would make this PR include or duplicate the manager-product corpus.

## Acceptance and rollback

- Target-family recall: 12 of 12 positive controls must remain `match`, including Android and React Native.
- Precision routing: all 17 broad or adjacent controls, including Mobile Mechanic and Mobile Sales Representative, must be `review`; none may become `no_match`.
- Negative-policy precedence: Android and React Native remain `no_match` under the paired
  iOS-only profile, while both remain `match` under the broad mobile profile.
- Compatibility: every pre-existing corpus case and the shipped example profile must retain its verdict when `titles.primary` is absent or empty.
- Auditability: a primary-evidence review must name the matched include terms and expected primary phrases; a main match must name the decisive matched primary phrase in both rule and evidence fields.
- Precedence: primary cannot rescue an include miss or an explicit exclude at the assessor; a configured word-filter rescue remains review-only at the full-pipeline boundary.

Rollback is two-layered. A profile can remove `titles.primary` to restore the old behavior immediately without changing code. If any frozen target-family control loses its main-list verdict or any profile without the key changes, revert the implementation commit; the review-only design means there is no persisted destructive state to migrate.

## Consequences

- Specialized profiles gain a deterministic main-list precision boundary without a public occupation taxonomy.
- Profiles must explicitly maintain the small primary phrase list; an omitted target synonym routes that title to review. This is intentional friction and the main recall risk.
- A wrongly broad primary declaration can reopen false main-list matches. The generic tool cannot validate occupation semantics without becoming the rejected taxonomy, so the public examples and frozen controls carry that configuration responsibility visibly.
- Generic profiles remain unchanged because the key is optional.
- Review volume can rise for a specialized profile, but the existing per-run occupation-review cap and durable overflow evidence bound and expose that cost.
- This change does not solve body-only semantic conflicts such as a `Database Engineer` description that is actually database administration. Those remain review/negative-keyword work for a future body-evidence model; this change does not pretend title evidence proves the JD.

## Human questions / additional tasks

None.
