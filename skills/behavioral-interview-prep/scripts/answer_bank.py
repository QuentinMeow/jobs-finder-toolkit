#!/usr/bin/env python3
"""Validate shared behavioral-answer sources and render deterministic aliases.

One YAML source under ``question-bank/sources/`` renders several Markdown
aliases, and they do NOT all land in the same tree:

* a ``_general_*`` alias is the question bank's own file and renders beside the
  source's parent, as it always has;
* every other alias is ``<company-key>-<name>`` and renders into that company's
  folder — ``config.companies_root()/<key>/derived/<slug>.md`` — because
  company-specific interview material is filed by company
  (``memory/decisions/interview-material-moves-by-company-only.md``).

The company folder must already exist. Nothing here invents one: the company
tree is owner data, and a made-up ``<key>/`` folder would either litter it or
hide the answer where the owner never looks.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

# Self-contained skill: this script lives in the behavioral-interview-prep
# skill's scripts/ folder alongside its _vendor/ copies of the pure toolkit
# modules. Put both the script folder and its _vendor/ on sys.path and import
# ONLY from those vendored copies — never from the repo root.
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "_vendor"):
    if str(_p) not in sys.path and _p.is_dir():
        sys.path.insert(0, str(_p))


SCHEMA_VERSION = 3
STAR_PARTS = ("situation", "task", "action", "result")
ANSWER_MODULES = (
    "quick_answer",
    "combined_answer",
    "technical_deep_dive_short",
    "technical_deep_dive_long",
)
ADDITIVE_MODULES = ("technical_deep_dive_short", "technical_deep_dive_long")
DEFAULT_BANNED_PHRASES = (
    "delve into",
    "game-changing",
    "in order to",
    "multifaceted",
    "paradigm shift",
    "pivotal",
    "spearheaded",
    "synergy",
    "transformative",
    "utilize",
)
PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD|FIXME|PLACEHOLDER)\b|\[[^\]]+\]", re.IGNORECASE)
# Output routing (see the module docstring): an alias with this prefix belongs to
# the question bank; anything else is <company-key>-<name> and belongs to that
# company's own generated-answers folder.
GENERAL_SLUG_PREFIX = "_general_"
COMPANY_DERIVED_DIRNAME = "derived"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
OUTPUT_SLUG_RE = re.compile(
    r"^(?:_general_03_[a-z0-9]+(?:-[a-z0-9]+)*|[a-z]+-[a-z0-9]+(?:-[a-z0-9]+)*)$"
)
WORD_RE = re.compile(r"\b[\w]+(?:[-'][\w]+)*\b")
SENTENCE_RE = re.compile(r"[^.!?]+[.!?][\"')\]]?(?=\s|$)")
CONNECTION_RE = re.compile(
    r"\b(?:after|although|as a result|because|before|but|once|rather than|since|so|"
    r"that meant|therefore|then|while|which)\b",
    re.IGNORECASE,
)
OWNERSHIP_RE = re.compile(
    r"\bI\b.{0,80}\b(?:drove|had to|led|needed to|owned|took ownership|was responsible)\b"
    r"|\b(?:drove|led|owned|took ownership)\b.{0,80}\bI\b",
    re.IGNORECASE,
)
IMPACT_RE = re.compile(
    r"\d|\b(?:accelerated|avoided|completed|cut|decreased|delivered|eliminated|enabled|"
    r"improved|increased|prevented|protected|reclaimed|reduced|restored|saved|unblocked)\b",
    re.IGNORECASE,
)
DURABLE_RE = re.compile(
    r"\b(?:alert|automated|documentation|documented|handoff|mechanism|monitoring|owner|"
    r"process|repeatable|runbook|standard|transferred)\b",
    re.IGNORECASE,
)


@dataclass
class ValidationResult:
    source: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


def _sentences(text: str) -> list[str]:
    return [match.group(0).strip() for match in SENTENCE_RE.finditer(text.strip())]


def sentence_count(text: str) -> int:
    return len(_sentences(text))


def _sentence_key(text: str) -> str:
    return " ".join(token.lower() for token in WORD_RE.findall(text))


def _content_tokens(text: str) -> set[str]:
    stop_words = {
        "a", "an", "and", "as", "at", "but", "by", "for", "from", "had", "in", "into",
        "is", "it", "my", "of", "on", "or", "our", "so", "that", "the", "their", "then",
        "this", "to", "was", "we", "were", "with",
    }
    return {
        token.lower()
        for token in WORD_RE.findall(text)
        if token.lower() not in stop_words and len(token) > 2
    }


def _module_paragraphs(module: dict[str, Any]) -> list[str]:
    return [
        module[part].strip()
        for part in STAR_PARTS
        if isinstance(module.get(part), str) and module[part].strip()
    ]


def _module_sentences(module: dict[str, Any]) -> list[str]:
    return [
        sentence
        for paragraph in _module_paragraphs(module)
        for sentence in _sentences(paragraph)
    ]


def _module_word_count(module: dict[str, Any]) -> int:
    return sum(count_words(paragraph) for paragraph in _module_paragraphs(module))


def _part_word_counts(module: dict[str, Any]) -> dict[str, int]:
    return {
        part: count_words(module.get(part, "")) if isinstance(module.get(part), str) else 0
        for part in STAR_PARTS
    }


def _validate_text(
    text: Any,
    where: str,
    result: ValidationResult,
    *,
    max_sentence_words: int,
    banned_phrases: Iterable[str],
) -> None:
    if not isinstance(text, str) or not text.strip():
        result.errors.append(f"{where} must be a non-empty string")
        return
    stripped = text.strip()
    if "\n" in stripped:
        result.errors.append(f"{where} must be one paragraph without line breaks")
    sentences = _sentences(stripped)
    if not sentences:
        result.errors.append(f"{where} must contain at least one complete sentence")
    for index, sentence in enumerate(sentences):
        words = count_words(sentence)
        if words > max_sentence_words:
            result.errors.append(
                f"{where} sentence {index + 1} has {words} words; maximum is {max_sentence_words}"
            )
    if PLACEHOLDER_RE.search(stripped):
        result.errors.append(f"{where} contains placeholder text")
    lowered = stripped.lower()
    for phrase in banned_phrases:
        if phrase.lower() in lowered:
            result.errors.append(f"{where} contains banned filler phrase {phrase!r}")


def _validate_spoken_flow(name: str, module: dict[str, Any], where: str, result: ValidationResult) -> None:
    paragraphs = _module_paragraphs(module)
    text = " ".join(paragraphs)
    sentences = _module_sentences(module)
    required_connections = 3 if name == "quick_answer" else 4
    if len(CONNECTION_RE.findall(text)) < required_connections:
        result.errors.append(
            f"{where} needs at least {required_connections} logical connectors so it reads as "
            "one connected spoken story"
        )
    if len(sentences) >= 6:
        short_sentences = sum(count_words(sentence) < 8 for sentence in sentences)
        if short_sentences > len(sentences) / 2:
            result.errors.append(
                f"{where} is too choppy; more than half of its sentences have fewer than 8 words"
            )

    counts = _part_word_counts(module)
    total = sum(counts.values())
    if total and counts["result"] / total < 0.15:
        result.errors.append(
            f"{where}.result has {counts['result']} of {total} words; impact must be at least 15%"
        )
    ownership_text = f"{module.get('task', '')} {module.get('action', '')}"
    if not OWNERSHIP_RE.search(ownership_text):
        result.errors.append(f"{where} must state the candidate's personal ownership explicitly")
    result_text = str(module.get("result", ""))
    if not IMPACT_RE.search(result_text):
        result.errors.append(f"{where}.result must state quantified or directional impact")


def _validate_module(
    name: str,
    module: Any,
    where: str,
    result: ValidationResult,
    *,
    max_sentence_words: int,
    banned_phrases: Iterable[str],
) -> None:
    if not isinstance(module, dict):
        result.errors.append(f"{where} must be a mapping")
        return

    bridge = module.get("bridge")
    if name in ADDITIVE_MODULES:
        _validate_text(
            bridge,
            f"{where}.bridge",
            result,
            max_sentence_words=max_sentence_words,
            banned_phrases=banned_phrases,
        )
    elif bridge:
        result.errors.append(f"{where} must not define a bridge")

    for part in STAR_PARTS:
        _validate_text(
            module.get(part),
            f"{where}.{part}",
            result,
            max_sentence_words=max_sentence_words,
            banned_phrases=banned_phrases,
        )

    if all(isinstance(module.get(part), str) and module[part].strip() for part in STAR_PARTS):
        counts = _part_word_counts(module)
        largest_non_action = max(counts[part] for part in STAR_PARTS if part != "action")
        if counts["action"] <= largest_non_action:
            result.errors.append(
                f"{where}.action must be the largest STAR paragraph; word counts are {counts}"
            )
        if name in ("quick_answer", "combined_answer"):
            _validate_spoken_flow(name, module, where, result)


def _validate_additive_overlap(answer: dict[str, Any], where: str, result: ValidationResult) -> None:
    core = answer.get("quick_answer")
    if not isinstance(core, dict):
        return
    core_sentences = _module_sentences(core)
    core_keys = {_sentence_key(sentence): sentence for sentence in core_sentences}

    for module_name in ADDITIVE_MODULES:
        module = answer.get(module_name)
        if not isinstance(module, dict):
            continue
        for sentence in _module_sentences(module):
            key = _sentence_key(sentence)
            if key in core_keys:
                result.errors.append(
                    f"{where}.{module_name} repeats a quick-answer sentence: {sentence!r}"
                )
                continue
            tokens = _content_tokens(sentence)
            if len(tokens) < 4:
                continue
            for core_sentence in core_sentences:
                core_tokens = _content_tokens(core_sentence)
                union = tokens | core_tokens
                if union and len(tokens & core_tokens) / len(union) >= 0.72:
                    result.warnings.append(
                        f"{where}.{module_name} may overlap the quick answer: {sentence!r}"
                    )
                    break


def _validate_tag(tag: Any, where: str, result: ValidationResult) -> None:
    if not isinstance(tag, str) or not tag.strip():
        result.errors.append(f"{where} must be a non-empty string")
        return
    stripped = tag.strip()
    if len(stripped) > 80:
        result.errors.append(f"{where} must be at most 80 characters")
    if any(character in stripped for character in "()\n"):
        result.errors.append(f"{where} must not contain parentheses or line breaks")


def _validate_story_references(
    references: Any,
    where: str,
    result: ValidationResult,
    *,
    max_sentence_words: int,
    banned_phrases: Iterable[str],
) -> None:
    if not isinstance(references, dict):
        result.errors.append(f"{where} must be a mapping")
        return
    extra = [key for key in references if key not in ("timeline", "focus_areas")]
    if extra:
        result.errors.append(f"{where} has unknown styles: {', '.join(extra)}")

    timeline = references.get("timeline")
    if not isinstance(timeline, list) or len(timeline) < 4:
        result.errors.append(f"{where}.timeline must contain at least four tagged paragraphs")
    else:
        timeline_text: list[str] = []
        for index, item in enumerate(timeline):
            item_where = f"{where}.timeline[{index}]"
            if not isinstance(item, dict):
                result.errors.append(f"{item_where} must be a mapping")
                continue
            _validate_tag(item.get("tag"), f"{item_where}.tag", result)
            _validate_text(
                item.get("text"),
                f"{item_where}.text",
                result,
                max_sentence_words=max_sentence_words,
                banned_phrases=banned_phrases,
            )
            if isinstance(item.get("text"), str):
                timeline_text.append(item["text"])
        if len(CONNECTION_RE.findall(" ".join(timeline_text))) < 4:
            result.errors.append(
                f"{where}.timeline needs explicit cause, sequence, or contrast connections"
            )

    focus_areas = references.get("focus_areas")
    if not isinstance(focus_areas, list) or len(focus_areas) < 3:
        result.errors.append(
            f"{where}.focus_areas must contain at least three problem-action-impact paragraphs"
        )
    else:
        for index, item in enumerate(focus_areas):
            item_where = f"{where}.focus_areas[{index}]"
            if not isinstance(item, dict):
                result.errors.append(f"{item_where} must be a mapping")
                continue
            _validate_tag(item.get("tag"), f"{item_where}.tag", result)
            for field_name in ("problem", "action", "impact"):
                _validate_text(
                    item.get(field_name),
                    f"{item_where}.{field_name}",
                    result,
                    max_sentence_words=max_sentence_words,
                    banned_phrases=banned_phrases,
                )
            if isinstance(item.get("action"), str) and not re.search(r"\bI\b", item["action"]):
                result.errors.append(f"{item_where}.action must use an explicit 'I' statement")
            if isinstance(item.get("impact"), str) and not IMPACT_RE.search(item["impact"]):
                result.errors.append(
                    f"{item_where}.impact must state quantified or directional impact"
                )


def _positive_number(settings: dict[str, Any], key: str, default: float, result: ValidationResult) -> float:
    value = settings.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        result.errors.append(f"settings.{key} must be a positive number")
        return default
    return float(value)


def _validate_answer(
    answer: Any,
    index: int,
    source: Path,
    result: ValidationResult,
    *,
    settings: dict[str, float],
    banned_phrases: Iterable[str],
) -> None:
    where = f"answers[{index}]"
    if not isinstance(answer, dict):
        result.errors.append(f"{where} must be a mapping")
        return

    project_title = answer.get("project_title")
    if not isinstance(project_title, str) or not project_title.strip():
        result.errors.append(f"{where}.project_title must be a non-empty string")

    source_stories = answer.get("source_stories")
    if not isinstance(source_stories, list) or not source_stories:
        result.errors.append(f"{where}.source_stories must contain at least one relative path")
    else:
        for story_index, story in enumerate(source_stories):
            if not isinstance(story, str) or not story.strip():
                result.errors.append(
                    f"{where}.source_stories[{story_index}] must be a non-empty string"
                )
                continue
            story_path = (source.parent / story).resolve()
            if not story_path.is_file():
                result.errors.append(
                    f"{where}.source_stories[{story_index}] does not exist: {story}"
                )

    missing = [name for name in ANSWER_MODULES if name not in answer]
    allowed = {"project_title", "source_stories", "story_references", *ANSWER_MODULES}
    extra = [name for name in answer if name not in allowed]
    if missing:
        result.errors.append(f"{where} is missing modules: {', '.join(missing)}")
    if extra:
        result.errors.append(f"{where} has unknown fields: {', '.join(extra)}")

    max_sentence_words = int(settings["max_sentence_words"])
    for name in ANSWER_MODULES:
        _validate_module(
            name,
            answer.get(name),
            f"{where}.{name}",
            result,
            max_sentence_words=max_sentence_words,
            banned_phrases=banned_phrases,
        )
    _validate_additive_overlap(answer, where, result)
    _validate_story_references(
        answer.get("story_references"),
        f"{where}.story_references",
        result,
        max_sentence_words=max_sentence_words,
        banned_phrases=banned_phrases,
    )

    valid_modules = {
        name: answer[name] for name in ANSWER_MODULES if isinstance(answer.get(name), dict)
    }
    if len(valid_modules) != len(ANSWER_MODULES):
        return
    words = {name: _module_word_count(module) for name, module in valid_modules.items()}
    rate = settings["speaking_rate_wpm"]
    quick_seconds = words["quick_answer"] / rate * 60
    if not settings["quick_answer_min_seconds"] <= quick_seconds <= settings["quick_answer_max_seconds"]:
        result.errors.append(
            f"{where}.quick_answer is {quick_seconds:.0f} seconds at {rate:g} WPM; expected "
            f"{settings['quick_answer_min_seconds']:g}-{settings['quick_answer_max_seconds']:g}"
        )
    elif abs(quick_seconds - settings["quick_answer_target_seconds"]) > 15:
        result.warnings.append(
            f"{where}.quick_answer is {quick_seconds:.0f} seconds; valid, but more than 15 "
            f"seconds from the {settings['quick_answer_target_seconds']:g}-second target"
        )
    combined_seconds = words["combined_answer"] / rate * 60
    if combined_seconds > settings["combined_answer_max_seconds"]:
        result.errors.append(
            f"{where}.combined_answer is {combined_seconds:.0f} seconds; maximum is "
            f"{settings['combined_answer_max_seconds']:g}"
        )
    if words["combined_answer"] <= words["quick_answer"]:
        result.errors.append(
            f"{where}.combined_answer must be longer than the quick answer"
        )
    long_path_seconds = (
        words["quick_answer"] + words["technical_deep_dive_long"]
    ) / rate * 60
    if long_path_seconds > settings["long_path_max_seconds"]:
        result.errors.append(
            f"{where} quick answer + long expansion is {long_path_seconds:.0f} seconds; "
            f"maximum is {settings['long_path_max_seconds']:g}"
        )
    if words["technical_deep_dive_long"] <= words["technical_deep_dive_short"]:
        result.errors.append(
            f"{where}.technical_deep_dive_long must be longer than the short expansion"
        )

    all_result_text = " ".join(
        str(answer.get(name, {}).get("result", ""))
        for name in ANSWER_MODULES
        if isinstance(answer.get(name), dict)
    )
    if not DURABLE_RE.search(all_result_text):
        result.warnings.append(
            f"{where} has no obvious durable mechanism, process, or ownership handoff"
        )


def load_and_validate(source: Path) -> ValidationResult:
    source = source.resolve()
    result = ValidationResult(source=source)
    try:
        loaded = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        result.errors.append(f"could not load YAML: {exc}")
        return result
    if not isinstance(loaded, dict):
        result.errors.append("YAML root must be a mapping")
        return result
    result.data = loaded

    if loaded.get("schema_version") != SCHEMA_VERSION:
        result.errors.append(f"schema_version must be {SCHEMA_VERSION}")

    slug = loaded.get("slug")
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        result.errors.append("slug must contain lowercase letters, numbers, and single hyphens")
    elif slug != source.stem:
        result.errors.append(f"slug {slug!r} must match source filename stem {source.stem!r}")
    if isinstance(slug, str) and slug.startswith("general-"):
        result.errors.append("general-* answers are Markdown-only and must not have YAML sources")

    primary_question = loaded.get("primary_question")
    if not isinstance(primary_question, str) or not primary_question.strip():
        result.errors.append("primary_question must be a non-empty string")

    variants = loaded.get("similar_questions")
    if not isinstance(variants, list) or len(variants) < 2:
        result.errors.append("similar_questions must contain at least two variants")
    elif not all(isinstance(item, str) and item.strip() for item in variants):
        result.errors.append("every similar_questions entry must be a non-empty string")

    outputs = loaded.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        result.errors.append("outputs must be a non-empty list")
    else:
        output_slugs: list[str] = []
        for index, output in enumerate(outputs):
            where = f"outputs[{index}]"
            if not isinstance(output, dict):
                result.errors.append(f"{where} must be a mapping")
                continue
            extra = [key for key in output if key not in ("slug", "title")]
            if extra:
                result.errors.append(f"{where} has unknown fields: {', '.join(extra)}")
            output_slug = output.get("slug")
            if not isinstance(output_slug, str) or not OUTPUT_SLUG_RE.fullmatch(output_slug):
                result.errors.append(
                    f"{where}.slug must be '_general_03_<source-stem>' for outputs[0] or a "
                    "company-prefixed alias such as amazon-deliver-results"
                )
            else:
                output_slugs.append(output_slug)
                if index == 0 and output_slug != f"_general_03_{slug}":
                    result.errors.append(
                        f"outputs[0].slug must be '_general_03_{slug}' to match the source family"
                    )
                if index > 0 and output_slug.startswith(GENERAL_SLUG_PREFIX):
                    result.errors.append(
                        "only outputs[0].slug may use a _general_03_ prefix"
                    )
            output_title = output.get("title")
            if not isinstance(output_title, str) or not output_title.strip():
                result.errors.append(f"{where}.title must be a non-empty string")
            elif (
                index == 0
                and isinstance(primary_question, str)
                and output_title.strip().rstrip(".") != primary_question.strip().rstrip(".")
            ):
                result.errors.append(
                    "outputs[0].title must match primary_question (final punctuation may differ)"
                )
        if len(output_slugs) != len(set(output_slugs)):
            result.errors.append("outputs must use unique slug values")

    settings_raw = loaded.get("settings", {})
    if not isinstance(settings_raw, dict):
        result.errors.append("settings must be a mapping")
        settings_raw = {}
    settings = {
        "speaking_rate_wpm": _positive_number(
            settings_raw, "speaking_rate_wpm", 120, result
        ),
        "quick_answer_target_seconds": _positive_number(
            settings_raw, "quick_answer_target_seconds", 90, result
        ),
        "quick_answer_min_seconds": _positive_number(
            settings_raw, "quick_answer_min_seconds", 75, result
        ),
        "quick_answer_max_seconds": _positive_number(
            settings_raw, "quick_answer_max_seconds", 130, result
        ),
        "combined_answer_max_seconds": _positive_number(
            settings_raw, "combined_answer_max_seconds", 240, result
        ),
        "long_path_max_seconds": _positive_number(
            settings_raw, "long_path_max_seconds", 300, result
        ),
        "max_sentence_words": _positive_number(
            settings_raw, "max_sentence_words", 35, result
        ),
    }
    if not (
        settings["quick_answer_min_seconds"]
        <= settings["quick_answer_target_seconds"]
        <= settings["quick_answer_max_seconds"]
    ):
        result.errors.append(
            "settings quick-answer timing must satisfy min <= target <= max"
        )
    required_quick_timing = {
        "quick_answer_target_seconds": 90,
        "quick_answer_min_seconds": 75,
        "quick_answer_max_seconds": 130,
    }
    for key, expected in required_quick_timing.items():
        if settings[key] != expected:
            result.errors.append(f"settings.{key} must be {expected:g}")

    banned_phrases = list(DEFAULT_BANNED_PHRASES)
    extra_banned = settings_raw.get("banned_phrases", [])
    if isinstance(extra_banned, list) and all(isinstance(item, str) for item in extra_banned):
        banned_phrases.extend(extra_banned)
    else:
        result.errors.append("settings.banned_phrases must be a list of strings")

    answers = loaded.get("answers")
    if not isinstance(answers, list) or len(answers) < 2:
        result.errors.append("answers must contain at least two project answer options")
        return result
    titles: list[str] = []
    answer_story_sets: list[frozenset[str]] = []
    for index, answer in enumerate(answers):
        _validate_answer(
            answer,
            index,
            source,
            result,
            settings=settings,
            banned_phrases=banned_phrases,
        )
        if isinstance(answer, dict) and isinstance(answer.get("project_title"), str):
            titles.append(answer["project_title"].strip().lower())
        if isinstance(answer, dict) and isinstance(answer.get("source_stories"), list):
            answer_story_sets.append(
                frozenset(
                    str((source.parent / story).resolve())
                    for story in answer["source_stories"]
                    if isinstance(story, str) and story.strip()
                )
            )
    if len(titles) != len(set(titles)):
        result.errors.append("answers must use unique project_title values")
    if len(answer_story_sets) != len(set(answer_story_sets)):
        result.errors.append("answers must use distinct source_stories project sets")
    if len(set().union(*answer_story_sets)) < 2:
        result.errors.append("answers must reference at least two distinct story files")

    allowed_root = {
        "schema_version",
        "slug",
        "primary_question",
        "similar_questions",
        "outputs",
        "settings",
        "answers",
    }
    extra_root = [key for key in loaded if key not in allowed_root]
    if extra_root:
        result.errors.append(f"YAML has unknown root fields: {', '.join(extra_root)}")
    return result


class UnroutableOutput(Exception):
    """A declared output alias has no target folder on disk.

    Raised instead of guessing. The alternative — creating
    ``<companies_root>/<key>/`` on the fly — writes an invented folder into the
    owner's private tree and files a real answer somewhere nobody looks.
    """


def _configured_companies_root() -> Path:
    """``config.companies_root()``, imported lazily.

    Only a company-prefixed alias needs it, so a question-bank-only run never
    loads the config (and never prints its example-fallback notice).
    """
    import config  # vendored copy; see the sys.path bootstrap at the top

    return config.companies_root()


def _company_dir(companies_root: Path, key: str) -> Path | None:
    """The existing company folder named exactly ``key``, else ``None``.

    Matches by listing the tree rather than testing ``(root / key).is_dir()``:
    on a case-insensitive filesystem that test passes for a folder whose real
    name differs in case, and the render would then target a path that does not
    exist on Linux. Company keys are lowercase by construction
    (``OUTPUT_SLUG_RE``), so an exact match is the only safe one.
    """
    try:
        entries = list(companies_root.iterdir())
    except OSError:
        return None
    for entry in entries:
        if entry.name == key and entry.is_dir():
            return entry
    return None


def _target_for(slug: str, source: Path, companies_root: Path | None) -> Path:
    """Resolve one output alias to the file it renders to."""
    if slug.startswith(GENERAL_SLUG_PREFIX):
        return source.parent.parent / f"{slug}.md"
    key = slug.split("-", 1)[0] if "-" in slug else ""
    if not key:
        raise UnroutableOutput(
            f"output {slug!r} is neither a {GENERAL_SLUG_PREFIX}* alias nor "
            "'<company-key>-<name>', so no target folder can be derived"
        )
    # Resolved like discover_sources() resolves a source: both trees must be
    # canonical, or one file reached two ways would look like two targets to the
    # duplicate-owner check.
    root = (
        companies_root if companies_root is not None else _configured_companies_root()
    ).resolve()
    company_dir = _company_dir(root, key)
    if company_dir is None:
        reason = (
            f"the company tree does not exist: {root}"
            if not root.is_dir()
            else f"there is no {key!r} folder in {root}"
        )
        raise UnroutableOutput(
            f"output {slug!r} files under company key {key!r}, but {reason}. "
            "Create the folder, or fix the alias prefix — this never invents one"
        )
    return company_dir / COMPANY_DERIVED_DIRNAME / f"{slug}.md"


def output_targets_for(
    source: Path, data: dict[str, Any], companies_root: Path | None
) -> list[tuple[Path, dict[str, str]]]:
    """Every declared alias paired with the file it renders to.

    ``companies_root`` is the company tree that company-prefixed aliases file
    under; pass ``None`` to resolve it from ``config.companies_root()``. Raises
    :class:`UnroutableOutput` if ANY alias of this source is unroutable, so a
    source never half-renders.
    """
    return [
        (_target_for(output["slug"], source, companies_root), output)
        for output in data["outputs"]
    ]


def _format_duration(words: int, rate: float) -> str:
    seconds = round(words / rate * 60)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _format_seconds(seconds: float) -> str:
    rounded = round(seconds)
    return f"{rounded // 60}:{rounded % 60:02d}"


def _render_star(module: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for part in STAR_PARTS:
        lines.extend([f"({part.title()}) {module[part].strip()}", ""])
    return lines


def _render_timeline(items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in items:
        lines.extend([f"({item['tag'].strip()}) {item['text'].strip()}", ""])
    return lines


def _continue_sentence(text: str) -> str:
    stripped = text.strip()
    if len(stripped) > 1 and stripped[0].isupper() and stripped[1].islower():
        return stripped[0].lower() + stripped[1:]
    return stripped


def _render_focus_areas(items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in items:
        lines.extend(
            [
                (
                    f"({item['tag'].strip()}) {item['problem'].strip()} "
                    f"To address that, {item['action'].strip()} "
                    f"As a result, {_continue_sentence(item['impact'])}"
                ),
                "",
            ]
        )
    return lines


def _answer_block_summary(index: int, title: str) -> str:
    return f"<summary><strong>Answer {index}</strong> — {title}</summary>"


def _module_details_summary(
    label: str, words: int, rate: float, *, qualifier: str = ""
) -> str:
    timing = f"{words} words / about {_format_duration(words, rate)}"
    suffix = f" · {qualifier}" if qualifier else ""
    return f"<summary><em>{label}</em> · {timing}{suffix}</summary>"


def _module_group_summary(label: str) -> str:
    return f"<summary><em>{label}</em></summary>"


def _reference_details_summary(label: str) -> str:
    return f"<summary><em>Reference</em> · {label}</summary>"


def _details_summary(label: str, words: int, rate: float, *, qualifier: str = "") -> str:
    """Backward-compatible alias for module summaries."""
    return _module_details_summary(label, words, rate, qualifier=qualifier)


def render_markdown(
    data: dict[str, Any], source: Path, output: dict[str, str] | None = None
) -> str:
    settings = data.get("settings", {})
    rate = float(settings.get("speaking_rate_wpm", 120))
    relative_source = f"sources/{source.name}"
    selected_output = output or data["outputs"][0]
    lines = [
        f"<!-- Generated from {relative_source}; do not edit by hand. -->",
        f"# {selected_output['title'].strip()}",
        "",
        "## Most natural question",
        "",
        f"> {data['primary_question'].strip()}",
        "",
        "## Similar questions",
        "",
    ]
    lines.extend(f"- {question.strip()}" for question in data["similar_questions"])
    lines.append("")

    for index, answer in enumerate(data["answers"], start=1):
        counts = {
            name: _module_word_count(answer[name])
            for name in ANSWER_MODULES
        }
        title = answer["project_title"].strip()
        lines.extend(
            [
                "<details>",
                _answer_block_summary(index, title),
                "",
                "---",
                "",
                "<details>",
                _module_details_summary(
                    "Self-contained · quick + short deep dive",
                    counts["combined_answer"],
                    rate,
                ),
                "",
            ]
        )
        lines.extend(_render_star(answer["combined_answer"]))
        lines.extend(
            [
                "</details>",
                "",
                "<details>",
                _module_details_summary(
                    "Quick answer",
                    counts["quick_answer"],
                    rate,
                    qualifier=(
                        "target "
                        f"{_format_seconds(float(settings.get('quick_answer_target_seconds', 90)))}"
                    ),
                ),
                "",
            ]
        )
        lines.extend(_render_star(answer["quick_answer"]))
        lines.extend(
            [
                "</details>",
                "",
                "<details>",
                _module_group_summary("Technical deep dives"),
                "",
                "<details>",
                _module_details_summary(
                    "Deep dive · short",
                    counts["technical_deep_dive_short"],
                    rate,
                    qualifier="new material",
                ),
                "",
                f"> {answer['technical_deep_dive_short']['bridge'].strip()}",
                "",
            ]
        )
        lines.extend(_render_star(answer["technical_deep_dive_short"]))
        lines.extend(
            [
                "</details>",
                "",
                "<details>",
                _module_details_summary(
                    "Deep dive · long",
                    counts["technical_deep_dive_long"],
                    rate,
                    qualifier="new material",
                ),
                "",
                f"> {answer['technical_deep_dive_long']['bridge'].strip()}",
                "",
            ]
        )
        lines.extend(_render_star(answer["technical_deep_dive_long"]))
        lines.extend(
            [
                "</details>",
                "",
                "</details>",
                "",
                "<details>",
                _reference_details_summary("timeline"),
                "",
            ]
        )
        lines.extend(_render_timeline(answer["story_references"]["timeline"]))
        lines.extend(
            [
                "</details>",
                "",
                "<details>",
                _reference_details_summary("isolated problem / action / impact"),
                "",
            ]
        )
        lines.extend(_render_focus_areas(answer["story_references"]["focus_areas"]))
        lines.extend(["</details>", "", "</details>", ""])
    return "\n".join(lines)


def discover_sources(path: Path) -> list[Path]:
    path = path.resolve()
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.glob("*.yaml"))
    return []


def _print_result(result: ValidationResult) -> None:
    for warning in result.warnings:
        print(f"WARN {result.source}: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"FAIL {result.source}: {error}", file=sys.stderr)


def run(command: str, path: Path, companies_root: Path | None = None) -> int:
    sources = discover_sources(path)
    if not sources:
        print(f"FAIL {path}: no YAML answer sources found", file=sys.stderr)
        return 1
    failed = False
    valid_results: list[ValidationResult] = []
    for source in sources:
        result = load_and_validate(source)
        _print_result(result)
        if not result.ok or result.data is None:
            failed = True
            continue
        valid_results.append(result)

    # Resolve every target ONCE: the duplicate-owner check below and the
    # render/check loop must reason about the same paths, and after routing they
    # can sit in different trees (question bank vs company folder).
    resolved: list[tuple[ValidationResult, list[tuple[Path, dict[str, str]]]]] = []
    output_owners: dict[Path, Path] = {}
    colliding_sources: set[Path] = set()
    for result in valid_results:
        assert result.data is not None
        try:
            targets = output_targets_for(result.source, result.data, companies_root)
        except UnroutableOutput as exc:
            print(f"FAIL {result.source}: {exc}", file=sys.stderr)
            failed = True
            continue
        resolved.append((result, targets))
        for output_path, _ in targets:
            owner = output_owners.get(output_path)
            if owner is not None:
                # The full path, not the name: two aliases can share a name in
                # different trees, and only the resolved path says which one collided.
                print(
                    f"FAIL {result.source}: output {output_path} is also declared by {owner}",
                    file=sys.stderr,
                )
                colliding_sources.update((owner, result.source))
                failed = True
            else:
                output_owners[output_path] = result.source

    for result, targets in resolved:
        if result.source in colliding_sources:
            continue
        assert result.data is not None
        source = result.source
        for output_path, output in targets:
            rendered = render_markdown(result.data, source, output)
            if command == "render":
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(rendered, encoding="utf-8")
                print(f"rendered {output_path}")
            elif command == "check":
                try:
                    current = output_path.read_text(encoding="utf-8")
                except OSError:
                    current = ""
                if current != rendered:
                    print(
                        f"FAIL {source}: generated Markdown is missing or stale: {output_path}",
                        file=sys.stderr,
                    )
                    failed = True
                else:
                    print(f"ok {output_path}")
            else:
                print(f"ok {source} -> {output_path.name}")
    return int(failed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "render", "check"))
    parser.add_argument("path", type=Path, help="YAML source file or question-bank/sources directory")
    parser.add_argument(
        "--companies-root",
        type=Path,
        default=None,
        help="company tree that company-prefixed aliases file under "
             "(default: config.companies_root())",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run(args.command, args.path, args.companies_root)


if __name__ == "__main__":
    raise SystemExit(main())
