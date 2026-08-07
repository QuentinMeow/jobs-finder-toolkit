#!/usr/bin/env python3
"""Turn one phase-recorder log into a redacted time-accounting summary.

Reader half of ``automation/metrics/phase_recorder.py``: it reads
``logs/phases/<session>.jsonl`` and answers four separate questions that are
never conflated into one number —

    active            model/agent time INSIDE a named phase (a RESIDUAL, see below)
    local_subprocess  measured runtime of commands wrapped with `run`
    external_wait     DECLARED waits (a `--kind external` run, or an
                      `external_wait`-kind phase)
    approval_wait     DECLARED approval pauses (paired approval marks, or an
                      `approval`-kind phase)

plus ``unattributed``, itemised, which is the point of the tool: time whose kind
is unknown is NAMED, never absorbed into "active".

Usage:
    .venv/bin/python automation/metrics/phase_summary.py --last
    .venv/bin/python automation/metrics/phase_summary.py --session ID --json
    .venv/bin/python automation/metrics/phase_summary.py --last --markdown --out FILE

``active_s`` is a RESIDUAL, not a measurement: it is whatever is left after the
measured and declared classes and the unattributed items are removed. It mixes
model reasoning, token streaming, tool-result handling and short human turns,
undifferentiated. Calling it "reasoning time" would be a fabrication.

COVERAGE ALWAYS NAMES ITS DENOMINATOR. ``reference_source`` is either
``external_supplied`` (a total the operator read off the harness UI and passed to
``session end --external-total-s``) or ``recorder_span`` (the recorder's own
first-to-last event span). Against its own span, contiguous ``phase set`` makes
coverage 100% BY CONSTRUCTION and the number proves nothing — a coverage
percentage without its denominator is meaningless.

REDACTION IS STRUCTURAL. Every field of the summary is a number, a duration, or
a value from a closed enum: there is no free-text field, so no path, branch,
label, command line or repository name can survive into it. That is a stronger
guarantee than scrubbing free text with a filter, which fails open on any leak
shape it does not recognise. The leak guard's own scan runs over the RENDERED
output as belt and braces, not as the primary mechanism.

Exit codes: 0 normal · 1 ``--min-coverage`` unmet, or ``--strict`` with a
redaction hit · 2 session not found / log unreadable. ``--min-coverage`` is a
MANUAL verification-record aid; this module is deliberately absent from
``automation/gates/run_gates.py`` — a telemetry threshold that blocks a commit
turns an honesty tool into something people work around.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase_recorder as PR  # noqa: E402  (stdlib-only sibling module)

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA = "phase-summary/1"
DEFAULT_IDLE_THRESHOLD = 120.0

# Two events whose ``mono_epoch`` agrees within this many seconds share a
# monotonic origin. A larger shift means sleep / suspend / a clock step, so the
# monotonic difference across it is NOT trustworthy.
CLOCK_EPOCH_TOLERANCE_S = 2.0

EPS = 1e-9

CLASSES = ("active", "local_subprocess", "external_wait", "approval_wait", "unattributed")
UNATTRIBUTED_KINDS = ("pre_arm", "between_phases", "long_gap", "clock_skew",
                      "after_last_event")

# Closed enums. Anything outside them collapses to a safe placeholder rather
# than travelling into the summary as free text.
KNOWN_FIXTURES = frozenset({"recon-v1"})
UNKNOWN_PHASE_LABEL = "other"


# ── loading ──────────────────────────────────────────────────────────────────

def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _parse_ts(value):
    """Parse an ISO-8601 stamp defensively; ``None`` when unusable."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return None


def load_events(path: Path):
    """``(events, load_integrity)``. A malformed line is skipped and counted.

    An event without a numeric ``mono`` cannot be placed on the timeline at all,
    so it counts as malformed rather than being guessed at from ``ts``.
    """
    integrity = {"malformed_lines": 0, "unsupported_version_lines": 0}
    events = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            integrity["malformed_lines"] += 1
            continue
        if not isinstance(rec, dict):
            integrity["malformed_lines"] += 1
            continue
        version = rec.get("v")
        if isinstance(version, int) and version != PR.SCHEMA_VERSION:
            integrity["unsupported_version_lines"] += 1
            continue
        mono = _num(rec.get("mono"))
        event = rec.get("event")
        if mono is None or not isinstance(event, str) or not event:
            integrity["malformed_lines"] += 1
            continue
        rec["mono"] = mono
        rec["wall"] = _parse_ts(rec.get("ts"))
        events.append(rec)
    return events, integrity


def _missing_seq(events) -> int:
    """Gaps in the per-session counter — a lost or reordered line."""
    seqs = sorted(
        rec["seq"] for rec in events
        if isinstance(rec.get("seq"), int) and not isinstance(rec.get("seq"), bool)
    )
    if len(seqs) < 2:
        return 0
    return max(0, (seqs[-1] - seqs[0] + 1) - len(set(seqs)))


# ── timeline ─────────────────────────────────────────────────────────────────

