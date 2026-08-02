# `render.py` "PDF: skipped" transient LibreOffice lock/first-run flake

- **Status**: fixed 2026-07-20 by `87f5e0d` ("render: kill the silent PDF-skip flake and
  convert PDFs in parallel"); confirmed still fixed 2026-08-02 — see Resolution below
- **Severity**: low (cosmetic — recoverable with a documented manual step)
- **Area**: resume-writer
- **Source**: `skills/resume-writer/LESSONS.md`, the Environment section (the line quoted
  below now reads the OPPOSITE of what it read when this was filed — see Resolution)

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

## Resolution

Fixed by `87f5e0d`, which implemented the "more durable fix" the last paragraph asks for.
`skills/resume-writer/scripts/pdf_convert.py`'s module docstring now states the guarantee:

> Two flake-hardening guarantees (a silent "PDF: skipped" used to hide both):
>   * detect + retry: LibreOffice occasionally exits 0 without writing the PDF
>     (a transient lock / first-run no-op). We verify a real PDF landed
>     (exists AND > MIN_PDF_BYTES); if not, we clear stray lock state, back off,
>     and retry ONCE. If a converter was available but still produced no valid
>     PDF, we raise PdfConversionError instead of returning a silent None.

`docx_to_pdf` now returns `None` ONLY when no converter exists at all, which is the
install-a-converter case rather than a flake. `skills/resume-writer/LESSONS.md` agrees:
"The old transient 'PDF: skipped' flake (LibreOffice exits 0 without writing the PDF) is now
handled inside `pdf_convert.py`", and it demotes the manual `soffice --headless` command from
"the current mitigation" to what to do "if that hard error ever persists".

The Source line above was pointing at a line range in LESSONS.md that had since moved and now
carries the contradicting text; it is re-pointed at the section rather than the numbers.
