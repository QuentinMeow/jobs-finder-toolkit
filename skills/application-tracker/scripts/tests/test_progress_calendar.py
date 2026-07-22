"""End-to-end tests for schema-v5 progress + the single calendar file.

Covers: `status.py --update-progress` (transactional meta + calendar, never a
folder move), `--check-calendar`, preview-first `--sync-calendar`, the v4->v5
fleet migration CLI, and the fail-closed behaviors (malformed markers,
duplicate ids, missing entries, checksum races, one-sided writes).

Each case runs the CLIs as subprocesses with JOBHUNT_CONFIG pointed at a
throwaway config + applications tree (no private overlay, fictional data
only), mirroring test_status_transitions.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[1]
STATUS = SCRIPTS / "status.py"
MIGRATE = SCRIPTS / "migrate_to_v5.py"
for _p in (SCRIPTS, SCRIPTS / "_vendor"):
    if str(_p) not in sys.path and _p.is_dir():
        sys.path.insert(0, str(_p))

from calendar_todos import (  # noqa: E402
    SECTION_SCHEDULED,
    SECTION_WAITING,
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
               *, version: int = 5) -> Path:
        app = self.apps / STATUS_DIRS[status_label] / slug
        (app / "source").mkdir(parents=True)
        for job in jobs:
            jd = job.get("jd_file")
            if jd:
                (app / "source" / jd).write_text("Fictional JD.", encoding="utf-8")
        meta = {
            "job_metadata_schema_version": version,
            "company": "Example Corp",
            "research_date": "2026-07-20",
            "jobs": jobs,
        }
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
        self.assertTrue(progress["calendar_item"].startswith("cal-example-corp"))
        self.assertTrue(self.calendar.is_file())
        calendar_text = self.calendar.read_text()
        self.assertIn(progress["calendar_item"], calendar_text)
        self.assertIn('"state":"booking_required"', calendar_text)
        self.assertIn("**Choose an interview time**", calendar_text)
        self.assertIn("[Example Corp · Backend Engineer]", calendar_text)
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
             "calendar_item": entry_id})])
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
             "calendar_item": "cal-example-corp-solo-01"})])
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
             "calendar_item": "cal-example-corp-solo-99"})])
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
             "calendar_item": entry_id})])
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
            plan = status.plan_field_updates(raw, {{("jobs", 0): {{"progress": {{
                "phase": "technical_interview", "state": "awaiting_schedule",
                "calendar_item": {entry_id!r}}}}}}})
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
             "calendar_item": entry_id})])
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
             "calendar_item": entry_id})])
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
             "calendar_item": entry_id})])
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
             "calendar_item": entry_id})])
        proc = self._run(STATUS)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Action needed", proc.stdout)
        self.assertIn("booking_required", proc.stdout)
        self.assertIn("Overdue waiting", proc.stdout)
        self.assertIn("follow-up was 2026-01-01", proc.stdout)

    # -- migration CLI ------------------------------------------------------- #
    def test_fleet_migration_is_preview_first_then_writes(self):
        def v4_job(role, status, jd, stage):
            job = _job(role, status, jd, {})
            del job["progress"]
            job["stage"] = stage
            return job

        slug_a = "example-corp-a-20260720"
        app_a = self._place("in_progress", slug_a, [
            v4_job("Backend Engineer", "in_progress", "JD-backend.md", "onsite"),
        ], version=4)
        slug_b = "example-corp-b-20260720"
        app_b = self._place("drafted", slug_b, [
            v4_job("Platform Engineer", "drafted", "JD-platform.md", ""),
        ], version=4)

        # After the cutover the validators only accept v5.
        check = self._run(STATUS, "--check-metadata")
        self.assertNotEqual(check.returncode, 0)
        self.assertIn("must be 5", check.stdout)

        before_a = (app_a / "meta.yaml").read_bytes()
        preview = self._run(MIGRATE)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("would migrate", preview.stdout)
        self.assertIn("-  stage: onsite", preview.stdout)  # diff shown
        self.assertEqual((app_a / "meta.yaml").read_bytes(), before_a)

        write = self._run(MIGRATE, "--write", "--quiet-diff")
        self.assertEqual(write.returncode, 0, write.stderr)
        meta_a = self._meta(app_a)
        self.assertEqual(meta_a["job_metadata_schema_version"], 5)
        self.assertEqual(meta_a["jobs"][0]["progress"],
                         {"phase": "interview_loop", "state": "unknown",
                          "label": "onsite"})
        self.assertNotIn("stage", meta_a["jobs"][0])
        meta_b = self._meta(app_b)
        self.assertEqual(meta_b["jobs"][0]["progress"],
                         {"phase": "application_prep",
                          "state": "action_required"})
        self.assertEqual(self._run(STATUS, "--check-metadata").returncode, 0)
        # Idempotence guard: a second write run fails loudly, changing nothing.
        again = self._run(MIGRATE, "--write")
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("already schema v5", again.stdout)


if __name__ == "__main__":
    unittest.main()
