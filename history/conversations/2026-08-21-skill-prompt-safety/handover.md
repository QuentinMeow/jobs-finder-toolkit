# Handover — skill prompt safety

- **Date**: 2026-08-21
- **Task(s)**: 2026-08-21-skill-prompt-safety

## What happened

- Nothing is blocked: the intermittent generic prompt rejection did not reproduce deterministically, and the repaired company-research workflow plus the full public/private skill inventory completed with zero post-change policy rejections.
- Company research now routes quick chat requests through a 138-line surface instead of preloading the former 568-line dossier workflow; the complete research requirements remain in an on-demand guide.
- A privacy-safe prompt-surface audit now covers all 19 public/private skills and runs in the policy lane; the installed system skill-creator now teaches the same diagnosis and progressive-disclosure pattern.
- Independent GPT-5.6-sol xhigh agents completed 31 representative skill executions covering every skill. The company-research canaries passed 7/7 after literal rubric gaps were repaired; the policy and maintenance lanes passed all 19 gates.

## Where things stand

- Work is in review in [2026-08-21-skill-prompt-safety](../../../tasks/3_in-review/2026-08-21-skill-prompt-safety/task.md); no commit or PR was created.
- The pinned eval evidence is [company-research-02fa203db610-20260821-prompt-surface.md](../../../evals/results/company-research-02fa203db610-20260821-prompt-surface.md).

## Decisions made for you

- Treated the error as an intermittent server safeguard event rather than a forbidden-word diagnosis because identical content later succeeded; undoing this only requires reverting the small guidance section.
- Reduced always-loaded context while preserving every research requirement in a routed guide; reverting would restore the 568-line monolith.
- Made heuristic vocabulary/mode findings advisory and enforced only conservative extreme-size limits, avoiding false CI failures on ordinary safety language.

## If X then Y

- If the same generic error recurs, capture the task/log timestamp and retry once in a fresh focused task; do not remove words based on one rejection.
- If a new skill crosses a strict prompt-surface limit, retier it or split task modes instead of raising the limit without measured evidence.

## Dead ends

- No single skill sentence reproduced the rejection; a fresh agent loaded roughly 30,000 tokens of the same Salesforce/company context successfully.
- The first company canary pass exposed output-quality gaps unrelated to policy rejection; independent judging and targeted reruns closed them before acceptance.

## Needs your attention

- No task-specific decision is pending. The pre-existing owner queue remains at 40 items; highest cost is [retire-copied-private-companies-root](../../../message-queue/needs-human/decisions/retire-copied-private-companies-root.md): deciding prevents duplicate private-company roots from causing path mistakes, while silence safely retains the recovery copy.
