"""The company key is ADDITIVE: it never decides whether a posting is skipped.

The key answers "which employer is this?" for filing and navigation. It is
hand-assigned in a review pass, which makes it the least-verified data in the
tree — and the least-verified data does not belong on the most consequential
path. On a filing path a wrong key costs a mislabelled report. On a match path it
would silently re-draft an application to an employer that already said no (an
alias *split*), or silently suppress a genuinely new posting (an alias *merge*).

Two tests, and they fail for different reasons on purpose:

``test_match_paths_do_not_mention_company_key``
    SOURCE level. It walks the same-module CALL CLOSURE of a named list of
    functions and asserts the literal never occurs anywhere in it. A behavioural
    test alone is not enough: an agent wiring the key into a skip path would
    naturally update the behavioural fixture in the same edit, but to get past
    this one they must DELETE A NAMED GUARD or ADD A NAMED CARVE-OUT, and both
    are diffs a reviewer sees.

``test_skip_sets_are_identical_with_and_without_company_key`` (+ the
``build_coverage`` method beside it)
    BEHAVIOURAL. It proves the readers that actually parse ``meta.yaml`` compute
    the same skip set — and the same set of same-company folders — before and
    after the key is added to every file, which is what the migration that puts
    the key on every application depends on.

Why the source half walks a graph
---------------------------------
It used to read ``inspect.getsource(fn)``, which returns **one function body**.
Every guarded function delegates to helpers that were not themselves guarded, so
moving one expression into a helper defeated the guard completely. An adversarial
review reproduced that on ``audit.build_coverage``: extract its company
normalisation into a module-level helper reading ``company_key or company`` and
the old guard, the shared suite and the job-search suite all stayed green while
a new posting at a merged employer went from one same-company folder to none.
That mutation is now a regression test
(``test_the_reproduced_helper_extraction_mutation_is_caught``), together with the
proof that the old body-only check missed it
(``test_the_old_body_only_guard_missed_that_mutation``).

WHAT THE WALK COVERS
--------------------
* The guarded function itself, and every function **in the same module** it can
  reach through resolvable calls, to a fixed point.
* Resolvable means: a call to a module-level ``def``; a call to a module-level
  class (which pulls in that class's ``__init__``); ``self.method()`` inside a
  method (resolved against that method's own class); and
  ``ClassName.method()``.
* Functions nested inside a guarded function are covered *textually*, because
  their text is inside the parent's source segment, and their calls are followed
  as if the parent made them. A path through one is reported as the parent.
* ``MAX_CLOSURE_DEPTH`` bounds the walk. The deepest closure in the tree today is
  4 hops (``skip_log.read_postings``), and reaching the limit **raises** rather
  than truncating, so the bound can never quietly hide a tail.

WHAT THE WALK DELIBERATELY DOES **NOT** COVER
---------------------------------------------
* **Cross-module calls.** ``skip_log.read_postings(...)``,
  ``registry.match_keys(...)``, ``scoring.title_ok(...)``,
  ``config.applications_root()`` and friends are recorded as unresolved and not
  followed. Building an import map and loading arbitrary modules is a lot of
  machinery for this, and the cross-module callees that matter are already
  guarded **as roots in their own right** — ``skip_log.read_postings``,
  ``skip_log.fold``, ``skip_log.fold_key``, ``Registry.match_keys``,
  ``Registry.canonical``, ``Registry._entry_keys`` all appear in
  ``MATCH_PATHS``. So the stopping point is: same-module closure, plus an
  explicit list of the cross-module hops that decide anything. A NEW helper in
  another module is not covered until it is added to ``MATCH_PATHS``, and that is
  the maintenance cost this design accepts.
* **Method calls on values whose class cannot be inferred** — ``posting.get()``,
  ``entry.keys()``, anything reached through a parameter or a local. Only
  ``self.x()`` and ``ClassName.x()`` resolve.
* **Dynamic dispatch**: ``getattr``, callables stored in dicts or lists,
  ``functools.partial``, and the source of decorators (``get_source_segment``
  starts at the ``def`` line).
* **Data flow.** This is a text test. A function can read the field without
  spelling it out (``meta[FIELD]``, ``meta.get(k)`` for a ``k`` computed
  elsewhere). Nothing static catches that; the behavioural half is the answer,
  which is why both halves exist.
* **Vendored copies.** Modules are parsed and loaded at the canonical path named
  in ``MATCH_PATHS``. ``automation/vendoring/sync_vendored.py --check`` is the
  only gate that fails when a ``scripts/_vendor/`` copy diverges.

Modules are loaded BY PATH under a unique alias. A plain import can resolve to a
vendored copy (other modules in this suite put a ``_vendor`` directory on
``sys.path``), and a guard that reads a copy would not guard the original.
"""
from __future__ import annotations

