#!/usr/bin/env python3
"""Run this repo's blocking gates locally — one command, one exit-code table.

WHY THIS EXISTS
---------------
Roughly two dozen checks block a commit or a merge here: the ``automation/hooks/
pre-commit`` chain and every ``run:`` step of ``.github/workflows/ci.yml``. There
was no single local command for them, so each agent and the owner hand-rolled the
invocations — and the recurring mistake was piping a gate into ``tail``/``grep`` to
shorten its output and then reading ``$?``::

    automation/reconcile/reconcile.py --check | tail -5 ; echo $?    # prints 0

``$?`` after a pipeline is the LAST stage's status, so that reads ``tail``'s 0 for a
gate that exited 1 — a RED gate read as GREEN. It has happened more than once, and
prose in ``AGENTS.md`` did not stop it. So this runner makes the correct thing the
easy thing:

  * every gate is a subprocess with **no shell** and **no pipe** — stdout+stderr are
    REDIRECTED into ``local/gates/<name>.log``, which preserves the real exit code
    (a redirect is not a pipeline) and loses none of the output;
  * the summary is an explicit ``NAME / EXIT / RESULT`` table plus one final line
    that says ALL GREEN or names every gate that failed;
  * a gate missing an optional prerequisite (LibreOffice absent, ``private/`` not
    mounted) reports **SKIP**, never PASS. A known-unsafe execution environment
    reports **FAIL** before a subprocess starts. Skips and failures are counted
    and named separately, always;
  * **"nothing ran" never renders as "everything passed".** A run in which no gate
    actually executed a check produces no evidence, so it gets its own verdict word
    (``NO EVIDENCE``) and its own exit code (3) — never ``ALL GREEN``, never 0. The
    green line always carries the denominator (``n of N gates ran``), and a run that
    narrowed the lane set names the lanes it dropped and why. Silent narrowing is how
    a run of 8 gates out of 36 was once read as a full suite.

Uncommitted work is visible to ``--impact-from``: a Git range is commit-to-commit and
cannot see a dirty tree, so the working tree is classified too and its lanes are
UNIONED into the selection (see ``impact_decision``).

Usage::

    .venv/bin/python automation/gates/run_gates.py               # everything
    .venv/bin/python automation/gates/run_gates.py --list        # the table, no runs
    .venv/bin/python automation/gates/run_gates.py --group hook  # what pre-commit runs
    .venv/bin/python automation/gates/run_gates.py --lane maintenance
    .venv/bin/python automation/gates/run_gates.py --impact-from origin/main --jobs 4
    .venv/bin/python automation/gates/run_gates.py --only reconciler,verify-links
    .venv/bin/python automation/gates/run_gates.py --lane publish --jobs 3

Exit codes: **0** when at least one gate executed and every SELECTED gate exited 0
(skips are reported, not failures) · **1** when a gate failed or was cut short ·
**3** when NO gate executed a check at all — nothing was selected, or everything
skipped. 3 is deliberately not 1: "no evidence" is not "red", and neither is green.
``automation/cutover/verify_copy.py`` already spends exit 3 on exactly this meaning.

The gate table below is derived from ``automation/hooks/pre-commit`` and
``.github/workflows/ci.yml`` — the invocations are copied, not invented. Drift is a
test, not a promise: ``automation/gates/tests/test_run_gates.py`` re-parses
``ci.yml`` on every run and fails when a step is neither in this table nor in the
``NOT_RUN_LOCALLY`` mapping with a written reason.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

# ── repo root ────────────────────────────────────────────────────────────────
# Resolved from THIS FILE, never from the working directory: a subagent's cwd
# resets between calls, and the runner is routinely invoked from a git worktree.
# In a worktree ``.git`` is a FILE (``gitdir: …``), not a directory, so the probe
# is ``.exists()`` rather than ``.is_dir()``.


def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise SystemExit(
        f"run_gates: no .git entry above {start} — cannot locate the repo root")


REPO_ROOT = _find_repo_root(Path(__file__).resolve().parent)
LOG_DIR_REL = "local/gates"  # local/ is the gitignored scratch tree (AGENTS.md)
GROUPS = ("hook", "ci", "both")

# CI invokes the always-on policy lane for every change, then one or more focused
# long-running lanes selected by automation/ci/classify_changes.py.  Keep gate
# membership here rather than duplicating it in the workflow: this table is what
# both CI and local reproductions consume through ``--lane``.
CI_LANES: dict[str, tuple[str, ...]] = {
    "policy": (
        "vendor-drift",
        "mail-send-less",
        "compileall",
        "instruction-budget",
        "skill-prompt-audit",
        "reconciler",
        "verify-links",
        "review-gate-verify-all",
        "leak-guard-tree",
    ),
    "maintenance": (
        "tests-reconcile",
        "tests-gardener",
        "tests-hooks",
        "tests-metrics",
        "tests-evals",
        "tests-gates",
        "tests-ci-classifier",
        "tests-cutover",
        "tests-workspace",
        "tests-github-workflow",
    ),
    "render": ("example-render",),
    "resume": ("tests-resume-writer",),
    "shared": ("tests-shared", "validate-example-store"),
    "job-search": (
        "tests-recall-audit",
        "tests-job-search",
        "filter-variants",
    ),
    "applications": (
        "tests-application-tracker",
        "tests-email-assistant",
        "tests-behavioral-prep",
    ),
    "publish": (
        "tests-publish-review",
        "tests-publish-guard",
        "tests-publish-export",
    ),
}
LONG_CI_LANES = tuple(name for name in CI_LANES if name != "policy")
_FULL_IMPACT_LANES = ("policy", *LONG_CI_LANES)

# Repo-root maintenance tooling may import the canonical shared module directly.
# Put its directory on sys.path so --list still works when invoked from any cwd.
SHARED_DIR = REPO_ROOT / "automation" / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

import libreoffice_env  # noqa: E402


# ── gate table ───────────────────────────────────────────────────────────────

PASS, FAIL, SKIP, NOTRUN = "PASS", "FAIL", "SKIP", "NOTRUN"

# "No gate executed a check." Not 0 (nothing was proven) and not 1 (nothing was
# disproven either). Mirrors automation/cutover/verify_copy.py, which already spends
# 3 on "nothing was verified" so an unrun check could never be read as a passed one.
EXIT_NO_EVIDENCE = 3


@dataclass(frozen=True)
class PreconditionResult:
    """A gate that must fail or skip before its subprocess starts."""

    status: str
    reason: str

    def __post_init__(self) -> None:
        if self.status not in (FAIL, SKIP):
            raise ValueError(f"precondition status must be FAIL or SKIP, got {self.status!r}")


@dataclass(frozen=True)
class Gate:
    """One blocking check.

    ``argv``            executed with NO shell, cwd = repo root. Python entries use
                        ``sys.executable`` so the runner works from a worktree
                        (which has no ``.venv`` of its own).
    ``what_it_proves``  one line; where the hook and CI invoke the same script with
                        DIFFERENT flags, this table carries the CI form and the line
                        says so.
    ``group``           ``hook`` (pre-commit only) · ``ci`` (CI only) · ``both``.
    ``env``             extra environment for this gate only.
    ``parallel_safe``   False = never run concurrently with anything, even under
                        ``--jobs N`` (see ``run_many``).
    ``precondition``    returns a PreconditionResult, a legacy SKIP reason
                        string, or None to run.
    ``dirties``         a gate that REWRITES TRACKED FILES leaves that note here; the
                        summary repeats it, because CI does this in a throwaway
                        checkout and your working tree is not one.
    """

    name: str
    argv: tuple[str, ...]
    what_it_proves: str
    group: str
    env: dict[str, str] = field(default_factory=dict)
    parallel_safe: bool = True
    precondition: Callable[[Path], PreconditionResult | str | None] | None = None
    dirties: str | None = None


# ── preconditions ────────────────────────────────────────────────────────────
def _needs_libreoffice(_root: Path) -> PreconditionResult | None:
    environment = libreoffice_env.libreoffice_environment()
    if environment.launchservices is libreoffice_env.LaunchServicesAccess.DENIED:
        return PreconditionResult(
            FAIL,
            libreoffice_env.launchservices_denied_diagnostic(environment.executable),
        )
    if environment.executable is None:
        return PreconditionResult(
            SKIP,
            "LibreOffice not found (JOBHUNT_SOFFICE / ~/Applications / "
            "/Applications / soffice or libreoffice on PATH). CI installs "
            "libreoffice-writer, so this gate — including check.py's one-page "
            "PDF validation — runs there and NOT here.",
        )
    return None


def _needs_overlay(plain_gate: str) -> Callable[[Path], str | None]:
    """The hook adds ``--require-roots`` only when ``private/`` is mounted."""

    def check(root: Path) -> str | None:
        if (root / "private").is_dir():
            return None
        return (f"private/ is not mounted, so the pre-commit hook runs the PLAIN form "
                f"here — covered by `{plain_gate}`. --require-roots is a "
                f"maintainer-checkout assertion; CI never passes it either.")

    return check


def _leak_guard_is_armed() -> bool:
    """Mirror of the guard's own arming rule: a real config.yaml, or the env tokens.

    Only used to pick which of CI's two branches to reproduce. The guard remains the
    authority — it prints its own unarmed report and exits 2 if this guess is wrong.
    """
    if os.environ.get("JOBHUNT_PERSONAL_TOKENS", "").strip():
        return True
    configured = os.environ.get("JOBHUNT_CONFIG")
    if configured and Path(configured).is_file():
        return True
    return (REPO_ROOT / "config.yaml").is_file()


def _skill_script_dirs(root: Path) -> list[str]:
    """CI's ``skills/*/scripts`` glob, expanded here because there is no shell."""
    return [p.relative_to(root).as_posix()
            for p in sorted((root / "skills").glob("*/scripts")) if p.is_dir()]


