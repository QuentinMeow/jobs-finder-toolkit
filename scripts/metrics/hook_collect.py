#!/usr/bin/env python3
"""Zero-platform metrics collector for Claude Code hooks.

Reads a hook JSON payload from stdin and appends ONE JSON line to
``logs/metrics.jsonl``. Metrics are OPT-IN: wire these hooks (SessionStart,
PostToolUse, Stop) from your local ``.claude/settings.local.json`` (see
``docs/METRICS.md`` for the metric set and rationale); they are intentionally
NOT tracked so contributors never run them by default.

Modes (``argv[1]``):
    session-start   {ts, event, session_id, model, source, git_sha}
    post-tool-use   {ts, event, session_id, tool_name}
    stop            {ts, event, session_id, <token sums>, wall_clock_s,
                     tool_calls, transcript_lines}

HARD INVARIANTS — this must NEVER block or fail a Claude Code session:
  * the whole body runs under a top-level try/except and the process ALWAYS
    exits 0 (a crashing Stop hook would otherwise stall every turn);
  * the Stop transcript parse stays well under a second for typical transcripts
    (single streaming pass, no whole-file load, cheap per-line work);
  * ``logs/`` is created on demand.

The transcript JSONL schema is version-brittle across Claude Code releases
(re-verify the payload shape after Claude Code upgrades). Every field access in
the parser is defensive and malformed lines are skipped, never raised.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Resolve paths from THIS file, not the cwd, so the log always lands in the
# repo regardless of where the hook happens to be invoked from.
REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = REPO_ROOT / "logs" / "metrics.jsonl"

# usage sub-keys summed for the Stop token totals (metric:
# "tokens (in/out/cache)"). Any subset may be present depending on the release.
_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _now() -> str:
    """Collector-side UTC timestamp (ISO 8601)."""
    return datetime.now(timezone.utc).isoformat()


def _git_sha():
    """Best-effort current commit SHA; ``None`` if git is unavailable.

    The git SHA ties every run to the exact SKILL/LESSONS version — essential
    for A/B and rollback attribution. Failure is tolerated.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except Exception:
        pass
    return None


def _read_payload() -> dict:
    """Parse the hook JSON payload from stdin; ``{}`` on any problem."""
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _append(row: dict) -> None:
    """Append one JSON line to the metrics log, creating ``logs/`` if missing."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _parse_ts(value):
    """Parse an ISO-8601 timestamp defensively; ``None`` if unparseable."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):  # datetime.fromisoformat only learned "Z" late
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _summarize_transcript(path_str) -> dict:
    """Stream the transcript JSONL and derive token / time / tool-use totals.

    One record per line. Each line is ``json.loads``-ed under try/except and we
    pull whatever is present:
      * ``message.usage.<key>``  -> summed into token totals;
      * ``message.content[*]`` blocks with ``type == "tool_use"`` -> tool_calls;
      * ``timestamp`` -> first/last drive ``wall_clock_s``.
    Nothing here may raise: on any error we return the totals accumulated so far.
    """
    summary = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "tool_calls": 0,
        "wall_clock_s": None,
        "transcript_lines": 0,
    }
    if not isinstance(path_str, str) or not path_str:
        return summary
    path = Path(path_str)
    if not path.is_file():
        return summary

    first_ts = None
    last_ts = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                summary["transcript_lines"] += 1

                ts = _parse_ts(rec.get("timestamp"))
                if ts is not None:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts

                message = rec.get("message")
                if not isinstance(message, dict):
                    continue

                usage = message.get("usage")
                if isinstance(usage, dict):
                    for key in _USAGE_KEYS:
                        val = usage.get(key)
                        if isinstance(val, (int, float)) and not isinstance(val, bool):
                            summary[key] += int(val)

                content = message.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            summary["tool_calls"] += 1
    except Exception:
        return summary

    if first_ts is not None and last_ts is not None:
        try:
            summary["wall_clock_s"] = round((last_ts - first_ts).total_seconds(), 3)
        except Exception:
            summary["wall_clock_s"] = None
    return summary


def _handle_session_start(payload: dict) -> dict:
    return {
        "ts": _now(),
        "event": "session-start",
        "session_id": payload.get("session_id"),
        "model": payload.get("model"),
        "source": payload.get("source"),
        "git_sha": _git_sha(),
    }


def _handle_post_tool_use(payload: dict) -> dict:
    return {
        "ts": _now(),
        "event": "post-tool-use",
        "session_id": payload.get("session_id"),
        "tool_name": payload.get("tool_name"),
    }


def _handle_stop(payload: dict) -> dict:
    row = {
        "ts": _now(),
        "event": "stop",
        "session_id": payload.get("session_id"),
    }
    row.update(_summarize_transcript(payload.get("transcript_path")))
    return row


_HANDLERS = {
    "session-start": _handle_session_start,
    "post-tool-use": _handle_post_tool_use,
    "stop": _handle_stop,
}


def main() -> int:
    try:
        mode = sys.argv[1] if len(sys.argv) > 1 else ""
        handler = _HANDLERS.get(mode)
        if handler is None:
            # Unknown / missing mode: do nothing, but never complain.
            return 0
        _append(handler(_read_payload()))
    except Exception:
        # Absolute invariant: a metrics hook must never surface an error to the
        # session. Swallow everything and exit clean.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
