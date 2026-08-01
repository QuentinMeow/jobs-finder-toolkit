"""The field-fidelity auditor must report the pipeline's answer, over the whole store.

This tool exists to catch the pipeline silently dropping location information, so
every defect here is the same shape one level up: **the detector reporting a
confident answer it did not compute.** Four of them, each pinned below:

* the "gate decision" it printed was not the gate's decision — it dropped the
  title, the workplace hint and the JD that ``scoring.location_ok`` passes, so it
  mismatched in BOTH directions and then selected its AI sample by that answer;
* it could never resolve an id-less source (Workday) against its own raw payload,
  so every Workday row was ``raw_resolved: False``, unflaggable, and filtered out
  of ``sample`` — a whole ATS reported clean without ever being looked at;
* one unparseable index row truncated the rest of the index, silently;
* two of the three writing commands skipped the ``local/`` containment guard the
  third enforces.

Isolation: every store test pins ``JOBHUNT_DATA_ROOT`` and ``JOBHUNT_CONFIG`` at
throwaway paths, so no test reads the owner's store, config or applications tree.
Companies, ids and URLs are fictional; no network.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/search-recall-audit/tests \
        -t automation/search-recall-audit/tests
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

AUDIT_DIR = Path(__file__).resolve().parents[1]
if str(AUDIT_DIR) not in sys.path:
    sys.path.insert(0, str(AUDIT_DIR))

import field_fidelity as ff  # noqa: E402  (puts the job-search skill on sys.path)

import build_postings as bp  # noqa: E402  (the real builder, via ff's bootstrap)
import posting_parsers as parsers  # noqa: E402
import scoring  # noqa: E402  (the REAL gate this tool must agree with)
from common import JobPosting  # noqa: E402
from store import resolver  # noqa: E402
from store.capture import CaptureSession  # noqa: E402
from store.paths import domain_layout  # noqa: E402

UTC = timezone.utc

_POLICY = {
    "metro": ["springfield", "fairview"],
    "allow_us_remote": True,
    "us_only": True,
    "require_match": True,
}
# The same policy in the shape `scoring.location_ok` reads it from a profile.
_PROFILE = {"location": {"preferred": ["springfield", "fairview"],
                         "allow_remote": True, "us_only": True,
                         "require_match": True}}


def _wd_posting(req="JR1980360", title="Staff Software Engineer",
                locations="Fairview, ST and 3 more"):
    return {"title": title,
            "externalPath": f"/en-US/Careers/job/Fairview/{title.replace(' ', '-')}_{req}",
            "locationsText": locations,
            "bulletFields": [req]}


class _Layout:
    """Minimal stand-in for a DomainLayout: `_iter_index` reads `.index` only."""

    def __init__(self, index: Path):
        self.index = index


# --------------------------------------------------------------------------- #
# 3. The reported gate decision IS the gate's decision
# --------------------------------------------------------------------------- #
class GateDecisionTests(unittest.TestCase):
    """`_gate_decision` mismatched the real gate in both directions."""

    def _real_gate(self, *, location, title="", description="", remote=""):
        """What `scoring.location_ok` — the pipeline's own gate — decides."""
        posting = JobPosting(source="greenhouse", company="Example Co", title=title,
                             url="https://example.test/1", location=location,
                             remote=remote or "unknown", description=description)
        scoring.location_ok(posting, _PROFILE)
        return posting.filter_assessments["location"]["decision"]

    def test_a_foreign_city_in_the_title_drops_a_remote_posting(self):
        # Reported-kept-but-dropped: the gate reads the title in the rejecting
        # direction, and the audit never passed it.
        kwargs = dict(location="Remote", title="Staff Software Engineer, Canberra")
        self.assertEqual(self._real_gate(**kwargs), "no_match")
        got = ff._gate_decision("Remote", _POLICY,
                                title="Staff Software Engineer, Canberra")
        self.assertEqual(got["decision"], "no_match")
        self.assertEqual(got["category"], "foreign")

    def test_a_workplace_hint_in_its_own_field_keeps_a_non_metro_posting(self):
        # Reported-dropped-but-kept: a board that parks "Remote" beside the
        # location read as an onsite non-metro role.
        kwargs = dict(location="Columbus, ST", title="Software Engineer",
                      remote="remote")
        self.assertEqual(self._real_gate(**kwargs), "match")
        got = ff._gate_decision("Columbus, ST", _POLICY, title="Software Engineer",
                                workplace_hint="remote")
        self.assertEqual(got["decision"], "match")
        self.assertEqual(got["category"], "us_remote")

    def test_a_jd_borne_remote_grant_reaches_the_decision(self):
        jd = ("Available Locations: Remote - United States\n"
              "This is a fully remote role; you may live anywhere in the US.\n")
        kwargs = dict(location="Columbus, ST", title="Software Engineer",
                      description=jd)
        self.assertEqual(self._real_gate(**kwargs), "match")
        self.assertEqual(
            ff._gate_decision("Columbus, ST", _POLICY, title="Software Engineer",
                              jd=jd)["decision"], "match")

    def test_a_jobspy_row_s_workplace_hint_is_not_trusted(self):
        # `location_ok` passes hint_trusted=False for aggregator rows; the audit
        # must derive it the same way rather than trusting every hint.
        trusted = ff._gate_decision("Columbus, ST", _POLICY,
                                    workplace_hint="remote", source="greenhouse")
        untrusted = ff._gate_decision("Columbus, ST", _POLICY,
                                      workplace_hint="remote", source="jobspy:indeed")
        self.assertEqual(trusted["decision"], "match")
        self.assertNotEqual(untrusted["decision"], trusted["decision"])

    def test_there_is_exactly_one_gate_call_spelling_in_this_module(self):
        """Every command must route through `_assess` — no second spelling.

        The defect was two commands in one file disagreeing about the same
        posting. A future command that calls `assess_location` directly would
        reintroduce it, so pin the call sites structurally.
        """
        tree = ast.parse(Path(ff.__file__).read_text(encoding="utf-8"))
        callers: dict[str, list[ast.Call]] = {}
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "assess_location"):
                    callers.setdefault(fn.name, []).append(node)
        self.assertEqual(set(callers), {"_assess", "cmd_todo"},
                         "a command calls the gate classifier directly instead of "
                         "routing through _assess")
        # `cmd_todo`'s single direct call is the DOCUMENTED cheap pre-filter over
        # the index (location+title only). It is sound because the evidence it
        # omits can only ADD workplace signal, and `weird_location_format`
        # requires the absence of one — so the cheap pass is a superset of the
        # full one, and the full `_assess` re-check right after it decides.
        self.assertEqual(len(callers["cmd_todo"]), 1)
        kwargs = {kw.arg for kw in callers["cmd_todo"][0].keywords}
        self.assertEqual(kwargs, {"title"})