def build_gates(root: Path = REPO_ROOT) -> list[Gate]:
    """The gate table, in the order the pre-commit hook meets them, then CI-only."""
    py = sys.executable
    example_config = {"JOBHUNT_CONFIG": str(root / "config.example.yaml")}
    # CI step 8 is an if/else on the identity tokens; reproduced, not invented.
    leak_tree_argv = (py, "automation/publish/check_public.py")
    if not _leak_guard_is_armed():
        leak_tree_argv += ("--allow-unarmed",)
    review_gate_argv = (py, "automation/publish/review_gate.py", "--verify-all")
    review_head = os.environ.get("JOBHUNT_REVIEW_HEAD", "").strip()
    if review_head:
        review_gate_argv += ("--head", review_head)

    return [
        # ── the pre-commit hook's chain, in its order ────────────────────────
        Gate(
            name="staged-private-paths",
            # The hook spells this `git diff --cached --name-only --diff-filter=ACMRT
            # | grep '^private/'`. A pipeline needs a shell and hides the exit code —
            # the two things this runner refuses — so it is re-expressed shell-free:
            # `--exit-code` makes git exit 1 exactly when the pathspec has staged
            # additions/modifications, which is the hook's condition, and --name-only
            # still prints the offending paths into the log.
            argv=("git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT",
                  "--exit-code", "--", "private/"),
            what_it_proves="No private/ overlay path is staged. Hook-only, and only "
                           "meaningful with something staged: `git add -f private/` "
                           "is silent, this is not.",
            group="hook",
            parallel_safe=False,  # reads the git index
        ),
        Gate(
            name="leak-guard-staged",
            argv=(py, "automation/publish/check_public.py", "--staged",
                  "--allow-unarmed"),
            what_it_proves="The blobs THIS commit would add carry no identity tokens, "
                           "structural PII, or absolute home path. Judges the staged "
                           "index, so run it with your change staged.",
            group="hook",
            parallel_safe=False,  # reads the git index
        ),
        Gate(
            name="review-gate-staged",
            argv=(py, "automation/publish/review_gate.py", "--staged"),
            what_it_proves="The staged tree does not change the published tree without "
                           "a row in automation/publish/review_ledger.yaml. Prints the "
                           "PENDING row to append. CI runs --verify-all instead.",
            group="hook",
            parallel_safe=False,  # reads the git index
        ),
        Gate(
            name="vendor-drift",
            argv=(py, "automation/vendoring/sync_vendored.py", "--check"),
            what_it_proves="Every skill's scripts/_vendor/ copy is byte-identical to "
                           "its automation/shared/ source. Same flags in hook and CI.",
            group="both",
        ),
        Gate(
            name="mail-send-less",
            argv=(py, "automation/shared/mail/check_mail_safety.py",
                  "--consumer", "skills/email-assistant/scripts"),
            what_it_proves="No mail provider folder or the email-assistant CLI exposes "
                           "send capability. Same flags in hook and CI.",
            group="both",
        ),
        Gate(
            name="compileall",
            # CI form: `compileall automation skills/*/scripts` (every skill). The hook
            # runs a narrower `-q automation` + four named skills; the CI set is a
            # superset, so passing here passes there.
            argv=(py, "-m", "compileall", "automation", *_skill_script_dirs(root)),
            what_it_proves="No toolkit or skill script has a syntax error. CI form "
                           "(every skills/*/scripts); the hook compiles -q and four "
                           "named skills only.",
            group="both",
        ),
        Gate(
            name="instruction-budget",
            argv=(py, "automation/metrics/instruction_budget.py", "--strict"),
            what_it_proves="No SKILL.md over 600 lines, LESSONS.md over 160, AGENTS.md "
                           "over its tier. Same flags in hook and CI.",
            group="both",
        ),
        Gate(
            name="skill-prompt-audit",
            argv=(py, "automation/metrics/skill_prompt_audit.py", "--strict"),
            what_it_proves="Every public, mounted-private, and adapter SKILL.md stays "
                           "within conservative direct-prompt, description, and section "
                           "limits; advisory prompt-shape signals remain content-safe.",
            group="both",
        ),
        Gate(
            name="reconciler",
            argv=(py, "automation/reconcile/reconcile.py", "--check"),
            what_it_proves="Queue/task/memory items match their templates/ schema, the "
                           "memory index is current, sessions have handovers, the "
                           "roadmap date parses. CI form (no --require-roots).",
            group="both",
        ),
        Gate(
            name="reconciler-require-roots",
            argv=(py, "automation/reconcile/reconcile.py", "--check", "--require-roots"),
            what_it_proves="Same, plus: every process root the reconciler names still "
                           "exists, so a rename breaks the check instead of disarming "
                           "it. Hook-only, and only when private/ is mounted.",
            group="hook",
            precondition=_needs_overlay("reconciler"),
        ),
        Gate(
            name="verify-links",
            # --no-overlay is copied from the hook, not invented, and it is not a
            # weakening. CI has no overlay, so the flag is a NO-OP there and this
            # stays byte-equivalent to what CI enforces. In a maintainer checkout it
            # is what stops the runner judging a SEPARATE repository at its own
            # commit: without it this gate read the overlay's markdown and reported
            # RED on a green tree. automation/hooks/pre-commit refuses the same thing
            # in a comment that names the symptom — "the branch becomes uncommittable
            # on the maintainer's own machine". Overlay link coverage is not dropped,
            # it belongs to the deliberate gardener routine (flagless verify_links.py,
            # whose output may name private/ paths and must never be pasted publicly).
            argv=(py, "automation/gardener/verify_links.py", "--no-overlay"),
            what_it_proves="Every backticked path and [text](path) in a must-resolve "
                           "document resolves; no skill symlink dangles. CI form (no "
                           "--require-roots) plus the hook's --no-overlay, a no-op in "
                           "CI's overlay-free checkout.",
            group="both",
        ),
        Gate(
            name="verify-links-require-roots",
            argv=(py, "automation/gardener/verify_links.py", "--require-roots",
                  "--no-overlay"),
            what_it_proves="Same, plus the named-root assertion. Hook-only, and only "
                           "when private/ is mounted.",
            group="hook",
            precondition=_needs_overlay("verify-links"),
        ),

        # ── CI-only: the unit suites of step 2c ──────────────────────────────
        Gate(
            name="tests-reconcile",
            argv=(py, "-m", "unittest", "discover", "automation/reconcile/tests"),
            what_it_proves="The reconciler's root handling and retry filing.",
            group="ci",
        ),
        Gate(
            name="tests-gardener",
            argv=(py, "-m", "unittest", "discover", "automation/gardener/tests"),
            what_it_proves="The gardener routines: link/reference verification, skill "
                           "drift, store report, the self-measure funnel.",
            group="ci",
        ),
        Gate(
            name="tests-hooks",
            argv=(py, "-m", "unittest", "discover", "automation/hooks/tests"),
            what_it_proves="The private-overlay git hooks: the store-payload and "
                           "staged-set-size guards, and the push-destination check.",
            group="ci",
        ),
        Gate(
            name="tests-recall-audit",
            argv=(py, "-m", "unittest", "discover", "automation/search-recall-audit/tests"),
            what_it_proves="The search-recall-audit readers of the append-only "
                           "applications skip-log.",
            group="ci",
        ),
        Gate(
            name="tests-metrics",
            argv=(py, "-m", "unittest", "discover", "automation/metrics/tests"),
            what_it_proves="The instruction-budget gate's discovery and leaf tiers.",
            group="ci",
        ),
        Gate(
            name="tests-evals",
            argv=(py, "-m", "unittest", "discover", "automation/evals/tests"),
            what_it_proves="The eval-record content pins: emit determinism, drift, "
                           "rename detection, the --write round-trip.",
            group="ci",
        ),
        Gate(
            name="tests-gates",
            argv=(py, "-m", "unittest", "discover", "automation/gates/tests"),
            what_it_proves="This runner: exit-code aggregation, SKIP is never a PASS, "
                           "selection flags, and the CI-drift check that fails when a "
                           "ci.yml step is neither in this table nor excused.",
            group="ci",
        ),
        Gate(
            name="tests-ci-classifier",
            argv=(py, "-m", "unittest", "discover", "automation/ci/tests"),
            what_it_proves="The fail-closed change classifier maps paths to stable "
                           "focused lane matrices and handles unsafe Git input.",
            group="ci",
        ),
        Gate(
            name="tests-cutover",
            argv=(py, "-m", "unittest", "discover", "automation/cutover/tests"),
            what_it_proves="The post-merge cutover tooling: the validation profile's "
                           "exit-code aggregation, the configured-path doctor's "
                           "fail-closed refusals, and verify_copy's never-overwrite, "
                           "never-delete guarantees.",
            group="ci",
        ),
        Gate(
            name="tests-workspace",
            argv=(py, "-m", "unittest", "discover", "automation/workspace/tests"),
            what_it_proves="The local Git dashboard inventories clean and dirty "
                           "worktrees, branch locality, cached remote state, and the "
                           "optional private overlay without depending on the caller's cwd.",
            group="ci",
        ),

        # ── CI-only: the rest of the build job ───────────────────────────────
        Gate(
            name="review-gate-verify-all",
            # CI sets JOBHUNT_REVIEW_HEAD on a pull_request, which adds
            # `--head <sha>` and pins the gate to the PR's own tip instead of a
            # merge preview. A blank or absent value preserves the local/main form.
            argv=review_gate_argv,
            what_it_proves="Recomputes EVERY historical ledger row's digest and file "
                           "count — the full append-only check. The hook only "
                           "recomputes a bounded tail. JOBHUNT_REVIEW_HEAD pins the "
                           "reviewed revision for pull requests.",
            group="ci",
            parallel_safe=False,  # walks the whole history with git
        ),
        Gate(
            name="example-render",
            argv=(py, "skills/resume-writer/scripts/render.py",
                  "examples/me/applications/6_drafted/example-corp-senior-software-engineer/"),
            what_it_proves="The worked example renders and passes check.py under the "
                           "fake config.example.yaml persona: locked fields, real "
                           "titles/skills, bullet lengths, one-page PDF.",
            group="ci",
            env=example_config,
            parallel_safe=False,  # writes into examples/ and drives a headless soffice
            precondition=_needs_libreoffice,
            dirties="rewrites the four tracked example DOCX/PDF artifacts under "
                    "examples/me/applications/6_drafted/example-corp-senior-software-engineer/ "
                    "(binary output is not byte-reproducible). CI does this in a "
                    "throwaway checkout; you are not in one — `git checkout -- examples/` "
                    "unless the new bytes are the point of your change.",
        ),
        Gate(
            name="tests-resume-writer",
            argv=(py, "-m", "unittest", "discover",
                  "-s", "skills/resume-writer/scripts/tests"),
            what_it_proves="Canonical/legacy schema normalization, multi-employer "
                           "extraction/render/layout, and one isolated "
                           "_test_application_ search-to-PDF workflow.",
            group="ci",
            env=example_config,
            parallel_safe=False,  # scaffolds under the example applications root
        ),
        Gate(
            name="tests-shared",
            argv=(py, "-m", "unittest", "discover", "automation/shared/tests"),
            what_it_proves="Job-metadata extraction/validation, the metadata editor, "
                           "company-levels import, layout/search/backfill, and the "
                           "raw-data-layer store library.",
            group="ci",
        ),
        Gate(
            name="validate-example-store",
            argv=(py, "automation/store/validate_store.py", "examples/store",
                  "--check-fixture-size"),
            what_it_proves="The fictional example store validates zone-by-zone; its "
                           "size threshold warns rather than blocks.",
            group="ci",
        ),
        Gate(
            name="tests-job-search",
            argv=(py, "-m", "unittest", "discover",
                  "-s", "skills/job-search/scripts/tests",
                  "-t", "skills/job-search/scripts/tests"),
            what_it_proves="The deterministic high-stakes filter corpus, "
                           "snapshot/refilter parity, review preservation, handoff "
                           "contracts.",
            group="ci",
            env=example_config,
            parallel_safe=False,  # writes under the example applications root
        ),
        Gate(
            name="filter-variants",
            argv=(py, "skills/job-search/scripts/validate_filter_variants.py", "--check"),
            what_it_proves="The recorded filter-variant corpus still matches what the "
                           "filter actually does.",
            group="ci",
        ),
        Gate(
            name="tests-application-tracker",
            argv=(py, "-m", "unittest", "discover",
                  "-s", "skills/application-tracker/scripts/tests"),
            what_it_proves="The meta.yaml schema, the per-job status rollup, and the "
                           "folder moves over owner data.",
            group="ci",
            env=example_config,
            parallel_safe=False,  # moves folders under the example applications root
        ),
        Gate(
            name="tests-email-assistant",
            argv=(py, "-m", "unittest", "discover",
                  "-s", "skills/email-assistant/scripts/tests"),
            what_it_proves="The send-less mail path, the Graph client, store sync.",
            group="ci",
        ),
        Gate(
            name="tests-behavioral-prep",
            argv=(py, "-m", "unittest", "discover",
                  "-s", "skills/behavioral-interview-prep/scripts/tests"),
            what_it_proves="The behavioral-prep story bank and answer validation.",
            group="ci",
        ),
        Gate(
            name="tests-github-workflow",
            argv=(py, "-m", "unittest", "discover",
                  "-s", "skills/github-workflow/scripts/tests"),
            what_it_proves="The PR-body checker, including the eval-gate discharge "
                           "forms CI's pr-body job blocks on.",
            group="ci",
        ),
        # These used to be one 112-second unittest discovery subprocess.  They use
        # separate process environments and temporary exports, so the publish lane
        # can run its three measured tails concurrently under ``--jobs 3``.
        Gate(
            name="tests-publish-review",
            argv=(py, "-m", "unittest",
                  "automation/publish/tests/test_review_gate.py"),
            what_it_proves="The append-only public review ledger's digest, history, "
                           "staged-tree, and fail-closed behavior.",
            group="ci",
        ),
        Gate(
            name="tests-publish-guard",
            argv=(py, "-m", "unittest",
                  "automation/publish/tests/test_leak_guard.py",
                  "automation/publish/tests/test_export_arming.py",
                  "automation/publish/tests/test_skill_manifests.py",
                  "automation/publish/tests/test_store_leak_guard.py"),
            what_it_proves="The public leak guard's structural-PII, path-denylist, "
                           "arming, skill-manifest, and store protections.",
            group="ci",
        ),
        Gate(
            name="tests-publish-export",
            argv=(py, "-m", "unittest",
                  "automation/publish/tests/test_export_enumeration.py",
                  "automation/publish/tests/test_export_destination.py"),
            what_it_proves="The public export enumerates exactly the allowed tree "
                           "and refuses unsafe or contaminated destinations.",
            group="ci",
        ),
        Gate(
            name="leak-guard-tree",
            argv=leak_tree_argv,
            what_it_proves="The whole tracked tree is publishable. CI's if/else, "
                           "reproduced: armed (config.yaml / $JOBHUNT_PERSONAL_TOKENS) "
                           "runs it bare; unarmed adds --allow-unarmed for the "
                           "token-independent checks. Also the pre-push gate, which "
                           "always demands the armed form.",
            group="ci",
        ),
    ]


