# message-queue/needs-agent/requests/ — human → AI drop box

Drop anything here, in any shape — a one-line ask, a half-formed idea, a
pasted error. No format requirements; this is the only folder in the repo
where unstructured notes are welcome. Example:

```markdown
# faster-jd-fetch.md
fetch_jd feels slow on workday pages lately, look into it when convenient
```

**Agent contract** (canonical version: `AGENTS.md` → "Async Collaboration"
boot ritual): at session start, list this folder. For each item: do it now
(if small and in scope), or convert it into a `tasks/0_backlog/` item or
`message-queue/needs-human/decisions/` question — then delete the request file in the same commit
that files its successor. If the right response is an *answer* to the
owner, append it under a dated `## Agent reply (YYYY-MM-DD)` heading and
LEAVE the file — the marker exempts it from reprocessing, and it is deleted
only after the owner acknowledges (edit or chat). The overload valve and
never-skip-silently rule are defined in the boot ritual.

Private-scope asks (real companies, dated personal facts) go in
`private/message-queue/needs-agent/requests/` instead.