import ast
import functools
import importlib.util
import inspect
import shutil
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace

from _canonical_imports import pin_shared_modules

pin_shared_modules()   # subject imports must resolve under automation/shared/

REPO_ROOT = Path(__file__).resolve().parents[3]

FIELD = "company_key"

# The walk terminates on its own — a module has finitely many functions and each
# is visited once. This bound is a TRIPWIRE, not a truncation: exceeding it
# raises. Deepest closure in the tree today is 4 hops.
MAX_CLOSURE_DEPTH = 8

# Every function that decides a SKIP, DEDUP, FILTER or COVERAGE outcome. Each is
# `(alias, module path relative to the repo root, dotted name inside the module)`.
#
# Adding a function here is cheap and always correct. Removing one is the edit this
# test exists to make visible: every row below is also pinned by name in
# `REQUIRED_GUARDS`, so a deletion has to be made TWICE, in one diff, to go green.
MATCH_PATHS: tuple[tuple[str, str, str], ...] = (
    # the applications skip-log readers — "have we already considered this posting?"
    ("search_jobs", "skills/job-search/scripts/search_jobs.py", "load_considered"),
    ("search_jobs", "skills/job-search/scripts/search_jobs.py", "already_considered"),
    ("handoff", "skills/job-search/scripts/handoff.py", "_posting_keys"),
    ("skip_log", "automation/shared/skip_log.py", "fold_key"),
    # the company search log — "did we search this employer recently?"
    ("search_jobs", "skills/job-search/scripts/search_jobs.py", "load_company_search_log"),
    ("search_jobs", "skills/job-search/scripts/search_jobs.py", "is_recently_searched"),
    # coverage — "is this posting already represented by an application?"
    ("store_refilter", "automation/search-recall-audit/store_refilter.py", "build_covered"),
    ("audit", "automation/search-recall-audit/audit.py", "build_coverage"),
    # filters and registry identity, which every one of the above resolves through
    ("query_postings", "skills/job-search/scripts/query_postings.py", "_apply_filters"),
    ("company_roles", "skills/job-search/scripts/company_roles.py", "_entry_from_registry"),
    ("registry", "skills/job-search/scripts/registry.py", "Registry.match_keys"),
    ("registry", "skills/job-search/scripts/registry.py", "Registry.canonical"),
    ("registry", "skills/job-search/scripts/registry.py", "Registry._entry_keys"),
    # the mail reconciler binds email threads to applications on its OWN match key.
    # It used to call that key `company_key`, which is exactly the collision this
    # guard exists for; it is now `company_match_key` and is guarded like the rest.
    ("reconciliation", "automation/shared/mail/reconciliation.py", "_company_match_key"),
    ("reconciliation", "automation/shared/mail/reconciliation.py", "_normalize_applications"),
    ("reconciliation", "automation/shared/mail/reconciliation.py", "_thread_candidates"),
    ("reconciliation", "automation/shared/mail/reconciliation.py", "link_message"),
    # ---- the DECIDERS -------------------------------------------------------
    # Everything above collects or normalizes. These take the actual verdict, and
    # an adversarial review found them missing: a guard over gatherers alone lets
    # the key reach the decision one call later. `find_application_matches` is the
    # sharp one — the same change that added this guard also put `company_key`
    # into the record dict this function iterates, one token away from the
    # `searchable` string it scores on.
    ("handoff", "skills/job-search/scripts/handoff.py", "_duplicate_reason"),
    ("handoff", "skills/job-search/scripts/handoff.py", "_register_row"),
    ("handoff", "skills/job-search/scripts/handoff.py", "group_by_company"),
    ("audit", "automation/search-recall-audit/audit.py", "coverage_for"),
    ("store_refilter", "automation/search-recall-audit/store_refilter.py", "is_blacklisted"),
    ("store_refilter", "automation/search-recall-audit/store_refilter.py", "gate_decisions"),
    ("skip_log", "automation/shared/skip_log.py", "read_postings"),
    ("skip_log", "automation/shared/skip_log.py", "fold"),
    ("application_context", "skills/email-assistant/scripts/application_context.py",
     "find_application_matches"),
)