# What CI runs that this runner deliberately does not. Every entry is asserted by
# automation/gates/tests/test_run_gates.py, which fails when a ci.yml invocation is
# in NEITHER the table above NOR this mapping — so CI cannot grow a gate the runner
# silently stops covering.
NOT_RUN_LOCALLY: dict[str, str] = {
    "automation/ci/classify_changes.py":
        "CI bootstrap rather than a blocking gate: it classifies the immutable Git "
        "range before dependency installation and chooses which run_gates.py lanes "
        "to invoke. Local --impact-from imports the same classifier, while its "
        "behavior is covered by its focused unit tests.",
    "skills/github-workflow/scripts/check_pr_body.py":
        "GitHub-only: the pr-body job reads the pull_request event's BODY, which does "
        "not exist locally. Run it by hand against a draft body — see "
        "skills/github-workflow/SKILL.md.",
}

# Not a `run:` step at all, so the drift test never sees it; named here because a
# reader of this file is entitled to know what the runner still does not cover.
NOT_RUN_LOCALLY_NON_PYTHON: dict[str, str] = {
    "gitleaks (secret-scan job)":
        "A GitHub Action, not a run: step. It scans the FULL history for credential "
        "shapes; install gitleaks and run it by hand if you need it before a push.",
    "canonical-counts job":
        "Reports tree-wide totals into the job summary on main after a merge. It "
        "gates nothing, and its numbers are only true post-merge.",
}


