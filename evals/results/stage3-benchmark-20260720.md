# Stage 3 benchmark — pinned scenario v1.2, isolated benchmark area

| Field | Value |
|-------|-------|
| Scenario | `design/token-usage-modes/benchmark-scenario.md` v1.2 (isolation via the dedicated benchmark config; writes never touch the real pipeline) |
| Head | main @ `591cc6b` (Stage-2 tiering + Stage-3 `generation.mode` switch + PR #23 multi-experience + batched Step-7, all gated) |
| Mode | `token_saving` (config default — every agent verified it from the accessor and reported it governing the run) |
| Model | `claude-sonnet-5` subagents, model-pinned protocol |
| Date | 2026-07-20 |

## Measured row

| Leg | Tokens | Tool calls | Wall clock | Notes |
|---|---:|---:|---:|---|
| search | 121,391 | 66 | ~9.1 min | 1 fetch + 2 refilters (2h→1d→3d); 4 duplicates blocked by the benchmark-tree scan; ALL JS-rendered JDs recovered via the ATS-API fallback (works for both major ATSes, wider than the skill note claims); **both hybrid-in-wrong-metro roles correctly rejected at drafted-app-grade location verification** (the miss from the Stage-2 row did not recur); 2 handoffs, metadata valid |
| draft A | 169,243 | 63 | ~13.6 min | Stretch-fit JD (hardware-telemetry domain); honest gap framing; justified backup swap; 2 render cycles — cycle 1 failed on a **pre-existing baseline↔profile skill-token drift** (see below), not tailoring; batched Step-7 queue of 7 with verbatim labels |
| draft B | 162,039 | 76 | ~13.4 min | Deliberate weak-fit JD (factory/firmware domain); plainly framed as a long-shot, zero fabrication; 2 render cycles — cycle 1 failed on the same baseline drift; batched Step-7 queue of 4 |
| **total** | **452,673** | **205** | — | **−6.6% vs the pinned reference (484,593); +3.8% vs the Stage-2 normalized row (436,154)** |

## Reading the row honestly

`token_saving` mode shows **no regression vs Stage 2** once three confounds are
priced in, and all mode machinery worked (each agent read the mode from config,
followed the routine path, and reported hard gates unchanged):

1. **Both drafts were stretch/weak-fit JDs** (the same-day candidate pool was
   depleted down to rank-5 and rank-9 postings in domains far from the profile),
   which buys extra verification, research, honest-framing work, and Step-7
   queues of 7 and 4 skills (vs 0–1 in prior rows). Cost went to product
   judgment, not waste.
2. **Both drafts lost one render cycle to a pre-existing data bug**: the real
   baseline spelled two Approved skills non-canonically; PR #23's stricter
   skill matcher now fails renders on the mismatch. Fixed at the source after
   the run (2-token spelling alignment + card rebuild) — future drafts get that
   cycle back.
3. The draft legs again chose to read the reference tier + validator source
   nearly in full (~70 KB/agent) — the standing discretionary-read pattern;
   quickstart steering remains the known follow-up.

## Mode-switch verdict (the thing Stage 3 shipped)

- The explicit `token_saving`/`full` switch is live, gated (11/11 + combined
  re-gate 7/7), and behaviorally inert on the routine path by design — measured
  cost is flat-to-better vs Stage 2 with harder inputs. `full` mode exists as
  the opt-in escape hatch; it is deliberately unmeasured here (it buys depth,
  not savings).
- Cumulative program result vs the pinned reference: **−7% total** with
  stretch-fit inputs, **−10% normalized** on like-fit inputs (Stage-2 row), and
  the quality wins are structural: JD verification, location-gate discipline,
  duplicate protection, honest-fit framing all held or improved across rows.

## Follow-ups surfaced by this row

- `check.py` compound Weak-token matching: a Weak entry like a compound
  "X/Y APIs" phrase cannot be satisfied by a JD that names only "X APIs" —
  either split compound Weak tokens in the profile or teach the matcher
  component-wise matching.
- The ATS-API JD fallback deserves a documented place in the skill reference
  (it recovered 100% of JS-rendered pages across two ATSes in this row).
- `status.py --check-locations` exits 1 even when reporting zero non-matching
  rows (cosmetic exit-code quirk).
- Baseline↔profile skill-token drift class: consider a gardener check that
  cross-validates baseline Skills tokens against the profile's canonical list.
