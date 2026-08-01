# `review-window --limit` silently clamps to 50, one sentence from a documented `--limit 2000`

- **Priority**: P2 (someday)
- **Area**: email
- **Source**: doc-vs-code contradiction audit, 2026-07-31 — filed as a task rather than an
  owner decision because both halves have an obviously right answer
- **Claimed-by**:

## Goal

The email skill stops telling agents to pass a `--limit` that `review-window` discards, and
the clamp stops being invisible when it fires.

## Context

`skills/email-assistant/SKILL.md:131-133`, step 1 of Pipeline Status Reconciliation:

> 1. Run `review-window --limit 50`, then widen the read-only scan with Inbox and Deleted
>    Items when the user asks for a mailbox-wide status review. Expand up to `--limit 2000`
>    only when a named older thread or outcome is still missing.

`automation/shared/mail/providers/outlook_graph/provider.py:248-249`:

```python
def review_window(self, limit: int = 20) -> dict[str, Any]:
    bounded = max(1, min(int(limit), 50))
```

An agent reading the numbered step in order runs `review-window --limit 2000`, gets 50
messages, and is told nothing. Argparse imposes no cap, so the value is accepted; the clamp
is silent.

**Where the 2000 belongs.** `MAX_LIST_LIMIT = 2000` (`provider.py:37`) is applied only in
`_list_folder` (`:164`) — i.e. to `inbox`, `sent` and `deleted`. The skill's own examples at
`:65,67,69` use it correctly against exactly those three commands. So the sentence in step 1
has attached the right number to the wrong command; the fix is to attach it back and say
`review-window` caps at 50 regardless.

**Why the silence matters more than the wrong number.** The agent that reads step 1 is doing
a mailbox-wide status reconciliation and believes it widened the scan by 40×. It did not.
Everything downstream — "no recruiter mail for this application" — is then drawn from a
window the agent thinks is 2000 deep and is 50 deep. A wrong flag that fails loudly is a
typo; a wrong flag that succeeds quietly produces confident wrong conclusions.

**Both halves have an obvious answer**, which is why this is a task and not a decision item:
the documented flag value is simply wrong for that command, and a clamp that changes what
the caller asked for should say so. The only judgement left is *how* it says so — a stderr
note, or an argparse-level rejection of a `--limit` above 50 for this subcommand. Pick one
in the PR and say why; either is defensible and both are reversible.

## Definition of done

- [ ] `skills/email-assistant/SKILL.md:131-133` attaches `--limit 2000` to the commands it
      actually applies to (`inbox`/`sent`/`deleted`) and states that `review-window` caps at
      50 whatever is passed
- [ ] `review_window` no longer clamps in silence — it warns, or the CLI rejects an
      out-of-range `--limit`; the PR says which and why
- [ ] A test in `automation/shared/mail/` pins the chosen behaviour at the boundary
      (`--limit 51`)
- [ ] `.venv/bin/python automation/shared/mail/check_mail_safety.py --consumer skills/email-assistant/scripts`
      stays clean
- [ ] Canary decision for the `SKILL.md` edit recorded per `evals/README.md` — the
      `email-assistant` set exists (`evals/canaries/email-assistant.yaml`), so a skip needs
      its one-line rationale in the PR
