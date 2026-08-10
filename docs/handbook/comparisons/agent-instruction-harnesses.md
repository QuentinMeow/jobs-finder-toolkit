# Agent instruction and harness patterns

## Result

The useful parts of the supplied image are engineering defaults, not universal laws. Six of its
seven visible rules can inform global guidance after qualification. Backward compatibility is a
product contract and cannot safely be decided across every repository. The blanket ban on temporary
bridges must also be rewritten to fit incremental delivery: temporary work should be isolated,
verified, and given an explicit exit condition.

The image says the source distilled eight rules after roughly 60 billion tokens, but only seven
bullets are visible. I found no primary Vercel source for that token-count attribution or the exact
wording, so this review treats the image as unattributed advice rather than evidence about Vercel or
the Next.js team.

## What established harnesses support

- The current [Codex `AGENTS.md` documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
  says global instructions load first, repository files layer on top, and the closest file has the
  highest precedence. Global text should therefore be conservative and repository-independent.
- The [Codex best-practices guide](https://learn.chatgpt.com/guides/best-practices) recommends short,
  accurate instruction files, task-specific references for depth, and adding rules after repeated
  mistakes rather than anticipating every edge case.
- OpenAI's [harness-engineering report](https://openai.com/index/harness-engineering/) says its large,
  monolithic `AGENTS.md` failed because it consumed context, diluted priorities, decayed quickly, and
  resisted verification. Its replacement is a short map to structured repository knowledge plus
  mechanically enforced invariants. The same report also documents a case where a small local helper
  was clearer and more testable than an opaque library, so "prefer a library" needs an inspectability
  and total-complexity exception.
- Anthropic's [long-running-agent harness study](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
  found that agents perform better when they deliver one working feature at a time, leave the tree in
  a clean state, and verify behavior end to end before marking work complete.
- Vercel's [Next.js agent evaluation](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals)
  supports compressed indexes and retrieval-led reasoning: it reduced an injected documentation index
  from about 40 KB to 8 KB while retaining the measured pass rate. Broad facts belong in passive
  guidance; action-specific procedures belong in skills.
- The open [AGENTS.md specification](https://agents.md/) defines no mandatory schema and recommends
  nested files for local rules, with the nearest instruction file winning conflicts.

## Disposition of the image rules

| Visible rule | Disposition | Global form |
|---|---|---|
| Remove backward compatibility | Pending owner decision | Omitted: compatibility depends on the product contract and data-migration obligations. |
| Use the simplest complete implementation | Adopt, qualified | Meet current requirements and known constraints without speculative abstraction or configuration. |
| Grow in working end-to-end layers | Adopt | Each increment leaves the product usable and verified. |
| Keep components modular | Adopt, qualified | Separate stable concerns, but do not split code merely to satisfy a style slogan. |
| Prefer maintained libraries | Adopt, qualified | Prefer them only when they reduce total complexity and risk; inspectability and supply-chain cost count. |
| Reuse existing dependencies first | Adopt | Check installed dependency docs, types, source, and tests before custom code or another package. |
| Reject temporary architecture | Modify; pending owner ratification | Optimize for maintainability and reversibility; isolate and track any necessary bridge with an exit condition. |

Two additional rules follow from the research: completion requires observable verification, and a
prose invariant that repeatedly fails should become a test, lint, type, or hook rather than another
paragraph.