# The membership pin. `len(MATCH_PATHS) >= 26` was the old assertion, and it stays
# green when a load-bearing row is deleted and an unrelated one added in the same
# edit — the exact shape of an adversarial diff. Every guarded row is named here
# instead. This is a SUBSET check, so adding a guard needs no edit here; only
# removing one does, and it then has to be removed from two places at once.
REQUIRED_GUARDS: frozenset[str] = frozenset({
    "skills/job-search/scripts/search_jobs.py::load_considered",
    "skills/job-search/scripts/search_jobs.py::already_considered",
    "skills/job-search/scripts/search_jobs.py::load_company_search_log",
    "skills/job-search/scripts/search_jobs.py::is_recently_searched",
    "skills/job-search/scripts/handoff.py::_posting_keys",
    "skills/job-search/scripts/handoff.py::_duplicate_reason",
    "skills/job-search/scripts/handoff.py::_register_row",
    "skills/job-search/scripts/handoff.py::group_by_company",
    "skills/job-search/scripts/query_postings.py::_apply_filters",
    "skills/job-search/scripts/company_roles.py::_entry_from_registry",
    "skills/job-search/scripts/registry.py::Registry.match_keys",
    "skills/job-search/scripts/registry.py::Registry.canonical",
    "skills/job-search/scripts/registry.py::Registry._entry_keys",
    "automation/shared/skip_log.py::fold_key",
    "automation/shared/skip_log.py::read_postings",
    "automation/shared/skip_log.py::fold",
    "automation/shared/mail/reconciliation.py::_company_match_key",
    "automation/shared/mail/reconciliation.py::_normalize_applications",
    "automation/shared/mail/reconciliation.py::_thread_candidates",
    "automation/shared/mail/reconciliation.py::link_message",
    "automation/search-recall-audit/store_refilter.py::build_covered",
    "automation/search-recall-audit/store_refilter.py::is_blacklisted",
    "automation/search-recall-audit/store_refilter.py::gate_decisions",
    "automation/search-recall-audit/audit.py::build_coverage",
    "automation/search-recall-audit/audit.py::coverage_for",
    "skills/email-assistant/scripts/application_context.py::find_application_matches",
})

# ── the carve-out ────────────────────────────────────────────────────────────
# A closure walk reaches the EMIT side as readily as the compare side, and the
# line this whole guard holds is emit-yes / compare-no. Each entry is
# `(module path, dotted name, reason, the exact lines that may mention FIELD)`.
#
# The pinned lines are what stop a carve-out swallowing a real violation: the
# permitted function must still exist, must still mention the field, and the set
# of its mentioning lines (whitespace-normalized) must be EXACTLY this tuple. Add
# a second use of the key inside a carved-out function and the guard goes red on
# the pin even though the function is on the list. Entries are also required to
# be disjoint from `MATCH_PATHS`: a guarded root can never carve itself out.
PERMITTED_MENTIONS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "skills/email-assistant/scripts/application_context.py",
        "_records",
        "The one place the field is legitimately SURFACED to a reader. Guarding a "
        "function that must EMIT the key would forbid the thing phase 7 added. "
        "`_records` is on the emit side, which is precisely why its consumer "
        "`find_application_matches` — where a comparison would live — is guarded "
        "and it is not.",
        ('"company_key": str(meta.get("company_key") or "").strip(),',),
    ),
)