def _build_axis(events):
    """Normalised ``t`` coordinates plus the indices where the clock jumped.

    ``mono`` is the arithmetic clock, but only while ``mono_epoch`` agrees: a
    machine sleep changes the monotonic origin, and the difference across that
    boundary is garbage. Where the epoch moved, the interval is measured on the
    WALL clock instead and remembered as a skew interval so the reader can
    classify it as unattributed rather than publish it as thinking time.
    """
    axis = []
    skew_gaps = []
    running = 0.0
    for index, rec in enumerate(events):
        if index == 0:
            axis.append(0.0)
            continue
        prev, cur = events[index - 1], rec
        prev_epoch, cur_epoch = prev.get("mono_epoch"), cur.get("mono_epoch")
        skewed = (
            isinstance(prev_epoch, (int, float)) and not isinstance(prev_epoch, bool)
            and isinstance(cur_epoch, (int, float)) and not isinstance(cur_epoch, bool)
            and abs(float(cur_epoch) - float(prev_epoch)) > CLOCK_EPOCH_TOLERANCE_S
        )
        delta = None
        if skewed:
            if prev.get("wall") is not None and cur.get("wall") is not None:
                delta = cur["wall"] - prev["wall"]
            skew_gaps.append(index - 1)
        if delta is None:
            delta = cur["mono"] - prev["mono"]
        if delta < 0:
            delta = 0.0
        running += delta
        axis.append(running)
    return axis, skew_gaps


def _clip(start, end, low, high):
    return max(start, low), min(end, high)


def _overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


# ── the summary ──────────────────────────────────────────────────────────────

def _display_phase(name):
    """Known phase names travel verbatim; anything else becomes a digest.

    An agent-chosen phase name is FREE TEXT (it could be a company name), so it
    can never appear in the summary. The digest still tells two unknown phases
    apart without naming either.
    """
    if isinstance(name, str) and name in PR.KNOWN_PHASES:
        return name, None
    if not isinstance(name, str) or not name:
        return UNKNOWN_PHASE_LABEL, None
    return UNKNOWN_PHASE_LABEL, PR.digest(name)


def _enum(value, allowed, default=None):
    return value if isinstance(value, str) and value in allowed else default


