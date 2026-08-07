---
name: explain-clearly
visibility: public
description: Write replies a person can understand without opening a single file — define every unfamiliar noun by what it does, state whether a thing exists, lead with the result instead of a chronology, and give the number or say plainly that there is none. Use before sending any reply that reports work, results, findings, a recommendation, or a decision; when the user says a reply was confusing, unstructured, a play-by-play, or asks "what does this actually mean"; and when writing a PR body, handover, or verification record.
---

# Explain Clearly

**One test governs this whole skill: could someone who has read none of your work,
opened none of your files, and does not know this codebase act on your reply?**

This is the HOW of writing to the owner. The WHAT — the five-part reply, the PR
`## What needs you` section, the handover — lives in
`docs/handbook/reporting-to-the-owner.md`, and this skill never restates it.
Read that for structure; read this for whether the words land.

## The four checks, before you send

1. **Every unfamiliar noun is defined by what it does, at first use.**
2. **Anything whose status changed says whether it exists — before and after.**
3. **The reply opens with the result, not the story of how you got there.**
4. **If they asked for a number, line one is the number or "there is none".**

If any check fails, the reply is not ready. They take about a minute.

---

## 1. Define by function, at first use

A reader cannot evaluate a thing they cannot picture. Name it, say **what class of
thing it is**, then **what it does** — the classic term/class/characteristic triad.
One clause is usually enough.

You are most likely to break this rule for a thing that **does not exist yet**:
a proposal, a deferred component, a rejected design. There is no file to point at,
so the name feels like the whole story. It is not.

> ❌ "The guarded executor was not built."
>
> ✅ "A guarded executor — **a command-line tool** that would **carry out the safe,
> mechanical steps of a post-merge cleanup for you: take a recovery checkpoint,
> replay your uncommitted edits onto the new file layout, then run the checks,
> while refusing anything that needs judgement** — was never built."

The bad version is four words the reader cannot act on. The good version is one
sentence, and now they can argue with the decision.

**Applies to:** components, flags, files, gates, roles, metrics, and any term you
imported from a design document. **Does not apply to:** words in ordinary English,
or a term you defined earlier *in the same reply*.

Two failure shapes to watch for:

- **Borrowed jargon.** A phrase from a spec or another agent's report feels
  defined because *you* read its definition. The reader did not.
- **Repetition mistaken for definition.** Naming a thing six times does not
  define it once.

## 2. Say whether the thing exists

"Was not built", "we dropped it", "it's gone", "removed" — each has more than one
reading. Ambiguity about existence is the most expensive kind, because the two
readings imply opposite actions from the reader.

Give the before and the after in plain existence terms, and say explicitly when
nothing was destroyed:

> ✅ "It never existed and it still does not exist. It was a **proposal** in the
> task description. No code for it was ever written, by anyone. I chose not to
> write it. Nothing was deleted or disabled."

> ✅ "It existed and worked. **I deleted it**, because …. To get it back: `git revert <sha>`."

State which of these four it is, every time: **never existed · newly created ·
changed · removed**.

## 3. Lead with the result, never the chronology

Order by what the reader needs, not by what happened when. A reply organised as
"first I did A, then B, then C" is a log; the reader has to do the summarising you
were supposed to do.

Open with: **what is true now that was not true before, and must they act?**

> ❌ "I read the task, then spawned four agents, then integrated their work, then
> ran the gates, then found some defects, then fixed them."
>
> ✅ "The branch now has working telemetry and a read-only planner; all gates pass.
> One decision needs you. The route there: four parallel agents, then two review
> passes that found 16 defects."

Method belongs *after* the result, compressed, and only where it changes how much
the reader trusts the result.

## 4. Give the number, or say there is none — first

When the request was quantitative ("how much faster?"), the answer's *first line*
is the measurement or its absence. Burying "I did not measure this" under a list
of accomplishments reads as a claim of success.

> ❌ opens with five things built; mentions on line 40 that nothing was timed.
>
> ✅ "**There is no measured speed improvement.** No before-measurement existed and
> I did not produce an after-measurement. What I built is the instrument that
> would produce one. The numbers I *do* have are about output size, not time: …"

Never let a real, impressive, *unrelated* number stand in for the missing one.
A 99.9% reduction in file size is not an answer to "how much faster".

## 5. The second-reading test

Before sending, re-read each sentence asking: **is there another way to read
this?** If yes, rewrite until there is one. Especially check:

- **negatives** — "not built", "no longer fails", "never runs";
- **pronouns and "it"** across a sentence boundary;
- **"we"** — you, the user, or both?
- **passive voice with no actor** — "the check was updated" hides who acts next;
- **counts without units or scope** — "16 fixed" out of how many, found by whom?

## Writing in the reader's world

Describe an effect in terms of the reader's task, not the codebase's internals.
The reader owns a job hunt; they do not own a classifier.

> ❌ "`classify_dirty` now grades rename evidence by R100 provenance."
>
> ✅ "When a merge has moved your files, the tool now proves which ones moved
> untouched and which were also edited — the second kind still needs you."

Keep one concrete anchor per claim: a command they can run, a number, a file they
would look at, or an outcome they would notice.

## Length

Clarity beats completeness: a long, thorough reply gets skimmed, and a skimmed
reply is an unread one. Cut anything that does not change what the reader thinks
or does. Detail belongs in the linked task, verification record, or handover —
and the link says what it holds so they can decide not to open it.

## Self-check

- [ ] Every noun a newcomer could not look up is defined by function at first use.
- [ ] Every status change says: never existed / created / changed / removed.
- [ ] The first sentence states the result and whether they must act.
- [ ] A quantitative question gets its number, or an explicit "not measured", first.
- [ ] No sentence has a second reading.
- [ ] No claim is method-only ("I ran X") without its effect.
- [ ] Someone who opens nothing can still act.

## When the user says the reply was unclear

Treat it as a defect report about the reply, not about the work. Do not re-send a
longer version — that is the usual instinct and it is wrong. Find which of the
four checks failed, fix that, and keep the reply the same length or shorter.