# ── the reproduced mutation, kept as a regression test ───────────────────────
# From the adversarial review of workspace phase 7 (2026-07-30). It is applied to
# the REAL module text rather than to a synthetic look-alike, so if
# `build_coverage` is refactored past these anchors the test fails loudly instead
# of quietly checking a fixture that no longer resembles the code.
MUTATION_TARGET = "automation/search-recall-audit/audit.py"
MUTATION_ANCHOR_CALL = '            base_co = _norm_company(m.get("company"))\n'
MUTATION_NEW_CALL = "            base_co = _company_identity(m)\n"
MUTATION_ANCHOR_DEF = "def build_coverage() -> dict:\n"
MUTATION_HELPER = (
    "def _company_identity(m: dict) -> str:\n"
    '    return _norm_company(m.get("company_key") or m.get("company"))\n'
    "\n"
    "\n"
)

# The readers that parse meta.yaml and return a skip/coverage set, as
# `(alias, module path, function name, argument order)`. The two disagree on
# argument order — `_posting_keys(root, log)` versus `build_covered(log, root)` —
# so the order is declared here rather than assumed. `audit.build_coverage` takes
# no arguments at all and gets its own method below instead of an adapter.
SKIP_SET_READERS: tuple[tuple[str, str, str, str], ...] = (
    ("handoff", "skills/job-search/scripts/handoff.py", "_posting_keys", "root-first"),
    ("store_refilter", "automation/search-recall-audit/store_refilter.py",
     "build_covered", "log-first"),
)

_META = """job_metadata_schema_version: 6
company: {company}
research_date: 2026-07-30
jobs:
  - role: {role}
    jd_file: JD-{slug}.md
    status: drafted
    url: {url}
"""

# Invented employers, never real ones. The point of the fixture is the SHAPE.
#
# The fourth row is an alias MERGE — a second display string for the first row's
# employer, carrying the SAME key. Without it every key here is a slug of its own
# company string, which normalizes back to that string, so a reader that wrongly
# matched on the key would compute the identical answer and the behavioural half
# would prove nothing. Six of the real tree's 214 company strings collapse this
# way, so the merge is the realistic case, not a contrived one.
FIXTURE_APPS = (
    ("acme-labs-senior-engineer-20260730", "Acme Labs", "Senior Engineer",
     "https://example.test/jobs/1", "acme-labs"),
    ("acme-cloud-platform-engineer-20260730", "Acme Cloud", "Platform Engineer",
     "https://example.test/jobs/2", "acme-cloud"),
    ("beacon-works-ml-engineer-20260730", "Beacon Works", "ML Engineer",
     "https://example.test/jobs/3", "beacon-works"),
    ("acme-labs-international-data-engineer-20260730", "Acme Labs International",
     "Data Engineer", "https://example.test/jobs/4", "acme-labs"),
)
MERGED_ALIAS_DISPLAY = FIXTURE_APPS[3][1]
MERGED_ALIAS_SLUG = FIXTURE_APPS[3][0]


def _load(alias: str, rel: str):
    """Import a module by PATH under a private alias, never by name."""
    unique = f"_guard_{alias}"
    path = REPO_ROOT / rel
    if not path.is_file():                       # a moved module must be loud
        raise AssertionError(f"guarded module is missing: {rel}")
    spec = importlib.util.spec_from_file_location(unique, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module                 # dataclasses read sys.modules
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(unique, None)
        raise
    return module


def _resolve(module, dotted: str):
    obj = module
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


# ── the same-module call-graph walker ────────────────────────────────────────
@functools.lru_cache(maxsize=None)
def _module_index(path: Path) -> tuple[str, dict[str, ast.AST], frozenset[str]]:
    """``(source, {dotted name: def node}, {module-level class names})``.

    Parsed rather than imported: the walk needs the syntax tree, and parsing a
    file cannot run its module-level code. Keyed on an absolute path so a
    mutated copy in a temp directory is indexed separately from the real module.
    """
    if not path.is_file():                       # a moved module must be loud
        raise AssertionError(f"guarded module is missing: {path}")
    source = path.read_text(encoding="utf-8")
    functions: dict[str, ast.AST] = {}
    classes: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = node
        elif isinstance(node, ast.ClassDef):
            classes.add(node.name)
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions[f"{node.name}.{member.name}"] = member
    return source, functions, frozenset(classes)


def _same_module_callees(path: Path, dotted: str) -> list[str]:
    """Dotted names this function calls that resolve INSIDE its own module.

    Unresolvable targets (imported modules, methods on values, dynamic dispatch)
    are dropped here; the module docstring records that gap.
    """
    _, functions, classes = _module_index(path)
    owner = dotted.rpartition(".")[0]
    found: list[str] = []
    for node in ast.walk(functions[dotted]):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name):
            if target.id in functions:
                found.append(target.id)
            elif target.id in classes and f"{target.id}.__init__" in functions:
                found.append(f"{target.id}.__init__")
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            base = target.value.id
            if base == "self" and owner and f"{owner}.{target.attr}" in functions:
                found.append(f"{owner}.{target.attr}")
            elif base in classes and f"{base}.{target.attr}" in functions:
                found.append(f"{base}.{target.attr}")
    return found


