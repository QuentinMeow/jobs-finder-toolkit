# When a rule has been broken twice, stop rewriting it and build the check

- **Filed**: 2026-08-02
- **Source**: [the piped-gate task](../../../tasks/4_done/2026-07-31-piping-a-gate-to-tail-hides-its-exit-code/task.md),
  which fixed the same defect with prose on 2026-07-31 — after which it happened
  again on 2026-08-01 (`git push … | grep …; echo $?` read `grep`'s 0 for a push
  that had failed) — plus PR #198, merged without the base check that
  `skills/github-workflow/SKILL.md` §2 already prescribed.

**Why:** the rule existed, in writing, in a file read earlier in the same session.
It still did not fire. This is not ignorance, and more prose does not fix it: an
instruction is consulted while you are *deciding what to do*, and both of these
mistakes happen while you are *doing something else* — shortening a wall of
output, or clearing the last PR in a queue.

The prior task is the proof. It swept the tree, found the pattern taught nowhere,
explicitly **considered an enforcement point and declined it** on a false-positive
count, and shipped "a stated convention" instead. Its own worklog records the
author hitting the bug in that session's first command. Prose written by someone
actively thinking about the rule did not protect the person who wrote it.

Both failures also share the property that made them expensive: **the wrong result
looks like the right one.** `<gate> | tail -5; echo $?` prints `0` for a gate that
exited 1; a PR merged into the wrong base still reports `MERGED`. Nothing
interrupts you.

**How to apply:**

- **Give the shortcut a safe form.** Piping to `tail` was never the goal — shorter
  output was. A gate runner that gives short output *and* an unmisreadable
  exit-code table takes the motive away; see the local-gate-runner row in
  `docs/handbook/command-cookbook.md`. A rule that forbids the only convenient
  path will be broken by whoever is in a hurry.
- **Make the check refuse, not advise.** A script that will not merge a PR whose
  base is not the one you named does what the paragraph telling you to check the
  base could not — see `skills/github-workflow/SKILL.md`.
- **Count a decline.** "Enforcement has too many false positives" is a real
  finding, but it is a decision to accept recurrence — record it that way, and
  revisit it the next time the defect appears rather than re-deriving the same
  sweep.
- **Never let a skip or a missing result render as a pass.** That is the same
  failure in different clothes.

Prose still has a job: it explains *why* a check exists, which is what lets the
next person fix the check instead of deleting it. It just cannot be the only
defence for a rule that has already failed once.
