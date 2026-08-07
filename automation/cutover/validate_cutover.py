#!/usr/bin/env python3
"""The named ``cutover`` validation profile — is the owner's data still intact?

WHY THIS EXISTS
---------------
After a working tree is cut over to a merged layout, the question is narrow and
answerable: does every application's metadata still parse, does the calendar
still agree with it, does every configured path still resolve, did every copied
file arrive byte-identical, are the repository hooks still wired? Those checks
all exist (or are added beside this file); what did not exist was ONE command
that runs them and prints an exit-code table nobody can misread.

This is not ``automation/reconcile/reconcile.py``. That is the process-layer
schema referee wired into pre-commit and CI; it judges queue/task/memory files.
This judges the owner's DATA and the paths that reach it, and gates nothing.

It also does not contain a runner. ``automation/gates/run_gates.py`` already
solved "run N subprocesses and report each one's real exit code" — no shell, no
pipe, stdout+stderr REDIRECTED per gate so ``returncode`` is that gate's own, a
thread pool where every future carries its own ``Result``, and a summary in which
a SKIP is counted and named separately and never folded into the pass count. So
this module loads that one and supplies its own gate table and log directory.
Rewriting the runner would mean re-deriving all of that in a second place.

Usage::

    .venv/bin/python automation/cutover/validate_cutover.py --profile cutover --jobs 4
    .venv/bin/python automation/cutover/validate_cutover.py --list
    .venv/bin/python automation/cutover/validate_cutover.py --only configured-paths
    .venv/bin/python automation/cutover/validate_cutover.py \\
        --log-dir local/cutover/<run-id>/gates

Profiles::

    cutover       app-metadata · calendar · configured-paths · copy-checksum ·
                  overlay-bootstrap
    cutover-full  the above, plus locations · company-keys

Exit codes::

    0  every selected gate PASSed (skips are reported by name, never counted green)
    1  any gate FAILed or did not run
    2  usage error (argparse)
    3  REFUSED before any subprocess started — no config, the fictional example
       persona, or no mounted overlay

Every gate here is read-only over the owner's data, so all of them are
parallel-safe: ``--jobs 4`` collapses the profile to roughly its slowest gate.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path
from typing import Sequence

PROFILE_CUTOVER = "cutover"
PROFILE_FULL = "cutover-full"
PROFILES = (PROFILE_CUTOVER, PROFILE_FULL)

TRACKER = "skills/application-tracker/scripts/status.py"
BOOTSTRAP = "automation/bootstrap_overlay.py"
CHECK_PATHS = "automation/cutover/check_configured_paths.py"
VERIFY_COPY = "automation/cutover/verify_copy.py"

LOG_DIR_TEMPLATE = "local/cutover/{run_id}/gates"
MANIFEST_FILENAME = "copied.txt"


def _find_repo_root(start: Path) -> Path:
    """The nearest ancestor holding a ``.git`` entry (a FILE in a worktree)."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise SystemExit(
        f"validate_cutover: no .git entry above {start} — cannot locate the repo root")


REPO_ROOT = _find_repo_root(Path(__file__).resolve().parent)


def _load_module(path: Path, module_name: str):
    """Load a sibling toolkit module without making ``automation`` a package."""
    if not path.is_file():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not create an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def load_run_gates(root: Path = REPO_ROOT):
    """The gate runner — its ``Gate``/``run_gate``/``run_many``/``summarise``."""
    return _load_module(root / "automation" / "gates" / "run_gates.py",
                        "_jobhunt_run_gates")


def load_config(root: Path = REPO_ROOT):
    """The canonical shared config module."""
    return _load_module(root / "automation" / "shared" / "config.py",
                        "_jobhunt_config")


RUN_GATES = load_run_gates()
Gate = RUN_GATES.Gate
PreconditionResult = RUN_GATES.PreconditionResult
run_gate = RUN_GATES.run_gate
run_many = RUN_GATES.run_many
summarise = RUN_GATES.summarise
PASS, FAIL, SKIP, NOTRUN = RUN_GATES.PASS, RUN_GATES.FAIL, RUN_GATES.SKIP, RUN_GATES.NOTRUN