def _closure_paths(path: Path, root: str) -> dict[str, tuple[str, ...]]:
    """Every same-module function reachable from ``root``, with its shortest path.

    Breadth-first, so the recorded path is the shortest one and reads as the
    call chain a human would follow. Terminates on the ``seen`` set;
    ``MAX_CLOSURE_DEPTH`` only fires if a module ever gets deep enough to make
    the bound meaningful, and it raises rather than returning a partial answer.
    """
    _, functions, _ = _module_index(path)
    if root not in functions:                    # a renamed guard must be loud
        raise AssertionError(f"{path.name} has no function {root!r}")
    paths: dict[str, tuple[str, ...]] = {root: (root,)}
    queue: deque[str] = deque([root])
    while queue:
        current = queue.popleft()
        here = paths[current]
        if len(here) > MAX_CLOSURE_DEPTH:
            raise AssertionError(
                f"call closure from {path.name}::{root} passed "
                f"MAX_CLOSURE_DEPTH={MAX_CLOSURE_DEPTH} at {' -> '.join(here)}. "
                "Raise the bound deliberately — do not let the walk truncate.")
        for callee in _same_module_callees(path, current):
            if callee not in paths:
                paths[callee] = here + (callee,)
                queue.append(callee)
    return paths


def _mentioning_lines(path: Path, dotted: str) -> tuple[str, ...]:
    """Whitespace-normalized lines of one function that spell ``FIELD`` out."""
    source, functions, _ = _module_index(path)
    segment = ast.get_source_segment(source, functions[dotted]) or ""
    return tuple(" ".join(line.split())
                 for line in segment.splitlines() if FIELD in line)


def _field_mentions(path: Path, root: str,
                    permitted: frozenset[str] = frozenset()) -> list[str]:
    """Call paths from ``root`` to a function whose source spells ``FIELD`` out.

    One string per offending function, e.g. ``build_coverage -> _company_identity``
    — a bare "somewhere in the closure" is not actionable.
    """
    source, functions, _ = _module_index(path)
    findings: list[str] = []
    for name, call_path in sorted(_closure_paths(path, root).items()):
        if name in permitted:
            continue
        if FIELD in (ast.get_source_segment(source, functions[name]) or ""):
            findings.append(" -> ".join(call_path))
    return sorted(findings)


