# Handover — soffice sandbox crash fix

- **Date**: 2026-08-03
- **Task(s)**: 2026-08-02-soffice-crashes-under-codex-sandbox

## What happened

- Nothing remains half-implemented: the macOS Codex sandbox now fails PDF gates before launching LibreOffice instead of producing a crash storm.
- Outside that sandbox, the fictional example render and all 105 resume-writer tests completed with PDF validation active.

## Where things stand

- Implementation is verified and ready to move to done with the session commit.

## Decisions made for you

- Query the actual LaunchServices sandbox capability, with an exact Codex marker only as fallback; path or process-name heuristics would be easier to reverse but less accurate.
- Treat a known denial as FAIL and a missing converter as SKIP; reversing this would reintroduce a false green.
- Retry only exit-0 invalid-PDF and launch/timeout cases; deterministic nonzero or signal exits fail once, which changes only broken conversions.
- Keep one canonical environment helper and vendor it into resume-writer; undoing this would restore discovery drift between the gate runner and renderer.

## If X then Y

- If a future macOS policy denies LibreOffice after the preflight allowed it, the signal-aware converter still stops after one failed launch and reports the raw code and signal.
- If Apple changes the private `sandbox_check` ABI, the exact Codex marker remains a conservative fallback; revalidate the typed call on the affected macOS release.

## Dead ends

- Making the PDF E2E skip on a known denial was rejected because the surrounding test gate would exit green without exercising PDF validation.
- Calling the variadic Seatbelt function without fixed ctypes arguments was rejected because it is unsafe on Apple silicon.

## Needs your attention

- No new item was filed. The 32 pre-existing public items and 7 private-overlay items remain unchanged. Highest cost: [`job-search-us-only-default-asymmetry`](../../../message-queue/needs-human/decisions/job-search-us-only-default-asymmetry.md) — Why this matters: inconsistent defaults can repeatedly hide eligible remote roles. If you do nothing: the documented status quo remains and the recurring-loss risk continues.