def run_id(now: float | None = None) -> str:
    """UTC stamp naming this run's log directory."""
    stamp = time.gmtime(now if now is not None else time.time())
    return time.strftime("%Y%m%dT%H%M%SZ", stamp)


# ── the gate table ───────────────────────────────────────────────────────────


def _manifest_precondition(manifest: Path):
    """A copy manifest that does not exist is a SKIP, and never a PASS.

    ``verify_copy.py --verify`` exits 3 on a missing manifest for the same
    reason; this stops the subprocess before it starts so the summary carries a
    named SKIP row instead of a red one.
    """

    def check(_root: Path):
        if manifest.is_file():
            return None
        return PreconditionResult(
            SKIP,
            f"no copy manifest at {manifest} — this run recorded no create-only "
            f"copies, so there is nothing to re-hash. An unrun check is a SKIP, "
            f"never a PASS.")

    return check


def build_gates(root: Path = REPO_ROOT, *, profile: str = PROFILE_CUTOVER,
                manifest: Path | None = None) -> list[Gate]:
    """The profile's gates, in the order a reader should meet them.

    Every argv is a real invocation of a script in this tree — verified against
    the flags those scripts define, and pinned by
    ``automation/cutover/tests/test_validate_cutover.py``.
    """
    if profile not in PROFILES:
        raise SystemExit(
            f"validate_cutover: unknown profile {profile!r} "
            f"(one of {', '.join(PROFILES)}).")
    py = sys.executable
    manifest = manifest or (root / "local" / "cutover" / MANIFEST_FILENAME)

    gates = [
        Gate(
            name="app-metadata",
            argv=(py, TRACKER, "--check-metadata"),
            what_it_proves="Every application's meta.yaml still parses and still "
                           "validates against schema v6 after the move.",
            group="cutover",
        ),
        Gate(
            name="calendar",
            argv=(py, TRACKER, "--check-calendar"),
            what_it_proves="calendar.md and the per-job progress records still agree "
                           "— the generated file most likely to be resolved by hand "
                           "during a layout conflict.",
            group="cutover",
        ),
        Gate(
            name="configured-paths",
            argv=(py, CHECK_PATHS),
            what_it_proves="Every config.*_path()/_dir()/_root() accessor resolves to "
                           "an existing destination of the right kind, so no tool is "
                           "quietly reading or writing the retired address.",
            group="cutover",
        ),
        Gate(
            name="copy-checksum",
            argv=(py, VERIFY_COPY, "--verify", "--manifest", str(manifest)),
            what_it_proves="Every git-ignored file copied to its merged destination "
                           "is byte-identical at both ends, and its source is still "
                           "there.",
            group="cutover",
            precondition=_manifest_precondition(manifest),
        ),
        Gate(
            name="overlay-bootstrap",
            argv=(py, BOOTSTRAP, "--check"),
            what_it_proves="Every tracked git hook is still installed in both repos "
                           "— a moved overlay whose hooks silently stopped running "
                           "looks identical to one whose hooks are fine.",
            group="cutover",
        ),
    ]
    if profile == PROFILE_FULL:
        gates += [
            Gate(
                name="locations",
                argv=(py, TRACKER, "--check-locations"),
                what_it_proves="Every drafted role still matches the configured "
                               "location policy.",
                group="cutover",
            ),
            Gate(
                name="company-keys",
                argv=(py, TRACKER, "--company-keys", "--strict"),
                what_it_proves="Every application's company_key still resolves in the "
                               "public registry.",
                group="cutover",
            ),
        ]
    return gates


# ── selection ────────────────────────────────────────────────────────────────


