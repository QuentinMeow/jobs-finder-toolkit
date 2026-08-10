# Should the README's clone command name this repository's real GitHub owner?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-09
- **Source**: [README quickstart clone line](../../../README.md)
- **Blocks**: nothing. The quickstart's first command already parses in zsh; this
  only decides whether it can be pasted with no edit at all.
- **Default path**: the README keeps a quoted `<owner>` placeholder and tells the
  reader to paste the URL from the repo's green "Code" button. No agent writes the
  real owner handle into a tracked file.
- **Cost if wrong**: one-time
- **Safe to merge because**: nothing was written that needs undoing — the choice
  is one line of `README.md`, changed with a normal edit either way.

## Background

Issue #282: the quickstart's first line was

```
git clone https://github.com/<owner>/jobs-finder-toolkit.git && cd jobs-finder-toolkit
```

Unquoted, `zsh` (the macOS default shell) reads `<owner>` as an input redirection,
so the line fails with `zsh:1: no such file or directory: owner` and `git` never
runs. That part is now fixed: the URL is quoted, so a reader who forgets to
substitute gets a plain bad-URL error from `git` instead of a phantom filename.

The obvious *full* fix — hardcode this repository's real clone URL so the line can
be pasted verbatim — collides with the leak guard, and the collision is not
fixable from inside the public tree:

- `automation/publish/check_public.py::_identity_tokens` splits the configured
  candidate name on non-alphanumerics and makes every part of 3+ characters an
  identity token.
- Token matching is a **case-insensitive substring** test
  (`find_token_and_pii_violations`: `low in rel_lower`, and the same for content).
- This repository's GitHub owner handle **contains the owner's first name as a
  substring**, so with a real `config.yaml` the guard reports
  `CONTENT README.md:<line> (token: '<first name>')` — verified locally by running
  the staged guard with `JOBHUNT_PERSONAL_TOKENS` set to just the first name;
  exit 1, one finding, that line.
- `private/leak_safe_words.txt` cannot exempt it: `_apply_safe_words` is applied
  **only** to `_overlay_skill_name_tokens()` (check_public.py line 767), never to
  `identity_tokens()`. There is deliberately no way to exempt an identity token.

So hardcoding the URL would leave the armed pre-push hook and the armed CI leak
guard permanently red on `README.md`, with no supported way to silence them.

## Options

The axis: how little the newcomer has to edit, against whether the leak guard
stays honest.

### Option A — keep the quoted placeholder (default path, shipped)

`git clone "https://github.com/<owner>/jobs-finder-toolkit.git"`, plus prose
telling the reader to paste the URL from the green "Code" button or their fork.
Costs the reader one substitution. Leaves the guard untouched.

***Example consequence:*** a newcomer pastes all three quickstart lines, sees
`fatal: unable to access 'https://github.com/<owner>/...'`, reads the sentence
directly under the block, pastes the real URL, and is running a minute later —
instead of googling why their shell says a file called `owner` is missing.

### Option B — hardcode the URL and teach the guard about the repo's own remote

Add a narrow, explicitly-named exemption to `check_public.py` — e.g. a constant
holding this repository's own `owner/repo` slug, whose occurrences are not counted
as token findings — then write the real URL into the README. The guard keeps
catching the owner's name everywhere else; it stops catching it in the one string
that is, by construction, already public and already in every user's
`git remote -v`.

***Example consequence:*** the quickstart becomes genuinely copy-paste-able, and
the next time someone edits `check_public.py` they have to reason about one more
exemption — and a future rename of the repository silently re-arms the finding
until the constant is updated.

## Recommendation

Option A for now. The shipped fix already removes the reported failure (a shell
parse error naming a nonexistent file), and Option B changes `automation/publish/`
— which `CONTRIBUTING.md` marks as an extra-careful-review leak-defense area — to
buy one saved paste. If you want Option B, it is a small, self-contained change
and worth doing deliberately rather than as a side effect of a docs fix.

**Strongest case against this:** the whole point of a quickstart is that it runs
without thought, and a placeholder is exactly the kind of small friction that
loses a first-time reader. The guard is protecting against a *substring* of a
public GitHub handle — a false positive by any reasonable reading — and the repo
already accepts a narrow allowlist for intentionally-shipped binaries
(`BINARY_ALLOWLIST`), so one more explicitly-named exemption is not a new kind of
thing.

**Confidence:** high on the mechanism — I ran the staged guard armed with only a
first-name token and reproduced the finding on the exact README line, and I read
`_apply_safe_words`'s single call site to confirm identity tokens cannot be
exempted. I did **not** check the real `config.yaml` (it is git-ignored and absent
from this worktree), so the conclusion assumes `candidate_name()` yields the first
name that the handle contains.

**Your answer:** ______
