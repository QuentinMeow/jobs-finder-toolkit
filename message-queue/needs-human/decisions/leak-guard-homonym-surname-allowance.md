# Should an owner be able to switch off leak-guard protection for a name that is also an ordinary English word?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-09
- **Source**: [the leak guard's token matcher](../../../automation/publish/check_public.py)
- **Blocks**: nothing. The mechanism is already merged and inert.
- **Default path**: the allowance ships OFF and stays off. No tracked file
  declares one, no agent ever adds one, and the guard behaves exactly as it does
  today unless the owner personally writes `leak_guard.english_word_tokens` into
  the git-ignored `config.yaml`.
- **Cost if wrong**: ratify
- **Safe to merge because**: nothing is enabled. The allowance needs a key the
  owner types into a git-ignored file that no agent writes; with the key absent
  the guard's token set, its matching and its exit codes are unchanged. Undo is
  `git revert` of the commit that added it, and nothing on disk has to be
  reverted with it — no owner data, no log row, no config.

## Background

The publish leak guard (`automation/publish/check_public.py`) is the only thing
between the owner's real name and a public GitHub repository, and it runs in
both the pre-commit and pre-push hooks. Until now it matched every identity
token by plain case-insensitive containment: if `Rivers` was a token, any file
containing the letters `rivers` anywhere — including inside `drivers` — was a
violation.

**What that did to ordinary surnames.** Measured on this repository's 1209
tracked files, 17 of the 40 most common US surnames produced false violations.
Counts before the fix: `King` 491 files (it is inside `making`), `Long` 374,
`Ross` 327 (`cross-session`), `Green` 268, `Ward` 186 (`outward`), `Lee` 69
(`time.sleep`, `FileExistsError`), `Quick` 57 (`quickstart`), `Park` 50
(`sparkling`), `Hall` 29 (`shallow`), `Reed` 17 (`agreed`).

**Why that is a safety problem and not an annoyance.** An owner with one of
those surnames cannot commit at all. They have exactly two exits: `--no-verify`
(forbidden by `AGENTS.md`) or deleting their identity from `config.yaml` — which
disarms the guard completely and permanently, because a guard with zero identity
tokens is the one state in which a tree full of the owner's real name reports
"Safe to publish". The false positive is the pressure that manufactures the
fail-open checkout. **Without some escape hatch, an owner whose surname is an
English word cannot use this repository at all.**

**What the merged fix already does.** Matching is now hybrid. A bare word — a
name part, a one-word employer — hits only at a word, identifier or case-hump
edge, so `making` no longer contains `King`. High-specificity tokens keep plain
containment: the email address, the linkedin/github handles, the home-directory
basename, and the name COMPOUNDS the guard now derives (`jordanrivers`,
`jrivers`, `jordanr`, `jordan-rivers`, `jordan rivers`, and the reversed forms).
The compounds are what keep the glued leak shapes caught —
`linkedin.com/in/jordanrivers`, `github.com/JordanRivers`, `jrivers@corp`,
`acme-jordanrivers/`, `/Users/jordanrivers`.

**What that fix does NOT solve, which is why this question exists.** Boundaries
cannot help a name that is *itself* an ordinary word. After the fix `Green`
still flags 210 files and `Long` still flags 107 — every one of them the honest
English word. And no rule can ever separate `Menlo Park` from `Alex Park`: they
are the same string in the same shape. The repository had no escape hatch for
this. The existing safe-word list (`private/leak_safe_words.txt`) is
deliberately scoped to auto-derived overlay SKILL names and reports a collision
with a declared identity token as `ineffective`, on the explicit reasoning that
a mechanism able to silently un-declare a declared secret is a disarming vector.

## Options

The axis is protection against usability, with visibility as the thing that
decides whether the trade is honest.

### Option A — opt-in, loudly reported allowance (what is merged now)

The owner names the word in the git-ignored `config.yaml`:

```yaml
leak_guard:
  english_word_tokens: ["Green"]
```

Only that one bare word stops being a violation. Every derived compound
(`alexgreen`, `agreen`, `alex-green`, `alex green`), the email address, the
handles and the home basename keep full containment protection, so the full name
written in any form is still caught. The guard prints the word and the number of
occurrences it skipped on **every** run, clean or failing, and the token still
arms the guard (it is still an identity token — the guard never falls into its
unarmed exit-2 state because of this).

***Example consequence:*** the owner commits a file containing the sentence "the
build is green" and it goes through; the guard's report says, verbatim from a
real run on this tree, `word allowance: 'Green' — identity protection REDUCED
(you declared it an ordinary English word); 552 occurrence(s) SKIPPED, not
reported below`. If a draft cover letter one day says
"Sincerely, Alex Green", the compound token `alex green` still stops the commit.
If it says only "Green", nothing stops it.

### Option B — no allowance at all

Ship the boundary fix and stop. An owner named Green or Long lives with ~210 and
~107 false violations and either edits every one out of the repository's own
prose or removes their identity from `config.yaml`.

***Example consequence:*** a new user named Long runs the setup, tries their
first commit, gets 107 violations naming files they never touched, and either
gives up or empties their name out of `config.yaml` — after which the guard
prints "Safe to publish" over every future commit, including the one that ships
their resume.

### Option C — infer it automatically from an English dictionary

The guard ships a word list and quietly downgrades any identity token that is an
English word.

***Example consequence:*** the owner never sees a false positive and also never
finds out that their surname stopped being protected; a surname like `Hunt`,
`Berry` or `Field` is silently unguarded on a machine where nobody chose that.
The protection level of a security gate then depends on a word list nobody in
this repository reviewed.

## Recommendation

**Option A**, which is what is merged. It is the only option that keeps the
decision with the person who owns the risk, keeps it visible on every run, and
keeps the highest-value tokens (the address, the handles, the full-name
compounds) at full strength. Option C is the same trade made silently, and
silence is exactly what makes a reduced gate dangerous. Option B is not a
neutral "do nothing": its real-world outcome is a disarmed guard, because a user
who cannot commit removes the thing that blocks them.

**Strongest case against this:** any owner-controllable switch that reduces a
security gate is a disarming vector, and this guard has already had to close
three of those. The bare surname is, on its own, the single most likely real
leak string in a resume repository — it is what appears in a rendered document,
a filename stem and a cover-letter signature. A report line printed on every run
is read on run one and skipped on run thirty, so "loudly reported" decays to
"reported" and then to "present". A defensible alternative is to accept Option B
and instead tell such an owner to keep the public repository un-armed and rely
on the token-independent checks (structural PII, path denylist, fail-closed
binaries), which catch most real leak shapes without any identity at all.

**Confidence:** medium — the before/after counts above are measured on this
tracked tree, the catch list (22 leak shapes, including the five glued ones) is
pinned by tests, and the end-to-end behaviour was run: armed with `Green` the
guard reports 217 violations and exits 1; armed with `Green` plus the allowance
it reports the line above and exits 0; the allowance alone still exits 2
(unarmed). What I did NOT do: survey how often a bare surname, with no compound
and no address nearby, is the only trace of identity in a real application
artifact — which is the number that would settle the "strongest case against".

## Related residual (not part of this question)

The home-directory basename keeps plain containment by design, and the allowance
deliberately never applies to it. An owner whose macOS home directory is named
`mark` therefore gets every occurrence of `markdown` and `bookmark` flagged, with
no way to relax it short of the same fail-open exits described above. Structural
check 5 (the home-path regex) already flags any real home path with zero tokens,
so the home-basename token adds little that check 5 does not. If you want that
changed, say so here and it becomes its own task.

<Answer in plain words — one sentence is enough. No need to copy an option
letter, quote anything back, or use any particular vocabulary.>

**Your answer:** ______