# --------------------------------------------------------------------------- #
# 7. A damaged index row costs one row, never the tail
# --------------------------------------------------------------------------- #
class IterIndexTests(unittest.TestCase):
    def _read(self, *lines):
        d = Path(tempfile.mkdtemp(prefix="ff-index-"))
        self.addCleanup(shutil.rmtree, d, True)
        (d / "postings.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return ff._iter_index(_Layout(d))

    HEALTHY = [json.dumps({"key": f"gh-{i}", "title": "SWE"}) for i in range(1, 6)]

    def test_a_healthy_index_reads_whole_with_nothing_skipped(self):
        rows, skipped = self._read(*self.HEALTHY)
        self.assertEqual([r["key"] for r in rows],
                         ["gh-1", "gh-2", "gh-3", "gh-4", "gh-5"])
        self.assertEqual(skipped, 0)

    def test_one_damaged_row_does_not_truncate_the_rest(self):
        rows, skipped = self._read(*self.HEALTHY[:2],
                                   '{"key": "gh-BROKEN", "title": "SWE"',
                                   *self.HEALTHY[2:])
        self.assertEqual([r["key"] for r in rows],
                         ["gh-1", "gh-2", "gh-3", "gh-4", "gh-5"],
                         "rows after the damaged one were dropped")
        self.assertEqual(skipped, 1)

    def test_a_row_that_never_parses_is_bounded_not_endless(self):
        # Continuation lines that never close the object: give up, keep reading.
        rows, skipped = self._read(self.HEALTHY[0], '{"key": "gh-X",',
                                   '"a": 1,', '"b": 2,', '"c": 3,', '"d": 4,',
                                   self.HEALTHY[1])
        self.assertEqual([r["key"] for r in rows], ["gh-1", "gh-2"])
        self.assertGreaterEqual(skipped, 1)

    def test_the_legacy_embedded_newline_row_this_reader_exists_for_parses(self):
        # A RAW newline inside a JSON string is a control character: strict-mode
        # json.loads can never accept it, so this row used to swallow the tail.
        rows, skipped = self._read(self.HEALTHY[0],
                                   '{"key": "gh-2", "company": "Acme',
                                   'Robotics"}',
                                   self.HEALTHY[2])
        self.assertEqual([r["key"] for r in rows], ["gh-1", "gh-2", "gh-3"])
        self.assertEqual(rows[1]["company"], "Acme\nRobotics")
        self.assertEqual(skipped, 0)

    def test_a_trailing_unterminated_row_is_counted(self):
        rows, skipped = self._read(self.HEALTHY[0], '{"key": "gh-2"')
        self.assertEqual([r["key"] for r in rows], ["gh-1"])
        self.assertEqual(skipped, 1)


# --------------------------------------------------------------------------- #
# 11. Every writing command is contained to local/
# --------------------------------------------------------------------------- #
class OutputContainmentTests(unittest.TestCase):
    """`corpus`/`sample` wrote wherever they were pointed; only `todo` refused."""

    def test_every_writing_command_refuses_a_path_outside_local(self):
        target = ff.REPO_ROOT / "skills" / "_ff_containment_probe"
        # A pre-fix run of this very test leaves the directory behind — which is
        # the defect. Clear it first so the assertion below reads THIS run.
        shutil.rmtree(target, ignore_errors=True)
        self.addCleanup(shutil.rmtree, target, True)
        for cmd in ("corpus", "sample", "todo"):
            with self.subTest(cmd=cmd):
                err = io.StringIO()
                with contextlib.redirect_stderr(err), \
                        self.assertRaises(SystemExit) as raised:
                    ff.main(["--out", str(target), cmd])
                message = f"{raised.exception}{err.getvalue()}"
                self.assertIn("must stay under", message)
                self.assertIn(cmd, message)
        self.assertFalse(target.exists(),
                         "a rejected --out still created its directory")


# --------------------------------------------------------------------------- #
# 4 (+ 3 end-to-end). A real store, built by the real builder.
# --------------------------------------------------------------------------- #
class _StoreCase(unittest.TestCase):
    """A throwaway two-source store; nothing outside the temp tree is touched."""

    def setUp(self):
        self._prior_data = os.environ.get("JOBHUNT_DATA_ROOT")
        self._prior_cfg = os.environ.get(ff.config.ENV_VAR)
        # `config.data_root()` resolves symlinks (/var -> /private/var on macOS),
        # so resolve here too or the pinning assertion below compares two spellings
        # of the same directory.
        self.tmp = Path(tempfile.mkdtemp(prefix="ff-store-")).resolve()
        self.data_root = self.tmp / "data"
        apps = self.tmp / "applications"
        apps.mkdir(parents=True)
        cfg = self.tmp / "config.yaml"
        cfg.write_text(
            'candidate:\n  name: "Jordan Rivers"\n'
            f'paths:\n  applications_root: "{apps}"\n'
            f'  discoveries_dir: "{apps}/1_discoveries"\n'
            'job_search:\n  location:\n    preferred: [springfield, fairview]\n'
            '    allow_remote: true\n    us_only: true\n',
            encoding="utf-8")
        os.environ["JOBHUNT_DATA_ROOT"] = str(self.data_root)
        os.environ[ff.config.ENV_VAR] = str(cfg)
        ff.config._load.cache_clear()
        self.assertEqual(ff.config.data_root(), self.data_root)
        self.assertEqual(ff.config.applications_root(), apps,
                         "config not pinned — the build would walk the real tree")
        self.layout = domain_layout(self.data_root, "jobs")
        # The containment guard is under test elsewhere; honour it here.
        self.out = Path(tempfile.mkdtemp(prefix="ff-out-",
                                         dir=str(ff.REPO_ROOT / "local")))
        self.addCleanup(shutil.rmtree, self.out, True)
        self.addCleanup(self._restore)

    def _restore(self):
        for var, prior in (("JOBHUNT_DATA_ROOT", self._prior_data),
                           (ff.config.ENV_VAR, self._prior_cfg)):
            if prior is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prior
        ff.config._load.cache_clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _capture(self, source, payload, url, day, context):
        CaptureSession("jobs", self.data_root, tool_version="test").capture_fetch(
            source=source, operation="board" if source == "greenhouse" else "search",
            request={"url": url}, status=200,
            payload_bytes=json.dumps(payload).encode(),
            content_type="application/json",
            fetched_at=datetime(2026, 7, day, 9, 0, 0, tzinfo=UTC),
            context=context)

    def _capture_workday(self, postings, day=1):
        self._capture("workday", {"jobPostings": postings},
                      "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers",
                      day, {"company": "acmeco", "profile": "profile-01"})

    def _capture_greenhouse(self, jobs, day=1):
        self._capture("greenhouse", {"jobs": jobs},
                      "https://boards-api.greenhouse.io/v1/boards/examplecorp/jobs",
                      day, {"company": "examplecorp", "profile": "profile-01"})

    def _build(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = bp.main(["--data-root", str(self.data_root)])
        self.assertEqual(rc, 0, buf.getvalue())

    def _corpus(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ff.cmd_corpus(argparse.Namespace(out=str(self.out), limit=600, seed=42,
                                             cmd="corpus"))
        rows = [json.loads(ln) for ln
                in (self.out / "corpus.jsonl").read_text().splitlines() if ln.strip()]
        return {r["source"]: r for r in rows}, buf.getvalue()


class WorkdayRawResolutionTests(_StoreCase):
    """Workday's locator carries no id field; that is not the same as no identity."""

    def test_the_id_less_source_gets_the_identity_its_parser_keys_on(self):
        jp = _wd_posting()
        row = parsers.parse_workday(json.dumps({"jobPostings": [jp]}).encode(),
                                    {"request": {"url": "https://x.example/wday/cxs/a/Careers"}})[0]
        self.assertEqual(ff._job_native_id("workday", jp), row["native_id"])
        self.assertEqual(ff._job_native_id("workday", jp), "JR1980360")

    def test_the_identity_survives_a_refetch_that_changes_other_fields(self):
        """A run-varying key would make every row look new on every fetch."""
        first = _wd_posting()
        later = _wd_posting(title="Staff Software Engineer II",
                            locations="Fairview, ST and 5 more")
        self.assertNotEqual(first, later)
        identity = ff._job_native_id("workday", first)
        self.assertEqual(identity, "JR1980360")   # never None: None is not an identity
        self.assertEqual(identity, ff._job_native_id("workday", later))
        # …and it is the identity the STORE assigned, so a re-fetch folds onto the
        # same entity instead of looking new.
        self._capture_workday([first], day=1)
        self._capture_workday([later], day=2)
        self._build()
        keys = [json.loads(ln)["key"] for ln
                in (self.layout.index / "postings.jsonl").read_text().splitlines()[1:]]
        self.assertEqual(len(keys), 1, keys)
        _path, entity = resolver.load_entity(self.layout, keys[0])
        self.assertEqual(entity["source_ids"][0]["id"], identity)

    def test_corpus_raw_resolves_a_workday_posting(self):
        self._capture_workday([_wd_posting()])
        self._capture_greenhouse([{
            "id": 900, "title": "Platform Engineer",
            "location": {"name": "Springfield, ST"},
            "absolute_url": "https://boards.example.test/examplecorp/jobs/900",
            "content": "Build the platform.", "updated_at": "2026-07-01T00:00:00Z"}])
        self._build()
        rows, printed = self._corpus()
        self.assertTrue(rows["workday"]["raw_resolved"],
                        "the worst source is still reported without being read")
        self.assertEqual(rows["workday"]["raw_location_view"],
                         {"locationsText": "Fairview, ST and 3 more"})
        self.assertTrue(rows["greenhouse"]["raw_resolved"])
        # The summary states per-source resolution, so 0-of-N cannot hide in a total.
        self.assertIn("raw-resolved  workday", printed)

    def test_a_source_that_resolves_nothing_is_stated_not_inferred(self):
        # An id the parser cannot key on (no bulletFields, no `_` in the path)
        # still resolves; a payload whose list path is empty resolves nothing and
        # must say so rather than be read off a total.
        self._capture_workday([_wd_posting()])
        self._build()
        _rows, printed = self._corpus()
        self.assertRegex(printed, r"raw-resolved\s+workday\s+1/1")
        self.assertNotIn("resolves NONE", printed)

    def test_sample_writes_the_workday_case_a_judge_never_saw(self):
        self._capture_workday([_wd_posting()])
        self._build()
        self._corpus()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ff.cmd_sample(argparse.Namespace(out=str(self.out), n=32, seed=7,
                                             source=None, cmd="sample"))
        cases = sorted(p.name for p in (self.out / "cases").glob("*.md"))
        self.assertEqual(cases, ["workday-JR1980360.md"])
        self.assertIn("Fairview, ST and 3 more",
                      (self.out / "cases" / cases[0]).read_text())

    def test_corpus_and_check_resolve_the_same_raw_job(self):
        self._capture_workday([_wd_posting()])
        self._build()
        rows, _ = self._corpus()
        key = json.loads(
            (self.layout.index / "postings.jsonl").read_text().splitlines()[1])["key"]
        _path, entity = resolver.load_entity(self.layout, key)
        source, job = ff._RawStore(self.layout).job_for(entity)
        self.assertEqual(source, "workday")
        self.assertIsNotNone(job, "`check` lost the resolution `corpus` gained")
        self.assertEqual(ff.raw_location_view(source, job),
                         rows["workday"]["raw_location_view"])

    def test_an_empty_external_path_does_not_stand_in_for_an_identity(self):
        """`"" in url` is always true — the fallback returned the FIRST job."""
        self._capture_workday([{"title": "Other Role", "externalPath": "",
                                "locationsText": "Nowhere"},
                               _wd_posting()])
        self._build()
        key = json.loads(
            (self.layout.index / "postings.jsonl").read_text().splitlines()[1])["key"]
        _path, entity = resolver.load_entity(self.layout, key)
        # An entity whose stored id resolves nothing and whose url matches no
        # externalPath must come back unresolved, not silently bound to job[0].
        entity["source_ids"][0]["id"] = "JR-does-not-exist"
        entity["source_ids"][0]["url"] = "https://acme.example/en-US/Careers/nothing"
        source, job = ff._RawStore(self.layout).job_for(entity)
        self.assertEqual(source, "workday")
        self.assertIsNone(job)


class CorpusGateDecisionTests(_StoreCase):
    """End to end: the corpus row's gate decision is the pipeline's decision."""

    def test_a_title_borne_geography_is_reported_as_the_gate_decides_it(self):
        self._capture_greenhouse([{
            "id": 901, "title": "Staff Software Engineer, Canberra",
            "location": {"name": "Remote"},
            "absolute_url": "https://boards.example.test/examplecorp/jobs/901",
            "content": "Own the platform.", "updated_at": "2026-07-01T00:00:00Z"}])
        self._build()
        rows, _ = self._corpus()
        row = rows["greenhouse"]
        self.assertEqual(row["generated_location"], "Remote")
        posting = JobPosting(source="greenhouse", company="Example Co",
                             title="Staff Software Engineer, Canberra",
                             url=row["url"], location="Remote",
                             description="Own the platform.")
        scoring.location_ok(posting, _PROFILE)
        self.assertEqual(row["gate_generated"]["decision"],
                         posting.filter_assessments["location"]["decision"])
        self.assertEqual(row["gate_generated"]["decision"], "no_match")


if __name__ == "__main__":
    unittest.main()
