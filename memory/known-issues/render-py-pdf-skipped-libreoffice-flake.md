# `render.py` "PDF: skipped" transient LibreOffice lock/first-run flake

- **Status**: open
- **Severity**: low (cosmetic — recoverable with a documented manual step)
- **Area**: resume-writer
- **Source**: `skills/resume-writer/LESSONS.md:87-88`

## Symptom

`render.py` sometimes prints `PDF: skipped` instead of producing the resume/cover
PDF, even though the DOCX rendered correctly. This is a transient LibreOffice
lock or first-run condition, not a deterministic failure — the same input can
succeed on a later invocation.

## Reproduction

Not reliably deterministic (transient). Observed on a LibreOffice
first invocation after a period without use, or when a prior `soffice` process
left a lock file behind. General shape:

```bash
.venv/bin/python skills/resume-writer/scripts/render.py "<application folder>/source/tailored.yaml"
# occasionally prints "PDF: skipped" instead of producing the .pdf
```

## Impact

The DOCX still renders correctly, so no data is lost, but the deliverable is
incomplete until a human (or the drafting agent) notices and manually converts
the DOCX to PDF. This costs a manual step and a moment of confusion per
occurrence; frequency is not quantified but is documented as a known,
recurring flake in LESSONS.md rather than a one-off.

## Root cause

Best current hypothesis (documented as a workaround, not root-caused further):
LibreOffice (`pdf_convert.py`, which probes `~/Applications/LibreOffice.app` then
`/Applications/LibreOffice.app` for `soffice`) can be in a transient
lock/first-run state where the headless conversion silently no-ops instead of
erroring, so `render.py` reports the PDF step as skipped rather than failed.

## Suggested fix

No structural fix has landed; the current mitigation is the documented manual
workaround in `skills/resume-writer/LESSONS.md`:

```bash
soffice --headless --convert-to pdf --outdir <folder> "<folder>/<RESUME_STEM>.docx"
```

then re-run `check.py` to confirm the page count. A more durable fix would have
`pdf_convert.py` detect the skip condition (e.g. missing output file after a
`soffice` invocation that exited 0) and retry once, or surface a clear non-zero
exit/error instead of a silent "skipped" so `render.py` callers can react
automatically instead of relying on a human noticing the message.