# ── selection ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImpactDecision:
    """Fail-closed lane selection for cumulative branch impact."""

    ref: str
    merge_base: str | None
    long_lanes: tuple[str, ...]
    full: bool
    reason: str
    uncommitted: int = 0  # working-tree changes folded into the classification

    @property
    def lanes(self) -> tuple[str, ...]:
        if self.full:
            return _FULL_IMPACT_LANES
        return ("policy", *self.long_lanes)

    @property
    def dropped_lanes(self) -> tuple[str, ...]:
        """Lanes the full matrix has that this decision does NOT run."""
        selected = set(self.lanes)
        return tuple(name for name in _FULL_IMPACT_LANES if name not in selected)


def _full_impact(ref: str, reason: str, merge_base: str | None = None,
                 uncommitted: int = 0) -> ImpactDecision:
    return ImpactDecision(ref, merge_base, LONG_CI_LANES, True, reason, uncommitted)


def _load_change_classifier(root: Path):
    """Load the stdlib-only CI classifier without making automation a package."""
    path = root / "automation/ci/classify_changes.py"
    if not path.is_file():
        raise FileNotFoundError(path)
    module_name = "_jobhunt_ci_classify_changes"
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


def _git_bytes(args: Sequence[str], root: Path) -> bytes:
    """Run one read-only git command, returning stdout. No shell, no pipe."""
    result = subprocess.run(list(args), cwd=root, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip().replace("\n", " ")
        raise RuntimeError(f"`{' '.join(args)}` exited {result.returncode}"
                           + (f": {detail}" if detail else ""))
    return result.stdout


def worktree_changes(classifier, root: Path = REPO_ROOT) -> tuple:
    """Every uncommitted change, in the CI classifier's own ``Change`` shape.

    ``--impact-from`` compares COMMITS, so a tree full of unstaged edits classifies
    as "the Git range contains no changes" and narrows to the policy lane — the run
    then reports success having measured nothing about the work in progress. That is
    the defect this function closes.

    Two reads, because Git splits the answer:

      * ``git diff --name-status HEAD`` — staged AND unstaged edits to tracked files;
      * ``git ls-files --others --exclude-standard`` — untracked files, recorded as
        additions. ``--exclude-standard`` honours ``.gitignore``, so the scratch tree
        (``local/``) and the private overlay never expand the selection.

    Raises on any input the classifier's own parser refuses; the caller turns that
    into the full lane matrix rather than a guess.
    """
    changes = list(classifier.parse_name_status(
        _git_bytes(["git", "diff", "--name-status", "-z", "-M", "HEAD", "--"], root)))
    untracked = _git_bytes(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], root)
    for raw in untracked.split(b"\0"):
        if not raw:
            continue
        if b"\n" in raw or b"\r" in raw:
            raise RuntimeError("an untracked path contained a line break")
        changes.append(classifier.Change("A", (raw,)))
    return tuple(changes)


