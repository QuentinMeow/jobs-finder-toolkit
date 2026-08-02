# The leak guard silently narrows its own token set when a token file is unreadable

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: found while implementing
  `2026-07-31-leak-guard-cannot-read-non-utf8-text`, 2026-08-02 — the same
  fail-open class, one layer up, on the guard's ARMING INPUT rather than on the
  files it scans
- **Claimed-by**: implementing agent, 2026-08-02

## Goal

Make a personal-token file that EXISTS but cannot be READ an error that refuses to
certify, while a token file that is simply ABSENT stays legitimate.

## Context

`automation/publish/check_public.py` read its supplementary token file like this:

```python
def _tokens_from_file(path: Path) -> set[str]:
    toks: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return toks
```

`supplementary_tokens()` calls it to build the employer / school / product token
set. A permission error, an I/O error, a dangling symlink, or one non-UTF-8 byte
made every one of those tokens vanish — and the guard still printed
`OK: no public-repo leaks detected. Safe to publish.` It could not distinguish
"file absent" (legitimate: a public clone has no overlay, and the guard must still
run) from "file present but unreadable" (a silently narrowed scan).

The asymmetry is the finding. For the files it SCANS the module fails CLOSED — an
unopenable tracked path is check 8, `UNREADABLE_OPEN_FAILED`, exit 1. For its own
arming input it failed OPEN. A guard that quietly forgets what it is looking for
still reports a clean tree, which is the worst possible failure mode for a
publish gate.

Note the split this does NOT change: the supplementary set can never ARM the
guard (`identity_tokens()` is the arming channel, and an empty one is exit 2).
This is about the supplementary set being silently INCOMPLETE while the guard is
armed and therefore willing to certify.

## Definition of done

- [x] A token file that exists but cannot be read is a violation that refuses to
      certify; an absent one is not.
- [x] Encoding is no longer a way to lose the set: the file is decoded losslessly
      (`_decode_lossless`), so one stray byte cannot drop every token.
- [x] Both branches asserted by test — `automation/publish/tests/test_leak_guard.py`,
      class `TokenSourceUnreadableTests` (unreadable, absent, dangling symlink,
      non-UTF-8, and the caller-supplied-tokens case that must stay inert).
- [x] The refusal is named in the report (`[9] Unreadable personal-token source`)
      and in the module docstring's numbered check list.
