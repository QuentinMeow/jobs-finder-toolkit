# todo/reviews/ — things awaiting (optional) human eyes

One file per item an agent thinks the owner may want to look at: a design
doc awaiting a read, a data-quality queue worth a glance (e.g. the job
store's suppressed-postings queue), a risky change that shipped with a
"sanity-check me" note. **Everything here is optional** — nothing blocks on
a review, and declining to look is a valid resolution.

## File format

```markdown
# <What to look at, in plain words>

- **Filed**: YYYY-MM-DD
- **Look at**: <path(s) or command to run>
- **Why you might care**: one or two sentences
- **If you do nothing**: what happens by default (must be safe)
- **Resolution**: (owner or agent fills in when handled/declined/stale)
```

Any session's boot ritual (step 4 in `AGENTS.md`) sweeps this folder:
items with a filled Resolution, or older than 30 days, are deleted —
nothing rots here. Private-scope items go in `private/todo/reviews/`, and
item text in THIS folder must stay leak-clean: point at private paths, never
quote private content (no real companies + dates, no message subjects).
