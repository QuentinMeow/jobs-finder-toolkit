#!/usr/bin/env python3
"""Stage-row harness for the reconciliation leg (R1–R4).

Instantiates the pinned fixture (``automation/evals/reconciliation_fixture.py``),
runs ONE stage's **deterministic part**, repeats it n ≥ 3 times, and prints the
median and range plus a results-template row fragment ready to paste into an
``evals/results/`` record. The stage map, boundaries and pinned subject-agent
prompts live in ``evals/protocols/reconciliation-stages.md``; this module is the
mechanical half of a row and never replaces the subject-agent half.

## What "deterministic part" means, and what it does NOT measure

A stage row has two halves. The **subject-agent half** — a fresh, model-pinned
agent given the stage's pinned prompt — is where the tokens and most of the wall
clock live, and it is run by hand per ``evals/protocols/stage-benchmarks.md``.
The **deterministic part** is the fixed sequence of commands that stage cannot
avoid: the git inventory reads, the classification plumbing, the validation
calls, the reconciler. It is the FLOOR. A row that reports 4 minutes for a stage
whose floor is 0.4 s has located 3.6 minutes of agent time; that subtraction is
the whole reason this half is measured separately.

Deliberately not measured here:

  * **tokens** — no model runs in this half. The field is ``not_measured``, never
    an estimate;
  * **execution / mutation** — the guarded executor is deferred and does not
    exist, so no stage benchmarks one. Nothing here checkpoints, rebases, copies
    or deletes anything in the fixture;
  * **publication (PR open → merge)** — external wait by definition; the completed
    ``2026-08-03-reduce-pr-ci-and-stack-latency`` measurements cover it and this
    task reuses them rather than reopening that design.

## Phase telemetry

If the opt-in phase recorder is armed for the session, pass ``--phase-session``
(and ``--phase-log-dir`` when it is not the default) and this harness will run
``automation/metrics/phase_summary.py --json`` at the end and embed the summary
under ``phase_summary``. When the module is absent, or the call fails, the field
reads ``recorder absent`` (or the failure reason) and every other number is
unaffected: **the harness's own ``time.monotonic()`` is always the authoritative
timing**, so a row never depends on the recorder existing.

## Usage

    .venv/bin/python automation/evals/reconciliation_bench.py --list-stages
    .venv/bin/python automation/evals/reconciliation_bench.py --stage R1 --runs 3
    .venv/bin/python automation/evals/reconciliation_bench.py --stage R4 --runs 3 \\
        --variant base --json --out local/reconciliation-bench/R4.json

Exit 0 when every run's steps produced their expected exit codes, 1 when a step
came back with an unexpected code (a stage whose floor did not behave is not a
measurement), 2 on a usage or fixture failure.
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import reconciliation_fixture as FIX  # noqa: E402

REPO_ROOT = FIX.REPO_ROOT

# Resolved from THIS FILE, never from the operator's cwd: a script that resolves
# its root from __file__ audits the tree it lives in, so running the harness from
# the main checkout would benchmark the main checkout's reconciler while the
# branch's copy sat unmeasured (memory/lessons: verify-from-the-branch's-own-copy).
RECONCILE = REPO_ROOT / "automation" / "reconcile" / "reconcile.py"
PHASE_SUMMARY = REPO_ROOT / "automation" / "metrics" / "phase_summary.py"

DEFAULT_WORK_DIR = REPO_ROOT / "local" / "reconciliation-bench"
DEFAULT_RUNS = 3


# ── stage model ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Step:
    """One timed unit of a stage's deterministic part.

    ``expect`` is the exit code the step MUST return. It is not decoration: R4's
    first reconciler call is expected to be **1** (the closeout records are
    missing, which is the stage's entry condition), and a harness that accepted
    any exit code there would report a green row for a fixture that had silently
    stopped reproducing the scenario.
    """

    name: str
    repo: str                       # "public" | "overlay" | "-"
    kind: str                       # "subprocess" | "inproc"
    argv: tuple[str, ...] = ()
    inproc: str = ""                # name of an _inproc_* function in this module
    expect: int = 0


@dataclass(frozen=True)
class Stage:
    stage_id: str
    title: str
    phase: str                      # the phase_recorder phase name this maps to
    variant: str
    boundary: str
    steps: tuple[Step, ...]


def _git(repo: str, *args: str, expect: int = 0, name: str = "") -> Step:
    return Step(name=name or f"git {' '.join(args[:2])}", repo=repo,
                kind="subprocess", argv=("git", *args), expect=expect)


_R1_INVENTORY = (
    ("status", "--porcelain=v1", "--branch"),
    ("branch", "-vv"),
    ("remote", "-v"),
    ("worktree", "list", "--porcelain"),
    ("rev-list", "--left-right", "--count", "main...origin/main"),
    ("log", "--oneline", "-n", "5"),
    ("rev-parse", "HEAD"),
)

STAGES: dict[str, Stage] = {
    "R1": Stage(
        stage_id="R1",
        title="Two-repository inventory (read-only)",
        phase="inventory",
        variant="base",
        boundary="the complete inventory of BOTH repositories is stated "
                 "(branch, upstream, worktrees, dirty paths, ahead/behind, remotes)",
        steps=tuple(
            [_git("public", *a, name=f"public: git {a[0]}") for a in _R1_INVENTORY]
            + [_git("overlay", *a, name=f"overlay: git {a[0]}") for a in _R1_INVENTORY]
        ),
    ),
    "R2": Stage(
        stage_id="R2",
        title="Dirty-path classification and plan",
        phase="plan",
        variant="base",
        boundary="every dirty path carries a classification (unchanged / renamed "
                 "by the merged layout / content-divergent / ignored / unknown) and "
                 "the proposed step sequence exists",
        steps=(
            _git("overlay", "status", "--porcelain=v1", "--untracked-files=all",
                 "--ignored=matching", name="overlay: dirty + ignored paths"),
            _git("overlay", "merge-base", "main", "origin/main",
                 name="overlay: merge base"),
            _git("overlay", "diff", "--name-status", "--find-renames=100%",
                 "main", "origin/main", name="overlay: rename evidence (-M100%)"),
            _git("overlay", "diff", "--numstat", "main", "origin/main",
                 name="overlay: layout delta size"),
            _git("overlay", "hash-object", f"{FIX.OLD_ROOT}/notes/journal.md",
                 name="overlay: object id of the dirty journal"),
            _git("overlay", "hash-object", f"{FIX.OLD_ROOT}/{FIX.GENERATED_REL}",
                 name="overlay: object id of the dirty generated file"),
            _git("overlay", "rev-parse", f"codex/dirty:{FIX.OLD_ROOT}/{FIX.GENERATED_REL}",
                 name="overlay: pre-refactor generated blob"),
            _git("overlay", "rev-parse", f"origin/main:{FIX.NEW_ROOT}/{FIX.GENERATED_REL}",
                 name="overlay: post-refactor generated blob"),
            _git("overlay", "ls-files", "--others", "--ignored", "--exclude-standard",
                 name="overlay: ignored working-tree files"),
            Step(name="classify: generated-file delta is path-only", repo="overlay",
                 kind="inproc", inproc="generated_delta_is_path_only"),
        ),
    ),
    "R3": Stage(
        stage_id="R3",
        title="Validation profile (one command, one set of exit codes)",
        phase="validation",
        variant="destination-exists",
        boundary="every validation in the profile has reported an exit code and "
                 "none was silently skipped",
        steps=(
            _git("overlay", "diff", "--check", name="overlay: whitespace/conflict markers"),
            _git("public", "ls-files", "--error-unmatch",
                 f"{FIX.NEW_ROOT}/{FIX.GENERATED_REL}",
                 name="public: configured generated path is tracked"),
            _git("public", "ls-files", "--error-unmatch",
                 f"{FIX.NEW_ROOT}/applications/6_drafted/example-role/meta.yaml",
                 name="public: configured application path is tracked"),
            _git("overlay", "hash-object", f"{FIX.OLD_ROOT}/{FIX.IGNORED_REL}",
                 name="overlay: checksum of the ignored source"),
            Step(name="validate: application metadata shape", repo="overlay",
                 kind="inproc", inproc="metadata_shape"),
            Step(name="validate: generated calendar points at the new layout",
                 repo="overlay", kind="inproc", inproc="calendar_points_at_new_layout"),
            Step(name="validate: ignored source retained at the old path",
                 repo="overlay", kind="inproc", inproc="ignored_source_retained"),
            Step(name="validate: ignored destination would not be overwritten",
                 repo="overlay", kind="inproc", inproc="ignored_destination_protected"),
        ),
    ),
    "R4": Stage(
        stage_id="R4",
        title="Closeout records through the real reconciler",
        phase="closeout",
        variant="base",
        boundary="`reconcile.py --root <public> --check` exits 0",
        steps=(
            Step(name="reconcile: entry condition is RED", repo="public",
                 kind="subprocess",
                 argv=(sys.executable, str(RECONCILE), "--check", "--root", "{public}"),
                 expect=1),
            Step(name="closeout: write the required records", repo="public",
                 kind="inproc", inproc="write_closeout_records"),
            Step(name="reconcile: regenerate memory/index.md", repo="public",
                 kind="subprocess",
                 argv=(sys.executable, str(RECONCILE), "--fix-index", "--root", "{public}")),
            Step(name="reconcile: exit condition is GREEN", repo="public",
                 kind="subprocess",
                 argv=(sys.executable, str(RECONCILE), "--check", "--root", "{public}")),
        ),
    ),
}


# ── in-process checks ────────────────────────────────────────────────────────
#
# Each returns (exit_code, note). They are the parts of a stage that are a
# JUDGEMENT over the tree rather than a command — the same judgement the stage's
# subject agent has to make, executed deterministically so the floor is honest.

def _run_git(repo: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(("git", "-C", str(repo), *args),
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout


def _inproc_generated_delta_is_path_only(m: FIX.FixtureManifest) -> tuple[int, str]:
    rc_old, old = _run_git(m.overlay, "show",
                           f"codex/dirty:{FIX.OLD_ROOT}/{FIX.GENERATED_REL}")
    rc_new, new = _run_git(m.overlay, "show",
                           f"origin/main:{FIX.NEW_ROOT}/{FIX.GENERATED_REL}")
    if rc_old or rc_new:
        return 2, "could not read both versions of the generated file"
    if FIX.rewrite_layout_paths(old) == new:
        return 0, "path-only: the layout rewrite is the entire delta"
    return 1, "NOT path-only — the replay is not mechanical"


def _inproc_metadata_shape(m: FIX.FixtureManifest) -> tuple[int, str]:
    meta = m.overlay / FIX.OLD_ROOT / "applications/6_drafted/example-role/meta.yaml"
    if not meta.is_file():
        return 1, f"missing {meta.name}"
    text = meta.read_text(encoding="utf-8")
    missing = [k for k in ("company:", "jobs:", "status:", "location:")
               if k not in text]
    if missing:
        return 1, f"missing key(s): {', '.join(missing)}"
    return 0, "company/jobs/status/location present"


def _inproc_calendar_points_at_new_layout(m: FIX.FixtureManifest) -> tuple[int, str]:
    rc, text = _run_git(m.overlay, "show",
                        f"origin/main:{FIX.NEW_ROOT}/{FIX.GENERATED_REL}")
    if rc:
        return 2, "could not read the post-refactor generated file"
    stale = [ln for ln in text.splitlines() if f"{FIX.OLD_ROOT}/" in ln]
    if stale:
        return 1, f"{len(stale)} row(s) still point at {FIX.OLD_ROOT}/"
    return 0, f"every row points at {FIX.NEW_ROOT}/"


def _inproc_ignored_source_retained(m: FIX.FixtureManifest) -> tuple[int, str]:
    source = m.overlay / FIX.OLD_ROOT / FIX.IGNORED_REL
    if not source.is_file():
        return 1, "the ignored source is GONE — an ignored file is owner data"
    if source.read_text(encoding="utf-8") != FIX._IGNORED_SOURCE:
        return 1, "the ignored source was modified"
    return 0, "retained, byte-identical"


def _inproc_ignored_destination_protected(m: FIX.FixtureManifest) -> tuple[int, str]:
    source = m.overlay / FIX.OLD_ROOT / FIX.IGNORED_REL
    dest = m.overlay / FIX.NEW_ROOT / FIX.IGNORED_REL
    if not dest.exists():
        return 0, "destination free — a copy is safe"
    text = dest.read_text(encoding="utf-8")
    if text == FIX._IGNORED_DESTINATION_OCCUPANT:
        return 0, "destination still holds its own bytes — not overwritten"
    # Every branch used to return 0, which made this step decorative: it is
    # registered as "ignored destination would not be overwritten" and could
    # not report the one state it exists to catch. The check is against the
    # OCCUPANT the fixture pre-placed, not against "are the bytes different" —
    # the R3 variant is destination-exists, so occupied-with-different-bytes is
    # the designed setup, and an overwrite is the failure.
    if text == source.read_text(encoding="utf-8"):
        return 1, "destination was OVERWRITTEN with the ignored source's bytes"
    return 1, "destination holds unexpected bytes — neither occupant nor source"


def _inproc_write_closeout_records(m: FIX.FixtureManifest) -> tuple[int, str]:
    written = FIX.write_closeout_records(m.public)
    return 0, f"wrote {', '.join(written)}"


_INPROC = {
    "generated_delta_is_path_only": _inproc_generated_delta_is_path_only,
    "metadata_shape": _inproc_metadata_shape,
    "calendar_points_at_new_layout": _inproc_calendar_points_at_new_layout,
    "ignored_source_retained": _inproc_ignored_source_retained,
    "ignored_destination_protected": _inproc_ignored_destination_protected,
    "write_closeout_records": _inproc_write_closeout_records,
}


# ── execution ────────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    name: str
    kind: str
    seconds: float
    exit_code: int
    expected: int
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == self.expected


@dataclass
class RunResult:
    index: int
    fixture_root: Path
    steps: list[StepResult] = field(default_factory=list)
    build_seconds: float = 0.0

    @property
    def seconds(self) -> float:
        return sum(s.seconds for s in self.steps)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)


def _cwd_for(step: Step, m: FIX.FixtureManifest) -> Path:
    return {"public": m.public, "overlay": m.overlay}.get(step.repo, m.root)


def _execute(step: Step, m: FIX.FixtureManifest) -> StepResult:
    if step.kind == "inproc":
        fn = _INPROC[step.inproc]
        start = time.monotonic()
        code, note = fn(m)
        elapsed = time.monotonic() - start
        return StepResult(step.name, step.kind, elapsed, code, step.expect, note)

    argv = tuple(a.replace("{public}", str(m.public)).replace("{overlay}", str(m.overlay))
                 for a in step.argv)
    if argv[0] == "git":
        argv = ("git", "-C", str(_cwd_for(step, m)), *argv[1:])
    start = time.monotonic()
    proc = subprocess.run(argv, cwd=str(_cwd_for(step, m)),
                          capture_output=True, text=True)
    elapsed = time.monotonic() - start
    note = ""
    if proc.returncode != step.expect:
        note = (proc.stderr.strip() or proc.stdout.strip() or "").splitlines()
        note = note[0] if note else f"exit {proc.returncode}"
    return StepResult(step.name, step.kind, elapsed, proc.returncode, step.expect, note)


def run_stage(stage: Stage, *, runs: int, work_dir: Path,
              variant: str | None = None, keep: bool = False) -> list[RunResult]:
    chosen = variant or stage.variant
    results: list[RunResult] = []
    for index in range(1, runs + 1):
        root = work_dir / f"{stage.stage_id}-{chosen}-run{index}"
        build_start = time.monotonic()
        manifest = FIX.build(root, variant=chosen, force=True)
        build_seconds = time.monotonic() - build_start
        result = RunResult(index=index, fixture_root=manifest.root,
                           build_seconds=build_seconds)
        for step in stage.steps:
            result.steps.append(_execute(step, manifest))
        results.append(result)
        if not keep and index < runs:
            shutil.rmtree(root, ignore_errors=True)
    return results


# ── phase telemetry (optional, never load-bearing) ───────────────────────────

def collect_phase_summary(session: str | None, log_dir: Path | None) -> dict:
    """The armed recorder's redacted summary, or a stated reason there is none.

    Never raises and never changes a timing number. The recorder is opt-in and is
    owned by ``automation/metrics/``; this harness degrades to "recorder absent"
    rather than making a stage row impossible to produce without it.
    """
    if not PHASE_SUMMARY.is_file():
        return {"status": "recorder absent",
                "detail": f"{PHASE_SUMMARY.relative_to(REPO_ROOT)} does not exist"}
    if session is None and log_dir is None:
        return {"status": "not collected",
                "detail": "no --phase-session given; arm the recorder and pass one"}
    argv = [sys.executable, str(PHASE_SUMMARY), "--json"]
    if session:
        argv += ["--session", session]
    else:
        argv += ["--last"]
    if log_dir:
        argv += ["--log-dir", str(log_dir)]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "unavailable", "detail": f"{type(exc).__name__}: {exc}"}
    if proc.returncode != 0:
        return {"status": "unavailable",
                "detail": f"phase_summary.py exited {proc.returncode}: "
                          f"{proc.stderr.strip()[:200]}"}
    try:
        return {"status": "collected", "summary": json.loads(proc.stdout)}
    except ValueError as exc:
        return {"status": "unavailable", "detail": f"unparseable JSON: {exc}"}


# ── reporting ────────────────────────────────────────────────────────────────

def _stats(values: list[float]) -> dict[str, float]:
    return {
        "median": round(statistics.median(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def summarize(stage: Stage, variant: str, results: list[RunResult],
              phase: dict) -> dict:
    per_step: list[dict] = []
    for position, step in enumerate(stage.steps):
        samples = [r.steps[position] for r in results]
        per_step.append({
            "name": step.name,
            "repo": step.repo,
            "kind": step.kind,
            "expected_exit": step.expect,
            "exit_codes": sorted({s.exit_code for s in samples}),
            "ok": all(s.ok for s in samples),
            "seconds": _stats([s.seconds for s in samples]),
            "note": next((s.note for s in samples if s.note), ""),
        })
    return {
        "schema": "reconciliation-stage-row/1",
        "stage_id": stage.stage_id,
        "title": stage.title,
        "phase": stage.phase,
        "boundary": stage.boundary,
        "fixture_version": FIX.FIXTURE_VERSION,
        "variant": variant,
        "runs": len(results),
        "arm": "current-path",
        "ok": all(r.ok for r in results),
        "build_seconds": _stats([r.build_seconds for r in results]),
        "deterministic_seconds": _stats([r.seconds for r in results]),
        "subprocess_steps": sum(1 for s in stage.steps if s.kind == "subprocess"),
        "inproc_steps": sum(1 for s in stage.steps if s.kind == "inproc"),
        "steps": per_step,
        "total_tokens": "not_measured",
        "tool_calls": "not_measured",
        "phase_summary": phase,
        "fixture_roots": [str(r.fixture_root) for r in results],
    }


def render_row(summary: dict) -> str:
    """A results-template stage-row fragment (``evals/results/TEMPLATE.md``)."""
    det = summary["deterministic_seconds"]
    lines = [
        f"### Stage row — {summary['stage_id']} · {summary['title']}",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Stage id | `{summary['stage_id']}` — boundary + prompt in "
        f"`evals/protocols/reconciliation-stages.md` |",
        f"| Fixture | `{summary['fixture_version']}` variant `{summary['variant']}` — "
        f"`automation/evals/reconciliation_fixture.py` (pinned commit SHAs) |",
        f"| Arm | `{summary['arm']}` (deterministic part only — no model ran) |",
        f"| n runs | {summary['runs']} |",
        "| Primary metric | `wall_clock_s` of the deterministic part — "
        "registered before the runs |",
        f"| Model version | `not applicable` — this half carries no model |",
        f"| Steps | {summary['subprocess_steps']} subprocess + "
        f"{summary['inproc_steps']} in-process |",
        f"| All steps at their expected exit code | "
        f"{'yes' if summary['ok'] else 'NO — the row is not a measurement'} |",
        "",
        "**Deterministic part** (seconds; median with the range beside it):",
        "",
        "| step | repo | median | min | max | expected exit | seen |",
        "|------|------|-------:|----:|----:|--------------:|------|",
    ]
    for step in summary["steps"]:
        s = step["seconds"]
        seen = ",".join(str(c) for c in step["exit_codes"])
        flag = "" if step["ok"] else " ⚠"
        lines.append(
            f"| {step['name']}{flag} | {step['repo']} | {s['median']:.4f} | "
            f"{s['min']:.4f} | {s['max']:.4f} | {step['expected_exit']} | {seen} |")
    lines += [
        f"| **TOTAL** | | **{det['median']:.4f}** | {det['min']:.4f} | "
        f"{det['max']:.4f} | | |",
        "",
        f"Fixture build (excluded from the total): median "
        f"{summary['build_seconds']['median']:.4f}s "
        f"[{summary['build_seconds']['min']:.4f}–"
        f"{summary['build_seconds']['max']:.4f}].",
        "",
        f"**Tokens:** `not_measured` — no model runs in this half. "
        f"**Tool calls:** `not_measured` (subprocess steps: "
        f"{summary['subprocess_steps']}).",
        "",
    ]
    phase = summary["phase_summary"]
    if phase.get("status") == "collected":
        lines.append("**Phase telemetry:** collected — paste the `phase_summary` "
                     "markdown table beside this row.")
    else:
        lines.append(f"**Phase telemetry:** {phase.get('status')} — "
                     f"{phase.get('detail', '')}".rstrip(" —"))
    lines += [
        "",
        f"**Boundary:** {summary['boundary']}",
        "",
        "**Subject-agent half:** run the stage's pinned prompt per "
        "`evals/protocols/stage-benchmarks.md` and record `total_tokens`, "
        "`tool_calls` and `wall_clock_s` in the row above this fragment. The "
        "numbers here are the FLOOR that half is measured against, not the row.",
    ]
    return "\n".join(lines) + "\n"


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", help=f"one of {', '.join(sorted(STAGES))}")
    parser.add_argument("--list-stages", action="store_true")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS,
                        help=f"repetitions (default {DEFAULT_RUNS}; the protocol "
                             f"requires at least 3)")
    parser.add_argument("--variant", default=None, choices=sorted(FIX.VARIANTS),
                        help="override the stage's isolating fixture variant")
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR),
                        help=f"where fixtures are instantiated (default "
                             f"{DEFAULT_WORK_DIR.relative_to(REPO_ROOT)})")
    parser.add_argument("--keep", action="store_true",
                        help="keep every run's fixture tree, not just the last")
    parser.add_argument("--phase-session", default=None,
                        help="session id of an armed phase recorder")
    parser.add_argument("--phase-log-dir", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", default=None, help="also write the output here")
    args = parser.parse_args(argv)

    if args.list_stages:
        print(f"reconciliation leg — fixture {FIX.FIXTURE_VERSION} "
              f"(protocol: evals/protocols/reconciliation-stages.md)")
        for sid in sorted(STAGES):
            st = STAGES[sid]
            print(f"  {sid}  {st.title}")
            print(f"        phase={st.phase}  variant={st.variant}")
            print(f"        boundary: {st.boundary}")
        return 0

    if not args.stage:
        parser.print_help()
        return 2
    stage = STAGES.get(args.stage.upper())
    if stage is None:
        print(f"reconciliation_bench: unknown stage {args.stage!r} — "
              f"known: {', '.join(sorted(STAGES))}", file=sys.stderr)
        return 2
    if args.runs < 1:
        print("reconciliation_bench: --runs must be >= 1", file=sys.stderr)
        return 2
    if args.runs < 3:
        print("reconciliation_bench: WARNING — the protocol requires at least 3 "
              "runs; this row is not recordable.", file=sys.stderr)

    variant = args.variant or stage.variant
    try:
        results = run_stage(stage, runs=args.runs,
                            work_dir=Path(args.work_dir).expanduser(),
                            variant=variant, keep=args.keep)
    except FIX.FixtureError as exc:
        print(f"reconciliation_bench: {exc}", file=sys.stderr)
        return 2

    phase = collect_phase_summary(
        args.phase_session,
        Path(args.phase_log_dir).expanduser() if args.phase_log_dir else None)
    summary = summarize(stage, variant, results, phase)
    text = json.dumps(summary, indent=2) if args.json else render_row(summary)
    print(text)
    if args.out:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