class MatchPathSourceGuard(unittest.TestCase):
    """Invariant 1: the key never appears in a match path's call closure."""

    def test_match_paths_do_not_mention_company_key(self) -> None:
        for _alias, rel, dotted in MATCH_PATHS:
            with self.subTest(function=f"{rel}::{dotted}"):
                permitted = frozenset(
                    name for module, name, _reason, _lines in PERMITTED_MENTIONS
                    if module == rel)
                findings = _field_mentions(REPO_ROOT / rel, dotted, permitted)
                self.assertEqual(
                    findings, [],
                    f"{rel}::{dotted} reaches {FIELD!r} through "
                    f"{'; '.join(findings)}. That function decides a skip, dedup, "
                    "filter or coverage outcome, and the company key is a "
                    "hand-assigned FILING key: a wrong one there silently "
                    "re-drafts an application to an employer that already said no, "
                    "or silently suppresses a genuinely new posting. Keep reading "
                    "the free-text company string through this path's own "
                    "normalizer. See memory/decisions/"
                    "company-key-is-additive-never-a-match-key.md")

    def test_the_guard_list_is_not_vacuous(self) -> None:
        """Every named function resolves, and no named guard has been dropped.

        Two failure modes, two assertions. A RENAME makes ``_resolve`` raise,
        which the subTest below reports. A DELETION shrinks the guard silently,
        which is why ``REQUIRED_GUARDS`` names every row: a count assertion stays
        green when one load-bearing row is swapped for an unrelated one.
        """
        present = {f"{rel}::{dotted}" for _alias, rel, dotted in MATCH_PATHS}
        missing = sorted(REQUIRED_GUARDS - present)
        self.assertEqual(
            missing, [],
            f"MATCH_PATHS no longer guards {missing}. Removing a guard is the "
            "edit this file exists to make visible: record the decision in "
            "memory/decisions/ and remove the row from REQUIRED_GUARDS in the "
            "same commit, so the deletion is legible in one diff.")
        for alias, rel, dotted in MATCH_PATHS:
            with self.subTest(function=f"{rel}::{dotted}"):
                self.assertTrue(callable(_resolve(_load(alias, rel), dotted)))

    def test_the_guard_would_catch_a_planted_mention(self) -> None:
        """The assertion is a real substring test, not a tautology."""
        def planted() -> str:
            return "company_key"                      # noqa: guard fixture

        self.assertIn(FIELD, inspect.getsource(planted))

    def test_the_walk_actually_leaves_the_function_body(self) -> None:
        """If the resolver broke, every guarded root would pass on an empty walk.

        The closure of ``build_coverage`` is the one this file's regression test
        depends on, so it is the one pinned: both of its helpers are reached, at
        the depth a direct call has.
        """
        reached = _closure_paths(REPO_ROOT / MUTATION_TARGET, "build_coverage")
        self.assertEqual(reached.get("canon"), ("build_coverage", "canon"))
        self.assertEqual(reached.get("_norm_company"),
                         ("build_coverage", "_norm_company"))

    def test_no_closure_reaches_the_depth_limit(self) -> None:
        """The recorded bound stays honest: today's deepest closure is 4 hops."""
        deepest = 0
        for _alias, rel, dotted in MATCH_PATHS:
            for call_path in _closure_paths(REPO_ROOT / rel, dotted).values():
                deepest = max(deepest, len(call_path) - 1)
        self.assertLess(
            deepest, MAX_CLOSURE_DEPTH,
            f"deepest closure is now {deepest} hops against a bound of "
            f"{MAX_CLOSURE_DEPTH}; raise the bound and update the docstring.")


class TheCarveOutIsNarrow(unittest.TestCase):
    """A carve-out must not be able to swallow a violation it was not written for."""

    def test_no_carve_out_exempts_a_guarded_function(self) -> None:
        guarded = {f"{rel}::{dotted}" for _alias, rel, dotted in MATCH_PATHS}
        overlap = sorted(f"{module}::{name}"
                         for module, name, _reason, _lines in PERMITTED_MENTIONS
                         if f"{module}::{name}" in guarded)
        self.assertEqual(
            overlap, [],
            f"{overlap} is both guarded and carved out, so its guard does "
            "nothing. A function that decides an outcome cannot be permitted to "
            "read the key under any reason.")

    def test_every_carve_out_is_live_and_pinned(self) -> None:
        """Each entry exists, still mentions the field, and mentions it EXACTLY so.

        A stale entry (the function stopped reading the key) goes red, so the
        list cannot accumulate dead permissions. A new use inside a permitted
        function goes red too, because the mentioning lines are pinned rather
        than merely counted — which is what keeps the carve-out from covering
        code it was never reviewed for.
        """
        for module, name, reason, lines in PERMITTED_MENTIONS:
            with self.subTest(function=f"{module}::{name}"):
                self.assertTrue(reason.strip(),
                                "a carve-out without a written reason is not one")
                self.assertEqual(
                    _mentioning_lines(REPO_ROOT / module, name), lines,
                    f"{module}::{name} no longer mentions {FIELD!r} the way this "
                    "carve-out was written for. If the use changed, re-read the "
                    "function and re-pin it; if it stopped reading the key, "
                    "delete the entry.")