def select_gates(gates: Sequence[Gate], *, only: str | None = None,
                 skip: str | None = None) -> list[Gate]:
    """Apply ``--only`` / ``--skip``. An unknown name is an error, not an empty run."""
    known = {gate.name for gate in gates}

    def split(value: str | None) -> list[str]:
        return [part.strip() for part in (value or "").split(",") if part.strip()]

    wanted, unwanted = split(only), split(skip)
    for name in (*wanted, *unwanted):
        if name not in known:
            raise SystemExit(
                f"validate_cutover: unknown gate {name!r}. Try --list.")
    return [gate for gate in gates
            if (not wanted or gate.name in wanted) and gate.name not in unwanted]


# ── profile-level precondition ───────────────────────────────────────────────


def refusal_reason(config_module) -> str | None:
    """Why the whole profile must refuse to start, or None when it may run.

    Checked BEFORE any subprocess: a profile that validated the fictional example
    persona and reported ALL GREEN is the worst outcome this command has.
    """
    try:
        active = config_module.config_path()
    except Exception as error:
        return (f"no configuration could be loaded ({type(error).__name__}: {error}). "
                f"Nothing below would be validating the owner's data.")
    example_name = getattr(config_module, "EXAMPLE_CONFIG_FILENAME",
                           "config.example.yaml")
    example = getattr(config_module, "EXAMPLE_CONFIG", None)
    is_example = Path(active).name == example_name
    if example is not None:
        try:
            is_example = is_example or Path(active).resolve() == Path(example).resolve()
        except OSError:
            pass
    if is_example:
        return (f"configuration resolved to the fictional example persona ({active}). "
                f"A green cutover report over the placeholder certifies nothing.")
    try:
        mounted = config_module.overlay_mounted()
    except Exception as error:
        return f"overlay_mounted() raised {type(error).__name__}: {error}"
    if not mounted:
        return ("no private overlay is mounted, so there is no cut-over data to "
                "validate. Mount the overlay, or run the public gates with "
                "automation/gates/run_gates.py instead.")
    return None


# ── reporting ────────────────────────────────────────────────────────────────


def print_listing(gates: Sequence[Gate], root: Path, log_dir: Path, out) -> None:
    print(f"cutover validation profile — {len(gates)} gates    "
          f"(interpreter: {sys.executable})", file=out)
    print(f"repo root: {root}", file=out)
    print(f"logs:      {log_dir}/<name>.log\n", file=out)
    for gate in gates:
        print(f"{gate.name}", file=out)
        print(f"    $ {RUN_GATES._display_argv(gate.argv)}", file=out)
        print(f"    proves: {gate.what_it_proves}", file=out)
        precondition = RUN_GATES._evaluate_precondition(gate, root)
        if precondition is not None:
            print(f"    {precondition.status} HERE: {precondition.reason}", file=out)
        print(file=out)


# ── cli ──────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate_cutover.py",
        description="Validate the owner's data and configured paths after a "
                    "post-merge cutover. NOT automation/reconcile/reconcile.py, "
                    "which is the process-layer schema gate.")
    parser.add_argument("--profile", choices=PROFILES, default=PROFILE_CUTOVER,
                        help="cutover (default) or cutover-full")
    parser.add_argument("--jobs", type=int, default=1, metavar="N",
                        help="run this many gates concurrently (default 1 — serial). "
                             "Every gate here is read-only, so all are parallel-safe.")
    parser.add_argument("--list", action="store_true",
                        help="print the gate table and exit 0 without running anything")
    parser.add_argument("--only", metavar="NAME[,NAME...]", help="run only these gates")
    parser.add_argument("--skip", metavar="NAME[,NAME...]",
                        help="run everything except these gates")
    parser.add_argument("--log-dir", metavar="DIR",
                        help="where per-gate logs go (default "
                             "local/cutover/<run-id>/gates); the copy manifest is "
                             "read from its parent unless --manifest says otherwise")
    parser.add_argument("--manifest", metavar="PATH",
                        help="the verify_copy.py manifest to re-hash (default "
                             "<log-dir>/../copied.txt)")
    parser.add_argument("--tail", type=int, default=15, metavar="N",
                        help="log lines to print inline for a FAILING gate (default 15)")
    return parser


