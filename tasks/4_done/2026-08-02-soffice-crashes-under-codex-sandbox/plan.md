# Plan — 2026-08-02-soffice-crashes-under-codex-sandbox

- [x] Reproduce the report from existing crash evidence without launching LibreOffice again.
- [x] Separate converter discovery from macOS LaunchServices usability.
- [x] Fail before launch in the known denied sandbox and keep missing tools as explicit skips.
- [x] Classify signal and nonzero exits as non-transient; preserve the exit-0 invalid-PDF retry.
- [x] Cover direct, parallel, gate-runner, and PDF E2E launch surfaces with regression tests.
- [x] Document the supported macOS workflow and the limited role of `JOBHUNT_SOFFICE`.
- [x] Verify both sandbox refusal and real conversion outside the sandbox.
