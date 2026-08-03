# Stop LibreOffice crash storms when PDF gates run inside the Codex macOS sandbox

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: Codex desktop crash investigation, 2026-08-02 (macOS crash reports, unified logs, and current converter code)
- **Claimed-by**: Codex

## Goal

Make the PDF gate fail once with an accurate, actionable sandbox diagnostic when macOS prevents LibreOffice from registering with system services. Preserve real DOCX-to-PDF and one-page validation outside that unsupported execution context.

## Context

### What happened

A full local gate run launched LibreOffice from Python inside the Codex desktop process coalition. macOS produced eight near-identical `soffice` crash reports in one run. Every report showed:

- LibreOffice `25.8.7.3`, native `x86_64`, launched by a Python parent under the Codex/ChatGPT process coalition;
- `EXC_CRASH (SIGABRT)`, termination signal 6, with `abort() called` on the main thread; and
- failure during macOS application initialization, before any document conversion code could run.

The main-thread stack was:

```text
abort
___RegisterApplication_block_invoke
_RegisterApplication
GetCurrentProcess
NSApplication initialization
libvclplug_osxlo create_SalInstance
InitVCL
```

The macOS unified log supplied the decisive evidence:

```text
Sandbox: soffice(...) deny(1) mach-lookup com.apple.coreservices.launchservicesd
```

The corresponding application-specific report said the process could not create its connection because the sandbox denied lookup of `com.apple.coreservices.launchservicesd`, followed by `XPC_ERROR_CONNECTION_INVALID`. This establishes the immediate cause: even with `--headless`, LibreOffice initializes the native macOS application layer, which needs LaunchServices access that the inherited Codex sandbox denies.

### What was ruled out

- **The DOCX inputs were not the cause.** The abort occurs in `InitVCL`/`NSApplication` before LibreOffice opens the requested document.
- **The installed application was not corrupt.** Outside the Codex sandbox, its deep code signature verified and macOS policy assessment accepted it as a notarized Developer ID application.
- **This was not an architecture translation failure.** The application and host were both native `x86_64`.
- **Changing only the binary path is not a demonstrated fix.** The bundled macOS LibreOffice build also carries the native VCL/AppKit initialization path; the important boundary is unsandboxed execution, not personal-versus-bundled installation.
- **No reproduction was attempted after the cause was established.** Another in-sandbox launch would only create another deterministic crash report.

### Why one gate run produced eight reports

`skills/resume-writer/scripts/pdf_convert.py` currently:

1. selects the first existing converter in this order: `JOBHUNT_SOFFICE`, the user's Applications folder, system Applications, then `PATH`;
2. treats every unsuccessful attempt as the same transient lock/first-run/no-output condition;
3. clears local lock state, sleeps, and retries once; and
4. reports only the final stderr under the label “known silent-skip / lock / first-run flake.”

A signal termination is represented by a negative `subprocess` return code (`-6` for `SIGABRT`), but the converter neither classifies nor reports that value. It therefore retries a deterministic sandbox abort and emits a misleading flake diagnosis.

The gate suite performs two PDF-producing phases. Each phase renders a resume and one cover letter, and the converter gives each document two attempts:

```text
2 gate phases × 2 documents × 2 attempts = 8 soffice launches/crash reports
```

`automation/gates/run_gates.py` amplifies the mismatch at preflight: `_needs_libreoffice()` checks only whether a candidate binary exists. Existence is sufficient to start the PDF gates but says nothing about whether the current execution environment permits that binary to initialize.

Relevant implementation and test surfaces:

- `skills/resume-writer/scripts/pdf_convert.py`
- `skills/resume-writer/scripts/tests/test_pdf_convert.py`
- `automation/gates/run_gates.py`
- `automation/gates/tests/test_run_gates.py`
- `docs/handbook/command-cookbook.md`

### Required behavioral boundaries

- Keep the existing one retry for the genuine “exit 0 but no valid PDF” flake.
- Do not retry a deterministic signal termination or another clearly non-transient nonzero exit.
- Do not weaken, skip, or silently mark the one-page PDF gate green.
- Preserve Linux/CI conversion behavior.
- Do not require a contributor's personal LibreOffice installation when an explicitly configured converter is available.
- Make the supported remedy clear: run the PDF-producing gate outside the inherited macOS app sandbox, or use a separately validated execution route that has the required system-service access.

## Definition of done

- A unit test supplies a mocked `CompletedProcess` terminated by `SIGABRT` and proves `docx_to_pdf()` invokes LibreOffice exactly once, raises `PdfConversionError`, and reports the negative return code plus the `SIGABRT` signal name.
- The same diagnostic distinguishes a sandbox/application-initialization failure from the existing exit-0/no-PDF lock/first-run flake and gives an actionable unsandboxed-run remedy.
- Existing tests still prove that exit 0 without a valid PDF retries exactly once and can succeed on the second attempt.
- The gate precondition or runner distinguishes “binary exists” from “usable in this execution environment”; on a known unsupported macOS Codex-sandbox run, it stops before creating a multi-process crash storm and never reports a skipped PDF gate as green.
- `test_pdf_convert.py` and `test_run_gates.py` cover the new classification and fail-fast path without launching a real GUI process.
- The command cookbook documents the supported macOS/Codex workflow and the role of `JOBHUNT_SOFFICE` without claiming that a different binary alone escapes the sandbox.
- A full gate run outside the unsupported sandbox completes with the PDF and one-page checks active; CI remains green.
