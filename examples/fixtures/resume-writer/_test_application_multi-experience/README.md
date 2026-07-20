# Multi-experience application fixture

This is a staging fixture, not a tracked job application. Tests copy it into a
temporary applications root and may rename the generated handoff folder to a
name beginning `_test_application_` after proving the normal production slug.
Nothing here belongs under `examples/applications/`.

Suggested flow:

1. Replace `__FIXTURE_ROOT_URI__` in `search/search-row.json` with this
   directory's escaped `file://` URI.
2. Run `handoff.py` with `--research-date 2026-07-20` and a temporary
   applications root.
3. Confirm the generated schema-v3 metadata and fetched JD, then seed the
   supplied `application/` files into that folder.
4. Set `JOBHUNT_CONFIG` to a temporary copy of `config.example.yaml`, rewriting only the
   temporary applications root when needed.
5. Render with the repository's public reference DOCX. Compare semantic text,
   normalized XML properties, page count, and artifact paths with `expected/`.

`config.example.yaml` points at the public example reference DOCX and an
intentionally absent `work/` tree. Tests must override or create that tree only
in a temporary directory. The checked-in generated DOCX/PDF files under
`application/` are a human-reviewable reference output; tests regenerate into
temporary storage and compare semantics/page counts rather than binary bytes.