def summarize(events, load_integrity=None, *, idle_threshold=DEFAULT_IDLE_THRESHOLD):
    """Compute the redacted summary object from already-loaded events."""
    integrity = {
        "malformed_lines": 0,
        "unsupported_version_lines": 0,
        "missing_seq": 0,
        "unpaired_approval_marks": 0,
        "clock_skew_events": 0,
        "unmatched_phase_closes": 0,
        "session_end_missing": False,
        "accounting_error": False,
        "overlong_runs": 0,
    }
    integrity.update(load_integrity or {})
    notes: list[str] = []

    if not events:
        return _empty_summary(integrity, notes)

    integrity["missing_seq"] = _missing_seq(events)
    axis, skew_gaps = _build_axis(events)
    integrity["clock_skew_events"] = len(skew_gaps)

    # ---- session bounds -----------------------------------------------------
    start_index = next(
        (i for i, e in enumerate(events) if e.get("event") == "session_start"), 0
    )
    end_index = next(
        (i for i in range(len(events) - 1, -1, -1)
         if events[i].get("event") == "session_end"),
        None,
    )
    if end_index is None:
        integrity["session_end_missing"] = True
        end_index = len(events) - 1
    t0, t1 = axis[start_index], axis[end_index]
    if t1 < t0:
        t1 = t0
    recorder_span = t1 - t0

    external_total = None
    if end_index is not None:
        external_total = _num(events[end_index].get("external_total_s"))
    if external_total is None:
        for rec in events:
            candidate = _num(rec.get("external_total_s"))
            if candidate is not None:
                external_total = candidate

    reference_total = recorder_span
    reference_source = "recorder_span"
    if external_total is not None:
        if external_total + EPS < recorder_span:
            # A supplied total SMALLER than what we observed is a contradiction.
            # Silently clamping it would publish a number we know is wrong.
            notes.append(
                f"clock_disagreement: the supplied external total ({external_total:.1f}s) "
                f"is smaller than the observed recorder span ({recorder_span:.1f}s); "
                f"falling back to recorder_span"
            )
        else:
            reference_total = external_total
            reference_source = "external_supplied"
    pre_arm = max(0.0, reference_total - recorder_span)

    # ---- intervals ----------------------------------------------------------
    phase_intervals = []           # (start, end, raw_name, kind, role, outcome)
    open_phase = None
    for index, rec in enumerate(events):
        event = rec.get("event")
        if event == "phase_open":
            if open_phase is not None:      # defensive: a lost close
                phase_intervals.append((*open_phase[:1], axis[index], *open_phase[1:]))
            open_phase = (axis[index], rec.get("phase"),
                          _enum(rec.get("kind"),
                                (PR.CLASS_ACTIVE, PR.CLASS_EXTERNAL, PR.CLASS_APPROVAL),
                                PR.CLASS_ACTIVE),
                          _enum(rec.get("repo_role"), PR.REPO_ROLES), None)
        elif event == "phase_close":
            if open_phase is None:
                integrity["unmatched_phase_closes"] += 1
                continue
            outcome = _enum(rec.get("outcome"),
                            ("ok", "failed", "unclosed", "partial", "abandoned"))
            phase_intervals.append((open_phase[0], axis[index], open_phase[1],
                                    open_phase[2], open_phase[3], outcome))
            open_phase = None
    if open_phase is not None:
        # An open phase at the end is auto-closed at T1 and flagged, so its time
        # is never lost and never silently attributed to the next phase.
        phase_intervals.append((open_phase[0], t1, open_phase[1], open_phase[2],
                                open_phase[3], "unclosed"))

    phase_intervals = [
        (max(s, t0), min(e, t1), name, kind, role, outcome)
        for (s, e, name, kind, role, outcome) in phase_intervals
        if min(e, t1) - max(s, t0) > EPS
    ]

    run_intervals = []             # (start, end, class, raw_phase)
    overlong_runs: list[float] = []  # declared duration that did not fit
    wrapped_local = 0.0
    wrapped_external = 0.0
    by_head = {}
    failed_by_head = {}
    hinted_count = 0
    hinted_seconds = 0.0
    for index, rec in enumerate(events):
        if rec.get("event") != "run":
            continue
        duration = _num(rec.get("duration_s")) or 0.0
        duration = max(0.0, duration)
        klass = _enum(rec.get("kind"), (PR.CLASS_LOCAL, PR.CLASS_EXTERNAL), PR.CLASS_LOCAL)
        if klass == PR.CLASS_EXTERNAL:
            wrapped_external += duration
        else:
            wrapped_local += duration
        head = _enum(rec.get("cmd_head"), PR.CMD_HEADS, "other")
        by_head[head] = by_head.get(head, 0) + 1
        exit_code = rec.get("exit_code")
        if isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0:
            failed_by_head[head] = failed_by_head.get(head, 0) + 1
        if rec.get("cmd_network_hint") is True and klass == PR.CLASS_LOCAL:
            hinted_count += 1
            hinted_seconds += duration
        # The event is appended AFTER the child exits, so it marks the END.
        lower = axis[index - 1] if index > 0 else t0
        start, end = _clip(max(lower, axis[index] - duration), axis[index], t0, t1)
        if end - start > EPS:
            run_intervals.append((start, end, klass, rec.get("phase")))
        # A child whose DECLARED duration does not fit the span it lands in is an
        # anomaly: a clock step, a hand-edited log, or a duration from another
        # session. The tiling clips it — which is the honest thing to do, and is
        # why this no longer shows up as a negative residual — so the discrepancy
        # is counted here instead of being silently absorbed.
        if duration - (end - start) > 1.0:
            overlong_runs.append(duration - (end - start))

    approval_intervals = []
    approval_marks_s = 0.0
    pending = None
    for index, rec in enumerate(events):
        if rec.get("event") != "mark":
            continue
        name = rec.get("mark")
        if name == PR.MARK_APPROVAL_START:
            if pending is not None:
                integrity["unpaired_approval_marks"] += 1
            pending = index
        elif name == PR.MARK_APPROVAL_END:
            if pending is None:
                # An END with no START is measured as ZERO. Approval wait is
                # DECLARED, never inferred: guessing where it began would
                # manufacture exactly the attribution this tool refuses.
                integrity["unpaired_approval_marks"] += 1
                continue
            start, end = _clip(axis[pending], axis[index], t0, t1)
            if end - start > EPS:
                approval_intervals.append((start, end))
                approval_marks_s += end - start
            pending = None
    if pending is not None:
        integrity["unpaired_approval_marks"] += 1

    skew_intervals = []
    for gap_index in skew_gaps:
        start, end = _clip(axis[gap_index], axis[gap_index + 1], t0, t1)
        if end - start > EPS:
            skew_intervals.append((start, end))

    # ---- tile [T0, T1) so every second is claimed exactly once ---------------
    segments = _tile(t0, t1, axis, phase_intervals, run_intervals,
                     approval_intervals, skew_intervals)
    _relabel_long_gaps(segments, axis, t0, t1, idle_threshold)

    tiled = {}
    for start, end, label, _source in segments:
        tiled[label] = tiled.get(label, 0.0) + (end - start)
    phase_covered = sum(e - s for (s, e, *_rest) in phase_intervals)

    external_phase_extra = sum(
        end - start for (start, end, label, source) in segments
        if label == PR.CLASS_EXTERNAL and source == "phase"
    )
    approval_phase_extra = sum(
        end - start for (start, end, label, source) in segments
        if label == PR.CLASS_APPROVAL and source == "phase"
    )

    unattributed_items = {
        "pre_arm": pre_arm,
        "between_phases": tiled.get("between_phases", 0.0),
        "long_gap": tiled.get("long_gap", 0.0),
        "clock_skew": tiled.get("clock_skew", 0.0),
        "after_last_event": tiled.get("after_last_event", 0.0),
    }
    unattributed_total = sum(unattributed_items.values())

    # Read the DE-OVERLAPPED tiling, not the raw sums.
    #
    # ``wrapped_local``/``wrapped_external``/``approval_marks_s`` add up every
    # interval's own duration, so overlapping intervals are counted once each.
    # Three concurrent wrapped children in a 6.3s session reported 18.0s of
    # subprocess time under a 6.3s total, and because ``active`` is the residual
    # it was driven to 0 — the classes summed to 18.1s against a reference of
    # 6.3s while the docs promised an exact partition. Concurrency is ordinary
    # here: the recorder advertises atomic appends under concurrent subagents.
    #
    # ``_tile`` already resolves each instant to exactly one class, so its
    # per-label totals are the partition. The raw sums survive as the separately
    # reported ``wrapped_*`` overlay, which is allowed to overlap by design.
    local_s = tiled.get(PR.CLASS_LOCAL, 0.0)
    external_s = tiled.get(PR.CLASS_EXTERNAL, 0.0)
    approval_s = tiled.get(PR.CLASS_APPROVAL, 0.0)

    if overlong_runs:
        integrity["overlong_runs"] = len(overlong_runs)
        notes.append(
            f"overlong_runs: {len(overlong_runs)} wrapped command(s) declared a "
            f"duration that did not fit the span they landed in (largest excess "
            f"{max(overlong_runs):.1f}s); each was clipped to the span, so the "
            f"classes still partition — but a duration that does not fit means a "
            f"clock step, an edited log, or a duration from another session"
        )

    # ``active`` is the RESIDUAL, so the classes partition the reference total by
    # construction. That makes the sum an identity rather than a check: it is the
    # de-overlapped tiling above that earns it, and the clamp below is only a
    # last resort for an input the tiling could not reconcile.
    active_s = reference_total - local_s - external_s - approval_s - unattributed_total
    if active_s < -1e-6:
        integrity["accounting_error"] = True
        notes.append(
            f"accounting_error: the measured and declared classes exceed the "
            f"reference total by {-active_s:.1f}s; active was clamped to 0 "
            f"(a negative residual means double-counted time, never negative work)"
        )
        active_s = 0.0
    active_s = max(0.0, active_s)

    classes = {
        "active": active_s,
        "local_subprocess": local_s,
        "external_wait": external_s,
        "approval_wait": approval_s,
        "unattributed": unattributed_total,
    }

    phase_rows = _phase_rows(events, phase_intervals, segments)

    coverage = {
        "phase_covered_s": phase_covered,
        "phase_coverage_pct": _pct(phase_covered, reference_total),
        "class_attributed_s": max(0.0, reference_total - unattributed_total),
        "class_attribution_pct": _pct(
            max(0.0, reference_total - unattributed_total), reference_total
        ),
    }

    unknown_phase_count = len({
        name for (_s, _e, name, *_r) in phase_intervals
        if _display_phase(name)[1] is not None
    })

    repos = []
    seen = set()
    for rec in events:
        role = _enum(rec.get("repo_role"), PR.REPO_ROLES)
        fingerprint = rec.get("repo_fingerprint")
        fingerprint = fingerprint if isinstance(fingerprint, str) and \
            len(fingerprint) <= 16 and all(c in "0123456789abcdef" for c in fingerprint) else None
        if role is None and fingerprint is None:
            continue
        key = (role, fingerprint)
        if key in seen:
            continue
        seen.add(key)
        repos.append({"role": role or "unknown", "fingerprint": fingerprint})

    session_digest = None
    harness = None
    harness_session_digest = None
    fixture = None
    for rec in events:
        if rec.get("session_digest") and session_digest is None:
            candidate = rec["session_digest"]
            if isinstance(candidate, str):
                session_digest = candidate
        harness = _enum(rec.get("harness"), PR.HARNESSES, harness)
        if isinstance(rec.get("harness_session_id"), str) and rec["harness_session_id"]:
            harness_session_digest = PR.digest(rec["harness_session_id"])
        if isinstance(rec.get("fixture"), str) and rec["fixture"] in KNOWN_FIXTURES:
            fixture = rec["fixture"]

    notes.extend(_derive_notes(
        reference_source=reference_source,
        approval_s=approval_s,
        unattributed_items=unattributed_items,
        idle_threshold=idle_threshold,
        hinted_count=hinted_count,
        hinted_seconds=hinted_seconds,
        integrity=integrity,
    ))

    return {
        "schema": SCHEMA,
        "session_digest": session_digest,
        "harness": harness,
        "harness_session_digest": harness_session_digest,
        "fixture": fixture,
        "repos": repos,
        "reference_total_s": _r(reference_total),
        "reference_source": reference_source,
        "recorder_span_s": _r(recorder_span),
        "pre_arm_s": _r(pre_arm),
        "idle_threshold_s": _r(idle_threshold),
        "coverage": {key: _r(value) for key, value in coverage.items()},
        "classes_s": {key: _r(classes[key]) for key in CLASSES},
        "unattributed_s": {key: _r(unattributed_items[key]) for key in UNATTRIBUTED_KINDS},
        "wrapped_subprocess_s": _r(wrapped_local + wrapped_external),
        "wrapped_local_s": _r(wrapped_local),
        "wrapped_external_s": _r(wrapped_external),
        "phases": phase_rows,
        "unknown_phase_count": unknown_phase_count,
        "wrapped_commands_by_head": dict(sorted(by_head.items())),
        "failed_commands_by_head": dict(sorted(failed_by_head.items())),
        "tokens": "not_measured",
        "tool_calls": "not_measured",
        "integrity": integrity,
        "notes": notes,
    }


