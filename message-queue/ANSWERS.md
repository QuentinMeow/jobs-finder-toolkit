# ANSWERS — the owner's batch answering surface

Agents never wait for an answer. Questions are filed with a default path, merged,
and shipped; you answer here whenever a batch has landed and you have time.

**How to use this file**

- One `## <slug>` block per item, where `<slug>` is the decision's filename
  without `.md` (`message-queue/needs-human/decisions/<slug>.md`).
- Write anything: a chosen option letter, a sentence, "keep the default", or a
  question back. Prose is fine — you are not filling a form.
- A bundled question (one file, several sub-decisions) takes sub-ids that match
  the item's own numbering: `## process-weight-what-to-cut / D3`.
- An answer that is itself a question stays open: the agent answers it inside
  the item with concrete examples and leaves the item filed.
- Answering here and answering in the item's own `**Your answer:**` line are
  equally valid. If both exist and disagree, **the item's own line wins** —
  it sits next to the context you were reading.

**What the agent does next**

On its next session an agent folds every filled block in one pass: a single
`Status: folding` commit for the whole pass, then the per-item work (fold into
the affected docs, record in `memory/decisions/`, delete the queue item), then
delete the folded blocks from this file. Your text is never edited or deleted
while it is still unfolded.

What is open, grouped by cost class (`recurring-loss` and `data` are the two worth your
time first; `ratify` items only bless what already ships):

```bash
grep -H '^- \*\*Cost if wrong\*\*' message-queue/needs-human/decisions/*.md | sort -k2
```

---

<!-- Add ## <slug> blocks below this line. -->
