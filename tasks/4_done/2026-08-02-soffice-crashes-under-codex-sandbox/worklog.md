# Worklog — 2026-08-02-soffice-crashes-under-codex-sandbox

## 2026-08-02 — session 1 (Codex)

- Filed the unclaimed P1 backlog task from crash-report, unified-log, converter-code, and gate-topology evidence. The next session should claim it, add signal-aware converter tests first, then implement fail-fast sandbox handling without weakening PDF validation.

## 2026-08-03 — session 2 (Codex)

- Claimed the task after a new crash report reproduced the documented macOS Codex-sandbox SIGABRT signature. Implementation and verification are delegated to GPT-5.6 Sol agents at extra-high reasoning under the top-level task owner.
- Added one shared converter-discovery and LaunchServices-capability helper, vendored it into resume-writer, and made the runner distinguish a missing converter (SKIP) from a known denied sandbox (FAIL before launch).
- Made nonzero and signal exits fail without retry while preserving exactly one retry for the exit-0 invalid-PDF flake. Repeated launch failures now have their own accurate diagnostic.
- Two independent reviews rejected an exit-0 E2E skip and an untyped variadic `sandbox_check` call; the final design makes denial red and pins the fixed ctypes arguments for Apple silicon.
- Verified the denied sandbox path without launching LibreOffice, then ran both real PDF-producing surfaces outside the sandbox in an isolated public-only copy: `example-render` passed with all checks and the resume-writer suite passed 105 tests.
- Eval gate skipped because no skill instruction file changed.