def impact_decision(ref: str, root: Path = REPO_ROOT) -> ImpactDecision:
    """Classify merge-base(ref, HEAD)..HEAD PLUS the working tree, fail-closed.

    The committed range and the working tree are classified separately and their
    lanes are UNIONED, so uncommitted work can only ever WIDEN the selection. Two
    alternatives were rejected: refusing to narrow at all while the tree is dirty
    (correct, but it makes the flag useless during normal work, and an unusable
    honest tool gets replaced by a dishonest hand-picked ``--lane`` list); and merely
    warning (the warning scrolls past, the exit code still says green). The accepted
    cost is that a dirty tree runs more gates — and that one unowned untracked file
    expands to the full matrix, which is the safe direction to be wrong in.
    """
    if not ref.strip() or ref.startswith("-"):
        return _full_impact(ref, "invalid or empty comparison ref")
    try:
        result = subprocess.run(
            ["git", "merge-base", "--", ref, "HEAD"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except (OSError, ValueError) as error:
        return _full_impact(ref, f"merge-base unavailable: {error}")
    if result.returncode:
        detail = result.stderr.strip().replace("\n", " ")
        reason = f"merge-base exited {result.returncode}"
        return _full_impact(ref, reason + (f": {detail}" if detail else ""))

    merge_base = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", merge_base):
        return _full_impact(ref, "merge-base returned an ambiguous object id")

    try:
        classifier = _load_change_classifier(root)
        advertised = tuple(classifier.LANES)
        if advertised != LONG_CI_LANES:
            return _full_impact(
                ref,
                "classifier lane names drift from the gate runner",
                merge_base,
            )
        classification = classifier.classify_range(root, merge_base, "HEAD")
        lanes = tuple(classification.lanes)
        full = classification.full
        reason = str(classification.reason).replace("\n", " ")
    except Exception as error:
        return _full_impact(
            ref, f"classifier unavailable or invalid: {error}", merge_base
        )

    # The working tree, which the committed range above cannot see.
    try:
        pending = worktree_changes(classifier, root)
        dirty = len(pending)
        if pending:
            tree = classifier.classify(pending)
            tree_lanes = tuple(tree.lanes)
            tree_full = tree.full
            tree_reason = str(tree.reason).replace("\n", " ")
        else:
            tree_lanes, tree_full, tree_reason = (), False, ""
    except Exception as error:
        return _full_impact(
            ref, f"uncommitted changes could not be classified: {error}", merge_base
        )

    if dirty:
        reason = (f"{reason}; plus {dirty} uncommitted change(s) folded in"
                  + (f" — {tree_reason}" if tree_reason else ""))
    if not isinstance(full, bool) or any(lane not in LONG_CI_LANES for lane in lanes):
        return _full_impact(ref, "classifier returned an ambiguous result", merge_base,
                            dirty)
    if not isinstance(tree_full, bool) or any(
            lane not in LONG_CI_LANES for lane in tree_lanes):
        return _full_impact(ref, "classifier returned an ambiguous result for the "
                                 "working tree", merge_base, dirty)
    if full or tree_full:
        return _full_impact(ref, reason or "classifier requested full coverage",
                            merge_base, dirty)
    if len(set(lanes)) != len(lanes) or len(set(tree_lanes)) != len(tree_lanes):
        return _full_impact(ref, "classifier returned duplicate lanes", merge_base,
                            dirty)
    union = set(lanes) | set(tree_lanes)
    ordered = tuple(lane for lane in LONG_CI_LANES if lane in union)
    return ImpactDecision(ref, merge_base, ordered, False, reason, dirty)


def print_impact_decision(decision: ImpactDecision, out) -> None:
    mode = "FULL fallback" if decision.full else "focused"
    base = decision.merge_base[:12] if decision.merge_base else "unavailable"
    reason = decision.reason or "no classifier reason"
    print(
        f"impact from {decision.ref!r} (merge-base {base}): {mode}; "
        f"lanes: {', '.join(decision.lanes)}; reason: {reason}",
        file=out,
    )
    dropped = decision.dropped_lanes
    if dropped:
        # Named, not merely absent: a reader who cannot see what was dropped cannot
        # judge whether the narrowing was appropriate for their change.
        print(f"  lanes DROPPED ({len(dropped)} of {len(_FULL_IMPACT_LANES)}): "
              f"{', '.join(dropped)}", file=out)
    if decision.uncommitted:
        print(f"  working tree: {decision.uncommitted} uncommitted change(s) folded "
              f"into this selection", file=out)
    else:
        print("  working tree: clean — this selection covers committed work only",
              file=out)


def _split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def select_gates(gates: Sequence[Gate], *, group: str | None = None,
                 lane: str | None = None, only: str | None = None,
                 skip: str | None = None) -> list[Gate]:
    """Apply selectors. Unknown names are errors and lane unions keep table order."""
    known = {g.name for g in gates}
    wanted, unwanted = _split(only), _split(skip)
    lanes = _split(lane)

    if lane is not None and not lanes:
        raise SystemExit("run_gates: --lane requires at least one lane name.")
    if lanes and group is not None:
        raise SystemExit("run_gates: --lane cannot be combined with --group; "
                         "a lane already defines its gate set.")
    if lanes and wanted:
        raise SystemExit("run_gates: --lane cannot be combined with --only; "
                         "use one selector, then optionally --skip gates.")
    unknown_lanes = [name for name in lanes if name not in CI_LANES]
    if unknown_lanes:
        raise SystemExit(
            f"run_gates: unknown lane {unknown_lanes[0]!r} "
            f"(one of {', '.join(CI_LANES)})."
        )
    lane_gate_names = {name for lane_name in lanes for name in CI_LANES[lane_name]}
    unknown_mapped_gates = sorted(lane_gate_names - known)
    if unknown_mapped_gates:
        raise SystemExit("run_gates: CI_LANES references unknown gate(s): "
                         + ", ".join(unknown_mapped_gates))

    for name in (*wanted, *unwanted):
        if name not in known:
            raise SystemExit(f"run_gates: unknown gate {name!r}. Try --list.")
    group = group or "both"
    if group not in GROUPS:
        raise SystemExit(f"run_gates: unknown group {group!r} (one of {', '.join(GROUPS)})")

    chosen = []
    for gate in gates:
        if lanes and gate.name not in lane_gate_names:
            continue
        if group != "both" and gate.group not in (group, "both"):
            continue
        if wanted and gate.name not in wanted:
            continue
        if gate.name in unwanted:
            continue
        chosen.append(gate)
    return chosen


# ── execution ────────────────────────────────────────────────────────────────


@dataclass
class Result:
    gate: Gate
    status: str
    exit_code: int | None = None
    seconds: float = 0.0
    log_path: Path | None = None
    reason: str | None = None

    @property
    def name(self) -> str:
        return self.gate.name


def _evaluate_precondition(gate: Gate, root: Path) -> PreconditionResult | None:
    """Normalize old string preconditions to explicit SKIP results."""
    if gate.precondition is None:
        return None
    result = gate.precondition(root)
    if isinstance(result, str):
        return PreconditionResult(SKIP, result)
    return result


def _is_wsl(*, release: str | None = None,
            environ: dict[str, str] | None = None) -> bool:
    """Return whether the current Linux process is hosted by Windows WSL."""
    environ = os.environ if environ is None else environ
    if release is None:
        try:
            release = Path("/proc/sys/kernel/osrelease").read_text(
                encoding="utf-8").strip()
        except OSError:
            release = ""
    return "microsoft" in release.lower() or bool(environ.get("WSL_DISTRO_NAME"))


def _is_windows_mount(path: Path) -> bool:
    return bool(re.match(r"^/mnt/[a-z](?:/|$)", path.absolute().as_posix().lower()))


def _wsl_temp_overrides(*, environ: dict[str, str] | None = None,
                        release: str | None = None,
                        temp_dir: Path | None = None) -> dict[str, str]:
    """Keep gate subprocess temp files off DrvFS when WSL inherits Windows TEMP."""
    environ = os.environ if environ is None else environ
    if not _is_wsl(release=release, environ=environ):
        return {}
    selected = temp_dir or Path(tempfile.gettempdir())
    native = Path("/tmp")
    if not _is_windows_mount(selected):
        return {}
    if not native.is_dir() or not os.access(native, os.W_OK | os.X_OK):
        return {}
    return {"TMPDIR": str(native), "TMP": str(native), "TEMP": str(native)}


def run_gate(gate: Gate, log_dir: Path, root: Path = REPO_ROOT) -> Result:
    """Run one gate. stdout+stderr are REDIRECTED to a file — never piped."""
    precondition = _evaluate_precondition(gate, root)
    if precondition is not None:
        exit_code = 1 if precondition.status == FAIL else None
        return Result(
            gate,
            precondition.status,
            exit_code=exit_code,
            reason=precondition.reason,
        )

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{gate.name}.log"
    inherited = dict(os.environ)
    temp_overrides = _wsl_temp_overrides(environ=inherited)
    env = {**inherited, **temp_overrides, **gate.env}
    started = time.monotonic()
    try:
        with log_path.open("wb") as log:
            env_prefix = ""
            if temp_overrides:
                env_prefix = "env TMPDIR=/tmp TMP=/tmp TEMP=/tmp "
            log.write(f"$ {env_prefix}{' '.join(gate.argv)}\n\n".encode())
            log.flush()
            completed = subprocess.run(list(gate.argv), cwd=root, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
    except FileNotFoundError:
        # The binary itself is missing (git, python, a converter). A missing tool is
        # a SKIP with the reason named — never a silent pass.
        return Result(gate, SKIP, seconds=time.monotonic() - started, log_path=log_path,
                      reason=f"executable not found: {gate.argv[0]}")
    elapsed = time.monotonic() - started
    status = PASS if completed.returncode == 0 else FAIL
    return Result(gate, status, completed.returncode, elapsed, log_path)


def run_many(gates: Sequence[Gate], log_dir: Path, *, jobs: int, fail_fast: bool,
             root: Path, on_done: Callable[[Result], None]) -> list[Result]:
    """Serial by default. --jobs N parallelises only the gates marked safe.

    Public because it is the piece other profiles reuse rather than re-derive:
    ``automation/cutover/validate_cutover.py`` loads this module and drives its
    own gate table through this function, so "each future carries its own real
    exit code, redirected never piped" is implemented once.

    Forced serial (``parallel_safe=False``) and why: the three staged-index gates and
    review-gate-verify-all read the git index/history; example-render and the
    resume-writer / job-search / application-tracker suites all write into the SAME
    examples/me/applications tree (and example-render drives a single headless
    LibreOffice profile). Those run first, one at a time, in table order. The
    publish-test shards are process-isolated and remain parallel-safe.
    """
    results: list[Result] = []
    serial = [g for g in gates if not g.parallel_safe or jobs <= 1]
    parallel = [g for g in gates if g.parallel_safe and jobs > 1]
    stopped = False

    for gate in serial:
        if stopped:
            results.append(Result(gate, NOTRUN, reason="--fail-fast: an earlier gate failed"))
            continue
        result = run_gate(gate, log_dir, root)
        results.append(result)
        on_done(result)
        if fail_fast and result.status == FAIL:
            stopped = True

    if parallel and not stopped:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(run_gate, g, log_dir, root): g for g in parallel}
            for future in as_completed(futures):
                if future.cancelled():
                    continue
                result = future.result()
                results.append(result)
                on_done(result)
                if fail_fast and result.status == FAIL:
                    stopped = True
                    for pending in futures:
                        pending.cancel()

    done = {r.name for r in results}
    for gate in gates:
        if gate.name not in done:
            results.append(Result(gate, NOTRUN,
                                  reason="--fail-fast: another gate failed first"))

    order = {g.name: i for i, g in enumerate(gates)}
    results.sort(key=lambda r: order[r.name])
    return results


# ── reporting ────────────────────────────────────────────────────────────────

def _tail(path: Path | None, lines: int) -> list[str]:
    if path is None or not path.is_file() or lines <= 0:
        return []
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return text[-lines:]


def _display_argv(argv: Sequence[str]) -> str:
    shown = ["python" if part == sys.executable else part for part in argv]
    return " ".join(shown)


def print_listing(gates: Sequence[Gate], root: Path, out) -> None:
    print(f"gate table — {len(gates)} gates    (interpreter: {sys.executable})", file=out)
    print(f"repo root: {root}", file=out)
    print(f"logs:      {root / LOG_DIR_REL}/<name>.log\n", file=out)
    for gate in gates:
        marks = [gate.group]
        if not gate.parallel_safe:
            marks.append("serial")
        print(f"{gate.name}  [{' · '.join(marks)}]", file=out)
        print(f"    $ {_display_argv(gate.argv)}", file=out)
        for key, value in sorted(gate.env.items()):
            print(f"      env {key}={value}", file=out)
        print(f"    proves: {gate.what_it_proves}", file=out)
        precondition = _evaluate_precondition(gate, root)
        if gate.dirties and precondition is None:
            print(f"    DIRTIES THE WORKTREE: {gate.dirties}", file=out)
        if precondition is not None:
            print(
                f"    {precondition.status} HERE: {precondition.reason}",
                file=out,
            )
        print(file=out)
    if NOT_RUN_LOCALLY or NOT_RUN_LOCALLY_NON_PYTHON:
        print("not run locally (asserted by automation/gates/tests):", file=out)
        for key, why in sorted({**NOT_RUN_LOCALLY, **NOT_RUN_LOCALLY_NON_PYTHON}.items()):
            print(f"  - {key}: {why}", file=out)


@dataclass(frozen=True)
class Coverage:
    """What the whole gate table holds, against what this invocation selected.

    Handed to ``summarise`` so the final line can carry a DENOMINATOR. ``ALL GREEN
    (8 gates)`` is true of a run that skipped 28 of the 36 gates in the table and
    reads exactly like a full suite; ``ALL GREEN (8 of 36 gates ran)`` cannot.
    """

    total: int
    selector: str = ""
    dropped_lanes: tuple[str, ...] = ()
    dropped_reason: str = ""


def summarise(results: Sequence[Result], out, *, tail: int, root: Path,
              require_pass: bool = False, coverage: Coverage | None = None) -> int:
    """Print the table + the one final line, and return the process exit code.

    Three verdicts, three exit codes, and no two of them render alike:

      * ``RED`` / 1 — a gate failed, or --fail-fast cut the run short;
      * ``NO EVIDENCE`` / ``EXIT_NO_EVIDENCE`` (3) — NO gate executed a check.
        Nothing was selected, or every selected gate skipped. This used to print
        ``ALL GREEN (0 gates)`` and exit 0, which is the whole reason this runner's
        output was ever trusted for a run that measured nothing;
      * ``ALL GREEN`` / 0 — at least one gate ran and nothing failed. Always carries
        ``n of N gates ran``, so a narrowed run cannot be mistaken for a full one.

    ``require_pass`` (default False) keeps ``validate_cutover.py``'s louder contract:
    there an unrun check is a FAILURE of the profile, not merely missing evidence, so
    it reports ``NOT GREEN`` and exits 1. Both branches refuse to say ALL GREEN.

    ``coverage`` supplies the denominator and the dropped-lane names. Omitted, the
    denominator falls back to the size of this selection — honest, just less useful.
    """
    failed = [r for r in results if r.status == FAIL]
    skipped = [r for r in results if r.status == SKIP]
    notrun = [r for r in results if r.status == NOTRUN]
    passed = [r for r in results if r.status == PASS]

    width = max((len(r.name) for r in results), default=4)
    print("", file=out)
    if results:  # an empty table is noise between the reader and the verdict
        print(f"{'NAME'.ljust(width)}  EXIT  RESULT   TIME  LOG", file=out)
        print(f"{'-' * width}  ----  ------  -----  ---", file=out)
    for result in results:
        code = "-" if result.exit_code is None else str(result.exit_code)
        secs = "-" if result.status in (SKIP, NOTRUN) else f"{result.seconds:.1f}s"
        log = ("-" if result.log_path is None
               else result.log_path.relative_to(root).as_posix())
        print(f"{result.name.ljust(width)}  {code:>4}  {result.status:<6}  {secs:>5}  {log}",
              file=out)
        if result.reason:
            print(f"{' ' * width}        -> {result.reason}", file=out)

    for result in failed:
        lines = _tail(result.log_path, tail)
        if not lines:
            continue
        print(f"\n--- {result.name} (exit {result.exit_code}) last {len(lines)} log "
              f"lines: {result.log_path} ---", file=out)
        for line in lines:
            print(f"  {line}", file=out)

    print("", file=out)
    for result in results:
        if (
            result.gate.dirties
            and result.status in (PASS, FAIL)
            and result.log_path is not None
        ):
            print(f"note: {result.name} {result.gate.dirties}", file=out)
    if skipped:
        print("skipped (NOT passes): "
              + ", ".join(r.name for r in skipped), file=out)
    if notrun:
        print("not run (--fail-fast): " + ", ".join(r.name for r in notrun), file=out)

    # ── coverage, printed in EVERY mode including the all-pass one ───────────
    total = coverage.total if coverage is not None else len(results)
    total = max(total, len(results))  # a caller cannot under-report the denominator
    unselected = total - len(results)
    executed = len(passed) + len(failed)
    if coverage is not None and coverage.dropped_lanes:
        print(f"lanes NOT run ({len(coverage.dropped_lanes)}): "
              + ", ".join(coverage.dropped_lanes)
              + (f" — {coverage.dropped_reason}" if coverage.dropped_reason else ""),
              file=out)
    detail = f"{len(skipped)} skipped, {unselected} not selected"
    if notrun:
        # --fail-fast abandons gates that were selected but never started. They are
        # neither skipped nor unselected, so leaving them out would make the four
        # numbers stop adding up to the denominator.
        detail += f", {len(notrun)} abandoned by --fail-fast"
    if coverage is not None and coverage.selector:
        detail += f", selector: {coverage.selector}"
    print(f"coverage: {executed} of {total} gates in the table executed "
          f"({detail})", file=out)

    skipped_names = ", ".join(r.name for r in skipped)
    if failed or notrun:
        names = ", ".join(r.name for r in failed) or "none"
        print(f"RED: {names} ({len(failed)} of {len(results)} failed)", file=out)
        return 1
    if not passed:
        # Nothing executed a check, so nothing was proven. Never ALL GREEN, never 0.
        census = (f"{len(skipped)} skipped: {skipped_names}" if skipped
                  else "0 skipped")
        nothing = (f"0 of {total} gates executed — nothing was verified "
                   f"({census}; {unselected} not selected)")
        if require_pass:
            print(f"NOT GREEN: {nothing}", file=out)
            return 1
        print(f"NO EVIDENCE: {nothing}", file=out)
        return EXIT_NO_EVIDENCE
    if skipped:
        print(f"ALL GREEN ({len(passed)} of {total} gates ran; "
              f"{len(skipped)} skipped: {skipped_names})", file=out)
    else:
        print(f"ALL GREEN ({len(passed)} of {total} gates ran)", file=out)
    return 0


# ── cli ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_gates.py",
        description="Run this repo's blocking gates locally, with an exit-code table "
                    "you cannot misread.")
    parser.add_argument("--list", action="store_true",
                        help="print the gate table and exit 0 without running anything")
    parser.add_argument("--only", metavar="NAME[,NAME...]",
                        help="run only these gates")
    parser.add_argument("--skip", metavar="NAME[,NAME...]",
                        help="run everything except these gates")
    # ``action="append"`` so BOTH spellings accumulate: ``--lane a,b`` and
    # ``--lane a --lane b``. As a plain store the repeated form silently kept
    # only the LAST lane, so a run that asked for two lanes checked one and said
    # ALL GREEN — the exact "checked less than you asked, reported success"
    # failure this runner exists to prevent.
    parser.add_argument("--lane", metavar="NAME[,NAME...]", action="append",
                        help="run one or more CI lanes (repeatable, or comma-separated): "
                             + ", ".join(CI_LANES))
    parser.add_argument("--impact-from", metavar="REF",
                        help="run policy plus long lanes affected since merge-base "
                             "REF (uncertainty runs every lane)")
    parser.add_argument("--group", choices=GROUPS,
                        help="hook = what pre-commit runs · ci = what CI runs · "
                             "both = everything (default)")
    parser.add_argument("--fail-fast", action="store_true",
                        help="stop after the first failing gate")
    parser.add_argument("--tail", type=int, default=15, metavar="N",
                        help="log lines to print inline for a FAILING gate (default 15)")
    parser.add_argument("--jobs", type=int, default=1, metavar="N",
                        help="run this many gates concurrently (default 1 — serial; "
                             "gates that share the git index or the examples/ tree "
                             "always run serially, see run_many)")
    return parser


def main(argv: Iterable[str] | None = None, out=None) -> int:
    out = out or sys.stdout
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.impact_from is not None:
        conflicts = [
            flag for flag, value in (
                ("--group", args.group), ("--lane", args.lane), ("--only", args.only)
            ) if value is not None
        ]
        if conflicts:
            raise SystemExit(
                "run_gates: --impact-from cannot be combined with "
                + ", ".join(conflicts)
                + "; impact classification already defines the gate set."
            )
        impact = impact_decision(args.impact_from, REPO_ROOT)
        lane = ",".join(impact.lanes)
    else:
        impact = None
        lane = ",".join(args.lane) if args.lane else None
    all_gates = build_gates(REPO_ROOT)
    gates = select_gates(all_gates, group=args.group, lane=lane,
                         only=args.only, skip=args.skip)

    if impact is not None:
        selection = f"impact from: {args.impact_from}"
        dropped_lanes = impact.dropped_lanes
        dropped_reason = impact.reason or "no classifier reason"
    elif args.lane:
        selection = f"lane: {','.join(args.lane)}"
        asked = {name for value in args.lane for name in _split(value)}
        dropped_lanes = tuple(name for name in CI_LANES if name not in asked)
        dropped_reason = "not named on the command line"
    else:
        selection = f"group: {args.group or 'both'}"
        dropped_lanes, dropped_reason = (), ""
    # --only/--skip narrow *inside* whatever the branch above chose. Naming them
    # keeps the selector from reading `group: both` on a run that checked one gate.
    for flag, value in (("--only", args.only), ("--skip", args.skip)):
        if value:
            selection += f", {flag} {value}"
    coverage = Coverage(total=len(all_gates), selector=selection,
                        dropped_lanes=dropped_lanes, dropped_reason=dropped_reason)

    if impact is not None:
        print_impact_decision(impact, out)
    if not gates:
        # Zero gates is zero evidence. It shares neither the words nor the exit code
        # of a green run — summarise owns both, so there is one place to get it right.
        print("run_gates: selection matched no gates.", file=out)
        return summarise([], out, tail=args.tail, root=REPO_ROOT, coverage=coverage)
    if args.list:
        print_listing(gates, REPO_ROOT, out)
        return 0

    log_dir = REPO_ROOT / LOG_DIR_REL
    log_dir.mkdir(parents=True, exist_ok=True)
    print(f"running {len(gates)} of {len(all_gates)} gates ({selection}, "
          f"jobs: {args.jobs}) — full output in {LOG_DIR_REL}/", file=out)

    def announce(result: Result) -> None:
        secs = "" if result.status in (SKIP, NOTRUN) else f"  {result.seconds:6.1f}s"
        code = "" if result.exit_code is None else f"  exit {result.exit_code}"
        print(f"  {result.status:<6} {result.name}{code}{secs}", file=out)
        out.flush()

    results = run_many(gates, log_dir, jobs=max(1, args.jobs),
                       fail_fast=args.fail_fast, root=REPO_ROOT, on_done=announce)
    return summarise(results, out, tail=args.tail, root=REPO_ROOT,
                     coverage=coverage)


if __name__ == "__main__":
    sys.exit(main())
