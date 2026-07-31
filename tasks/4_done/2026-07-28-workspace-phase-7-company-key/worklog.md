# Worklog — 2026-07-28-workspace-phase-7-company-key

## 2026-07-30

Recon first, because every count in the plan turned out to be stale and one of its premises was
wrong. Two parallel read-only passes — one over the public machinery, one measuring the overlay —
then a design pass, then implementation.

**What recon changed.** Four of the plan's five headline numbers were wrong (243 folders not 242,
214 strings not 213, 95 unresolvable not 94, 126 `notes.md` not 135). More importantly the
*premise* was wrong: the 44% unresolvable is not spelling drift, it is ~85% employers structurally
absent from a registry that only holds companies with a supported ATS token. That is why the phase
needs a key space rather than a better alias list — and it means "retire the other three alias
registries" was never implementable.

Recon also found that `private/companies/_index.yaml` already had a public consumer, a hardcoded
path literal, and a public test fixture pinning its shape — so the file was being read by a leak
detector that had never once run, because the file did not exist.

**Order of work.** The private index landed *second*, deliberately: it arms the detector, and the
public commits that follow it are the ones most likely to leak. That sequencing is not in the plan.

**Three things I got wrong and had to measure my way out of.**

1. I would have approved routing the gate's path literal through `config.companies_root()` as an
   obvious tidy-up. The design showed it silently disarms the detector once phase 8 creates
   `examples/companies/`, because `overlay_mounted()` returns True under the example config.
2. I specified a minimum alias length to suppress detector noise. Run against the real index it
   deleted two legitimate abbreviations. Corrected mid-flight to a stop-list.
3. The implementer then found my correction was *also* wrong in a way neither of us had seen: a
   large stop-list is a detector-blinding operation, because publishing a word puts it in the
   public tree and the detector permanently subtracts anything already there. Its ~620-word list
   was withdrawn for a 152-token one, every token verified already present.

Each was caught by running the thing against real data rather than by reasoning about it.

**What the implementer found that nobody asked for.** `--file-retries` writes tracked files whose
bodies repeat a finding's subject and message; the new check's subjects are application paths and
company keys. One run would have committed an application slug into the public tree, and the leak
guard would not have stopped it because company names are not identity tokens. Closed with three
lines and two tests.

**What was cut, and why.** The `company_key` pass over 243 `meta.yaml` files waits on seven owner
judgements — settling keys before 243 files point at them is cheaper than re-pointing them. The
email-assistant `durable:`/`promote` work went to 7c because it is greenfield (no Python writes
`notes.md` at all today) and its first consumer *moves files*, which should not run on
44%-hand-judged data in the change that creates it.

**Where it stands.** Public stack: `chore/01-correct-stale-tailoring-card-pointer` →
`feat/02-company-index-module`. Private: one PR holding the index and the seven questions.
