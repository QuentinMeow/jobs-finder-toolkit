"""Tests for YAML-backed behavioral answer validation and rendering."""

from __future__ import annotations

import copy
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

import yaml


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from answer_bank import (  # noqa: E402
    UnroutableOutput,
    load_and_validate,
    output_targets_for,
    render_markdown,
    run,
)


def _files_under(root: Path) -> set[Path]:
    """Every file in a fixture tree — used to prove a run wrote nothing else."""
    return {path for path in root.rglob("*") if path.is_file()}


def _valid_answer(project_title: str = "Registry capacity recovery") -> dict:
    return {
        "project_title": project_title,
        "source_stories": ["../../story-bank/example-project.md"],
        "quick_answer": {
            "situation": (
                "A shared engineering service was nearing a known capacity limit because routine "
                "cleanup removed references without reclaiming the underlying storage. Ownership "
                "had also moved between teams, so the current operating procedure was unclear."
            ),
            "task": (
                "As the on-call engineer, I took ownership of restoring a safe capacity margin "
                "while keeping the maintenance from interrupting the next workday."
            ),
            "action": (
                "I first traced the live configuration and source code rather than trusting the "
                "stale runbook, which showed that offline cleanup was the only effective option. "
                "I then aligned the receiving team on a weekend window, communication plan, and "
                "rollback signals. Before deleting anything, I tested normal writes, enabled "
                "read-only mode, verified the expected rejection, and reviewed a dry run. Once "
                "the scope looked safe, I monitored the real cleanup and restored writes through "
                "the normal deployment path."
            ),
            "result": (
                "As a result, the operation reclaimed substantial storage, moved the service away "
                "from its failure threshold, and finished before Monday without reported weekday "
                "disruption. I also documented the verified commands and transferred a repeatable "
                "runbook to the long-term owner."
            ),
        },
        "combined_answer": {
            "situation": (
                "A shared engineering service was close to a historical capacity limit because "
                "its scheduled cleanup removed references but left the underlying blobs. Since "
                "ownership had recently moved, the only available runbook was stale and no current "
                "owner had completed the operation."
            ),
            "task": (
                "As the on-call engineer, I took ownership of creating and executing a safe plan "
                "that restored capacity, protected active artifacts, and returned the service to "
                "normal before the next workday."
            ),
            "action": (
                "I reconstructed the procedure from current source, deployment settings, and live "
                "behavior rather than assuming the old commands were still safe. That investigation "
                "confirmed that the fleet had to enter read-only mode before one host could clean "
                "the shared backend. I aligned the receiving team on a weekend window, user "
                "communication, success signals, and rollback steps. Before the change, I verified "
                "a normal write; after enabling read-only mode, I confirmed the expected rejection. "
                "I preserved recent artifacts, reviewed a dry run, and then monitored the real "
                "cleanup, service health, and user reports. Once the completion marker appeared, "
                "I restored writes through the normal deployment path and repeated the write test."
            ),
            "result": (
                "As a result, the cleanup reclaimed a large capacity margin and the maintenance "
                "finished before Monday without reported weekday disruption. The receiving team "
                "also got a tested runbook with validation, monitoring, failure, and rollback "
                "steps, so the result did not depend on my historical context."
            ),
        },
        "technical_deep_dive_short": {
            "bridge": "If useful, I can explain the controls I used around the maintenance window.",
            "situation": (
                "The cleanup temporarily blocked writes while it operated on a shared storage backend."
            ),
            "task": (
                "I needed to distinguish a safe transition from a partial deployment before deletion began."
            ),
            "action": (
                "I compared write behavior before and after the configuration change, reviewed the "
                "dry-run deletion scope, and watched service metrics throughout the operation. I "
                "also kept the normal deployment rollback ready until the final write test passed."
            ),
            "result": (
                "Those controls prevented an unsafe partial cleanup and restored normal service "
                "within the planned window."
            ),
        },
        "technical_deep_dive_long": {
            "bridge": "If time allows, I can walk through the deeper technical and ownership decisions.",
            "situation": (
                "The documented binary location, deployment settings, and ownership information no "
                "longer matched production, while storage reporting also arrived with a delay."
            ),
            "task": (
                "I had to rebuild a trustworthy procedure from current evidence and define "
                "completion signals that did not rely on one delayed metric."
            ),
            "action": (
                "I located the current repository, rebuilt the maintenance binary, and paired it "
                "with the live service configuration. Because every host used the same backend, I "
                "proved that one execution host was sufficient rather than starting competing jobs. "
                "I defined write checks, deployment state, process output, service health, and later "
                "storage measurements as separate signals. I preserved recent artifacts and reviewed "
                "the dry-run scope before authorizing deletion. After the completion marker appeared, "
                "I restored the fleet configuration, repeated the write test, and waited for the "
                "delayed capacity metric before closing the work."
            ),
            "result": (
                "That evidence chain verified both service recovery and meaningful storage reduction, "
                "while the resulting runbook gave future owners a repeatable process."
            ),
        },
        "story_references": {
            "timeline": [
                {
                    "tag": "Context: capacity risk",
                    "text": (
                        "The service approached a historical limit because normal cleanup did not "
                        "remove stored blobs, while an ownership transition left the operating path unclear."
                    ),
                },
                {
                    "tag": "Ownership: on-call response",
                    "text": (
                        "As the on-call engineer, I took ownership of the risk and first reconstructed "
                        "the current procedure from code, configuration, and production behavior."
                    ),
                },
                {
                    "tag": "Execution: staged maintenance",
                    "text": (
                        "After aligning a weekend plan, I verified writes, enabled read-only mode, "
                        "reviewed a dry run, and then monitored the real cleanup."
                    ),
                },
                {
                    "tag": "Impact: capacity and handoff",
                    "text": (
                        "As a result, the service regained capacity before Monday, and the receiving "
                        "team inherited a tested runbook rather than another one-off operation."
                    ),
                },
            ],
            "focus_areas": [
                {
                    "tag": "Technical: reclaiming real storage",
                    "problem": "Routine cleanup left the backing blobs in place.",
                    "action": "I identified and safely ran the offline cleanup against the shared backend.",
                    "impact": "The operation reclaimed storage and restored a safe capacity margin.",
                },
                {
                    "tag": "Risk: write restriction",
                    "problem": "The cleanup required a temporary fleet-wide write restriction.",
                    "action": "I used before-and-after write tests, a dry run, monitoring, and rollback signals.",
                    "impact": "Those controls prevented unexpected weekday disruption.",
                },
                {
                    "tag": "Ownership: durable handoff",
                    "problem": "The current owner lacked a verified operating procedure.",
                    "action": "I documented every tested command, signal, failure mode, and recovery step.",
                    "impact": "The handoff enabled the receiving team to repeat the process without me.",
                },
            ],
        },
    }