class TheReproducedMutation(unittest.TestCase):
    """The helper extraction that defeated the body-only guard, as a test."""

    def _mutated_copy(self) -> Path:
        text = (REPO_ROOT / MUTATION_TARGET).read_text(encoding="utf-8")
        for anchor in (MUTATION_ANCHOR_CALL, MUTATION_ANCHOR_DEF):
            self.assertIn(
                anchor, text,
                f"{MUTATION_TARGET} no longer contains {anchor!r}, so this "
                "regression test would check a mutation that cannot be applied. "
                "Re-derive the mutation against the current source.")
        text = text.replace(MUTATION_ANCHOR_CALL, MUTATION_NEW_CALL)
        text = text.replace(MUTATION_ANCHOR_DEF, MUTATION_HELPER + MUTATION_ANCHOR_DEF)
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = directory / "audit_mutated.py"
        path.write_text(text, encoding="utf-8")
        return path

    def test_the_reproduced_helper_extraction_mutation_is_caught(self) -> None:
        self.assertEqual(
            _field_mentions(self._mutated_copy(), "build_coverage"),
            ["build_coverage -> _company_identity"],
            "the mutation the guard was rewritten for is not reported, or is "
            "reported without the call path that makes it actionable")

    def test_the_old_body_only_guard_missed_that_mutation(self) -> None:
        """Why the walk exists: ``inspect.getsource`` returns the body alone.

        This is the other half of the regression — without it, nothing records
        that the mutation really was invisible to the check this replaced.
        """
        source, functions, _ = _module_index(self._mutated_copy())
        body = ast.get_source_segment(source, functions["build_coverage"]) or ""
        self.assertNotIn(
            FIELD, body,
            "the mutation is now visible in the body itself, so it no longer "
            "demonstrates the hole the transitive walk was written to close")


