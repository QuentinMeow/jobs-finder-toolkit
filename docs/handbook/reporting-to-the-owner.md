# Reporting to the owner

This doc owns the PROSE for every surface a human reads: the final reply that
ends a session, the ask section of a PR body, and the handover. It does not own
their structure. Field schemas live in `templates/` (copy one, never write a
format from memory); the PR body format lives in
`skills/github-workflow/SKILL.md`; the queue's routing and ranking live in
`message-queue/README.md`. This doc is what fills them in.

The reason it exists: in `async` mode the agent decides everything reversible on
its own and the work merges before the owner reads a word of it
(`docs/handbook/collaboration-modes.md`). The reply is not a summary of a
conversation the owner sat in. It is the only view they get of decisions taken
in their name.

## 1. Three layers, never inverted

Every surface is written in three layers, in this order:

1. **One sentence** — does the reader need to act?
2. **One short paragraph** — what it was before, what broke, what is true now,
   and why that response. At most four moving parts. Past four the reader stops
   holding the thread.
3. **The depth** — last, or behind a link.

The order you worked in is not the order the reader needs. You found the bug
last and it is the first thing they want; you spent the session on the refactor
and they may never need to know it happened.

## 2. The final session reply — five parts, in this fixed order

**(1) Blocked and needed.** Whether anything is blocked, and whether anything
needs them right now. Never open with process. Never claim a clean result while
an open risk contradicts it — "all gates green" is false reporting when a gate
was red and you filed it instead of fixing it.

**(2) What was done, as outcomes.** Three to six lines. Each line reads
`<what is different> — <how it was before>`. Not the steps, not the files
touched.

**(3) What was decided for them.** One line each: what was chosen, why, and what
undoing it would cost. Include the obviously-right ones — the owner cannot tell
an obvious decision from a load-bearing one until they see it. This part is not
optional. `async` mode means every reversible fork was settled without them, so
if this part is empty on a session that did real work, the decisions were still
made; they just were not reported.

**(4) What they owe.** Ranked by `Cost if wrong`, worst first
(`message-queue/README.md` defines the values). Each entry carries four things:
the ask as a link to its queue file, why it matters, what happens if they do
nothing, and what you would pick plus the strongest reason against it. A bare
item name is not an entry.

**(5) Where it is.** PR numbers, branch names, tasks moved between status
folders.

## 3. Repeat every still-open item in every reply

Every reply lists every open `needs-human/` item, not only the ones filed this
session. An unanswered item that stops being mentioned is an item that silently
died — nothing else in the repo surfaces one to the owner on its own.

A long list may be grouped: this session's items first, then the ones already
waiting, one line each. Grouping is presentation. Dropping an item is not
presentation.

## 4. The PR ask section

A PR that relies on a pending default path carries a `## What needs you`
section, directly after `## What changes for you`. It is a numbered list, ranked
worst-first, and each item carries the same four fields as part 4 of the reply:
the link, why it matters, what happens on silence, and your pick with the
strongest argument against it.

That section **projects** live message-queue items. It never originates an ask.
Something that exists only in a PR body is not an ask at all: PR bodies are not
swept by the boot ritual, not ranked by `Cost if wrong`, and not reachable once
the PR merges. File the queue item first, then project it. When there is
genuinely nothing to project, the section says so in one fixed sentence —
`.github/pull_request_template.md` carries the exact wording.

## 5. Rules that hold on every surface

- **Effect, not mechanism.** The test: delete every proper noun from your
  sentence. If nothing meaningful survives, you described mechanism. "The
  reconciler now calls `parse_last_updated`" survives as nothing; "a roadmap
  dated `whenever` now fails the commit instead of passing" survives.
- **Every change claim carries a before and an after** — or says plainly that
  there is no observable difference. "No observable difference" is a legitimate
  and useful answer. A missing before is not.
- **State uncertainty as a number, or say you did not measure.** Likelihood and
  confidence are separate axes: "this probably fixes it, and I am sure it breaks
  nothing else" is two claims, and one of them may be the weak one. Repository,
  session, PR, gate, and verification reporting is always factual. A direct-human
  exception for a named behavioral answer does not authorize a fabricated
  measurement here or anywhere outside that answer and its private disclosure
  ledger. "I did not measure it" is a complete answer.
- **Gloss a repo-local term once, at first use.** "The leak guard (the check
  that scans every tracked file for the owner's real name)". Half a sentence, in
  every document, every time — the reader may not have read the last one.
- **Name the actor.** "The check was updated" hides who acts next. Say who did
  it, and say who has to do the next thing.
- **Self-contained on the decision, linked on the evidence.** The reader decides
  from the reply alone. Every evidence link says what it holds and why they need
  not open it: "the full gate log, if you want each exit code beside its SHA".
- **Banned:** "just", "simply", "obviously", "as discussed", "various fixes".
  The first three tell the reader their difficulty is their own fault; the
  fourth cites a conversation that may not have happened; the fifth is a count
  standing in for content. The PR-body checker
  (`skills/github-workflow/scripts/check_pr_body.py`) bans a separate list of
  marketing words. These five are in addition, and nothing checks them.

## 6. Before you send

- Does the first sentence say whether they need to act?
- Is every "what was done" line a difference, with its before?
- Is there a "what was decided for you" part, including the easy calls?
- Is every open item listed — including ones carried over from earlier sessions
  — with a link, why it matters, and what happens on silence?
- Does any claim of a clean result survive re-reading the gate exit codes?
- Would this still be actionable to someone who read nothing else?
