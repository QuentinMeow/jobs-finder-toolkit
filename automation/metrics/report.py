#!/usr/bin/env python3
"""Aggregate ``logs/metrics.jsonl`` into per-session rows and rollups.

Reads the JSONL emitted by ``automation/metrics/hook_collect.py`` and prints one
row per session, plus optional per-SHA rollups for A/B comparison. Token count
and wall-clock are near-deterministic per fixed task, so ``--by-sha`` (n,
mean/median tokens + wall-clock per commit) is the cheap efficiency channel for
matched-pair harness A/B tests (see ``evals/ab-protocol.md``).

Usage:
    .venv/bin/python automation/metrics/report.py [--log PATH] [--by-sha]

Malformed / partial lines are skipped, never fatal — the transcript-derived Stop
rows are version-brittle (re-verify the hook payload shape after upgrades).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG = REPO_ROOT / "logs" / "metrics.jsonl"

# Token sub-keys carried on Stop rows (mirrors hook_collect._USAGE_KEYS).
_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)

_SHORT_SHA = 12  # display length for git SHAs


def _load_rows(log_path: Path):
    """Yield each well-formed JSON object from the log; skip junk lines."""
    if not log_path.is_file():
        return
    with log_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if isinstance(rec, dict):
                yield rec


def _num(value):
    """Coerce to a number, else 0 (tolerates None / strings in brittle rows)."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return value
    return 0


def aggregate(rows):
    """Fold event rows into one dict per session_id."""
    sessions = {}

    def _session(sid):
        return sessions.setdefault(
            sid,
            {
                "session_id": sid,
                "git_sha": None,
                "model": None,
                "source": None,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "wall_clock_s": None,
                "tool_calls_stop": None,   # tool_use count from the Stop transcript parse
                "tool_calls_events": 0,    # count of PostToolUse rows
                "stops": 0,
            },
        )

    for rec in rows:
        sid = rec.get("session_id")
        if sid is None:
            continue
        event = rec.get("event")
        sess = _session(sid)

        if event == "session-start":
            sess["git_sha"] = rec.get("git_sha") or sess["git_sha"]
            sess["model"] = rec.get("model") or sess["model"]
            sess["source"] = rec.get("source") or sess["source"]
        elif event == "post-tool-use":
            sess["tool_calls_events"] += 1
        elif event == "stop":
            sess["stops"] += 1
            for key in _TOKEN_KEYS:
                sess[key] += _num(rec.get(key))
            wc = rec.get("wall_clock_s")
            if isinstance(wc, (int, float)) and not isinstance(wc, bool):
                sess["wall_clock_s"] = wc
            tc = rec.get("tool_calls")
            if isinstance(tc, (int, float)) and not isinstance(tc, bool):
                sess["tool_calls_stop"] = int(tc)

    # Derive a single tool_calls figure: prefer the Stop transcript count, fall
    # back to the number of PostToolUse events we logged.
    for sess in sessions.values():
        sess["total_tokens"] = sum(sess[k] for k in _TOKEN_KEYS)
        sess["tool_calls"] = (
            sess["tool_calls_stop"]
            if sess["tool_calls_stop"] is not None
            else sess["tool_calls_events"]
        )
    return sessions


def _fmt(value):
    return "-" if value is None else str(value)


def print_sessions(sessions):
    header = (
        "SESSION",
        "SHA",
        "MODEL",
        "IN",
        "OUT",
        "CACHE_R",
        "CACHE_C",
        "WALL_S",
        "TOOLS",
    )
    display = []
    for sess in sorted(sessions.values(), key=lambda s: str(s["session_id"])):
        display.append(
            (
                str(sess["session_id"]),
                (sess["git_sha"] or "-")[:_SHORT_SHA],
                _fmt(sess["model"]),
                str(sess["input_tokens"]),
                str(sess["output_tokens"]),
                str(sess["cache_read_input_tokens"]),
                str(sess["cache_creation_input_tokens"]),
                _fmt(sess["wall_clock_s"]),
                str(sess["tool_calls"]),
            )
        )

    widths = [
        max(len(header[i]), *(len(row[i]) for row in display)) if display else len(header[i])
        for i in range(len(header))
    ]

    def fmt(cols):
        cells = [cols[0].ljust(widths[0]), cols[1].ljust(widths[1]), cols[2].ljust(widths[2])]
        cells += [cols[i].rjust(widths[i]) for i in range(3, len(cols))]
        return "  ".join(cells)

    print("Per-session metrics:")
    print(fmt(header))
    print(fmt(tuple("-" * w for w in widths)))
    for row in display:
        print(fmt(row))


def _mean_median(values):
    clean = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not clean:
        return None, None
    return round(statistics.mean(clean), 1), round(statistics.median(clean), 1)


def print_by_sha(sessions):
    """Per-SHA rollup: n, mean/median total tokens and wall-clock (A/B channel)."""
    by_sha = {}
    for sess in sessions.values():
        by_sha.setdefault(sess["git_sha"] or "(unknown)", []).append(sess)

    header = (
        "SHA",
        "N",
        "TOK_MEAN",
        "TOK_MEDIAN",
        "WALL_MEAN",
        "WALL_MEDIAN",
    )
    display = []
    for sha, group in sorted(by_sha.items()):
        tok_mean, tok_median = _mean_median([s["total_tokens"] for s in group])
        wall_mean, wall_median = _mean_median([s["wall_clock_s"] for s in group])
        display.append(
            (
                sha[:_SHORT_SHA],
                str(len(group)),
                _fmt(tok_mean),
                _fmt(tok_median),
                _fmt(wall_mean),
                _fmt(wall_median),
            )
        )

    widths = [
        max(len(header[i]), *(len(row[i]) for row in display)) if display else len(header[i])
        for i in range(len(header))
    ]

    def fmt(cols):
        cells = [cols[0].ljust(widths[0])]
        cells += [cols[i].rjust(widths[i]) for i in range(1, len(cols))]
        return "  ".join(cells)

    print("\nRollup by git SHA (total tokens = in+out+cache):")
    print(fmt(header))
    print(fmt(tuple("-" * w for w in widths)))
    for row in display:
        print(fmt(row))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG,
        help=f"path to the metrics JSONL (default: {DEFAULT_LOG})",
    )
    parser.add_argument(
        "--by-sha",
        action="store_true",
        help="also print per-git-SHA rollups for A/B comparison",
    )
    args = parser.parse_args(argv)

    sessions = aggregate(_load_rows(args.log))
    if not sessions:
        print(f"No session metrics found in {args.log}")
        return 0

    print_sessions(sessions)
    if args.by_sha:
        print_by_sha(sessions)
    return 0


if __name__ == "__main__":
    sys.exit(main())