def main(argv: Sequence[str] | None = None, out=None, *, gate_builder=None) -> int:
    out = out or sys.stdout
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    if args.log_dir:
        log_dir = Path(args.log_dir).expanduser()
        if not log_dir.is_absolute():
            log_dir = (REPO_ROOT / log_dir).resolve()
    else:
        log_dir = REPO_ROOT / LOG_DIR_TEMPLATE.format(run_id=run_id())
    # The default manifest is the STABLE per-checkout path that build_gates
    # uses, never log_dir.parent: log_dir carries a fresh per-invocation run id,
    # so deriving the manifest from it names a directory this run just created
    # and copy-checksum could never find a manifest — the documented default
    # invocation would skip the one gate that proves the payloads arrived.
    manifest = (Path(args.manifest).expanduser() if args.manifest
                else REPO_ROOT / "local" / "cutover" / MANIFEST_FILENAME)

    builder = gate_builder or build_gates
    gates = select_gates(
        builder(REPO_ROOT, profile=args.profile, manifest=manifest),
        only=args.only, skip=args.skip)
    if not gates:
        print("validate_cutover: selection matched no gates.", file=out)
        return 1

    if args.list:
        print_listing(gates, REPO_ROOT, log_dir, out)
        return 0

    reason = refusal_reason(load_config(REPO_ROOT))
    if reason is not None:
        print(f"REFUSED: {reason}", file=out)
        print("No gate ran. This is exit 3, not a failure of any check.", file=out)
        return 3

    log_dir.mkdir(parents=True, exist_ok=True)
    print(f"running {len(gates)} gates (profile: {args.profile}, "
          f"jobs: {args.jobs}) — full output in {log_dir}", file=out)

    def announce(result) -> None:
        secs = "" if result.status in (SKIP, NOTRUN) else f"  {result.seconds:6.1f}s"
        code = "" if result.exit_code is None else f"  exit {result.exit_code}"
        print(f"  {result.status:<6} {result.name}{code}{secs}", file=out)
        out.flush()

    results = run_many(gates, log_dir, jobs=max(1, args.jobs), fail_fast=False,
                       root=REPO_ROOT, on_done=announce)
    # summarise() renders each log path relative to the root it is handed. A
    # caller-supplied --log-dir outside the checkout is legitimate (a scratch
    # tree, a test), so the display anchor follows the logs rather than raising.
    display_root = (REPO_ROOT if log_dir.is_relative_to(REPO_ROOT)
                    else log_dir.parent)
    return rollup(results, summarise(results, out, tail=args.tail,
                                     root=display_root, require_pass=True), out)


def rollup(results, summary_code: int, out) -> int:
    """A skipped check is not a passed check — enforce this module's own exit 0.

    ``run_gates.summarise`` returns 0 whenever nothing FAILED and prints
    ``ALL GREEN``. That is correct for the repo-wide lanes, where a SKIP means
    "not applicable in this checkout". It is wrong here: this docstring promises
    exit 0 means *every selected gate PASSed*, and ``copy-checksum`` is the only
    gate proving the owner's git-ignored payloads survived the move
    byte-identical. ``verify_copy.py`` exits 3 for "nothing was verified"
    precisely so an unrun check could never read green; flattening that to 0
    inverts it. A selection where nothing ran therefore refuses.
    """
    if summary_code != 0:
        return summary_code  # includes the require_pass=True all-skip refusal
    passed = [r for r in results if r.status == PASS]
    skipped = [r for r in results if r.status == SKIP]
    if skipped:
        names = ", ".join(sorted(r.name for r in skipped))
        print(f"PARTIAL: {len(passed)} verified, {len(skipped)} UNPROVEN "
              f"(skipped, not passed): {names}.", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
