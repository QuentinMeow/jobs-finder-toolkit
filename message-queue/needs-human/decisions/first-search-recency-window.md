# Should a company's FIRST-ever automated search use a wider recency window?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31 (public surface for a question first raised in the overlay on 2026-07-26)
- **Source**: [`search_jobs.py`'s recency gate](../../../skills/job-search/scripts/search_jobs.py) vs [`company_roles.py --match-only`](../../../skills/job-search/scripts/company_roles.py), which disagree by design
- **Blocks**: nothing. Every run still works; the cost is silent, not loud.
- **Default path**: **no code change.** Keep the narrow recency default for every run, and hand-run a wide refilter when a company is being searched for the first time. This is the only open default in either queue whose cost is *missed opportunities* rather than tidiness — that is why it is surfaced here rather than left to age.
- **Cost if wrong**: recurring-loss
- **Safe to merge because**: the narrow window is the shipped behaviour and a wide refilter can be
  hand-run per company at any time — but a posting that ages out between runs is not recoverable,
  which is why this ranks above every other open item.

## Background

Two scripts in `skills/job-search/scripts/` answer "what is open at this company?" differently,
and the difference is invisible unless you run both:

- **`search_jobs.py`** applies a `date_ok` gate that drops any posting older than the profile's
  `max_age_days` (the shipped template sets 3). For a **recurring** search this is exactly right —
  freshness is the product, and re-surfacing month-old reqs every run is noise.
- **`company_roles.py --match-only`** applies location and match filters and **no recency filter
  at all**.

For a company that has **never been searched before**, there is no "recurring" to speak of: the
whole board is new information, and the recency gate silently discards roles that are still live
on the employer's ATS purely because they were posted a while ago. The two scripts then disagree
about the same company, and the one an agent reaches for first is the one that drops them.

**This is a decision about public code**, which is why it is filed here. Its evidence is not
public: the concrete instances that surfaced it are real postings at real employers, recorded in
the overlay's own queue, and `AGENTS.md`'s leak rule forbids naming them in this tree. Two things
can be said without naming anything: the affected postings were **US-remote, carried no visa
denial, matched on every other gate, and were still open on the employer's ATS** — one of them by
a wide margin of age, one by about six weeks. Neither reached a draft.

**What the owner needs to know that this file cannot show:** the overlay item carrying that
evidence is a separate repository and was not edited by the change that filed this. It should be
read alongside this one.

## Options

### Option A — leave it; hand-run a wide refilter on a first search
Zero code, no risk of flooding ordinary runs with stale reqs. **Cost: it relies on an agent
remembering to do the wide pass**, on exactly the run where nobody has established a baseline yet.
The recovery is a refilter of an existing snapshot — no re-fetch — but nothing prompts it, and a
missed first-search role is not recorded anywhere as missed.

### Option B — widen the window automatically on a company's first search
Detect "we have never searched this company" (the company-search log already knows) and apply a
wide `max_age_days` for that run only, narrowing to the profile default on every subsequent run.
**Cost:** a first search returns a much larger, older set that needs curation, and "first search"
has to be defined against a log that can be wrong after a folder is deleted. It also means two
runs of the same command against the same company can legitimately return different sets, which is
a property worth deciding on deliberately rather than discovering.

### Option C — make the two scripts agree instead
Give `company_roles.py --match-only` the same recency gate, so the disagreement disappears and the
narrow window is the single answer. Cheapest to reason about, and the one option that makes the
loss *complete* rather than recoverable — the roles simply stop being visible anywhere.

## Recommendation

**Option B, scoped narrowly**: widen only on a first search, only for that run, and print the
widened window in the run's header so the output says why it looks different. The asymmetry that
motivates A — freshness matters on repeat runs, coverage matters on the first — is real, and A
already concedes it by prescribing the manual wide pass; B is the same policy with the "remember
to do it" step removed. Reject C: it resolves the disagreement by deleting the more informative
half.

If you prefer A, the honest version of it is to make the wide first pass a **step in the
job-search skill**, not a recipe in a queue file, so it is instruction rather than folklore.

**Your answer:** (2026-08-02, in chat) Option B. For a first search we always find all
available roles, and match older roles by default.