def _empty_summary(integrity, notes):
    notes = list(notes) + ["empty_log: no usable events were found"]
    return {
        "schema": SCHEMA,
        "session_digest": None,
        "harness": None,
        "harness_session_digest": None,
        "fixture": None,
        "repos": [],
        "reference_total_s": 0.0,
        "reference_source": "recorder_span",
        "recorder_span_s": 0.0,
        "pre_arm_s": 0.0,
        "idle_threshold_s": DEFAULT_IDLE_THRESHOLD,
        "coverage": {"phase_covered_s": 0.0, "phase_coverage_pct": 0.0,
                     "class_attributed_s": 0.0, "class_attribution_pct": 0.0},
        "classes_s": {key: 0.0 for key in CLASSES},
        "unattributed_s": {key: 0.0 for key in UNATTRIBUTED_KINDS},
        "wrapped_subprocess_s": 0.0,
        "wrapped_local_s": 0.0,
        "wrapped_external_s": 0.0,
        "phases": [],
        "unknown_phase_count": 0,
        "wrapped_commands_by_head": {},
        "failed_commands_by_head": {},
        "tokens": "not_measured",
        "tool_calls": "not_measured",
        "integrity": integrity,
        "notes": notes,
    }


def _r(value) -> float:
    """Publish seconds at MILLIsecond precision, not tenths.

    Tenths are what the table shows, but rounding the stored numbers to tenths
    would break the partition invariant: five buckets each rounded to 0.1s can
    miss their total by up to 0.25s, and a published table whose classes do not
    add up to the reference total is exactly the kind of arithmetic nobody
    should have to take on trust.
    """
    return round(float(value), 3)


