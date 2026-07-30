"""The company key is ADDITIVE: it never decides whether a posting is skipped.

The key answers "which employer is this?" for filing and navigation. It is
hand-assigned in a review pass, which makes it the least-verified data in the
tree — and the least-verified data does not belong on the most consequential
path. On a filing path a wrong key costs a mislabelled report. On a match path it
would silently re-draft an application to an employer that already said no (an
alias *split*), or silently suppress a genuinely new posting (an alias *merge*).

Two tests, and they fail for different reasons on purpose:

``test_match_paths_do_not_mention_company_key``
    SOURCE level. It reads the source of a named list of functions and asserts the
    literal never occurs. A behavioural test alone is not enough: an agent wiring
    the key into a skip path would naturally update the behavioural fixture in the
    same edit, but to get past this one they must DELETE A NAMED GUARD, which is a
    diff a reviewer sees.

``test_skip_sets_are_identical_with_and_without_company_key``
    BEHAVIOURAL. It proves the readers that actually parse ``meta.yaml`` compute
    the same skip set before and after the key is added to every file — which is
    what the migration that puts the key on every application depends on.

Modules are loaded BY PATH under a unique alias. A plain import can resolve to a
vendored copy (other modules in this suite put a ``_vendor`` directory on
``sys.path``), and a guard that reads a copy would not guard the original.
"""
from __future__ import annotations

import importlib.util
import inspect
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

FIELD = "company_key"

# Every function that decides a SKIP, DEDUP, FILTER or COVERAGE outcome. Each is
# `(alias, module path relative to the repo root, dotted name inside the module)`.
#
# Adding a function here is cheap and always correct. Removing one is the edit this
# test exists to make visible, so removing one without a recorded decision is a bug.
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
)

# The readers that parse meta.yaml and return a skip/coverage set, as
# `(alias, module path, function name, argument order)`. The two disagree on
# argument order — `_posting_keys(root, log)` versus `build_covered(log, root)` —
# so the order is declared here rather than assumed.
SKIP_SET_READERS: tuple[tuple[str, str, str, str], ...] = (
    ("handoff", "skills/job-search/scripts/handoff.py", "_posting_keys", "root-first"),
    ("store_refilter", "automation/search-recall-audit/store_refilter.py",
     "build_covered", "log-first"),
)

_META = """job_metadata_schema_version: 5
company: {company}
research_date: 2026-07-30
jobs:
  - role: {role}
    jd_file: JD-{slug}.md
    status: drafted
    url: {url}
"""

# Invented employers, never real ones. The point of the fixture is the SHAPE.
FIXTURE_APPS = (
    ("acme-labs-senior-engineer-20260730", "Acme Labs", "Senior Engineer",
     "https://example.test/jobs/1", "acme-labs"),
    ("acme-cloud-platform-engineer-20260730", "Acme Cloud", "Platform Engineer",
     "https://example.test/jobs/2", "acme-cloud"),
    ("beacon-works-ml-engineer-20260730", "Beacon Works", "ML Engineer",
     "https://example.test/jobs/3", "beacon-works"),
)


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


class MatchPathSourceGuard(unittest.TestCase):
    """Invariant 1: the key never appears in a match path's source."""

    def test_match_paths_do_not_mention_company_key(self) -> None:
        for alias, rel, dotted in MATCH_PATHS:
            with self.subTest(function=f"{rel}::{dotted}"):
                function = _resolve(_load(alias, rel), dotted)
                source = inspect.getsource(function)
                self.assertNotIn(
                    FIELD, source,
                    f"{rel}::{dotted} mentions {FIELD!r}. That function decides a "
                    "skip, dedup, filter or coverage outcome, and the company key "
                    "is a hand-assigned FILING key: a wrong one there silently "
                    "re-drafts an application to an employer that already said no, "
                    "or silently suppresses a genuinely new posting. Keep reading "
                    "the free-text company string through this path's own "
                    "normalizer. See memory/decisions/"
                    "company-key-is-additive-never-a-match-key.md")

    def test_the_guard_list_is_not_vacuous(self) -> None:
        """Every named function resolves, so the guard cannot be emptied by a rename.

        Without this, renaming a guarded function would make ``_resolve`` raise —
        which the subTest above would report — but DELETING a row would silently
        shrink the guard to nothing. Here the count is pinned too.
        """
        self.assertGreaterEqual(len(MATCH_PATHS), 17)
        for alias, rel, dotted in MATCH_PATHS:
            with self.subTest(function=f"{rel}::{dotted}"):
                self.assertTrue(callable(_resolve(_load(alias, rel), dotted)))

    def test_the_guard_would_catch_a_planted_mention(self) -> None:
        """The assertion is a real substring test, not a tautology."""
        def planted() -> str:
            return "company_key"                      # noqa: guard fixture

        self.assertIn(FIELD, inspect.getsource(planted))


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
