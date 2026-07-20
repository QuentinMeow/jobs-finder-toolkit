# Resume-writer fixtures

This corpus defines public, offline test inputs for flexible resume schemas,
single-column DOCX extraction, and a multi-experience application workflow. Every
identity, employer, school, product, URL, achievement, and metric in this tree is
synthetic. Jordan Rivers is the repository's fictional example candidate; no
prose here describes a real person.

The multi-experience E2E scenario checks in one reviewable resume and cover-letter
DOCX/PDF output set; the remaining scenarios stay text/declarative except for
sanitized input DOCX files and the intentionally invalid corrupt-package case.
Tests materialize recipes in a temporary directory and compare semantic text,
normalized XML properties, page count, diagnostics, and artifact names. Binary
equality is intentionally out of scope because DOCX ZIP timestamps and PDF
producer metadata vary across Word and LibreOffice.

## Support tiers

1. `schema-normalization` accepts canonical `employers:`, legacy singular
   `employer:`, and the `experience:` list alias. Supplying more than one
   representation is an error. Canonical output always uses an ordered
   `employers:` list; each employer has locked company/role/date/location fields,
   optional direct `bullets:`, and optional named `projects:`.
2. `single-column-extraction` covers ordinary paragraph-based resumes: repeated
   employers, promotions, native list bullets, Unicode date separators, direct
   role achievements, and optional named projects. Source order must be
   preserved.
3. `unsupported-layout` fails closed for two-column/table/text-box structures,
   empty documents, and corrupt packages. An actionable diagnostic is expected;
   silently dropping experience or leaking a traceback is not.
4. `application-e2e` stages a complete fake search-to-render case outside the
   numbered application pipeline. It is copied into a temporary
   `applications/6_drafted/` tree during tests.

## Fixture layout

- Each extraction scenario has a human-reviewable `input.yaml` recipe. A test
  harness may materialize it into `input.docx` in temporary storage; the corrupt
  case may retain intentionally invalid DOCX bytes as an input fixture. The
  legacy case also has `input-docx.yaml` for extraction coverage.
- Supported scenarios have `expected-canonical.yaml`.
- Rejected scenarios have `expected-diagnostics.yaml` with stable diagnostic
  codes and messages.
- `_test_application_multi-experience/` contains the complete E2E seed and
  semantic expectations. The leading `_test_application_` name is for fixture
  discovery only; production scanners must not receive a special-case skip.
- `provenance/` records the two pinned MIT structural references. Upstream
  binaries, source templates, identities, prose, and document metadata are not
  shipped.

`docx-paragraphs-v1` recipes are deliberately small. A harness creates one Word
paragraph per item, applies `style`, sets all runs bold when `bold: true`, and
adds native numbering when `list: bullet`. Tabs in `text` remain real paragraph
tabs. `document.columns`, `tables`, and `text_boxes` are capability signals, not
instructions to flatten an unsupported layout into a supported one.

## Intended assertions

For every supported case, build the input DOCX in a temporary directory, run the
extractor, normalize its YAML once, and compare parsed objects with
`expected-canonical.yaml`. Then validate employer and project order explicitly.
For unsupported cases, assert a nonzero result, the exact diagnostic code, no
traceback, and no partial canonical YAML.

For the E2E case, replace `__FIXTURE_ROOT_URI__` in the search row with the local
`search/jd-page.html` URI, run handoff against a temporary applications root,
seed the supplied application inputs, render, and compare extracted text with
the files under `expected/`. The manifest lists which paths are inputs versus
generated artifacts and which environment-dependent values must be normalized.

## Scenarios

- `legacy-project-focused`: singular legacy `employer:` normalization.
- `chronological-two-employer`: two jobs with direct chronological bullets.
- `same-company-promotion`: repeated company entries representing a promotion.
- `hybrid-role-bullets-projects`: direct achievements followed by named projects.
- `new-grad-internships-projects`: education-first input with internships and
  school-owned projects.
- `concurrent-contractor-roles`: overlapping dates that must not be merged.
- `unsupported-two-column`: explicit two-column/table layout rejection.
- `empty-corrupt`: empty package and invalid-package diagnostics.

The recipes are original synthetic fixtures. General single-column ordering and
compact chronological structure were recreated after inspecting the pinned
references described in `provenance/`; no upstream expressive content was
copied.