def _pct(part, whole) -> float:
    if whole <= EPS:
        return 0.0
    return round(100.0 * part / whole, 1)


def _tile(t0, t1, axis, phase_intervals, run_intervals, approval_intervals,
          skew_intervals):
    """Cut ``[T0, T1)`` into elementary segments, each with exactly ONE class.

    Priority order (highest first) is the derivation order: measured subprocess
    time, declared external waits, declared approval waits, detected clock skew,
    then the phase's own kind, then time no phase covered. Because the segments
    TILE the span, the classes partition it by construction.
    """
    claims = [
        (PR.CLASS_LOCAL, "run",
         [(s, e) for (s, e, k, _p) in run_intervals if k == PR.CLASS_LOCAL]),
        (PR.CLASS_EXTERNAL, "run",
         [(s, e) for (s, e, k, _p) in run_intervals if k == PR.CLASS_EXTERNAL]),
        (PR.CLASS_APPROVAL, "approval_mark", list(approval_intervals)),
        ("clock_skew", "skew", list(skew_intervals)),
    ]

    bounds = {t0, t1}
    for value in axis:
        if t0 - EPS <= value <= t1 + EPS:
            bounds.add(min(max(value, t0), t1))
    for _label, _source, intervals in claims:
        for start, end in intervals:
            bounds.add(start)
            bounds.add(end)
    for start, end, *_rest in phase_intervals:
        bounds.add(start)
        bounds.add(end)
    ordered = sorted(bounds)

    last_close = max((e for (_s, e, *_r) in phase_intervals), default=None)

    segments = []
    for index in range(len(ordered) - 1):
        start, end = ordered[index], ordered[index + 1]
        if end - start <= EPS:
            continue
        mid = (start + end) / 2.0
        label = source = None
        for claim_label, claim_source, intervals in claims:
            if any(a <= mid < b for (a, b) in intervals):
                label, source = claim_label, claim_source
                break
        if label is None:
            phase = next(
                ((kind) for (a, b, _n, kind, _role, _o) in phase_intervals
                 if a <= mid < b),
                None,
            )
            if phase is not None:
                label, source = phase, "phase"
            elif last_close is None or mid < last_close:
                label, source = "between_phases", "outside"
            else:
                label, source = "after_last_event", "outside"
        segments.append([start, end, label, source])
    return segments


def _relabel_long_gaps(segments, axis, t0, t1, idle_threshold) -> None:
    """A long silence inside a phase is UNATTRIBUTED, not active.

    Six minutes of quiet is not evidence of six minutes of reasoning. Only the
    part of the gap that nothing else claimed is considered, and it is counted
    IN FULL (not just the excess over the threshold) — the whole gap's kind is
    unknown, not merely the tail of it.
    """
    if idle_threshold is None or idle_threshold <= 0:
        return
    for index in range(len(axis) - 1):
        gap_start, gap_end = _clip(axis[index], axis[index + 1], t0, t1)
        if gap_end - gap_start <= idle_threshold:
            continue
        candidates = [
            seg for seg in segments
            if seg[2] == PR.CLASS_ACTIVE and seg[0] >= gap_start - EPS
            and seg[1] <= gap_end + EPS
        ]
        if sum(seg[1] - seg[0] for seg in candidates) > idle_threshold:
            for seg in candidates:
                seg[2] = "long_gap"
                seg[3] = "long_gap"


