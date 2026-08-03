"""No shipped module deletes anything beneath ``config.applications_root()``.

WHY THIS EXISTS
---------------
``memory/decisions/handoff-records-every-folder-it-creates.md`` makes the
applications skip-log record **every** folder handoff creates, whatever exit code
the run returned. The owner's answer was explicitly conditional:

    "if the code and agent behaviour never delete an application folder, and if a
    deleted folder therefore means *I* deleted it, then Option A is right"

So "a missing application folder means the OWNER removed it" is not a nicety — it
is the premise that makes a permanent skip the right reading of a missing folder.
If any module ever removes a path under the applications root, that premise is
gone and the failure is **silent**: a posting the owner still wanted, skipped
forever, with nothing on disk to say why.

The premise was verified by hand on 2026-08-02. A hand sweep is exactly as durable
as the next refactor, which is what this module replaces.

WHAT IT CHECKS
--------------
Deliberately NOT a tree-wide ``rmtree`` ban — the toolkit legitimately removes
caches, store debris, vendored copies, generated symlinks, export destinations and
temporary files, and a blanket ban would be either red on day one or so
exception-riddled it stopped meaning anything. The protected tree is the
applications root and nothing else.

For every non-test module under ``automation/`` and ``skills/``:

1. **Taint pass** — names that hold a path under the applications root are traced
   from ``config.applications_root()`` through assignments (``root / slug``,
   ``root.glob(...)``), ``for`` targets over a tainted iterable, and module-level
   functions that RETURN a tainted expression (``_status_dir``,
   ``find_application``, handoff's ``_applications_root``), to a fixpoint. Taint
   is **per scope**: a name bound inside one function does not taint the same
   name in another.
2. **Removal pass** — ``shutil.rmtree`` / ``os.remove`` / ``os.unlink`` /
   ``os.rmdir`` / ``os.removedirs`` on a tainted argument, or ``.unlink()`` /
   ``.rmdir()`` / ``.rmtree()`` on a tainted receiver, is a violation.
3. **Name backstop** — inside a module that reaches the applications root at all,
   a removal whose target reads as an application folder (``app_dir``,
   ``application_folder``, …) is a violation even when the taint pass cannot see
   where it came from, which is the common case for a path arriving as a function
   parameter.

KNOWN LIMITS, stated so nobody reads this guard as more than it is:

* **Cross-module flow is not traced.** A path handed from one module to another
  through a parameter is caught only by the name backstop.
* **``shutil.move`` is not a removal.** ``status.py`` moves an application between
  status folders on every ``--update``; both endpoints are inside the root, and
  the recorded decision's list of forbidden operations is removals. A move that
  carried a folder OUT of the root would slip past — that is the one gap worth
  knowing about.
* **The overlay is not scanned.** ``private/`` is a separate repo that may not be
  mounted, and a gate whose verdict depends on the checkout is not a gate.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from _canonical_imports import pin_shared_modules

pin_shared_modules()   # required of every test module in this directory

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNED_ROOTS = ("automation", "skills")

DECISION_DOC = "memory/decisions/handoff-records-every-folder-it-creates.md"

# The accessor every path under the protected tree ultimately comes from.
ROOT_ACCESSOR = "applications_root"

# Module-qualified removals: the PATH is the first positional argument.
REMOVAL_CALLS = {
    ("shutil", "rmtree"),
    ("os", "remove"),
    ("os", "unlink"),
    ("os", "rmdir"),
    ("os", "removedirs"),
}
# Method removals: the PATH is the receiver (``p.unlink()``).
REMOVAL_METHODS = {"unlink", "rmdir", "rmtree", "removedirs"}
# Receivers that are a module, not a path — ``shutil.rmtree`` is handled above.
NOT_A_PATH = {"shutil", "os", "sys", "pathlib", "Path", "tempfile", "subprocess"}

# Attribute/method hops that keep you inside the tree you started in. ``.parent``
# is included on purpose: a status folder is still under the applications root,
# and removing one is worse than removing a single application.
PATH_HOPS = {
    "glob", "rglob", "iterdir", "resolve", "expanduser", "absolute",
    "parent", "joinpath", "with_name", "with_suffix",
}
# Calls that pass a path straight through.
PASSTHROUGH = {"Path", "str", "sorted", "list", "next", "reversed", "tuple"}

_APP_WORDS = {"app", "apps", "application", "applications"}
_PLACE_WORDS = {"dir", "folder", "path"}


def _reads_as_application_folder(identifier: str) -> bool:
    """Heuristic backstop: does this name obviously hold an application folder?

    Requires BOTH an application word and a place word, so ``apps_root`` (a root,
    scanned read-only in several modules) and a bare ``path`` (store and cache
    debris) do not trip it, while ``app_dir`` / ``application_folder`` do.
    """
    tokens = {t for t in re.split(r"[^a-z]+", identifier.lower()) if t}
    if identifier.lower() in ("app", "application"):
        return True
    return bool(tokens & _APP_WORDS) and bool(tokens & _PLACE_WORDS)


def _root_name(node: ast.AST) -> str | None:
    """The identifier a path expression is rooted at, or None.

    ``root / slug`` -> ``root``; ``root.glob(x)`` -> ``root``; ``Path(root)`` ->
    ``root``; ``config.applications_root()`` -> the sentinel ``ROOT_ACCESSOR``.
    """
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            if node.attr == ROOT_ACCESSOR:
                return ROOT_ACCESSOR
            if node.attr in PATH_HOPS:
                node = node.value
                continue
            return None
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id == ROOT_ACCESSOR:
                    return ROOT_ACCESSOR
                if func.id in PASSTHROUGH:
                    node = node.args[0] if node.args else None
                    if node is None:
                        return None
                    continue
                return func.id            # a local helper; resolved by the fixpoint
            if isinstance(func, ast.Attribute):
                if func.attr == ROOT_ACCESSOR:
                    return ROOT_ACCESSOR
                if func.attr in PATH_HOPS or func.attr in PASSTHROUGH:
                    node = func.value
                    continue
                return None
            return None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            node = node.left
            continue
        if isinstance(node, ast.Subscript):
            node = node.value
            continue
        return None


def _own_nodes(scope: ast.AST):
    """Every node belonging to THIS scope — nested defs are their own scopes."""
    stack = list(getattr(scope, "body", []))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _child_defs(scope: ast.AST) -> list[ast.AST]:
    """The function definitions directly inside this scope (through classes)."""
    out: list[ast.AST] = []
    stack = list(getattr(scope, "body", []))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(node)
            continue
        stack.extend(ast.iter_child_nodes(node))
    return out


class _Analyzer:
    """One module's taint state.

    Taint is **scope-aware**: a name assigned inside a function is tainted only
    in that function (and the closures nested in it). Module-wide name matching
    was tried first and was wrong in the way that matters — ``search_jobs.py``
    binds ``path`` to an applications-root path in one function and to a cache
    file in another, and a flat name set reports the cache ``unlink`` as a
    violation. A guard that cries wolf gets an exception list, and an exception
    list is where guards go to die.
    """

    def __init__(self, tree: ast.AST) -> None:
        self.tree = tree
        self.tainted_funcs: set[str] = set()
        self.scopes: list[tuple[ast.AST, set[str]]] = []

    def _is_tainted(self, node: ast.AST, tainted: set[str]) -> bool:
        name = _root_name(node)
        if name is None:
            return False
        return (name == ROOT_ACCESSOR
                or name in tainted
                or name in self.tainted_funcs)

    def run(self) -> None:
        for _ in range(8):              # module-level helpers converge in 2-3
            before = set(self.tainted_funcs)
            self.scopes = []
            self._scan_scope(self.tree, set())
            if self.tainted_funcs == before:
                return

    def _scan_scope(self, scope: ast.AST, inherited: set[str]) -> None:
        tainted = set(inherited)
        nodes = list(_own_nodes(scope))
        for _ in range(4):              # assignments are not in dependency order
            before = len(tainted)
            for node in nodes:
                self._seed(node, tainted)
            if len(tainted) == before:
                break
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in nodes:
                if (isinstance(node, ast.Return) and node.value is not None
                        and self._is_tainted(node.value, tainted)):
                    self.tainted_funcs.add(scope.name)
                    break
        self.scopes.append((scope, tainted))
        for child in _child_defs(scope):
            self._scan_scope(child, tainted)

    def _seed(self, node: ast.AST, tainted: set[str]) -> None:
        """Add every name this statement binds to an applications-root path."""
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target])
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            value, targets = node.iter, [node.target]
        else:
            return
        if value is None or not self._is_tainted(value, tainted):
            return
        for target in targets:
            for sub in ast.walk(target):
                if isinstance(sub, ast.Name):
                    tainted.add(sub.id)

    def reaches_applications_root(self) -> bool:
        return bool(self.tainted_funcs or any(names for _s, names in self.scopes))

    def violations(self) -> list[tuple[int, str]]:
        """``(lineno, description)`` for every removal aimed at the tree."""
        found: list[tuple[int, str]] = []
        touches_root = self.reaches_applications_root()
        for scope, tainted in self.scopes:
            for node in _own_nodes(scope):
                if isinstance(node, ast.Call):
                    found.extend(self._call_violations(node, tainted,
                                                       touches_root))
        return sorted(set(found))

    def _call_violations(self, node: ast.Call, tainted: set[str],
                         touches_root: bool) -> list[tuple[int, str]]:
        func = node.func
        if not isinstance(func, ast.Attribute):
            return []
        qualifier = func.value.id if isinstance(func.value, ast.Name) else None
        if qualifier is not None and (qualifier, func.attr) in REMOVAL_CALLS:
            target = node.args[0] if node.args else None
            if target is None:
                return []
            label = f"{qualifier}.{func.attr}({ast.unparse(target)})"
            if self._is_tainted(target, tainted):
                return [(node.lineno, f"{label} — argument is a path under the "
                                      "applications root")]
            if touches_root and _reads_as_application_folder(
                    _root_name(target) or ""):
                return [(node.lineno,
                         f"{label} — argument names an application folder")]
            return []
        if func.attr in REMOVAL_METHODS and qualifier not in NOT_A_PATH:
            label = f"{ast.unparse(func.value)}.{func.attr}()"
            if self._is_tainted(func.value, tainted):
                return [(node.lineno, f"{label} — receiver is a path under the "
                                      "applications root")]
            if touches_root and _reads_as_application_folder(
                    _root_name(func.value) or ""):
                return [(node.lineno,
                         f"{label} — receiver names an application folder")]
        return []


def _analyze(source: str) -> _Analyzer:
    analyzer = _Analyzer(ast.parse(source))
    analyzer.run()
    return analyzer


def _subject_files() -> list[Path]:
    """Every shipped (non-test) Python module under the scanned roots."""
    out: list[Path] = []
    for root in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            parts = path.relative_to(REPO_ROOT).parts
            if "tests" in parts or path.name.startswith("test_"):
                continue
            out.append(path)
    return out


class ApplicationFolderNeverDeletedTests(unittest.TestCase):
    def test_no_shipped_module_removes_a_path_under_the_applications_root(self):
        offenders: list[str] = []
        for path in _subject_files():
            rel = path.relative_to(REPO_ROOT).as_posix()
            try:
                analyzer = _analyze(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:                       # pragma: no cover
                self.fail(f"{rel} does not parse: {exc}")
            for lineno, detail in analyzer.violations():
                offenders.append(f"  {rel}:{lineno}  {detail}")

        self.assertEqual(
            offenders, [],
            "A module now removes a path under config.applications_root():\n"
            + "\n".join(offenders)
            + "\n\nThis invalidates the premise of "
            + DECISION_DOC
            + ":\n  the applications skip-log is append-only and authoritative, "
              "and every folder\n  handoff creates is recorded permanently — "
              "which is only the right reading of a\n  missing folder while a "
              "missing folder can ONLY mean the OWNER removed it.\n"
              "  Code that deletes under the applications root turns a posting "
              "the owner still\n  wanted into a silent, permanent skip.\n"
              "  Do not delete this assertion to go green: revisit the decision "
              "(it says how),\n  or keep the removal out of the applications "
              "tree. AGENTS.md says the same thing\n  for agents — application "
              "folders are removed by the USER only.")

    # -- the guard's own teeth --------------------------------------------- #
    # A guard nobody has watched fail is a comment. These plant the exact
    # regressions it exists to catch, so it cannot rot into always-green.

    def test_guard_catches_a_removal_of_a_folder_derived_from_the_root(self):
        source = (
            "import config, shutil\n"
            "def cleanup(slug):\n"
            "    root = config.applications_root()\n"
            "    folder = root / '6_drafted' / slug\n"
            "    shutil.rmtree(folder)\n"
        )
        self.assertTrue(_analyze(source).violations())

    def test_guard_catches_a_removal_through_a_helper_that_returns_the_path(self):
        source = (
            "import config\n"
            "def _status_dir(status):\n"
            "    return config.applications_root() / status\n"
            "def cleanup(status, slug):\n"
            "    (_status_dir(status) / slug).unlink()\n"
        )
        self.assertTrue(_analyze(source).violations())

    def test_guard_catches_a_removal_while_walking_the_tree(self):
        source = (
            "import config, os\n"
            "def cleanup():\n"
            "    for meta in config.applications_root().rglob('meta.yaml'):\n"
            "        os.remove(meta)\n"
        )
        self.assertTrue(_analyze(source).violations())

    def test_guard_catches_a_folder_arriving_as_a_parameter(self):
        """The name backstop — no assignment to trace, which is the usual shape."""
        source = (
            "import config, shutil\n"
            "def scan():\n"
            "    return config.applications_root().iterdir()\n"
            "def cleanup(app_dir):\n"
            "    shutil.rmtree(app_dir)\n"
        )
        self.assertTrue(_analyze(source).violations())

    def test_guard_leaves_removals_outside_the_applications_tree_alone(self):
        """Cache, store and export debris stay deletable — the scope is narrow."""
        source = (
            "import config, shutil\n"
            "def rebuild(cache_dir):\n"
            "    apps_root = config.applications_root()\n"
            "    for meta in apps_root.rglob('meta.yaml'):\n"
            "        read(meta)\n"
            "    shutil.rmtree(cache_dir / 'derived')\n"
            "    (cache_dir / 'stale.json').unlink()\n"
        )
        self.assertEqual(_analyze(source).violations(), [])

    def test_guard_leaves_a_status_transition_move_alone(self):
        """``--update`` moves a folder between status dirs; a move is not a removal."""
        source = (
            "import config, shutil\n"
            "def move(slug, src, status):\n"
            "    dest = config.applications_root() / status / slug\n"
            "    shutil.move(str(src), str(dest))\n"
        )
        self.assertEqual(_analyze(source).violations(), [])

    def test_the_scan_actually_covers_the_modules_that_reach_the_tree(self):
        """A scan that silently stopped matching anything would be green forever."""
        reaching = [path.relative_to(REPO_ROOT).as_posix()
                    for path in _subject_files()
                    if _analyze(path.read_text(encoding="utf-8")
                                ).reaches_applications_root()]
        self.assertIn("skills/application-tracker/scripts/status.py", reaching)
        self.assertIn("skills/job-search/scripts/handoff.py", reaching)
        self.assertGreaterEqual(len(reaching), 8, reaching)


if __name__ == "__main__":
    unittest.main()