def _valid_data() -> dict:
    second_answer = copy.deepcopy(_valid_answer())
    second_answer["project_title"] = "Migration test framework"
    second_answer["source_stories"] = ["../../story-bank/example-project-2.md"]
    return {
        "schema_version": 3,
        "slug": "example-deliver-results",
        "primary_question": "Tell me about a time you delivered a result despite major obstacles.",
        "similar_questions": [
            "Tell me about a time you delivered despite obstacles.",
            "Tell me about a time you owned a stalled problem.",
        ],
        "outputs": [
            {
                "slug": "_general_03_example-deliver-results",
                "title": "Tell me about a time you delivered a result despite major obstacles",
            },
            {
                "slug": "amazon-deliver-results",
                "title": "Amazon — Deliver Results",
            },
        ],
        "settings": {
            "speaking_rate_wpm": 120,
            "quick_answer_target_seconds": 90,
            "quick_answer_min_seconds": 75,
            "quick_answer_max_seconds": 130,
            "combined_answer_max_seconds": 240,
            "long_path_max_seconds": 300,
            "max_sentence_words": 35,
            "banned_phrases": [],
        },
        "answers": [_valid_answer(), second_answer],
    }


class AnswerBankTests(unittest.TestCase):
    def _write_fixture(self, root: Path, data: dict | None = None) -> Path:
        story_dir = root / "behavioral" / "story-bank"
        source_dir = root / "behavioral" / "question-bank" / "sources"
        story_dir.mkdir(parents=True)
        source_dir.mkdir(parents=True)
        (story_dir / "example-project.md").write_text("# Example project\n", encoding="utf-8")
        (story_dir / "example-project-2.md").write_text(
            "# Second example project\n", encoding="utf-8"
        )
        (story_dir / "example-project-3.md").write_text(
            "# Third example project\n", encoding="utf-8"
        )
        source = source_dir / "example-deliver-results.yaml"
        source.write_text(
            yaml.safe_dump(data or _valid_data(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return source

    def _write_companies(self, root: Path, *keys: str) -> Path:
        """A company tree with one folder per key; returns the tree root."""
        companies = root / "companies"
        companies.mkdir(parents=True, exist_ok=True)
        for key in keys:
            (companies / key).mkdir()
        return companies

    def test_valid_source_renders_and_checks_deterministically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            companies = self._write_companies(root, "amazon")
            source = self._write_fixture(root)
            result = load_and_validate(source)
            self.assertEqual(result.errors, [])
            self.assertIsNotNone(result.data)
            rendered = render_markdown(result.data, source)
            self.assertIn("# Tell me about a time you delivered", rendered)
            self.assertIn("## Most natural question", rendered)
            self.assertIn("<summary><strong>Answer 1</strong> — Registry capacity recovery", rendered)
            self.assertNotIn("<details open>", rendered)
            combined_pos = rendered.index("<em>Self-contained · quick + short deep dive</em>")
            quick_pos = rendered.index("<em>Quick answer</em>", combined_pos)
            self.assertLess(combined_pos, quick_pos)
            self.assertIn("<em>Technical deep dives</em>", rendered)
            self.assertIn("(Situation) A shared engineering service", rendered)
            self.assertNotIn("### Situation", rendered)
            self.assertIn("<em>Reference</em> · timeline", rendered)
            self.assertIn("<em>Reference</em> · isolated problem / action / impact", rendered)
            self.assertEqual(run("render", source, companies), 0)
            self.assertEqual(run("check", source, companies), 0)
            answer_bank = source.parent.parent
            self.assertTrue(
                (answer_bank / "_general_03_example-deliver-results.md").is_file()
            )
            self.assertFalse((answer_bank / "amazon-deliver-results.md").exists())
            company_output = (
                companies / "amazon" / "derived" / "amazon-deliver-results.md"
            ).read_text(encoding="utf-8")
            self.assertIn("# Amazon — Deliver Results", company_output)

    def test_selected_answer_index_is_visible_before_question_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _valid_data()
            data["answers"][0]["project_title"] = "(Select) Registry capacity recovery"
            data["answers"][0]["follow_up_questions"] = [
                "How did you validate the rollback path?",
                "What trade-off did you make to ship on time?",
                "What would you change if you repeated the project?",
            ]
            source = self._write_fixture(Path(tmp), data)
            result = load_and_validate(source)
            self.assertEqual(result.errors, [])
            rendered = render_markdown(result.data, source)
            selected_line = "- **(Select) Answer 1 — Registry capacity recovery**"
            rendered_title = result.data["outputs"][0]["title"]
            self.assertIn("## Selected answer\n\n" + selected_line, rendered)
            self.assertIn(
                f"# {rendered_title}\n\n## Selected answer\n\n" + selected_line,
                rendered,
            )
            self.assertLess(rendered.index(selected_line), rendered.index("## Most natural question"))
            self.assertIn(
                "<summary><strong>Answer 1</strong> — (Select) Registry capacity recovery",
                rendered,
            )
            self.assertIn("<em>Reference</em> · likely follow-up questions", rendered)
            self.assertIn("- How did you validate the rollback path?", rendered)
            self.assertIn("- (Context: capacity risk)", rendered)

            data["answers"][1]["project_title"] = "(Select) Migration test framework"
            source.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            result = load_and_validate(source)
            self.assertEqual(result.errors, [])
            rendered = render_markdown(result.data, source)
            rendered_title = result.data["outputs"][0]["title"]
            self.assertIn(f"# {rendered_title}\n\n## Selected answers", rendered)
            self.assertIn("- **(Select) Answer 2 — Migration test framework**", rendered)

    def test_follow_up_questions_require_three_question_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _valid_data()
            data["answers"][0]["follow_up_questions"] = ["What changed?", "Why now?"]
            source = self._write_fixture(Path(tmp), data)
            result = load_and_validate(source)
            self.assertTrue(
                any("follow_up_questions must contain at least three" in error for error in result.errors)
            )

    def test_human_authorized_disclosure_validates_and_renders_privately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            data = _valid_data()
            data["answers"][0]["fabrication_disclosures"] = [
                {
                    "claim": "I designed the complete architecture.",
                    "status": "source-conflict",
                    "authorization": "direct-human-request",
                    "authorized_on": "2026-08-04",
                    "evidence": "The source describes a shared design.",
                    "used_in": ["quick_answer.action", "combined_answer.action"],
                }
            ]
            source = self._write_fixture(root, data)
            result = load_and_validate(source)
            self.assertEqual(result.errors, [])
            rendered = render_markdown(result.data, source)
            self.assertIn("<em>Private claim disclosures</em> · not spoken", rendered)
            self.assertIn("**source-conflict** — I designed the complete architecture.", rendered)
            self.assertIn("Do not say this section aloud", rendered)

    def test_disclosure_rejects_non_human_authorization_and_bad_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            data = _valid_data()
            data["answers"][0]["fabrication_disclosures"] = [
                {
                    "claim": "I saved $8 million each year.",
                    "status": "estimated",
                    "authorization": "agent-inferred",
                    "authorized_on": "not-a-date",
                    "evidence": "No supporting measurement exists.",
                    "used_in": ["quick_answer.result"],
                }
            ]
            result = load_and_validate(self._write_fixture(root, data))
            errors = "\n".join(result.errors)
            self.assertIn("status must be one of", errors)
            self.assertIn("authorization must be direct-human-request", errors)
            self.assertIn("authorized_on must be an ISO date", errors)


    def test_output_targets_split_general_and_company_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            companies = self._write_companies(root, "amazon")
            source = self._write_fixture(root)
            data = load_and_validate(source).data
            targets = [path for path, _ in output_targets_for(source, data, companies)]
            self.assertEqual(
                targets,
                [
                    source.parent.parent / "_general_03_example-deliver-results.md",
                    companies / "amazon" / "derived" / "amazon-deliver-results.md",
                ],
            )

    def test_render_writes_only_its_resolved_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            companies = self._write_companies(root, "amazon")
            source = self._write_fixture(root)
            before = _files_under(root)
            self.assertEqual(run("render", source, companies), 0)
            self.assertEqual(
                _files_under(root) - before,
                {
                    source.parent.parent / "_general_03_example-deliver-results.md",
                    companies / "amazon" / "derived" / "amazon-deliver-results.md",
                },
            )

    def test_unknown_company_prefix_fails_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            companies = self._write_companies(root)  # tree exists, no company folders
            source = self._write_fixture(root)
            before = _files_under(root)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = run("render", source, companies)
            self.assertEqual(exit_code, 1)
            self.assertIn("there is no 'amazon' folder in", stderr.getvalue())
            # All or nothing: the _general_ alias of the same source is not written either.
            self.assertEqual(_files_under(root), before)
            self.assertFalse((companies / "amazon").exists())

    def test_missing_company_tree_fails_without_creating_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            companies = root / "companies"  # never created (a config-less checkout)
            source = self._write_fixture(root)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = run("render", source, companies)
            self.assertEqual(exit_code, 1)
            self.assertIn("the company tree does not exist", stderr.getvalue())
            self.assertFalse(companies.exists())

    def test_company_folder_must_match_the_key_case_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            companies = self._write_companies(root, "Amazon")
            source = self._write_fixture(root)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = run("render", source, companies)
            self.assertEqual(exit_code, 1)
            self.assertIn("there is no 'amazon' folder in", stderr.getvalue())
            self.assertFalse((companies / "Amazon" / "derived").exists())

    def test_alias_without_a_hyphen_is_unroutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            companies = self._write_companies(root, "amazon")
            data = _valid_data()
            data["outputs"][1]["slug"] = "amazon"
            source = self._write_fixture(root, data)
            # The schema rejects it first; the router refuses it independently.
            result = load_and_validate(source)
            self.assertTrue(any("outputs[1].slug" in error for error in result.errors))
            with self.assertRaises(UnroutableOutput):
                output_targets_for(source, data, companies)

    def test_more_than_two_project_answers_are_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _valid_data()
            second = copy.deepcopy(data["answers"][0])
            second["project_title"] = "Project registry automation"
            second["source_stories"] = ["../../story-bank/example-project-3.md"]
            data["answers"].append(second)
            source = self._write_fixture(Path(tmp), data)
            result = load_and_validate(source)
            self.assertEqual(result.errors, [])
            rendered = render_markdown(result.data, source)
            self.assertIn("<summary><strong>Answer 3</strong> — Project registry automation", rendered)

    def test_at_least_two_project_answers_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _valid_data()
            data["answers"] = data["answers"][:1]
            source = self._write_fixture(Path(tmp), data)
            result = load_and_validate(source)
            self.assertTrue(any("at least two" in error for error in result.errors))

    def test_project_answers_must_use_distinct_story_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _valid_data()
            data["answers"][1]["source_stories"] = data["answers"][0]["source_stories"]
            source = self._write_fixture(Path(tmp), data)
            result = load_and_validate(source)
            self.assertTrue(any("distinct source_stories" in error for error in result.errors))

    def test_first_output_must_be_general(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _valid_data()
            data["outputs"].reverse()
            source = self._write_fixture(Path(tmp), data)
            result = load_and_validate(source)
            self.assertTrue(any("outputs[0].slug" in error for error in result.errors))

    def test_directory_run_rejects_cross_tree_output_alias_collisions(self):
        # Two sources in the question bank, distinct _general_ aliases, but the
        # same company alias: the collision only exists in the OTHER tree, so it
        # is visible only if the owner check compares resolved targets.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            companies = self._write_companies(root, "amazon")
            source = self._write_fixture(root)
            second_data = _valid_data()
            second_data["slug"] = "second-results"
            second_data["outputs"][0]["slug"] = "_general_03_second-results"
            second_source = source.with_name("second-results.yaml")
            second_source.write_text(
                yaml.safe_dump(second_data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            before = _files_under(root)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = run("render", source.parent, companies)
            self.assertEqual(exit_code, 1)
            report = stderr.getvalue()
            self.assertIn("is also declared by", report)
            self.assertIn(
                str(companies / "amazon" / "derived" / "amazon-deliver-results.md"), report
            )
            # Both colliding sources are skipped, so nothing is rendered at all.
            self.assertEqual(_files_under(root), before)

    def test_quick_answer_enforces_75_to_130_second_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _valid_data()
            data["settings"]["quick_answer_min_seconds"] = 120
            source = self._write_fixture(Path(tmp), data)
            result = load_and_validate(source)
            self.assertTrue(any("quick_answer is" in error for error in result.errors))

    def test_quick_answer_requires_connected_spoken_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _valid_data()
            data["answers"][0]["quick_answer"]["action"] = (
                "I owned the work. I read the code. I made a plan. I ran the cleanup. "
                "I checked the service. I wrote the guide."
            )
            source = self._write_fixture(Path(tmp), data)
            result = load_and_validate(source)
            self.assertTrue(
                any("logical connectors" in error or "too choppy" in error for error in result.errors)
            )

    def test_quick_answer_requires_prominent_impact(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _valid_data()
            data["answers"][0]["quick_answer"]["result"] = "The work ended."
            source = self._write_fixture(Path(tmp), data)
            result = load_and_validate(source)
            self.assertTrue(any(".result" in error and "impact" in error for error in result.errors))

    def test_additive_deep_dive_cannot_repeat_quick_answer_sentence(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _valid_data()
            repeated = data["answers"][0]["quick_answer"]["situation"]
            data["answers"][0]["technical_deep_dive_short"]["situation"] = repeated
            source = self._write_fixture(Path(tmp), data)
            result = load_and_validate(source)
            self.assertTrue(any("repeats a quick-answer sentence" in error for error in result.errors))

    def test_story_reference_focus_area_requires_problem_action_impact(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _valid_data()
            del data["answers"][0]["story_references"]["focus_areas"][0]["impact"]
            source = self._write_fixture(Path(tmp), data)
            result = load_and_validate(source)
            self.assertTrue(any("focus_areas[0].impact" in error for error in result.errors))

    def test_general_prefix_rejects_yaml_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _valid_data()
            data["slug"] = "general-example"
            source = self._write_fixture(Path(tmp), data)
            renamed = source.with_name("general-example.yaml")
            source.rename(renamed)
            result = load_and_validate(renamed)
            self.assertTrue(any("Markdown-only" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