def _phase_rows(events, phase_intervals, segments):
    """One row per (phase, repo role). Columns use the same derivation as the totals."""
    groups = {}
    for start, end, name, _kind, role, outcome in phase_intervals:
        display, phase_digest = _display_phase(name)
        key = (display, phase_digest, role or "unknown")
        row = groups.setdefault(key, {
            "phase": display,
            "phase_digest": phase_digest,
            "repo_role": role or "unknown",
            "occurrences": 0,
            "elapsed_s": 0.0,
            "active_s": 0.0,
            "local_subprocess_s": 0.0,
            "external_wait_s": 0.0,
            "approval_wait_s": 0.0,
            "unattributed_s": 0.0,
            "wrapped_commands": 0,
            "failed_commands": 0,
            "outcome": outcome,
            "_intervals": [],
        })
        row["occurrences"] += 1
        row["elapsed_s"] += end - start
        row["_intervals"].append((start, end))
        if outcome not in (None, "ok"):
            row["outcome"] = outcome

    raw_to_key = {}
    for start, end, name, _kind, role, _outcome in phase_intervals:
        display, phase_digest = _display_phase(name)
        raw_to_key.setdefault(name, (display, phase_digest, role or "unknown"))

    for rec in events:
        if rec.get("event") != "run":
            continue
        key = raw_to_key.get(rec.get("phase"))
        row = groups.get(key)
        if row is None:
            continue
        row["wrapped_commands"] += 1
        exit_code = rec.get("exit_code")
        if isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0:
            row["failed_commands"] += 1
    # NOTE: the per-run ``duration_s`` is deliberately NOT accumulated into the
    # row's class columns. Concurrent children overlap, so summing their raw
    # durations reported 6.1s of subprocess time inside a 2.2s phase. The rows
    # read their classes from the same de-overlapped tiling the totals do, which
    # is also what makes the rows sum to the totals.

    for row in groups.values():
        for seg_start, seg_end, label, source in segments:
            covered = sum(_overlap(seg_start, seg_end, a, b) for (a, b) in row["_intervals"])
            if covered <= EPS:
                continue
            if label in ("long_gap", "clock_skew"):
                row["unattributed_s"] += covered
            elif label == PR.CLASS_APPROVAL:
                row["approval_wait_s"] += covered
            elif label == PR.CLASS_EXTERNAL:
                row["external_wait_s"] += covered
            elif label == PR.CLASS_LOCAL:
                row["local_subprocess_s"] += covered
        row["active_s"] = max(0.0, row["elapsed_s"] - row["local_subprocess_s"]
                              - row["external_wait_s"] - row["approval_wait_s"]
                              - row["unattributed_s"])

    rows = []
    for row in groups.values():
        row.pop("_intervals", None)
        for key in ("elapsed_s", "active_s", "local_subprocess_s", "external_wait_s",
                    "approval_wait_s", "unattributed_s"):
            row[key] = _r(row[key])
        rows.append(row)
    rows.sort(key=lambda r: (r["phase"], r["repo_role"], r["phase_digest"] or ""))
    return rows


def _derive_notes(*, reference_source, approval_s, unattributed_items, idle_threshold,
                  hinted_count, hinted_seconds, integrity) -> list[str]:
    """Notes come from a FIXED catalogue with numeric fields only.

    Nothing here interpolates a label, a path or a command line, which is what
    keeps the ``notes`` array as unable to leak as the rest of the schema.
    """
    notes = []
    if reference_source == "recorder_span":
        notes.append(
            "coverage denominator is the recorder's OWN span, not a user-visible total: "
            "with contiguous `set` this is ~100% by construction and proves nothing. "
            "Pass `session end --external-total-s` for a real coverage claim."
        )
    if approval_s <= EPS and unattributed_items["long_gap"] > EPS:
        notes.append(
            f"approval_wait is 0.0s because no approval marks were recorded — that "
            f"means NOT MEASURED, not 'there was none'; "
            f"{unattributed_items['long_gap']:.1f}s of long gaps could contain approvals"
        )
    if unattributed_items["long_gap"] > EPS:
        notes.append(
            f"long_gap: {unattributed_items['long_gap']:.1f}s of silence over "
            f"{idle_threshold:.0f}s inside a phase — kind unknown, not attributed"
        )
    if unattributed_items["pre_arm"] > EPS:
        notes.append(
            f"pre_arm: {unattributed_items['pre_arm']:.1f}s lies outside the recorder's "
            f"span (before it was armed, and after the last event if the session ended "
            f"implicitly)"
        )
    if hinted_count:
        notes.append(
            f"{hinted_count} command(s) ({hinted_seconds:.1f}s) ran as "
            f"kind=local_subprocess but look network-bound; flagged, never "
            f"reclassified — rerun them with `--kind external` if that is what they are"
        )
    if integrity.get("session_end_missing"):
        notes.append(
            "session_end is missing: the span ends at the last recorded event and "
            "anything after it is unmeasured"
        )
    if integrity.get("unpaired_approval_marks"):
        notes.append(
            f"{integrity['unpaired_approval_marks']} unpaired approval mark(s) "
            f"contributed 0.0s (approval wait is declared, never inferred)"
        )
    if integrity.get("malformed_lines"):
        notes.append(f"{integrity['malformed_lines']} malformed log line(s) were skipped")
    if integrity.get("missing_seq"):
        notes.append(
            f"{integrity['missing_seq']} event(s) are missing from the sequence counter"
        )
    if integrity.get("clock_skew_events"):
        notes.append(
            f"{integrity['clock_skew_events']} clock-skew interval(s) "
            f"({unattributed_items['clock_skew']:.1f}s) crossed a monotonic-origin shift "
            f"and are unattributed"
        )
    return notes


