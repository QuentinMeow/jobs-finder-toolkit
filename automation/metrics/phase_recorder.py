#!/usr/bin/env python3
"""Opt-in, harness-agnostic phase recorder (writer half).

Appends ONE JSON line per event to ``logs/phases/<session>.jsonl`` so a session's
wall clock can afterwards be split into *active*, *local subprocess*, *external
wait* and *approval wait* time by ``automation/metrics/phase_summary.py`` (the
reader half). It is deliberately NOT an extension of ``hook_collect.py``: that
tool reads a Claude Code hook payload from stdin and its transcript parser is
version-brittle, whereas this one is a plain CLI any harness (Codex, Claude Code,
a human shell) can call.

Usage (see ``docs/handbook/metrics.md`` for the full recipe):
    .venv/bin/python automation/metrics/phase_recorder.py session start --label recon
    .venv/bin/python automation/metrics/phase_recorder.py set inventory
    .venv/bin/python automation/metrics/phase_recorder.py run --phase validation -- \
        .venv/bin/python automation/gates/run_gates.py
    .venv/bin/python automation/metrics/phase_recorder.py session end --external-total-s 1653

HARD INVARIANTS — a telemetry tool must never break a session or a gate:
  * every subcommand exits 0 even when the log dir is unwritable, the pointer
    file is missing, or the existing log is corrupt (usage errors — an unknown
    subcommand, a missing argument — still exit 2, because silently swallowing a
    typo would hide the mistake instead of the failure);
  * ``run`` returns the CHILD's exit code VERBATIM, including when recording
    fails entirely. AGENTS.md forbids reporting a failed command as green;
  * ``run`` never pipes the child. stdin/stdout/stderr are inherited, so the
    caller's ``$?`` and stream semantics are exactly what they would be without
    the wrapper;
  * ``logs/`` is created on demand, is git-ignored AND on the leak guard's
    path-denylist, so raw events are structurally uncommittable.

Time is recorded as the triple ``(mono, wall, mono_epoch)``. ``time.monotonic()``
has an UNDEFINED per-process origin and this CLI is invoked as many short-lived
processes, so the monotonic value alone is meaningless across invocations.
``mono_epoch = round(time.time() - time.monotonic())`` is the cross-process
handshake: two events whose ``mono_epoch`` agrees within a couple of seconds
share a monotonic origin and their difference is trustworthy; a shift (sleep,
suspend, clock step) is DETECTED by the reader and reported as unattributed
time rather than silently producing a wrong duration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Resolved from THIS file, never from the cwd: a subagent's working directory
# moves between calls, so a relative log path would scatter the events.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_DIR = REPO_ROOT / "logs" / "phases"

SCHEMA_VERSION = 1
POINTER_NAME = "current.json"
SESSION_ENV = "JOBHUNT_PHASE_SESSION"
LOG_DIR_ENV = "JOBHUNT_PHASE_LOG_DIR"

# One event must be ONE line for the O_APPEND write to stay atomic under
# concurrent subagents. A long command line is truncated, never wrapped.
MAX_LINE_BYTES = 4096
MAX_ARG_CHARS = 200

# Recognised phase names. An UNKNOWN name is recorded verbatim rather than
# rejected — rejecting it would tempt an agent to skip instrumentation, and the
# summary collapses unknown names to a digest anyway.
KNOWN_PHASES = (
    "inventory",
    "context",
    "plan",
    "mutation",
    "validation",
    "commit",
    "publish",
    "external_wait",
    "closeout",
)

# The time CLASSES. Phase name and class are ORTHOGONAL axes: `gh pr checks
# --watch` is simultaneously a wrapped subprocess and a GitHub wait, so the
# wrapped-subprocess total is an overlay summed independently of these.
CLASS_ACTIVE = "active"
CLASS_LOCAL = "local_subprocess"
CLASS_EXTERNAL = "external_wait"
CLASS_APPROVAL = "approval_wait"

_KIND_ALIASES = {
    "active": CLASS_ACTIVE,
    "local": CLASS_LOCAL,
    "local_subprocess": CLASS_LOCAL,
    "subprocess": CLASS_LOCAL,
    "external": CLASS_EXTERNAL,
    "external_wait": CLASS_EXTERNAL,
    "wait": CLASS_EXTERNAL,
    "approval": CLASS_APPROVAL,
    "approval_wait": CLASS_APPROVAL,
}

# ``cmd`` itself never leaves the raw log; the summary only ever sees this
# closed enum, which is why the summary cannot leak a command line.
CMD_HEADS = ("git", "gh", "python", "soffice", "other")
_GIT_NETWORK_VERBS = frozenset({
    "fetch", "push", "pull", "clone", "ls-remote", "remote", "submodule",
})
_NETWORK_BASENAMES = frozenset({"gh", "curl", "wget", "ssh", "scp", "rsync"})

REPO_ROLES = ("public", "overlay", "unknown")
HARNESSES = ("codex", "claude-code", "other")

MARK_APPROVAL_START = "approval-start"
MARK_APPROVAL_END = "approval-end"
KNOWN_MARKS = (MARK_APPROVAL_START, MARK_APPROVAL_END, "note")


# ── primitives ───────────────────────────────────────────────────────────────

def _warn(message: str) -> None:
    """Recording problems are reported, never raised (they must not fail a run)."""
    try:
        sys.stderr.write(f"phase_recorder: {message}\n")
    except Exception:
        pass


def _now() -> tuple[str, float, int]:
    """``(wall ISO-8601, monotonic, mono_epoch)`` — the cross-process handshake.

    ``mono`` is the ONLY arithmetic clock; ``ts`` is for humans; ``mono_epoch``
    is what lets a later process decide whether its own ``mono`` shares an origin
    with this one (see the module docstring).
    """
    mono = time.monotonic()
    wall = time.time()
    return (
        datetime.fromtimestamp(wall, timezone.utc).isoformat(),
        round(mono, 6),
        int(round(wall - mono)),
    )


def digest(text: str) -> str:
    """First 8 hex of ``sha256(text)`` — distinguishes a value without naming it.

    Used for the session id and repository identity. This is a FINGERPRINT, not
    encryption: it is one-way, but a short low-entropy input can be confirmed by
    someone who already guessed it. It exists so two runs can be told apart, not
    to protect a secret.
    """
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:8]


def normalize_kind(value, default: str) -> str:
    """Map a CLI kind word onto a time class; unknown words fall back."""
    if not isinstance(value, str) or not value:
        return default
    return _KIND_ALIASES.get(value.strip().lower(), default)


def cmd_head(argv0) -> str:
    """Collapse ``argv[0]`` to an allowlisted basename (never a path)."""
    if not isinstance(argv0, str) or not argv0:
        return "other"
    name = Path(argv0).name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    if name == "git":
        return "git"
    if name == "gh":
        return "gh"
    if name.startswith("python") or name.startswith("pypy"):
        return "python"
    if name in ("soffice", "libreoffice", "soffice.bin"):
        return "soffice"
    return "other"


def network_hint(argv) -> bool:
    """True when a command LOOKS network-bound.

    Advisory ONLY. A hinted command is flagged in the summary, never
    reclassified: silently moving its seconds from ``local_subprocess`` to
    ``external_wait`` would be a second fabrication channel and would make two
    runs incomparable depending on which heuristic version ran.
    """
    if not argv:
        return False
    name = Path(str(argv[0])).name.lower()
    if name in _NETWORK_BASENAMES:
        return True
    if name == "git":
        for token in argv[1:]:
            token = str(token)
            if token.startswith("-"):
                continue
            return token in _GIT_NETWORK_VERBS
    return False


def _repo_fingerprint(cwd) -> str | None:
    """8 hex of the repository's ROOT-commit sha — distinguishes repos, names none.

    Best effort: a missing git, a non-repo cwd, or a shallow clone yields
    ``None`` and the event simply carries no fingerprint.
    """
    try:
        out = subprocess.run(
            ["git", "rev-list", "--max-parents=0", "HEAD"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    roots = sorted(out.stdout.split())
    return digest(roots[0]) if roots else None


# ── log dir / pointer / session id ───────────────────────────────────────────

def resolve_log_dir(explicit=None) -> Path:
    """``--log-dir`` > ``$JOBHUNT_PHASE_LOG_DIR`` > ``<repo>/logs/phases``."""
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get(LOG_DIR_ENV)
    if env:
        return Path(env).expanduser()
    return DEFAULT_LOG_DIR


def pointer_path(log_dir: Path) -> Path:
    return log_dir / POINTER_NAME


def log_path_for(log_dir: Path, session: str) -> Path:
    """One file per session, so two sessions in one log dir never interleave."""
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in session)[:120]
    return log_dir / f"{safe or 'session'}.jsonl"


def read_pointer(log_dir: Path):
    """The current session id, or ``None`` when the pointer is missing/corrupt."""
    try:
        raw = pointer_path(log_dir).read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        return None
    if isinstance(data, dict):
        session = data.get("session")
        if isinstance(session, str) and session:
            return session
    return None


def _write_pointer(log_dir: Path, session: str) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {"session": session, "updated": _now()[0]}
    pointer_path(log_dir).write_text(
        json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _clear_pointer(log_dir: Path) -> None:
    try:
        pointer_path(log_dir).unlink()
    except FileNotFoundError:
        pass


def allocate_session(label=None) -> str:
    """``<label|sess>-YYYYMMDD-<6 hex>`` — unique without a coordination point."""
    stem = "sess"
    if isinstance(label, str) and label.strip():
        cleaned = "".join(
            c if (c.isalnum() or c in "-_") else "-" for c in label.strip().lower()
        ).strip("-")
        if cleaned:
            stem = cleaned[:32]
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{stem}-{day}-{os.urandom(3).hex()}"


def resolve_session(explicit, log_dir: Path, *, use_pointer: bool = True):
    """``--session`` > ``$JOBHUNT_PHASE_SESSION`` > the pointer file > ``None``.

    ``session start`` passes ``use_pointer=False``: a second ``start`` must mint
    a NEW session rather than silently append to whatever the pointer still
    names, which would fuse two runs into one row.
    """
    if explicit:
        return explicit
    env = os.environ.get(SESSION_ENV)
    if env:
        return env
    return read_pointer(log_dir) if use_pointer else None


# ── reading back the session state (single source of truth: the log) ─────────

def read_state(log_path: Path) -> dict:
    """Derive the live state from the log itself — no side-car state file.

    A side-car could disagree with the log; the log cannot disagree with itself.
    Cost is one small-file read per invocation (hundreds of lines at most).
    Everything here is defensive: a corrupt log degrades to a fresh-looking
    state, it never raises.
    """
    state = {
        "next_seq": 0,
        "phase": None,
        "phase_kind": CLASS_ACTIVE,
        "repo_role": None,
        "repo_fingerprint": None,
        "harness": None,
        "harness_session_id": None,
        "fixture": None,
        "events": 0,
        "started_mono": None,
        "phase_open_mono": None,
        "ended": False,
    }
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return state
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        state["events"] += 1
        seq = rec.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            state["next_seq"] = max(state["next_seq"], seq + 1)
        for key in ("repo_role", "repo_fingerprint", "harness",
                    "harness_session_id", "fixture"):
            value = rec.get(key)
            if value:
                state[key] = value
        event = rec.get("event")
        mono = rec.get("mono")
        mono = mono if isinstance(mono, (int, float)) and not isinstance(mono, bool) else None
        if event == "session_start":
            state["started_mono"] = mono
            state["ended"] = False
        elif event == "session_end":
            state["ended"] = True
            state["phase"] = None
            state["phase_open_mono"] = None
        elif event == "phase_open":
            state["phase"] = rec.get("phase")
            state["phase_kind"] = rec.get("kind") or CLASS_ACTIVE
            state["phase_open_mono"] = mono
        elif event == "phase_close":
            state["phase"] = None
            state["phase_open_mono"] = None
    return state


# ── writing ──────────────────────────────────────────────────────────────────

def _shrink_cmd(cmd):
    return [str(a)[:MAX_ARG_CHARS] for a in cmd]


def serialize(row: dict) -> str:
    """One JSON line, guaranteed under ``MAX_LINE_BYTES``.

    An over-long ``cmd`` is truncated (with ``cmd_truncated``) rather than
    allowed to split the line — a split line is an unparseable event AND breaks
    the atomicity of the append.
    """
    def _encode(obj):
        text = json.dumps(obj, ensure_ascii=False)
        return text, len(text.encode("utf-8"))

    text, size = _encode(row)
    if size <= MAX_LINE_BYTES:
        return text

    row = dict(row)
    if row.get("cmd"):
        row["cmd"] = _shrink_cmd(row["cmd"])
        row["cmd_truncated"] = True
        text, size = _encode(row)
        if size <= MAX_LINE_BYTES:
            return text
        row["cmd"] = row["cmd"][:1]
        text, size = _encode(row)
        if size <= MAX_LINE_BYTES:
            return text
        row["cmd"] = None
        text, size = _encode(row)
        if size <= MAX_LINE_BYTES:
            return text
    if isinstance(row.get("label"), str):
        row["label"] = row["label"][:64]
        row["label_truncated"] = True
        text, size = _encode(row)
        if size <= MAX_LINE_BYTES:
            return text
    minimal = {
        key: row.get(key)
        for key in ("v", "session", "session_digest", "seq", "ts", "mono",
                    "mono_epoch", "event", "phase", "kind", "duration_s",
                    "exit_code", "outcome")
    }
    minimal["truncated"] = True
    return json.dumps(minimal, ensure_ascii=False)


def append_event(log_path: Path, row: dict) -> bool:
    """Append one event. Returns success; NEVER raises (fail-safe invariant)."""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(serialize(row) + "\n")
        return True
    except Exception as exc:  # unwritable dir, read-only fs, full disk, ...
        _warn(f"could not record event ({exc.__class__.__name__}: {exc})")
        return False


def _base_row(session: str, seq: int, event: str, clock=None) -> dict:
    ts, mono, epoch = clock if clock is not None else _now()
    return {
        "v": SCHEMA_VERSION,
        "session": session,
        "session_digest": digest(session),
        "seq": seq,
        "ts": ts,
        "mono": mono,
        "mono_epoch": epoch,
        "event": event,
        "pid": os.getpid(),
    }


class _Recorder:
    """Bookkeeping shared by every subcommand (log dir, session, seq, state)."""

    def __init__(self, args, *, allocate=False):
        self.log_dir = resolve_log_dir(getattr(args, "log_dir", None))
        session = resolve_session(
            getattr(args, "session", None), self.log_dir, use_pointer=not allocate
        )
        if session is None and allocate:
            session = allocate_session(getattr(args, "label", None))
        self.session = session
        self.log_path = log_path_for(self.log_dir, session) if session else None
        self.state = read_state(self.log_path) if self.log_path else read_state(Path(os.devnull))
        self._seq = self.state["next_seq"]

    def row(self, event: str, clock=None) -> dict:
        row = _base_row(self.session, self._seq, event, clock)
        self._seq += 1
        row["phase"] = self.state.get("phase")
        row["kind"] = None
        row["repo_role"] = self.state.get("repo_role")
        row["repo_fingerprint"] = self.state.get("repo_fingerprint")
        row["harness"] = self.state.get("harness")
        row["harness_session_id"] = self.state.get("harness_session_id")
        row["fixture"] = self.state.get("fixture")
        return row

    def write(self, row: dict) -> bool:
        if self.log_path is None:
            _warn("no session; run `session start` first (nothing recorded)")
            return False
        return append_event(self.log_path, row)

    def apply_repo(self, args, row: dict) -> None:
        """Attach ``repo_role`` (+ fingerprint) when the caller declared one."""
        role = getattr(args, "repo_role", None)
        if role:
            row["repo_role"] = role
            fingerprint = _repo_fingerprint(getattr(args, "cwd", None) or Path.cwd())
            if fingerprint:
                row["repo_fingerprint"] = fingerprint
            self.state["repo_role"] = row["repo_role"]
            self.state["repo_fingerprint"] = row["repo_fingerprint"]


# ── subcommands ──────────────────────────────────────────────────────────────

def cmd_session_start(args) -> int:
    rec = _Recorder(args, allocate=True)
    row = rec.row("session_start")
    row["phase"] = None
    if args.label:
        row["label"] = args.label
    if args.harness:
        row["harness"] = args.harness
    if args.harness_session_id:
        row["harness_session_id"] = args.harness_session_id
    if args.fixture:
        row["fixture"] = args.fixture
    if args.external_started_at:
        row["external_started_at"] = args.external_started_at
    rec.apply_repo(args, row)
    rec.write(row)
    try:
        _write_pointer(rec.log_dir, rec.session)
    except Exception as exc:
        _warn(f"could not write the pointer file ({exc.__class__.__name__}: {exc})")
    # The id goes to stdout undecorated so a shell can capture it directly.
    print(rec.session)
    return 0


def cmd_session_end(args) -> int:
    rec = _Recorder(args)
    if rec.session is None:
        _warn("no active session to end (nothing recorded)")
        return 0
    clock = _now()          # one instant, so the auto-close leaves no hole
    if rec.state.get("phase"):
        close = rec.row("phase_close", clock)
        close["kind"] = rec.state.get("phase_kind")
        close["outcome"] = "unclosed"
        rec.write(close)
        rec.state["phase"] = None
    row = rec.row("session_end", clock)
    row["phase"] = None
    row["outcome"] = args.outcome
    if args.external_total_s is not None:
        row["external_total_s"] = args.external_total_s
    rec.write(row)
    try:
        _clear_pointer(rec.log_dir)
    except Exception as exc:
        _warn(f"could not clear the pointer file ({exc.__class__.__name__}: {exc})")
    return 0


def _open_phase(rec: _Recorder, args, *, contiguous: bool) -> None:
    """Close any open phase then open ``args.phase``.

    ``set`` (contiguous) and ``open`` differ only in the flag written on the
    implicit close, so no interval can be lost either way.

    Both events share ONE clock reading. Calling ``_now()`` twice would leave a
    sub-millisecond hole between the close and the open — small, but it makes
    "contiguous" false, and a timeline that is only nearly contiguous is a
    timeline nobody can assert on.
    """
    clock = _now()
    kind = normalize_kind(getattr(args, "kind", None), CLASS_ACTIVE)
    if rec.state.get("phase"):
        close = rec.row("phase_close", clock)
        close["kind"] = rec.state.get("phase_kind")
        close["outcome"] = "ok"
        close["implicit_close"] = not contiguous
        rec.write(close)
    row = rec.row("phase_open", clock)
    row["phase"] = args.phase
    row["kind"] = kind
    if getattr(args, "label", None):
        row["label"] = args.label
    rec.apply_repo(args, row)
    rec.write(row)
    rec.state["phase"] = args.phase
    rec.state["phase_kind"] = kind


def cmd_set(args) -> int:
    rec = _Recorder(args)
    if rec.session is None:
        _warn("no active session; run `session start` first (nothing recorded)")
        return 0
    _open_phase(rec, args, contiguous=True)
    return 0


def cmd_open(args) -> int:
    rec = _Recorder(args)
    if rec.session is None:
        _warn("no active session; run `session start` first (nothing recorded)")
        return 0
    _open_phase(rec, args, contiguous=False)
    return 0


def cmd_close(args) -> int:
    rec = _Recorder(args)
    if rec.session is None or not rec.state.get("phase"):
        _warn("no open phase to close (nothing recorded)")
        return 0
    row = rec.row("phase_close")
    row["kind"] = rec.state.get("phase_kind")
    row["outcome"] = args.outcome
    row["implicit_close"] = False
    rec.write(row)
    return 0


def cmd_mark(args) -> int:
    rec = _Recorder(args)
    if rec.session is None:
        _warn("no active session; run `session start` first (nothing recorded)")
        return 0
    row = rec.row("mark")
    row["mark"] = args.name
    if args.name in (MARK_APPROVAL_START, MARK_APPROVAL_END):
        row["kind"] = CLASS_APPROVAL
    if args.label:
        row["label"] = args.label
    rec.write(row)
    return 0


def cmd_run(args) -> int:
    """Wrap a child command. Returns the CHILD's exit code, verbatim.

    Every recording step is individually guarded: a telemetry failure must not
    change the status the caller reads, and must not suppress the child.
    """
    child = list(args.command or [])
    if not child:
        _warn("run needs a command: `run [opts] -- CMD [ARGS...]`")
        return 2

    rec = None
    try:
        rec = _Recorder(args)
        if rec.session is None:
            _warn("no active session; the command still runs, nothing is recorded")
        elif args.phase:
            phase_args = argparse.Namespace(
                phase=args.phase,
                kind=args.phase_kind,
                label=None,
                repo_role=args.repo_role,
                cwd=args.cwd,
            )
            _open_phase(rec, phase_args, contiguous=True)
    except Exception as exc:
        _warn(f"pre-run recording failed ({exc.__class__.__name__}: {exc})")

    cwd = str(args.cwd) if args.cwd else None
    started = time.monotonic()
    spawn_error = None
    try:
        # NO pipe, NO capture: the child inherits our stdin/stdout/stderr so the
        # caller sees exactly what it would without the wrapper.
        exit_code = subprocess.run(child, cwd=cwd).returncode
        # Python reports a signalled child as NEGATIVE (-15 for SIGTERM); a shell
        # reports 128+N (143). Passing the negative through makes the wrapper
        # change the code the caller sees — sys.exit(-15) becomes 241 — which
        # breaks the one promise `run` makes: the exit code is the child's,
        # exactly as if the wrapper were not there.
        if exit_code < 0:
            exit_code = 128 - exit_code
    except Exception as exc:
        spawn_error = f"{exc.__class__.__name__}: {exc}"
        exit_code = 127
    duration = time.monotonic() - started

    if spawn_error is not None:
        _warn(f"could not start {child[0]!r} ({spawn_error})")

    try:
        if rec is not None and rec.session is not None:
            row = rec.row("run")
            row["kind"] = normalize_kind(args.kind, CLASS_LOCAL)
            row["duration_s"] = round(duration, 6)
            row["exit_code"] = exit_code
            row["cmd"] = list(child)
            row["cmd_head"] = cmd_head(child[0])
            row["cmd_network_hint"] = network_hint(child)
            row["spawn_failed"] = spawn_error is not None
            if args.label:
                row["label"] = args.label
            rec.apply_repo(args, row)
            rec.write(row)
    except Exception as exc:
        _warn(f"post-run recording failed ({exc.__class__.__name__}: {exc})")

    return exit_code


def cmd_status(args) -> int:
    rec = _Recorder(args)
    elapsed = None
    if rec.state.get("started_mono") is not None:
        elapsed = round(time.monotonic() - rec.state["started_mono"], 1)
    payload = {
        "session": rec.session,
        "session_digest": digest(rec.session) if rec.session else None,
        "log_path": str(rec.log_path) if rec.log_path else None,
        "phase": rec.state.get("phase"),
        "phase_kind": rec.state.get("phase_kind") if rec.state.get("phase") else None,
        "events": rec.state.get("events", 0),
        "elapsed_s": elapsed,
        "ended": rec.state.get("ended", False),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    elif rec.session is None:
        print("no active session")
    else:
        print(
            f"session={payload['session']} phase={payload['phase'] or '-'} "
            f"events={payload['events']} elapsed_s={payload['elapsed_s']}"
        )
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────

def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--session", help="session id (default: $%s, else the pointer file)"
                                          % SESSION_ENV)
    parser.add_argument("--log-dir", help=f"event log directory (default: {DEFAULT_LOG_DIR})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phase_recorder.py",
        description="Opt-in phase recorder: append session/phase/subprocess events.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    session_p = sub.add_parser("session", help="start / end a recording session")
    session_sub = session_p.add_subparsers(dest="subcmd", required=True)

    start = session_sub.add_parser("start", help="start a session (prints its id)")
    _add_common(start)
    start.add_argument("--label", help="slug used in the generated session id (raw log only)")
    start.add_argument("--harness", choices=HARNESSES)
    start.add_argument("--harness-session-id",
                       help="the harness's own session id, for joining logs/metrics.jsonl")
    start.add_argument("--external-started-at",
                       help="ISO-8601 start time read off the harness UI")
    start.add_argument("--fixture", help="benchmark fixture name")
    start.add_argument("--repo-role", choices=REPO_ROLES)
    start.set_defaults(func=cmd_session_start, cwd=None)

    end = session_sub.add_parser("end", help="end the session")
    _add_common(end)
    end.add_argument("--external-total-s", type=float,
                     help="elapsed seconds read off the harness UI (the coverage denominator)")
    end.add_argument("--outcome", choices=("ok", "partial", "failed", "abandoned"),
                     default="ok")
    end.set_defaults(func=cmd_session_end)

    for name, func, contiguous in (("set", cmd_set, True), ("open", cmd_open, False)):
        phase_p = sub.add_parser(
            name,
            help=("close-then-open at one instant (contiguous timeline)" if contiguous
                  else "open a phase, allowing a gap since the last one"),
        )
        _add_common(phase_p)
        phase_p.add_argument("phase", help="|".join(KNOWN_PHASES) + " (unknown names are kept)")
        phase_p.add_argument("--kind", choices=("active", "external", "approval"),
                             default="active")
        phase_p.add_argument("--repo-role", choices=REPO_ROLES)
        phase_p.add_argument("--label", help="free text; raw log only")
        phase_p.set_defaults(func=func, cwd=None)

    close = sub.add_parser("close", help="close the open phase")
    _add_common(close)
    close.add_argument("--outcome", choices=("ok", "failed"), default="ok")
    close.set_defaults(func=cmd_close)

    mark = sub.add_parser("mark", help="record a point event")
    _add_common(mark)
    mark.add_argument("name", help="|".join(KNOWN_MARKS))
    mark.add_argument("--label", help="free text; raw log only")
    mark.set_defaults(func=cmd_mark)

    run = sub.add_parser("run", help="time a child command (exit = the child's)")
    _add_common(run)
    run.add_argument("--phase", help="`set` this phase before running")
    run.add_argument("--phase-kind", choices=("active", "external", "approval"),
                     default="active", help="kind for --phase")
    run.add_argument("--kind", choices=("local_subprocess", "external"),
                     default="local_subprocess")
    run.add_argument("--label", help="free text; raw log only")
    run.add_argument("--cwd", help="working directory for the child")
    run.add_argument("--repo-role", choices=REPO_ROLES)
    run.add_argument("command", nargs="*", help="the command, after a literal --")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="show the active session and open phase")
    _add_common(status)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    return parser


def _split_child(argv: list[str]) -> tuple[list[str], list[str] | None]:
    """Split on the FIRST literal ``--``; everything after it is the child argv."""
    if "--" in argv:
        index = argv.index("--")
        return argv[:index], argv[index + 1:]
    return argv, None


def main(argv=None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    head, child = _split_child(raw)
    parser = build_parser()
    args = parser.parse_args(head)  # usage errors exit 2 here, by design
    if child is not None:
        args.command = child
    try:
        return args.func(args)
    except Exception as exc:
        # Absolute invariant: recording must never surface an error to the
        # session. ``cmd_run`` returns before this point, so a child's status is
        # never replaced by this 0.
        _warn(f"unexpected failure, ignored ({exc.__class__.__name__}: {exc})")
        return 0


if __name__ == "__main__":
    sys.exit(main())
