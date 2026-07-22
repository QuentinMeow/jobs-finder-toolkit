"""Tests for the single calendar/todo file module (calendar_todos.py)."""
import sys
import unittest
from pathlib import Path

SHARED_DIR = Path(__file__).resolve().parents[1]
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from calendar_todos import (  # noqa: E402
    CALENDAR_TEMPLATE,
    SECTION_ACTION,
    SECTION_SCHEDULED,
    SECTION_WAITING,
    generate_entry_id,
    parse_calendar,
    plan_calendar_update,
    record_cancellation,
    record_reschedule,
    render_entry,
)


def _fields(**overrides) -> dict:
    fields = {
        "id": "cal-examplecorp-senior-software-engineer-01",
        "application": "examplecorp-senior-software-engineer",
        "role": "Senior Software Engineer",
        "phase": "technical_interview",
        "state": "booking_required",
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


def _calendar_with(fields, *, checked=False, text="ExampleCorp — choose a time",
                   section=SECTION_ACTION) -> str:
    lines = render_entry(fields, checked=checked, text=text)
    block = "".join(lines)
    return CALENDAR_TEMPLATE.replace(f"{section}\n", f"{section}\n\n{block}", 1)


class ParseTests(unittest.TestCase):
    def test_template_parses_clean(self):
        doc = parse_calendar(CALENDAR_TEMPLATE)
        self.assertEqual(doc.errors, [])
        self.assertEqual(doc.entries, {})

    def test_roundtrip_entry_parses_with_placement(self):
        text = _calendar_with(_fields())
        doc = parse_calendar(text)
        self.assertEqual(doc.errors, [])
        entry = doc.entries["cal-examplecorp-senior-software-engineer-01"]
        self.assertEqual(entry.state, "booking_required")
        self.assertEqual(entry.section, SECTION_ACTION)
        self.assertFalse(entry.checked)
        self.assertEqual(entry.text, "ExampleCorp — choose a time")

    def test_malformed_marker_yaml_fails(self):
        text = CALENDAR_TEMPLATE.replace(
            "## Action needed\n",
            "## Action needed\n\n- [ ] broken\n  <!-- jobhunt-calendar\n"
            "  id: [unclosed\n  -->\n", 1)
        doc = parse_calendar(text)
        self.assertTrue(any("not valid YAML" in e for e in doc.errors))

    def test_marker_without_bullet_fails(self):
        text = CALENDAR_TEMPLATE.replace(
            "## Action needed\n",
            "## Action needed\n\n  <!-- jobhunt-calendar\n  id: cal-a-01\n  -->\n", 1)
        doc = parse_calendar(text)
        self.assertTrue(any("checkbox bullet" in e for e in doc.errors))

    def test_unclosed_marker_fails(self):
        text = CALENDAR_TEMPLATE.replace(
            "## Action needed\n",
            "## Action needed\n\n- [ ] x\n  <!-- jobhunt-calendar\n  id: cal-a-01\n", 1)
        doc = parse_calendar(text)
        self.assertTrue(any("never closed" in e for e in doc.errors))

    def test_duplicate_ids_fail(self):
        entry = "".join(render_entry(_fields(), checked=False, text="dup"))
        text = CALENDAR_TEMPLATE.replace(
            "## Action needed\n", f"## Action needed\n\n{entry}\n{entry}", 1)
        doc = parse_calendar(text)
        self.assertTrue(any("duplicate calendar entry id" in e for e in doc.errors))

    def test_scheduled_without_time_or_timezone_fails(self):
        no_time = _calendar_with(
            _fields(state="scheduled", timezone="America/Los_Angeles"),
            section=SECTION_SCHEDULED)
        doc = parse_calendar(no_time)
        self.assertTrue(any("requires starts_at with an exact time" in e
                            for e in doc.errors))
        no_tz = _calendar_with(
            _fields(state="scheduled", starts_at="2026-08-01T10:00:00"),
            section=SECTION_SCHEDULED)
        doc = parse_calendar(no_tz)
        self.assertTrue(any("requires an explicit timezone" in e
                            for e in doc.errors))
        # A date without a time-of-day is not an exact time.
        date_only = _calendar_with(
            _fields(state="scheduled", starts_at="2026-08-01",
                    timezone="America/Los_Angeles"),
            section=SECTION_SCHEDULED)
        doc = parse_calendar(date_only)
        self.assertTrue(any("exact time" in e for e in doc.errors))

    def test_unknown_marker_key_fails(self):
        # render_entry only emits known keys, so plant the stray key by hand.
        text = _calendar_with(_fields()).replace(
            "  source: manual\n", "  source: manual\n  surprise: true\n")
        doc = parse_calendar(text)
        self.assertTrue(any("unknown key(s): surprise" in e for e in doc.errors))

    def test_marker_in_personal_notes_section_fails(self):
        text = _calendar_with(_fields(), section="## My notes and personal todos")
        doc = parse_calendar(text)
        self.assertTrue(any("personal-notes section" in e for e in doc.errors))

    def test_missing_section_heading_fails(self):
        text = CALENDAR_TEMPLATE.replace("## Scheduled\n", "")
        doc = parse_calendar(text)
        self.assertTrue(any("missing required section heading '## Scheduled'" in e
                            for e in doc.errors))


class PlanTests(unittest.TestCase):
    def test_unmarked_text_survives_byte_for_byte(self):
        base = _calendar_with(_fields())
        personal = (
            "\n- [ ] my dentist appointment (never touch this)\n"
            "\nSome free-form prose the owner wrote.   \n")
        text = base + personal
        raw = text.encode("utf-8")
        updated = _fields(state="awaiting_schedule")
        plan = plan_calendar_update(raw, {updated["id"]: updated})
        self.assertEqual(plan.errors, ())
        out = plan.output_bytes.decode("utf-8")
        self.assertIn(personal, out)  # every unmarked byte intact
        doc = parse_calendar(out)
        self.assertEqual(doc.entries[updated["id"]].section, SECTION_WAITING)

    def test_move_to_scheduled_requires_time(self):
        base = _calendar_with(_fields())
        updated = _fields(state="scheduled")
        plan = plan_calendar_update(base.encode(), {updated["id"]: updated})
        self.assertTrue(any("requires starts_at" in e for e in plan.errors))
        self.assertEqual(plan.output_bytes, base.encode())

    def test_move_to_scheduled_with_time_lands_in_scheduled_section(self):
        base = _calendar_with(_fields())
        updated = _fields(state="scheduled", starts_at="2026-08-01T10:00:00",
                          timezone="America/Los_Angeles")
        plan = plan_calendar_update(base.encode(), {updated["id"]: updated})
        self.assertEqual(plan.errors, ())
        doc = parse_calendar(plan.output_bytes.decode())
        entry = doc.entries[updated["id"]]
        self.assertEqual(entry.section, SECTION_SCHEDULED)
        self.assertEqual(entry.starts_at, "2026-08-01T10:00:00")

    def test_create_missing_requires_flag(self):
        fields = _fields()
        plan = plan_calendar_update(
            CALENDAR_TEMPLATE.encode(), {fields["id"]: fields})
        self.assertTrue(any("not found in the calendar file" in e
                            for e in plan.errors))
        plan = plan_calendar_update(
            CALENDAR_TEMPLATE.encode(), {fields["id"]: fields},
            create_missing=True)
        self.assertEqual(plan.errors, ())
        doc = parse_calendar(plan.output_bytes.decode())
        self.assertIn(fields["id"], doc.entries)

    def test_plan_fails_closed_on_a_malformed_calendar(self):
        broken = CALENDAR_TEMPLATE.replace(
            "## Action needed\n",
            "## Action needed\n\n- [ ] broken\n  <!-- jobhunt-calendar\n"
            "  id: cal-broken\n", 1)
        fields = _fields()
        plan = plan_calendar_update(
            broken.encode(), {fields["id"]: fields}, create_missing=True)
        self.assertTrue(plan.errors)
        self.assertEqual(plan.output_bytes, broken.encode())

    def test_scheduled_entries_insert_chronologically(self):
        first = _fields(id="cal-a-01", state="scheduled",
                        starts_at="2026-08-10T09:00:00", timezone="UTC")
        text = _calendar_with(first, section=SECTION_SCHEDULED)
        earlier = _fields(id="cal-b-01", application="b-corp-role",
                          state="scheduled", starts_at="2026-08-05T09:00:00",
                          timezone="UTC")
        plan = plan_calendar_update(
            text.encode(), {earlier["id"]: earlier}, create_missing=True)
        self.assertEqual(plan.errors, ())
        out = plan.output_bytes.decode()
        self.assertLess(out.index("cal-b-01"), out.index("cal-a-01"))


class RescheduleTests(unittest.TestCase):
    def test_reschedule_preserves_old_occurrence_as_superseded(self):
        fields = _fields(state="reschedule_pending",
                         starts_at="2026-08-01T10:00:00",
                         timezone="America/Los_Angeles")
        out = record_reschedule(fields, "2026-08-08T15:00:00",
                                "America/Los_Angeles")
        self.assertEqual(out["state"], "scheduled")
        self.assertEqual(out["starts_at"], "2026-08-08T15:00:00")
        self.assertEqual(out["history"], [{
            "starts_at": "2026-08-01T10:00:00",
            "timezone": "America/Los_Angeles",
            "status": "superseded",
        }])
        # History is append-only: a second reschedule keeps both occurrences.
        again = record_reschedule(out, "2026-08-09T15:00:00",
                                  "America/Los_Angeles")
        self.assertEqual(len(again["history"]), 2)
        self.assertEqual(again["history"][1]["starts_at"], "2026-08-08T15:00:00")

    def test_cancellation_keeps_occurrence_and_never_closes(self):
        fields = _fields(state="scheduled", starts_at="2026-08-01T10:00:00",
                         timezone="UTC")
        out = record_cancellation(fields)
        self.assertEqual(out["state"], "action_required")
        self.assertIsNone(out["starts_at"])
        self.assertEqual(out["history"][-1]["status"], "cancelled")

    def test_rescheduled_entry_roundtrips_through_the_planner(self):
        fields = _fields(state="scheduled", starts_at="2026-08-01T10:00:00",
                         timezone="America/Los_Angeles")
        base = _calendar_with(fields, section=SECTION_SCHEDULED)
        updated = record_reschedule(fields, "2026-08-08T15:00:00",
                                    "America/Los_Angeles")
        plan = plan_calendar_update(base.encode(), {fields["id"]: updated})
        self.assertEqual(plan.errors, ())
        doc = parse_calendar(plan.output_bytes.decode())
        entry = doc.entries[fields["id"]]
        self.assertEqual(entry.starts_at, "2026-08-08T15:00:00")
        self.assertEqual(entry.history, ({
            "starts_at": "2026-08-01T10:00:00",
            "timezone": "America/Los_Angeles",
            "status": "superseded",
        },))


class IdTests(unittest.TestCase):
    def test_generate_entry_id_is_stable_and_collision_free(self):
        slug = "example-corp-senior-software-engineer-20260416"
        first = generate_entry_id([], slug)
        self.assertEqual(first, "cal-example-corp-senior-software-engineer-01")
        second = generate_entry_id([first], slug)
        self.assertEqual(second, "cal-example-corp-senior-software-engineer-02")


if __name__ == "__main__":
    unittest.main()