# ── rendering (ONE source of numbers for every output form) ──────────────────

_TABLE_HEADER = ("phase", "repo", "elapsed", "active", "subproc", "ext wait",
                 "approval", "unattr", "cmds")


def _table_rows(summary) -> list[tuple[str, ...]]:
    rows = []
    for row in summary["phases"]:
        name = row["phase"]
        if row.get("phase_digest"):
            name = f"{name}:{row['phase_digest']}"
        rows.append((
            name,
            row["repo_role"],
            f"{row['elapsed_s']:.1f}s",
            f"{row['active_s']:.1f}s",
            f"{row['local_subprocess_s']:.1f}s",
            f"{row['external_wait_s']:.1f}s",
            f"{row['approval_wait_s']:.1f}s",
            f"{row['unattributed_s']:.1f}s",
            str(row["wrapped_commands"]),
        ))
    classes = summary["classes_s"]
    rows.append((
        "TOTAL",
        "",
        f"{summary['reference_total_s']:.1f}s",
        f"{classes['active']:.1f}s",
        f"{classes['local_subprocess']:.1f}s",
        f"{classes['external_wait']:.1f}s",
        f"{classes['approval_wait']:.1f}s",
        f"{classes['unattributed']:.1f}s",
        str(sum(summary["wrapped_commands_by_head"].values())),
    ))
    return rows


def _footer_lines(summary) -> list[str]:
    denominator = (
        "external total, harness UI" if summary["reference_source"] == "external_supplied"
        else "recorder span — NOT a user-visible total"
    )
    unattributed = summary["unattributed_s"]
    lines = [
        f"phase coverage {summary['coverage']['phase_coverage_pct']:.1f}% of "
        f"{summary['reference_total_s']:.1f}s ({denominator}) · "
        f"class attribution {summary['coverage']['class_attribution_pct']:.1f}%",
        "unattributed: " + " · ".join(
            f"{key} {unattributed[key]:.1f}s" for key in UNATTRIBUTED_KINDS
        ),
        f"wrapped subprocess {summary['wrapped_subprocess_s']:.1f}s "
        f"(local {summary['wrapped_local_s']:.1f}s + external "
        f"{summary['wrapped_external_s']:.1f}s; overlaps external_wait by design)",
        f"tokens: {summary['tokens'].replace('_', ' ')} · "
        f"tool_calls: {summary['tool_calls'].replace('_', ' ')} "
        f"(wrapped commands only: {sum(summary['wrapped_commands_by_head'].values())})",
    ]
    for note in summary["notes"]:
        lines.append(f"note: {note}")
    return lines


def render_markdown(summary) -> str:
    rows = _table_rows(summary)
    aligns = ["|:---" if i < 2 else "|---:" for i in range(len(_TABLE_HEADER))]
    out = ["| " + " | ".join(_TABLE_HEADER) + " |", "".join(aligns) + "|"]
    for row in rows:
        out.append("| " + " | ".join(row) + " |")
    out.append("")
    out.extend(_footer_lines(summary))
    return "\n".join(out) + "\n"


def render_text(summary) -> str:
    rows = _table_rows(summary)
    table = [_TABLE_HEADER, *rows]
    widths = [max(len(r[i]) for r in table) for i in range(len(_TABLE_HEADER))]

    def line(cols):
        cells = [cols[i].ljust(widths[i]) if i < 2 else cols[i].rjust(widths[i])
                 for i in range(len(cols))]
        return "  ".join(cells).rstrip()

    out = [line(_TABLE_HEADER), line(tuple("-" * w for w in widths))]
    out.extend(line(row) for row in rows)
    out.append("")
    out.extend(_footer_lines(summary))
    return "\n".join(out) + "\n"


# ── redaction self-check (belt and braces, never the primary mechanism) ──────

def _leak_guard():
    """Import the leak guard lazily; ``None`` when it is unavailable."""
    publish = REPO_ROOT / "automation" / "publish"
    if str(publish) not in sys.path:
        sys.path.insert(0, str(publish))
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            import check_public  # noqa: E402  (stdlib-only sibling module)
    except Exception:
        return None
    return check_public


def active_tokens():
    """The personal-token list to substring-check the rendered summary against.

    Patched out in tests so nothing reads the operator's real config. The
    config loader narrates which config it found on stderr; that is useful for
    the leak guard and pure noise here, so it is swallowed.
    """
    guard = _leak_guard()
    if guard is None:
        return None
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            return list(guard.personal_tokens())
    except Exception:
        return None


def redaction_hits(text, tokens=None):
    """``[(kind, matched)]`` — structural PII plus personal-token substrings.

    Returns ``None`` when the check could not run at all (the caller fails
    closed under ``--strict``): a self-check that silently did nothing is worse
    than no self-check, because it reads as a pass.
    """
    guard = _leak_guard()
    if guard is None:
        return None
    hits = []
    try:
        hits.extend(guard._structural_hits(text))
    except Exception:
        return None
    if tokens is None:
        tokens = active_tokens() or []
    lowered = text.lower()
    for token in tokens:
        if isinstance(token, str) and token and token.lower() in lowered:
            hits.append(("token", token))
    return hits