class SkipSetsAreUnchangedByTheKey(unittest.TestCase):
    """Invariant 2: adding the key to every application changes no skip set."""

    def _tree(self, root: Path, *, keyed: bool) -> tuple[Path, Path]:
        apps = root / "applications"
        drafted = apps / "6_drafted"
        drafted.mkdir(parents=True)
        for slug, company, role, url, key in FIXTURE_APPS:
            app = drafted / slug
            source = app / "source"
            source.mkdir(parents=True)
            (source / f"JD-{slug}.md").write_text(role, encoding="utf-8")
            text = _META.format(company=company, role=role, slug=slug, url=url)
            if keyed:
                # Exactly the migration's edit: one top-level scalar inserted
                # immediately after the top-level ``company:`` line.
                text = text.replace(f"company: {company}\n",
                                    f"company: {company}\ncompany_key: {key}\n")
            (app / "meta.yaml").write_text(text, encoding="utf-8")
        log = apps / "0_profile" / "applications-log.jsonl"
        log.parent.mkdir(parents=True)
        log.write_text("", encoding="utf-8")
        return log, apps

    def _call(self, alias: str, rel: str, name: str, order: str,
              log: Path, apps: Path) -> tuple[set, set]:
        reader = getattr(_load(alias, rel), name)
        return reader(apps, log) if order == "root-first" else reader(log, apps)

    def test_skip_sets_are_identical_with_and_without_company_key(self) -> None:
        results: dict[bool, dict[str, tuple]] = {}
        for keyed in (False, True):
            temporary = Path(tempfile.mkdtemp())
            try:
                log, apps = self._tree(temporary, keyed=keyed)
                per_reader: dict[str, tuple] = {}
                for alias, rel, name, order in SKIP_SET_READERS:
                    urls, pairs = self._call(alias, rel, name, order, log, apps)
                    per_reader[f"{rel}::{name}"] = (
                        tuple(sorted(urls)), tuple(sorted(pairs)))
                results[keyed] = per_reader
            finally:
                shutil.rmtree(temporary, ignore_errors=True)

        for label in results[False]:
            with self.subTest(reader=label):
                self.assertEqual(
                    results[False][label], results[True][label],
                    f"{label} computed a different skip set once every meta.yaml "
                    "carried a company_key. The key is additive; it must not "
                    "change what is skipped.")

    def test_coverage_folders_are_identical_with_and_without_company_key(self) -> None:
        """The third reader, which the ``(log, root)`` table above cannot hold.

        ``audit.build_coverage()`` takes no arguments — it reads
        ``config.applications_root()`` and ``config.applications_jsonl_path()``
        — so it gets its own method rather than an adapter that contorts the
        table. It is worth the extra method because it asks the question the
        reproduced mutation changed: for a NEW posting at the merged employer,
        which existing folders count as the same company? Under the mutation
        that answer went from one folder to none, which is a genuinely new
        posting being suppressed.
        """
        answers: dict[bool, tuple[str, ...]] = {}
        for keyed in (False, True):
            temporary = Path(tempfile.mkdtemp())
            try:
                log, apps = self._tree(temporary, keyed=keyed)
                audit = _load("audit", "automation/search-recall-audit/audit.py")
                # Patch the module object this test loaded, never global state:
                # `_load` re-executes the file under a private alias each call.
                audit.config = SimpleNamespace(
                    applications_root=lambda apps=apps: str(apps),
                    applications_jsonl_path=lambda log=log: str(log))
                coverage = audit.build_coverage()
                seen = audit.coverage_for(
                    {"company": MERGED_ALIAS_DISPLAY,
                     "url": "https://example.test/jobs/new"}, coverage)
                answers[keyed] = tuple(
                    sorted(f["slug"] for f in seen["folders_same_company"]))
            finally:
                shutil.rmtree(temporary, ignore_errors=True)

        # Non-vacuity first: two empty answers would compare equal no matter what
        # `build_coverage` did. Phase 7's mutation testing found exactly that.
        self.assertEqual(
            answers[False], (MERGED_ALIAS_SLUG,),
            "the unkeyed fixture must find the merged employer's folder, or the "
            "comparison below proves nothing")
        self.assertEqual(
            answers[True], answers[False],
            "build_coverage returned a different set of same-company folders "
            "once every meta.yaml carried a company_key. On an alias merge that "
            "suppresses a genuinely new posting.")

    def test_the_fixture_actually_produces_a_skip_set(self) -> None:
        """A comparison of two empty sets would pass no matter what.

        Mutation testing found exactly this: an equality assertion over two empty
        results stayed green with the key wired straight into the match path.
        """
        temporary = Path(tempfile.mkdtemp())
        try:
            log, apps = self._tree(temporary, keyed=True)
            for alias, rel, name, order in SKIP_SET_READERS:
                with self.subTest(reader=f"{rel}::{name}"):
                    urls, pairs = self._call(alias, rel, name, order, log, apps)
                    self.assertEqual(len(urls), len(FIXTURE_APPS))
                    self.assertEqual(len(pairs), len(FIXTURE_APPS))
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def test_the_fixture_carries_an_alias_merge(self) -> None:
        """Two display strings, one key — or the keyed run cannot differ at all.

        Every other row's key is a slug of its own company string, which
        normalizes back to that string; a reader matching on the key alone would
        compute the identical answer and every comparison here would be vacuous.
        """
        keys_by_company = {company: key for _slug, company, _r, _u, key in FIXTURE_APPS}
        self.assertEqual(len(set(keys_by_company.values())),
                         len(keys_by_company) - 1,
                         "exactly one pair of fixture rows must share a key")
        self.assertEqual(keys_by_company[MERGED_ALIAS_DISPLAY],
                         keys_by_company[FIXTURE_APPS[0][1]])
        self.assertNotEqual(MERGED_ALIAS_DISPLAY, FIXTURE_APPS[0][1])

    def test_the_keyed_fixture_really_carries_the_key(self) -> None:
        """The 'after' tree must differ from the 'before' tree, or nothing is proved."""
        temporary = Path(tempfile.mkdtemp())
        try:
            _, apps = self._tree(temporary, keyed=True)
            metas = sorted(apps.rglob("meta.yaml"))
            self.assertEqual(len(metas), len(FIXTURE_APPS))
            for meta in metas:
                self.assertIn(f"{FIELD}:", meta.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
