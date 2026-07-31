# Verification — 2026-07-30-company-research-shipped-vs-beta-needs-a-maturity-check

Real output, captured 2026-07-31 on `fix/10-company-research-correctness`.

## The failure shape, reproduced live against a public docs site

The task says a docs page read "Available on all plans" for a product that had been in open
beta for ~15 months, and that the maturity signal lives in the body text the skill never
names. Reproduced on the public docs of the same vendor the canary set already uses as its
real-company fixture:

```
$ STRIP='import sys,re,html;t=sys.stdin.read();t=re.sub(r"<(script|style).*?</\1>","",t,flags=re.S);t=re.sub(r"<[^>]+>"," ",t);print(re.sub(r"\s+"," ",html.unescape(t)))'
$ curl -s -L -A "Mozilla/5.0" "https://developers.cloudflare.com/ai-search/platform/limits-pricing/" \
    | .venv/bin/python -c "$STRIP" \
    | grep -o -i -E ".{60}(open beta|private beta|generally available|early access).{60}"
dflare will contact you with next steps. Pricing During the open beta, AI Search is free
within these limits. Workers AI and AI G
```

The stage word is in the **body of the pricing page**. That is exactly the class of source
the skill did not name, and the class the new "Maturity fetches" recipe fetches.

## The counter-check that corrected the task's wording

The task (and the eval record) say docs landing pages "carry no maturity badge". On
2026-07-31 that vendor's landing page did carry one:

```
$ curl -s -L -A "Mozilla/5.0" "https://developers.cloudflare.com/ai-search/" \
    | .venv/bin/python -c "$STRIP" \
    | grep -o -i -E "(open beta|private beta|generally available|early access|\bbeta\b)" | sort | uniq -c
   1 Beta
```

So the absolute claim does not hold, and `reference.md` was worded to the claim that does:
a landing page *sometimes* carries a badge, and **its silence proves nothing**. The
SKILL.md not-evidence list says the same thing — it rules out "a docs landing/nav page
carrying no stage word" and "the **absence** of a beta badge", never the presence of one.

## The plain-text docs mirror is real, and must be grepped rather than read

```
$ curl -s -o /dev/null -w "HTTP %{http_code} size %{size_download}\n" -L \
    "https://developers.cloudflare.com/ai-search/llms-full.txt"
HTTP 200 size 1107419
```

1.1 MB for one product. `reference.md` therefore tells the agent to grep it, with that
figure and its date recorded so a future reader knows why.

## What the task claimed that did not hold

The task states the skill's guidance for establishing *shipped* "is only 'cite the
artifact'". It was not:

```
$ git show b7227ae97:skills/company-research/SKILL.md | sed -n '306,308p'
- **Already shipped** — AI features/products live in the hands of users or engineers,
  with dates and evidence (changelog, blog, release). Tag `[confirmed]`/`[likely]`.
```

The skill already named changelog / blog / release. The actual gap was three other things,
and those are what this change adds: no statement of what does NOT establish GA, no rule
for the ambiguous case, and no output marker for the maturity call. The task's headline —
four wrong "shipped" calls from following the skill's own sources — is unaffected.

## Budget after the edit

```
$ .venv/bin/python automation/metrics/instruction_budget.py --strict
skills/company-research/SKILL.md                       535  36022     9005        600      ok
OK: all instruction files within budget.
```

## Canary evidence

`evals/results/company-research-48f9b46a366e-20260731-correctness.md`. Four canaries run,
**4/4 rubric_pass**. The two runs that write `06` staged **22 products**, every one with a
quotable sentence and a URL, and:

- independently rediscovered the failure that filed this task — the AI-search product,
  `[open beta since 2025-04-07 - 15.8 months]`, established from the pricing docs **body**;
- found a longer one nobody had reported: a `[open beta since 2024-04-02 - 27.9 months]`
  sub-feature sitting inside a GA product, which is why the gate now says to classify a
  sub-feature in its own right;
- refused all three trap signals **by name in the output file** ("Available on all plans",
  "available to all <product> customers", and the absence of a badge);
- filed **six** products under `Maturity unverified` with the URLs checked. Zero open- or
  private-beta products appeared under "Already shipped" in either run.

The runs also found the gate's own fetch recipe was broken (see the task's worklog and the
eval record, finding 1) — the documented grep returned zero hits on a file containing the
answer three times, which the gate would have read as ambiguity. Fixed and re-verified.