# ── CLI ──────────────────────────────────────────────────────────────────────

def _resolve_log(args):
    """``(path, error)`` for the session the caller asked about.

    ``--last`` deliberately ignores the pointer file: the pointer names the
    session that is still OPEN, which is not the one you just ended.
    """
    log_dir = PR.resolve_log_dir(args.log_dir)
    session = args.session
    if not session and not args.last:
        session = PR.read_pointer(log_dir)
    if session:
        path = PR.log_path_for(log_dir, session)
        if path.is_file():
            return path, None
        return None, f"no log for session {session!r} under {log_dir}"
    try:
        candidates = sorted(
            (p for p in log_dir.glob("*.jsonl") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
    except Exception as exc:
        return None, f"cannot read {log_dir} ({exc.__class__.__name__}: {exc})"
    if not candidates:
        return None, f"no phase logs under {log_dir}"
    return candidates[-1], None


def _unredacted_allowed(out_path: Path) -> bool:
    """``--unredacted`` may only ever target scratch, never a tracked path."""
    resolved = out_path.expanduser().resolve()
    try:
        relative = resolved.relative_to(REPO_ROOT)
    except ValueError:
        return True          # outside the repo entirely: not a tracked path
    return relative.parts[:1] in (("logs",), ("local",))


def _unredacted_payload(summary, events):
    return {
        "schema": "phase-summary-unredacted/1",
        "summary": summary,
        "events": events,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="phase_summary.py", description=__doc__.split("\n")[0])
    parser.add_argument("--session", help="session id (default: the pointer file, else --last)")
    parser.add_argument("--last", action="store_true",
                        help="use the most recently written log in the log dir")
    parser.add_argument("--log-dir", help=f"event log directory (default: {PR.DEFAULT_LOG_DIR})")
    parser.add_argument("--json", action="store_true", help="emit the redacted summary object")
    parser.add_argument("--markdown", action="store_true", help="emit a paste-ready table")
    parser.add_argument("--out", type=Path, help="also write the output to this path")
    parser.add_argument("--idle-threshold", type=float, default=DEFAULT_IDLE_THRESHOLD,
                        help=f"seconds of in-phase silence that become unattributed "
                             f"(default {DEFAULT_IDLE_THRESHOLD:g})")
    parser.add_argument("--min-coverage", type=float,
                        help="exit 1 below this phase-coverage %% (manual aid, NEVER a gate)")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 and write nothing if the redaction self-check hits")
    parser.add_argument("--unredacted", action="store_true",
                        help="emit the raw events too; requires --out under logs/ or local/")
    args = parser.parse_args(argv)

    path, error = _resolve_log(args)
    if path is None:
        sys.stderr.write(f"phase_summary: {error}\n")
        return 2
    try:
        events, load_integrity = load_events(path)
    except Exception as exc:
        sys.stderr.write(f"phase_summary: cannot read {path} "
                         f"({exc.__class__.__name__}: {exc})\n")
        return 2

    summary = summarize(events, load_integrity, idle_threshold=args.idle_threshold)

    if args.unredacted:
        if args.out is None:
            sys.stderr.write("phase_summary: --unredacted requires --out\n")
            return 2
        if not _unredacted_allowed(args.out):
            sys.stderr.write(
                "phase_summary: --unredacted refuses a tracked path; write it under "
                "logs/ or local/\n"
            )
            return 2
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(_unredacted_payload(summary, events), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        return 0

    def _render():
        if args.json:
            return json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
        if args.markdown:
            return render_markdown(summary)
        return render_text(summary)

    # Belt and braces: the structural schema is what prevents a leak; this check
    # only proves it, and fails CLOSED under --strict when it could not run. It
    # runs over EVERY output form, so a hit cannot hide in the one you did not
    # ask for. Notes are appended, then the output is rendered again so the
    # finding is actually visible in what gets pasted into a record.
    probe = _render() + json.dumps(summary, ensure_ascii=False)
    hits = redaction_hits(probe)
    if hits is None:
        summary["notes"].append("redaction self-check could not run (leak guard unavailable)")
        if args.strict:
            sys.stderr.write("phase_summary: redaction self-check unavailable (--strict)\n")
            return 1
    elif hits:
        kinds = sorted({kind for kind, _match in hits})
        summary["notes"].append(
            f"redaction self-check flagged {len(hits)} hit(s): {', '.join(kinds)}"
        )
        if args.strict:
            sys.stderr.write(
                f"phase_summary: redaction self-check found {len(hits)} hit(s) "
                f"({', '.join(kinds)}); nothing written\n"
            )
            return 1
    rendered = _render()

    sys.stdout.write(rendered)
    if args.out is not None:
        try:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(rendered, encoding="utf-8")
        except Exception as exc:
            sys.stderr.write(f"phase_summary: could not write {args.out} "
                             f"({exc.__class__.__name__}: {exc})\n")
            return 2

    if args.min_coverage is not None:
        if summary["coverage"]["phase_coverage_pct"] + 1e-9 < args.min_coverage:
            sys.stderr.write(
                f"phase_summary: phase coverage "
                f"{summary['coverage']['phase_coverage_pct']:.1f}% is below the requested "
                f"{args.min_coverage:.1f}% (denominator: {summary['reference_source']})\n"
            )
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
