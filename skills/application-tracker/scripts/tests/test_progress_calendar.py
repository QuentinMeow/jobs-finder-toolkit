"""End-to-end tests for schema-v6 progress + the single calendar file.

Covers: `status.py --update-progress` (transactional meta + calendar, never a
folder move), `--check-calendar`, preview-first `--sync-calendar`, the v5->v6
fleet migration CLI, and the fail-closed behaviors (malformed markers,
duplicate ids, missing entries, checksum races, one-sided writes).

Each case runs the CLIs as subprocesses with JOBHUNT_CONFIG pointed at a
throwaway config + applications tree (no private overlay, fictional data
only), mirroring test_status_transitions.py.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[1]
STATUS = SCRIPTS / "status.py"
MIGRATE = SCRIPTS / "migrate_to_v6.py"
for _p in (SCRIPTS, SCRIPTS / "_vendor"):
    if str(_p) not in sys.path and _p.is_dir():
        sys.path.insert(0, str(_p))

from calendar_todos import (  # noqa: E402
    COMPANY_VIEW_END,
    COMPANY_VIEW_START,
    SECTION_SCHEDULED,
    SECTION_WAITING,
    default_entry_text,
    parse_calendar,
    render_entry,
)

STATUS_DIRS = {
    "drafted": "6_drafted",
    "applied": "5_applied",
    "in_progress": "4_in_progress",
    "rejected": "3_rejected",
    "ignored": "2_ignored",
}

CALENDAR_SKELETON = (
    "# Interview calendar\n\n"
    "## Action needed\n\n"
    f"{SECTION_WAITING}\n\n"
    f"{SECTION_SCHEDULED}\n\n"
    "## My notes and personal todos\n\n"
    "- [ ] my own note — tooling must never touch this line\n"
)


def _job(role: str, status: str, jd_file: str, progress: dict) -> dict:
    return {
        "role": role,
        "jd_file": jd_file,
        "status": status,
        "progress": progress,
        "workplace": "remote",
        "sponsorship": "unknown",
        "job_level": {"normalized": "senior", "min": 5.0, "max": 5.8,
                      "confidence": "low", "source": "title"},
        "required_yoe": {"min": 5, "max": None, "confidence": "high",
                         "source": "job_description"},
        "salary_range": None,
    }


class ProgressCalendarTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.apps = self.root / "apps"
        self.calendar = self.apps / "0_profile" / "calendar.md"
        (self.root / "config.yaml").write_text(textwrap.dedent(f"""\
            paths:
              applications_root: "{self.apps.as_posix()}"
            """), encoding="utf-8")

    # -- harness ----------------------------------------------------------- #
    def _place(self, status_label: str, slug: str, jobs: list[dict],
               *, version: int = 6, company: str = "Example Corp",
               next_action: str | None = None) -> Path:
        app = self.apps / STATUS_DIRS[status_label] / slug
        (app / "source").mkdir(parents=True)
        for job in jobs:
            jd = job.get("jd_file")
            if jd:
                (app / "source" / jd).write_text("Fictional JD.", encoding="utf-8")
        meta = {
            "job_metadata_schema_version": version,
            "company": company,
            "research_date": "2026-07-20",
            "jobs": jobs,
        }
        if next_action is not None:
            meta["next_action"] = next_action
        (app / "meta.yaml").write_text(
            yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
        return app

    def _write_calendar(self, text: str) -> None:
        self.calendar.parent.mkdir(parents=True, exist_ok=True)
        self.calendar.write_text(text, encoding="utf-8")

    def _run(self, script: Path, *args):
        env = dict(os.environ, JOBHUNT_CONFIG=str(self.root / "config.yaml"))
        return subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True, env=env)

    def _find(self, slug: str):
        for label, folder in STATUS_DIRS.items():
            app = self.apps / folder / slug
            if app.is_dir():
                return label, app
        return None

    def _meta(self, app: Path) -> dict:
        return yaml.safe_load((app / "meta.yaml").read_text())

    def _entry_fields(self, entry_id: str, slug: str, *, state: str,
                      phase: str = "technical_interview", **overrides) -> dict:
        fields = {
            "id": entry_id,
            "application": slug,
            "role": "Backend Engineer",
            "phase": phase,
            "state": state,
            "label": None,
            "starts_at": None,
            "timezone": None,
            "follow_up_at": None,
            "source": "manual",
            "reschedule_to": None,
            "reschedule_timezone": None,
            "cancel": False,
            "history": [],
        }
        fields.update(overrides)
        return fields

    def _calendar_with_entry(self, fields: dict, *, section: str,
                             checked: bool = False,
                             text: str = "Example Corp — Backend Engineer") -> str:
        block = "".join(render_entry(fields, checked=checked, text=text))
        return CALENDAR_SKELETON.replace(
            f"{section}\n", f"{section}\n\n{block}", 1)

    def _check_calendar_entry(self, entry_id: str) -> None:
        lines = self.calendar.read_text(encoding="utf-8").splitlines(keepends=True)
        doc = parse_calendar("".join(lines))
        entry = doc.entries[entry_id]
        lines[entry.start_line] = lines[entry.start_line].replace("- [ ]", "- [x]", 1)
        self.calendar.write_text("".join(lines), encoding="utf-8")

    # -- --update-progress -------------------------------------------------- #
    def test_update_progress_creates_calendar_entry_and_never_moves(self):
        slug = "example-corp-solo-20260720"
        self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "recruiter_screen", "state": "unknown"})])
        proc = self._run(STATUS, "--update-progress", slug, "backend",
                         "--phase", "technical_interview",
                         "--state", "booking_required",
                         "--label", "Virtual technical screen")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        label, app = self._find(slug)
        self.assertEqual(label, "in_progress")  # progress-only: no folder move
        progress = self._meta(app)["jobs"][0]["progress"]
        self.assertEqual(progress["phase"], "technical_interview")
        self.assertEqual(progress["state"], "booking_required")
        self.assertEqual(progress["label"], "Virtual technical screen")
        self.assertEqual(progress["source"], {"kind": "manual", "ref": ""})
        self.assertEqual(len(progress["calendar_items"]), 1)
        self.assertTrue(progress["calendar_items"][0].startswith("cal-example-corp"))
        self.assertTrue(self.calendar.is_file())
        calendar_text = self.calendar.read_text()
        self.assertIn(progress["calendar_items"][0], calendar_text)
        self.assertIn('"state":"booking_required"', calendar_text)
        self.assertIn("**Choose an interview time**", calendar_text)
        self.assertIn("[Example Corp · Backend Engineer]", calendar_text)
        check = self._run(STATUS, "--check-calendar")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_update_progress_refreshes_stale_application_and_role_identity(self):
        slug = "example-corp-renamed-20260720"
        entry_id = "cal-example-corp-original-01"
        self._place("in_progress", slug, [_job(
            "AI Data Engineer", "in_progress", "JD-ai-data.md",
            {"phase": "recruiter_screen", "state": "paused",
             "calendar_items": [entry_id]})])
        fields = self._entry_fields(
            entry_id, "example-corp-original-20260720",
            state="paused", phase="recruiter_screen", role="Legacy Role")
        self._write_calendar(self._calendar_with_entry(
            fields, section=SECTION_WAITING,
            text=default_entry_text(
                "Example Corp", "Legacy Role", "paused", fields=fields)))

        proc = self._run(
            STATUS, "--update-progress", slug, "AI Data",
            "--phase", "onboarding", "--state", "waiting_employer",
            "--label", "Offer accepted; awaiting onboarding")
        self.assertEqual(proc.returncode, 0, proc.stderr)

        entry = parse_calendar(self.calendar.read_text()).entries[entry_id]
        self.assertEqual(entry.application, slug)
        self.assertEqual(entry.role, "AI Data Engineer")
        self.assertIn("AI Data Engineer", entry.text)
        self.assertNotIn("Legacy Role", entry.text)
        check = self._run(STATUS, "--check-calendar")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_update_progress_records_neutral_email_evidence_in_meta_and_calendar(self):
        slug = "example-corp-solo-20260720"
        self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "recruiter_screen", "state": "unknown"})])
        email_ref = "acct-01/" + "a" * 64
        proc = self._run(
            STATUS, "--update-progress", slug, "backend",
            "--phase", "recruiter_screen", "--state", "booking_required",
            "--email-ref", email_ref,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        _label, app = self._find(slug)
        progress = self._meta(app)["jobs"][0]["progress"]
        self.assertEqual(progress["source"], {"kind": "email", "ref": email_ref})
        self.assertNotIn(email_ref, self.calendar.read_text())

    def test_update_progress_rejects_non_neutral_email_reference(self):
        slug = "example-corp-solo-20260720"
        app = self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "recruiter_screen", "state": "unknown"})])
        before = (app / "meta.yaml").read_bytes()
        proc = self._run(
            STATUS, "--update-progress", slug, "backend",
            "--phase", "recruiter_screen", "--state", "booking_required",
            "--email-ref", "provider-message-id@example.com",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("neutral acct-NN", proc.stderr)
        self.assertEqual((app / "meta.yaml").read_bytes(), before)

    def test_update_progress_scheduled_without_time_fails_closed(self):
        slug = "example-corp-solo-20260720"
        app = self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "technical_interview", "state": "awaiting_schedule"})])
        before = (app / "meta.yaml").read_bytes()
        proc = self._run(STATUS, "--update-progress", slug, "backend",
                         "--phase", "technical_interview",
                         "--state", "scheduled")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--starts-at", proc.stderr)
        self.assertEqual((app / "meta.yaml").read_bytes(), before)  # no write

    def test_update_progress_records_a_complete_visible_event(self):
        slug = "example-corp-solo-20260720"
        self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "technical_interview", "state": "awaiting_schedule"})])
        proc = self._run(
            STATUS, "--update-progress", slug, "backend",
            "--phase", "technical_interview", "--state", "scheduled",
            "--starts-at", "2026-08-03T10:00:00-07:00",
            "--ends-at", "2026-08-03T11:00:00-07:00",
            "--timezone", "America/Los_Angeles",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = self.calendar.read_text()
        self.assertIn("**Mon, Aug 3 · 10:00 AM PDT–11:00 AM PDT**", text)
        self.assertIn('"ends_at":"2026-08-03T11:00:00-07:00"', text)

    def test_update_progress_refuses_to_overwrite_a_distinct_confirmed_occurrence(self):
        slug = "example-corp-solo-20260720"
        self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "technical_interview", "state": "awaiting_schedule"})])
        first = self._run(
            STATUS, "--update-progress", slug, "backend",
            "--phase", "interview_loop", "--state", "scheduled",
            "--starts-at", "2026-08-11T10:00:00-07:00",
            "--timezone", "America/Los_Angeles",
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        _label, app = self._find(slug)
        before_meta = (app / "meta.yaml").read_bytes()
        before_calendar = self.calendar.read_bytes()

        second = self._run(
            STATUS, "--update-progress", slug, "backend",
            "--phase", "interview_loop", "--state", "scheduled",
            "--starts-at", "2026-08-13T09:00:00-07:00",
            "--timezone", "America/Los_Angeles",
        )

        self.assertNotEqual(second.returncode, 0)
        self.assertIn("refusing to overwrite", second.stderr)
        self.assertIn("--add-occurrence", second.stderr)
        self.assertEqual((app / "meta.yaml").read_bytes(), before_meta)
        self.assertEqual(self.calendar.read_bytes(), before_calendar)

    def test_parallel_occurrences_append_and_reduce_only_after_the_last_completion(self):
        slug = "example-corp-solo-20260720"
        self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "interview_loop", "state": "awaiting_schedule"})])
        occurrences = (
            ("2026-08-11T13:00:00-07:00", "2026-08-11T15:00:00-07:00"),
            ("2026-08-13T13:00:00-07:00", "2026-08-13T15:00:00-07:00"),
            ("2026-08-13T15:30:00-07:00", "2026-08-13T16:30:00-07:00"),
        )
        for index, (start, end) in enumerate(occurrences):
            args = [
                "--update-progress", slug, "backend",
                "--phase", "interview_loop", "--state", "scheduled",
                "--starts-at", start, "--ends-at", end,
                "--timezone", "America/Los_Angeles",
            ]
            if index:
                args.append("--add-occurrence")
            result = self._run(STATUS, *args)
            self.assertEqual(result.returncode, 0, result.stderr)

        _label, app = self._find(slug)
        progress = self._meta(app)["jobs"][0]["progress"]
        entry_ids = progress["calendar_items"]
        self.assertEqual(len(entry_ids), 3)
        self.assertEqual(len(set(entry_ids)), 3)
        self.assertEqual(progress["state"], "scheduled")
        calendar_text = self.calendar.read_text(encoding="utf-8")
        for start, _end in occurrences:
            self.assertIn(start, calendar_text)
        self.assertEqual(self._run(STATUS, "--check-calendar").returncode, 0)

        self._check_calendar_entry(entry_ids[0])
        first_done = self._run(STATUS, "--sync-calendar", "--write")
        self.assertEqual(first_done.returncode, 0, first_done.stderr)
        progress = self._meta(app)["jobs"][0]["progress"]
        self.assertEqual(progress["state"], "scheduled")
        self.assertIn('"status":"completed"', self.calendar.read_text())

        self._check_calendar_entry(entry_ids[1])
        self._check_calendar_entry(entry_ids[2])
        all_done = self._run(STATUS, "--sync-calendar", "--write")
        self.assertEqual(all_done.returncode, 0, all_done.stderr)
        progress = self._meta(app)["jobs"][0]["progress"]
        self.assertEqual(progress["state"], "awaiting_result")
        self.assertEqual(self._run(STATUS, "--check-calendar").returncode, 0)

    def test_update_progress_allows_same_occurrence_enrichment(self):
        slug = "example-corp-solo-20260720"
        self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "technical_interview", "state": "awaiting_schedule"})])
        common = (
            STATUS, "--update-progress", slug, "backend",
            "--phase", "technical_interview", "--state", "scheduled",
            "--starts-at", "2026-08-11T10:00:00-07:00",
            "--timezone", "America/Los_Angeles",
        )
        first = self._run(*common)
        self.assertEqual(first.returncode, 0, first.stderr)

        enriched = self._run(
            *common,
            "--ends-at", "2026-08-11T11:00:00-07:00",
        )

        self.assertEqual(enriched.returncode, 0, enriched.stderr)
        self.assertIn(
            '"ends_at":"2026-08-11T11:00:00-07:00"',
            self.calendar.read_text(),
        )

    # -- the CLI's own prose must not contradict the CLI ------------------- #
    # Both cases below were real drift: the docstring told agents to pre-record
    # the time in calendar.md and re-sync (the test above proves flags in ONE
    # invocation are enough), and --write's help named only --sync-calendar
    # while its own guard also accepts --refresh-calendar.

    def test_update_progress_docstring_matches_the_enforced_scheduled_contract(self):
        tree = ast.parse(STATUS.read_text(encoding="utf-8"))
        doc = next(
            ast.get_docstring(node) for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "update_progress")
        self.assertIn("--starts-at", doc)
        self.assertIn("--timezone", doc)
        # The retired instruction: record it in calendar.md, then re-sync.
        self.assertNotIn("--sync-calendar", doc)

    def test_write_help_names_every_flag_its_guard_accepts(self):
        guard = self._run(STATUS, "--write")
        self.assertNotEqual(guard.returncode, 0)
        accepted = set(re.findall(r"--[a-z-]+", guard.stderr.split("requires", 1)[1]))
        self.assertEqual(accepted, {"--sync-calendar", "--refresh-calendar"})

        # argparse lists each option at a fixed two-space indent; anchor there so
        # a wrapped "Add --write ..." inside a neighbour's help never matches.
        help_text = self._run(STATUS, "--help").stdout
        block = re.split(r"^  --write\b", help_text, maxsplit=1, flags=re.M)[1]
        block = re.split(r"^  --[a-z]", block, maxsplit=1, flags=re.M)[0]
        for flag in accepted:
            self.assertIn(flag, block, f"--write help omits {flag}")

    def test_assessment_and_offer_actions_are_first_class_todos(self):
        slug = "example-corp-solo-20260720"
        self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "assessment", "state": "unknown"})])
        proc = self._run(
            STATUS, "--update-progress", slug, "backend",
            "--phase", "assessment", "--state", "in_progress",
            "--action", "Submit the take-home", "--due-at", "2026-08-05",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = self.calendar.read_text()
        self.assertIn("**Submit the take-home**", text)
        self.assertIn("Due Wed, Aug 5", text)
        self.assertIn('"state":"in_progress"', text)

    def test_refresh_calendar_is_preview_first_and_removes_evidence_clutter(self):
        slug = "example-corp-solo-20260720"
        entry_id = "cal-example-corp-solo-01"
        fields = self._entry_fields(
            entry_id, slug, state="scheduled",
            starts_at="2026-08-03T10:00:00-07:00",
            timezone="America/Los_Angeles",
            source="email:acct-01/" + "a" * 64,
        )
        legacy = self._calendar_with_entry(
            fields, section=SECTION_SCHEDULED,
            text="Example Corp — Backend Engineer: confirmed interview")
        # Convert the compact test helper back to the legacy multi-line shape.
        marker = "".join(render_entry(fields, checked=False, text="unused")).splitlines()[1]
        payload = yaml.safe_load(
            marker.split("<!-- jobhunt-calendar ", 1)[1].rsplit(" -->", 1)[0])
        payload["source"] = fields["source"]
        legacy_marker = "  <!-- jobhunt-calendar\n" + "\n".join(
            f"  {line}" for line in yaml.safe_dump(
                payload, sort_keys=False).rstrip().splitlines()) + "\n  -->"
        legacy = legacy.replace(marker, legacy_marker)
        self._write_calendar(legacy)
        self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "technical_interview", "state": "scheduled",
             "calendar_items": [entry_id]})])
        before = self.calendar.read_bytes()
        preview = self._run(STATUS, "--refresh-calendar")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(self.calendar.read_bytes(), before)
        write = self._run(STATUS, "--refresh-calendar", "--write")
        self.assertEqual(write.returncode, 0, write.stderr)
        text = self.calendar.read_text()
        self.assertIn("**Mon, Aug 3 · 10:00 AM PDT**", text)
        self.assertNotIn("acct-01/", text)
        self.assertEqual(text.count("<!-- jobhunt-calendar"), 1)

    def test_refresh_generates_idempotent_company_view_with_all_roles_and_email_update(self):
        slug = "example-corp-multi-20260720"
        app = self._place("in_progress", slug, [
            _job(
                "Backend Engineer", "in_progress", "JD-backend.md",
                {
                    "phase": "technical_interview",
                    "state": "awaiting_schedule",
                    "updated_at": "2026-07-28T23:00:00Z",
                    "source": {"kind": "email", "ref": "acct-01/" + "a" * 64},
                },
            ),
            _job(
                "Platform Engineer", "applied", "JD-platform.md",
                {
                    "phase": "application_review",
                    "state": "waiting_employer",
                    "updated_at": "2026-07-27T18:00:00Z",
                    "source": {"kind": "manual", "ref": ""},
                },
            ),
        ])
        (app / "notes.md").write_text(textwrap.dedent("""\
            # Example Corp — Notes

            ## Upcoming Events & To-Dos

            - [ ] Waiting for a confirmed interview time

            ## Email Timeline

            ### 2026-07-28 4:00 PM PT — Outbound — Interview availability

            - **Summary:** Sent several Pacific-time interview windows.
            - **Outcome / next step:** Availability submitted; awaiting a confirmed time.

            ### 2026-07-27 9:00 AM PT — Inbound — Scheduling request

            - **Summary:** Recruiter asked for availability.
            - **Outcome / next step:** Send availability.
            """), encoding="utf-8")
        self._place("applied", "other-corp-role-20260720", [
            _job(
                "Excluded Role", "applied", "JD-excluded.md",
                {"phase": "application_review", "state": "waiting_employer"},
            ),
        ], company="Other Corp")
        self._write_calendar(CALENDAR_SKELETON)
        before = self.calendar.read_bytes()

        preview = self._run(STATUS, "--refresh-calendar")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(self.calendar.read_bytes(), before)
        write = self._run(STATUS, "--refresh-calendar", "--write")
        self.assertEqual(write.returncode, 0, write.stderr)
        first = self.calendar.read_bytes()
        text = first.decode("utf-8")
        self.assertEqual(text.count(COMPANY_VIEW_START), 1)
        self.assertEqual(text.count(COMPANY_VIEW_END), 1)
        self.assertEqual(text.count("| Company | Role | Current step | State |"), 1)
        self.assertIn("Backend Engineer", text)
        self.assertIn("Platform Engineer", text)
        self.assertNotIn("Excluded Role", text)
        self.assertEqual(
            text.count("Availability submitted; awaiting a confirmed time."), 1)
        self.assertIn("[Email timeline]", text)
        self.assertIn("Pipeline and company updates", text)
        self.assertNotIn("acct-01/", text)
        self.assertIn("my own note — tooling must never touch this line", text)

        again = self._run(STATUS, "--refresh-calendar", "--write")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.calendar.read_bytes(), first)
        self.assertEqual(self._run(STATUS, "--check-calendar").returncode, 0)

    def test_company_update_falls_back_to_human_next_action_then_role_metadata(self):
        self._place(
            "in_progress",
            "alpha-corp-role-20260720",
            [_job(
                "Backend Engineer", "in_progress", "JD-backend.md",
                {
                    "phase": "recruiter_screen",
                    "state": "awaiting_schedule",
                    "updated_at": "2026-07-28T20:00:00Z",
                    "source": {"kind": "email", "ref": "acct-01/" + "b" * 64},
                },
            )],
            company="Alpha Corp",
            next_action="Availability submitted; wait for the recruiter to confirm.",
        )
        self._place(
            "in_progress",
            "beta-corp-role-20260720",
            [_job(
                "Infrastructure Engineer", "in_progress", "JD-infra.md",
                {
                    "phase": "technical_interview",
                    "state": "scheduled",
                    "updated_at": "2026-07-29T18:00:00Z",
                    "source": {"kind": "manual", "ref": ""},
                },
            )],
            company="Beta Corp",
        )
        self._write_calendar(CALENDAR_SKELETON)
        write = self._run(STATUS, "--refresh-calendar", "--write")
        self.assertEqual(write.returncode, 0, write.stderr)
        text = self.calendar.read_text()
        self.assertIn(
            "**Alpha Corp:** Availability submitted; wait for the "
            "recruiter to confirm. · [Human]",
            text,
        )
        self.assertIn(
            "**Beta Corp:** Infrastructure Engineer: Technical Interview — "
            "Scheduled. · [Application metadata]",
            text,
        )

    def test_company_view_surfaces_unlinked_owner_action_from_metadata(self):
        self._place("in_progress", "example-corp-role-20260720", [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "technical_interview", "state": "booking_required"},
        )])
        self._write_calendar(CALENDAR_SKELETON)
        write = self._run(STATUS, "--refresh-calendar", "--write")
        self.assertEqual(write.returncode, 0, write.stderr)
        text = self.calendar.read_text()
        prep = text[:text.index("<details>")]
        self.assertIn("### Do now", prep)
        self.assertIn("Choose an interview time", prep)
        self.assertIn("| When | Company | Role | Action |", prep)
        self.assertEqual(self._run(STATUS, "--check-calendar").returncode, 0)

    def test_company_view_aligns_one_interview_per_row_and_folds_past_events(self):
        slug = "example-corp-multi-20260720"
        upcoming_one = "cal-example-corp-multi-01"
        upcoming_two = "cal-example-corp-multi-02"
        past = "cal-example-corp-multi-03"
        self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {
                "phase": "interview_loop",
                "state": "scheduled",
                "label": "Virtual onsite",
                "calendar_items": [upcoming_one, upcoming_two, past],
            },
        )])
        blocks = []
        for entry_id, starts_at, ends_at, action in (
            (upcoming_one, "2099-08-10T13:00:00-07:00", "2099-08-10T14:00:00-07:00",
             "Attend coding interview"),
            (upcoming_two, "2099-08-10T15:30:00-07:00", "2099-08-10T16:30:00-07:00",
             "Attend architecture interview"),
            (past, "2000-01-05T09:00:00-08:00", "2000-01-05T10:00:00-08:00",
             "Attend recruiter interview"),
        ):
            fields = self._entry_fields(
                entry_id, slug, state="scheduled", phase="interview_loop",
                label="Virtual onsite", starts_at=starts_at, ends_at=ends_at,
                timezone="America/Los_Angeles", action=action,
            )
            blocks.append("".join(render_entry(fields, checked=False, text="legacy")))
        self._write_calendar(CALENDAR_SKELETON.replace(
            f"{SECTION_SCHEDULED}\n",
            f"{SECTION_SCHEDULED}\n\n" + "\n".join(blocks),
            1,
        ))

        refresh = self._run(STATUS, "--refresh-calendar", "--write")
        self.assertEqual(refresh.returncode, 0, refresh.stderr)
        text = self.calendar.read_text()
        self.assertIn("#### Week of Aug 10–16, 2099", text)
        self.assertIn("##### Monday, August 10, 2099", text)
        self.assertEqual(text.count("| Time | Status | Company / commitment | Role | Event |"), 2)
        self.assertIn("| 1:00 PM–2:00 PM PDT | Confirmed | Example Corp |", text)
        self.assertIn("| 3:30 PM–4:30 PM PDT | Confirmed | Example Corp |", text)
        self.assertIn("| coding interview |", text)
        self.assertIn("| architecture interview |", text)
        self.assertIn("<summary><strong>Past schedule</strong></summary>", text)
        self.assertIn("##### Wednesday, January 5, 2000", text)
        self.assertIn("<summary><strong>Pipeline and company updates</strong></summary>", text)
        self.assertEqual(self._run(STATUS, "--check-calendar").returncode, 0)

    def test_refresh_html_keeps_actions_separate_and_is_byte_stable(self):
        slug = "example-corp-multi-20260720"
        action_id = "cal-example-corp-multi-01"
        first_id = "cal-example-corp-multi-02"
        second_id = "cal-example-corp-multi-03"
        self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {
                "phase": "interview_loop",
                "state": "booking_required",
                "calendar_items": [action_id, first_id, second_id],
            },
        )])
        action = self._entry_fields(
            action_id, slug, state="booking_required", phase="interview_loop",
            action="Choose the final interview time", due_at="2099-08-09")
        first = self._entry_fields(
            first_id, slug, state="scheduled", phase="interview_loop",
            label="Virtual onsite", starts_at="2099-08-10T13:00:00-07:00",
            ends_at="2099-08-10T14:00:00-07:00",
            timezone="America/Los_Angeles", action="Attend coding interview")
        second = self._entry_fields(
            second_id, slug, state="scheduled", phase="interview_loop",
            label="Virtual onsite", starts_at="2099-08-10T15:30:00-07:00",
            ends_at="2099-08-10T16:30:00-07:00",
            timezone="America/Los_Angeles", action="Attend architecture interview")
        calendar = CALENDAR_SKELETON.replace(
            "## Action needed\n", "## Action needed\n\n" + "".join(
                render_entry(action, checked=False, text="legacy")), 1)
        supplemental = (
            '<!-- jobhunt-availability {"timezone":"America/Los_Angeles",'
            '"days":["monday","tuesday","wednesday","thursday","friday"],'
            '"start":"08:00","end":"17:00","business_days":10,'
            '"buffer_minutes":15,"minimum_window_minutes":60} -->\n'
            '<!-- jobhunt-agenda {"id":"agenda-unlinked-interview",'
            '"kind":"interview","company":"Unlinked Co",'
            '"role":"Infrastructure Engineer (posting link unresolved)",'
            '"round":"Technical interview",'
            '"starts_at":"2099-08-10T14:30:00-07:00",'
            '"ends_at":"2099-08-10T15:00:00-07:00",'
            '"timezone":"America/Los_Angeles"} -->\n'
            '<!-- jobhunt-agenda {"id":"agenda-unlinked-action",'
            '"kind":"action","company":"Unlinked Co",'
            '"role":"Infrastructure Engineer (posting link unresolved)",'
            '"action":"Submit four availability slots"} -->\n\n'
        )
        calendar = calendar.replace(
            "## Action needed\n", supplemental + "## Action needed\n", 1)
        calendar = calendar.replace(
            f"{SECTION_SCHEDULED}\n", f"{SECTION_SCHEDULED}\n\n" + "".join(
                render_entry(first, checked=False, text="legacy")
                + render_entry(second, checked=False, text="legacy")), 1)
        self._write_calendar(calendar)

        write = self._run(STATUS, "--refresh-calendar", "--write", "--html")
        self.assertEqual(write.returncode, 0, write.stderr)
        markdown = self.calendar.read_text()
        html = self.calendar.with_suffix(".html").read_text()
        self.assertLess(markdown.index("### Do now"), markdown.index("### Schedule"))
        prep = markdown[:markdown.index("<details>")]
        generated = markdown[
            markdown.index(COMPANY_VIEW_START):markdown.index(COMPANY_VIEW_END)
        ]
        self.assertIn("Choose the final interview time", prep)
        self.assertEqual(prep.count("##### Monday, August 10, 2099"), 1)
        self.assertEqual(prep.count("| Confirmed |"), 3)
        self.assertEqual(generated.count("Submit four availability slots"), 1)
        self.assertLess(
            generated.index("Submit four availability slots"),
            generated.index("Choose the final interview time"),
        )
        self.assertIn("Unlinked Co", prep)
        self.assertIn("### Available interview times", prep)
        self.assertIn("```text", prep)
        self.assertIn("| Time | Status | Company / commitment | Role | Event |", prep)
        self.assertIn(
            'href="../4_in_progress/example-corp-multi-20260720/meta.yaml" '
            'target="_blank" rel="noopener noreferrer"',
            html,
        )
        self.assertEqual(html.count("<a "), html.count('target="_blank"'))
        self.assertIn("@media (max-width: 720px)", html)
        self.assertIn('<div class="table-wrap" role="region"', html)
        self.assertEqual(html.count("Submit four availability slots"), 1)
        self.assertIn("Unlinked Co", html)
        self.assertIn("<h2>Available interview times</h2>", html)
        self.assertIn('<pre class="availability-copy">', html)
        self.assertIn('<section class="week">', html)
        self.assertIn('<article class="event event-interview">', html)
        self.assertLess(html.index("<h2>Do now</h2>"), html.index("<h2>Schedule</h2>"))
        first_markdown, first_html = self.calendar.read_bytes(), self.calendar.with_suffix(".html").read_bytes()
        again = self._run(STATUS, "--refresh-calendar", "--write", "--html")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.calendar.read_bytes(), first_markdown)
        self.assertEqual(self.calendar.with_suffix(".html").read_bytes(), first_html)
        self.assertEqual(self._run(STATUS, "--check-calendar").returncode, 0)

    def test_status_transition_adds_and_removes_company_view_without_role_entry(self):
        slug = "example-corp-solo-20260720"
        self._place("applied", slug, [_job(
            "Backend Engineer", "applied", "JD-backend.md",
            {"phase": "application_review", "state": "waiting_employer"},
        )])
        advance = self._run(
            STATUS, "--update-job", slug, "backend", "in_progress")
        self.assertEqual(advance.returncode, 0, advance.stderr)
        self.assertEqual(self._find(slug)[0], "in_progress")
        text = self.calendar.read_text()
        self.assertEqual(text.count(COMPANY_VIEW_START), 1)
        self.assertIn("| Example Corp |", text)
        self.assertIn("Backend Engineer", text)
        self.assertIn(
            "../4_in_progress/example-corp-solo-20260720/meta.yaml", text)
        self.assertNotIn("<!-- jobhunt-calendar {", text)
        self.assertEqual(self._run(STATUS, "--check-calendar").returncode, 0)

        close = self._run(
            STATUS, "--update-job", slug, "backend", "rejected")
        self.assertEqual(close.returncode, 0, close.stderr)
        self.assertEqual(self._find(slug)[0], "rejected")
        text = self.calendar.read_text()
        self.assertEqual(text.count(COMPANY_VIEW_START), 1)
        self.assertIn("_None currently._", text)
        self.assertNotIn("### Example Corp", text)

    def test_update_progress_closed_state_is_rejected_with_hint(self):
        slug = "example-corp-solo-20260720"
        app = self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "recruiter_screen", "state": "unknown"})])
        before = (app / "meta.yaml").read_bytes()
        proc = self._run(STATUS, "--update-progress", slug, "backend",
                         "--phase", "recruiter_screen", "--state", "closed")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--update-job", proc.stderr)
        self.assertEqual((app / "meta.yaml").read_bytes(), before)

    def test_update_progress_preserves_unmarked_calendar_text(self):
        slug = "example-corp-solo-20260720"
        self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "recruiter_screen", "state": "unknown"})])
        self._write_calendar(CALENDAR_SKELETON)
        proc = self._run(STATUS, "--update-progress", slug, "backend",
                         "--phase", "recruiter_screen",
                         "--state", "booking_required")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = self.calendar.read_text()
        self.assertIn("- [ ] my own note — tooling must never touch this line",
                      text)

    def test_update_progress_records_ordered_subslots_on_one_organizer_block(self):
        slug = "example-corp-onsite-20260720"
        entry_id = "cal-example-corp-onsite-01"
        self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {
                "phase": "interview_loop",
                "state": "scheduled",
                "label": "Virtual onsite",
                "calendar_items": [entry_id],
            },
        )])
        fields = self._entry_fields(
            entry_id, slug, state="scheduled", phase="interview_loop",
            label="Virtual onsite", starts_at="2099-08-10T13:00:00-07:00",
            ends_at="2099-08-10T15:00:00-07:00",
            timezone="America/Los_Angeles", action="Attend virtual onsite",
        )
        self._write_calendar(CALENDAR_SKELETON.replace(
            f"{SECTION_SCHEDULED}\n",
            f"{SECTION_SCHEDULED}\n\n" + "".join(
                render_entry(fields, checked=False, text="legacy")),
            1,
        ))

        update = self._run(
            STATUS, "--update-progress", slug, "Backend Engineer",
            "--phase", "interview_loop", "--state", "scheduled",
            "--label", "Virtual onsite", "--calendar-item", entry_id,
            "--display-round", "1:00–2:00 PM — Coding — Alex",
            "--display-round", "2:00–3:00 PM — Architecture — Casey",
        )
        self.assertEqual(update.returncode, 0, update.stderr)
        doc = parse_calendar(self.calendar.read_text())
        self.assertEqual(doc.entries[entry_id].display_rounds, (
            "1:00–2:00 PM — Coding — Alex",
            "2:00–3:00 PM — Architecture — Casey",
        ))
        generated = self.calendar.read_text()[
            self.calendar.read_text().index(COMPANY_VIEW_START):
            self.calendar.read_text().index(COMPANY_VIEW_END)
        ]
        self.assertEqual(generated.count("1:00 PM–3:00 PM PDT | Confirmed"), 1)
        self.assertIn("1:00–2:00 PM — Coding — Alex", generated)
        self.assertIn("2:00–3:00 PM — Architecture — Casey", generated)

    # -- fail-closed calendar states ---------------------------------------- #
    def test_malformed_marker_fails_everything_closed(self):
        slug = "example-corp-solo-20260720"
        app = self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "recruiter_screen", "state": "unknown"})])
        self._write_calendar(CALENDAR_SKELETON.replace(
            "## Action needed\n",
            "## Action needed\n\n- [ ] broken\n  <!-- jobhunt-calendar\n"
            "  id: cal-broken-01\n", 1))
        before = (app / "meta.yaml").read_bytes()
        update = self._run(STATUS, "--update-progress", slug, "backend",
                           "--phase", "recruiter_screen",
                           "--state", "booking_required")
        self.assertNotEqual(update.returncode, 0)
        self.assertEqual((app / "meta.yaml").read_bytes(), before)
        self.assertNotEqual(self._run(STATUS, "--check-calendar").returncode, 0)
        self.assertNotEqual(
            self._run(STATUS, "--sync-calendar", "--write").returncode, 0)

    def test_duplicate_entry_ids_fail_closed(self):
        slug = "example-corp-solo-20260720"
        fields = self._entry_fields("cal-example-corp-solo-01", slug,
                                    state="booking_required")
        block = "".join(render_entry(fields, checked=False, text="dup"))
        self._write_calendar(CALENDAR_SKELETON.replace(
            "## Action needed\n", f"## Action needed\n\n{block}\n{block}", 1))
        app = self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "technical_interview", "state": "booking_required",
             "calendar_items": ["cal-example-corp-solo-01"]})])
        before = (app / "meta.yaml").read_bytes()
        self.assertNotEqual(self._run(STATUS, "--check-calendar").returncode, 0)
        update = self._run(STATUS, "--update-job", slug, "backend", "rejected")
        self.assertNotEqual(update.returncode, 0)
        self.assertEqual((app / "meta.yaml").read_bytes(), before)
        self.assertEqual(self._find(slug)[0], "in_progress")  # never moved

    def test_missing_referenced_entry_blocks_the_transition(self):
        slug = "example-corp-solo-20260720"
        self._write_calendar(CALENDAR_SKELETON)
        app = self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "technical_interview", "state": "booking_required",
             "calendar_items": ["cal-example-corp-solo-99"]})])
        before = (app / "meta.yaml").read_bytes()
        proc = self._run(STATUS, "--update-job", slug, "backend", "rejected")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing calendar entry", proc.stderr)
        self.assertEqual((app / "meta.yaml").read_bytes(), before)
        self.assertEqual(self._find(slug)[0], "in_progress")

    def test_calendar_checksum_race_rolls_back_the_meta_write(self):
        # Plan meta + calendar, then let a concurrent edit land on calendar.md
        # before the calendar write: the transaction must roll the already-
        # written meta.yaml back to its pre-image (no one-sided write).
        slug = "example-corp-solo-20260720"
        entry_id = "cal-example-corp-solo-01"
        fields = self._entry_fields(entry_id, slug, state="booking_required")
        self._write_calendar(
            self._calendar_with_entry(fields, section="## Action needed"))
        app = self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "technical_interview", "state": "booking_required",
             "calendar_items": [entry_id]})])
        driver = self.root / "race_driver.py"
        driver.write_text(textwrap.dedent(f"""\
            import importlib.util, json, sys
            from pathlib import Path
            scripts = Path({str(SCRIPTS)!r})
            for p in (scripts, scripts / "_vendor"):
                sys.path.insert(0, str(p))
            spec = importlib.util.spec_from_file_location(
                "status_under_test", scripts / "status.py")
            status = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(status)
            meta_path = Path({str(app / 'meta.yaml')!r})
            raw = meta_path.read_bytes()
            new_progress = {{
                "phase": "technical_interview", "state": "awaiting_schedule",
                "calendar_items": [{entry_id!r}],
            }}
            plan = status.plan_field_updates(
                raw, {{("jobs", 0): {{"progress": new_progress}}}})
            assert not plan.errors, plan.errors
            cal_path = status._calendar_path()
            cal_raw = cal_path.read_bytes()
            doc = status.parse_calendar(cal_raw.decode("utf-8"))
            fields = doc.entries[{entry_id!r}].fields()
            fields["state"] = "awaiting_schedule"
            cal_plan = status.plan_calendar_update(cal_raw, {{{entry_id!r}: fields}})
            assert not cal_plan.errors, cal_plan.errors
            # Concurrent human edit AFTER planning, BEFORE the commit:
            cal_path.write_bytes(cal_raw + b"\\n- [ ] note added mid-flight\\n")
            try:
                status._commit_meta_and_calendar(
                    [(meta_path, raw, plan)], cal_plan)
                print(json.dumps({{"exited": False}}))
            except SystemExit:
                print(json.dumps({{
                    "exited": True,
                    "meta_unchanged": meta_path.read_bytes() == raw,
                }}))
            """), encoding="utf-8")
        env = dict(os.environ, JOBHUNT_CONFIG=str(self.root / "config.yaml"))
        proc = subprocess.run([sys.executable, str(driver)],
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout.splitlines()[-1])
        self.assertTrue(result["exited"])
        self.assertTrue(result["meta_unchanged"])  # rolled back, not one-sided
        self.assertIn("note added mid-flight", self.calendar.read_text())

    # -- --sync-calendar ----------------------------------------------------- #
    def test_checked_booking_box_syncs_to_awaiting_schedule(self):
        slug = "example-corp-solo-20260720"
        entry_id = "cal-example-corp-solo-01"
        fields = self._entry_fields(entry_id, slug, state="booking_required")
        self._write_calendar(self._calendar_with_entry(
            fields, section="## Action needed", checked=True))
        app = self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "technical_interview", "state": "booking_required",
             "calendar_items": [entry_id]})])
        before_meta = (app / "meta.yaml").read_bytes()
        before_calendar = self.calendar.read_bytes()

        preview = self._run(STATUS, "--sync-calendar")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("booking_required -> awaiting_schedule", preview.stdout)
        # Preview writes NOTHING.
        self.assertEqual((app / "meta.yaml").read_bytes(), before_meta)
        self.assertEqual(self.calendar.read_bytes(), before_calendar)

        apply = self._run(STATUS, "--sync-calendar", "--write")
        self.assertEqual(apply.returncode, 0, apply.stderr)
        progress = self._meta(app)["jobs"][0]["progress"]
        self.assertEqual(progress["state"], "awaiting_schedule")
        text = self.calendar.read_text()
        self.assertIn('"state":"awaiting_schedule"', text)
        self.assertEqual(self._find(slug)[0], "in_progress")  # still no move
        self.assertEqual(self._run(STATUS, "--check-calendar").returncode, 0)

    def test_reschedule_to_confirms_and_preserves_superseded_occurrence(self):
        slug = "example-corp-solo-20260720"
        entry_id = "cal-example-corp-solo-01"
        fields = self._entry_fields(
            entry_id, slug, state="scheduled",
            starts_at="2026-08-01T10:00:00", timezone="America/Los_Angeles",
            reschedule_to="2026-08-08T15:00:00",
            reschedule_timezone="America/Los_Angeles")
        self._write_calendar(self._calendar_with_entry(
            fields, section=SECTION_SCHEDULED))
        app = self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "technical_interview", "state": "scheduled",
             "calendar_items": [entry_id]})])
        apply = self._run(STATUS, "--sync-calendar", "--write")
        self.assertEqual(apply.returncode, 0, apply.stderr)
        text = self.calendar.read_text()
        self.assertIn('"starts_at":"2026-08-08T15:00:00"', text)
        self.assertIn('"history":[', text)
        self.assertIn('"starts_at":"2026-08-01T10:00:00"', text)
        self.assertIn('"status":"superseded"', text)
        progress = self._meta(app)["jobs"][0]["progress"]
        self.assertEqual(progress["state"], "scheduled")
        self.assertEqual(self._run(STATUS, "--check-calendar").returncode, 0)

    def test_cancel_records_occurrence_without_rejecting_the_role(self):
        slug = "example-corp-solo-20260720"
        entry_id = "cal-example-corp-solo-01"
        fields = self._entry_fields(
            entry_id, slug, state="scheduled",
            starts_at="2026-08-01T10:00:00", timezone="UTC", cancel=True)
        self._write_calendar(self._calendar_with_entry(
            fields, section=SECTION_SCHEDULED))
        app = self._place("in_progress", slug, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "technical_interview", "state": "scheduled",
             "calendar_items": [entry_id]})])
        apply = self._run(STATUS, "--sync-calendar", "--write")
        self.assertEqual(apply.returncode, 0, apply.stderr)
        text = self.calendar.read_text()
        self.assertIn('"status":"cancelled"', text)
        meta = self._meta(app)
        self.assertEqual(meta["jobs"][0]["status"], "in_progress")  # NOT rejected
        self.assertEqual(meta["jobs"][0]["progress"]["state"], "action_required")

    # -- pipeline health ----------------------------------------------------- #
    def test_status_table_surfaces_action_needed_and_overdue_waiting(self):
        slug_action = "example-corp-action-20260720"
        self._place("in_progress", slug_action, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "technical_interview", "state": "booking_required"})])
        slug_wait = "example-corp-wait-20260720"
        entry_id = "cal-example-corp-wait-01"
        fields = self._entry_fields(
            entry_id, slug_wait, state="awaiting_schedule",
            follow_up_at="2026-01-01")
        self._write_calendar(self._calendar_with_entry(
            fields, section=SECTION_WAITING))
        self._place("in_progress", slug_wait, [_job(
            "Backend Engineer", "in_progress", "JD-backend.md",
            {"phase": "technical_interview", "state": "awaiting_schedule",
             "calendar_items": [entry_id]})])
        proc = self._run(STATUS)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Action needed", proc.stdout)
        self.assertIn("booking_required", proc.stdout)
        self.assertIn("Overdue waiting", proc.stdout)
        self.assertIn("follow-up was 2026-01-01", proc.stdout)

    # -- metadata validation ------------------------------------------------ #
    def test_check_metadata_rejects_total_compensation_range(self):
        slug = "example-corp-unsupported-comp-20260720"
        app = self._place("drafted", slug, [_job(
            "Backend Engineer", "drafted", "JD-backend.md",
            {"phase": "application_prep", "state": "action_required"})])
        meta = self._meta(app)
        meta["jobs"][0]["total_compensation_range"] = {
            "min": 200000,
            "max": 300000,
        }
        (app / "meta.yaml").write_text(
            yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")

        proc = self._run(
            STATUS, "--check-metadata", "--statuses", "drafted")

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(
            "jobs[0].total_compensation_range is not supported",
            proc.stdout,
        )

    # -- migration CLI ------------------------------------------------------- #
    def test_fleet_migration_is_preview_first_then_writes(self):
        slug_a = "example-corp-a-20260720"
        app_a = self._place("in_progress", slug_a, [
            _job(
                "Backend Engineer", "in_progress", "JD-backend.md",
                {
                    "phase": "interview_loop",
                    "state": "scheduled",
                    "calendar_item": "cal-example-corp-a-01",
                },
            ),
        ], version=5)
        slug_b = "example-corp-b-20260720"
        app_b = self._place("drafted", slug_b, [
            _job(
                "Platform Engineer", "drafted", "JD-platform.md",
                {"phase": "application_prep", "state": "action_required"},
            ),
        ], version=5)

        # After the cutover the validators only accept v6.
        check = self._run(STATUS, "--check-metadata")
        self.assertNotEqual(check.returncode, 0)
        self.assertIn("must be 6", check.stdout)

        before_a = (app_a / "meta.yaml").read_bytes()
        preview = self._run(MIGRATE)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("would migrate", preview.stdout)
        self.assertIn("calendar_items: [cal-example-corp-a-01]", preview.stdout)
        self.assertEqual((app_a / "meta.yaml").read_bytes(), before_a)

        write = self._run(MIGRATE, "--write", "--quiet-diff")
        self.assertEqual(write.returncode, 0, write.stderr)
        meta_a = self._meta(app_a)
        self.assertEqual(meta_a["job_metadata_schema_version"], 6)
        self.assertEqual(
            meta_a["jobs"][0]["progress"]["calendar_items"],
            ["cal-example-corp-a-01"],
        )
        self.assertNotIn("calendar_item", meta_a["jobs"][0]["progress"])
        meta_b = self._meta(app_b)
        self.assertNotIn("calendar_items", meta_b["jobs"][0]["progress"])
        self.assertEqual(self._run(STATUS, "--check-metadata").returncode, 0)
        # Idempotence guard: a second write run fails loudly, changing nothing.
        again = self._run(MIGRATE, "--write")
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("already schema v6", again.stdout)


if __name__ == "__main__":
    unittest.main()
