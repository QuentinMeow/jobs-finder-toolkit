"""Import user-supplied company-level facts into a schema-v2 YAML cache.

This maintenance tool is deliberately file-only: it accepts normalized YAML,
JSON, or CSV rows and never fetches or scrapes data.

Usage:
    .venv/bin/python automation/maintenance/import_company_levels.py INPUT DESTINATION
    .venv/bin/python automation/maintenance/import_company_levels.py INPUT DESTINATION --write

The first form validates and merges in memory without changing DESTINATION.
``--write`` atomically replaces DESTINATION after a checksum guard confirms that
the cache has not changed since it was read.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_DIR = REPO_ROOT / "automation" / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from job_metadata import NORMALIZED_LEVELS, SOURCE_TIERS, pick_candidate  # noqa: E402


SUPPORTED_FIELDS = {
    "company",
    "level",
    "aliases",
    "title_patterns",
    "normalized",
    "google_min",
    "google_max",
    "required_yoe_min",
    "required_yoe_max",
    "base_min",
    "base_max",
    "stock_min",
    "stock_max",
    "bonus_min",
    "bonus_max",
    "total_min",
    "total_max",
    "currency",
    "period",
    "geography",
    "location_patterns",
    "provider",
    "url",
    "retrieved_at",
    "confidence",
    "sample_size",
    "method",
    "statistic",
    "access_method",
    "license",
}

LIST_FIELDS = {"aliases", "title_patterns", "location_patterns"}
NUMBER_FIELDS = {
    "google_min",
    "google_max",
    "required_yoe_min",
    "required_yoe_max",
    "base_min",
    "base_max",
    "stock_min",
    "stock_max",
    "bonus_min",
    "bonus_max",
    "total_min",
    "total_max",
}
RANGE_FIELDS = {
    "google_equivalent": ("google_min", "google_max"),
    "required_yoe": ("required_yoe_min", "required_yoe_max"),
    "salary_range": ("base_min", "base_max"),
    "stock_range": ("stock_min", "stock_max"),
    "bonus_range": ("bonus_min", "bonus_max"),
    "total_compensation_range": ("total_min", "total_max"),
}
COMPENSATION_FIELDS = (
    "salary_range",
    "stock_range",
    "bonus_range",
    "total_compensation_range",
)
VALID_PERIODS = {"year", "month", "week", "day", "hour"}
VALID_CONFIDENCE = {"high", "medium", "low", "unknown"}
LEVELS_FYI_ACCESS_METHODS = {
    "user_supplied",
    "licensed_api",
    "licensed_export",
}
SOURCE = "company_level_import"


class ImportValidationError(ValueError):
    """Raised when an import file or normalized row is invalid."""


def _identity(value: Any) -> str:
    """Normalize a company or level name for identity matching."""
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower())
    return " ".join(text.split())


def _company_identity(value: Any) -> str:
    text = _identity(value)
    text = re.sub(
        r"\b(?:incorporated|inc|llc|ltd|corp|corporation|company)\b",
        " ",
        text,
    )
    return " ".join(text.split())


def _normalized_access_method(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _as_list(value: Any, *, field: str, lead: str) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ImportValidationError(
                    f"{lead}.{field} must be a JSON array or delimited string"
                ) from exc
        else:
            separator = "|" if "|" in text else ";" if ";" in text else ","
            value = [item.strip() for item in text.split(separator)]
    if not isinstance(value, list):
        raise ImportValidationError(f"{lead}.{field} must be a list")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ImportValidationError(
                f"{lead}.{field} entries must be non-empty strings"
            )
        if item.strip() not in result:
            result.append(item.strip())
    return result


def _as_number(value: Any, *, field: str, lead: str) -> int | float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ImportValidationError(f"{lead}.{field} must be numeric or null")
    if isinstance(value, str):
        value = value.strip().replace(",", "")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ImportValidationError(
            f"{lead}.{field} must be numeric or null"
        ) from exc
    if not math.isfinite(number):
        raise ImportValidationError(f"{lead}.{field} must be finite")
    if number < 0:
        raise ImportValidationError(f"{lead}.{field} must be non-negative")
    return int(number) if number.is_integer() else number


def _as_sample_size(value: Any, *, lead: str) -> int | None:
    if value in (None, ""):
        return None
    number = _as_number(value, field="sample_size", lead=lead)
    if not isinstance(number, int):
        raise ImportValidationError(
            f"{lead}.sample_size must be a non-negative integer or null"
        )
    return number


def _as_date(value: Any, *, lead: str) -> str:
    if value in (None, ""):
        raise ImportValidationError(f"{lead}.retrieved_at is required")
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        if len(text) == 10:
            parsed = date.fromisoformat(text)
        else:
            parsed = datetime.fromisoformat(
                text[:-1] + "+00:00" if text.endswith("Z") else text
            ).date()
    except ValueError as exc:
        raise ImportValidationError(
            f"{lead}.retrieved_at must be an ISO date or datetime"
        ) from exc
    return parsed.isoformat()


def _looks_like_levels_fyi(provider: str, url: str) -> bool:
    text = f"{provider} {url}".lower()
    return bool(re.search(r"\blevels[\s._-]*fyi\b", text))


def _is_employer_official(row: dict[str, Any]) -> bool:
    """Recognize an explicit employer-official provider/access declaration."""
    text = " ".join(
        str(row.get(field) or "") for field in ("provider", "access_method", "method")
    ).lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", text)
    markers = (
        "employer official",
        "official employer",
        "company official",
        "official company",
        "official careers",
        "employer careers",
    )
    return any(marker in normalized for marker in markers)


def _coverage(row: dict[str, Any]) -> list[str]:
    coverage = []
    if row.get("normalized") or row.get("aliases") or row.get("title_patterns"):
        coverage.append("level")
    components = (
        ("google_equivalent", "google_min", "google_max"),
        ("required_yoe", "required_yoe_min", "required_yoe_max"),
        ("base", "base_min", "base_max"),
        ("stock", "stock_min", "stock_max"),
        ("bonus", "bonus_min", "bonus_max"),
        ("total", "total_min", "total_max"),
    )
    for label, low, high in components:
        if row.get(low) is not None or row.get(high) is not None:
            coverage.append(label)
    return coverage


def normalize_record(raw: Any, index: int) -> dict[str, Any]:
    """Validate and normalize one input row."""
    lead = f"records[{index}]"
    if not isinstance(raw, dict):
        raise ImportValidationError(f"{lead} must be a mapping")
    unknown = sorted(str(field) for field in set(raw) - SUPPORTED_FIELDS)
    if unknown:
        raise ImportValidationError(
            f"{lead} has unsupported fields: {', '.join(unknown)}"
        )

    row = {field: raw.get(field) for field in SUPPORTED_FIELDS}
    for field in ("company", "level", "provider", "access_method"):
        row[field] = str(row.get(field) or "").strip()
        if not row[field]:
            raise ImportValidationError(f"{lead}.{field} is required")

    row["retrieved_at"] = _as_date(row.get("retrieved_at"), lead=lead)
    for field in LIST_FIELDS:
        row[field] = _as_list(row.get(field), field=field, lead=lead)
    for field in NUMBER_FIELDS:
        row[field] = _as_number(row.get(field), field=field, lead=lead)
    row["sample_size"] = _as_sample_size(row.get("sample_size"), lead=lead)

    for field in (
        "normalized",
        "currency",
        "period",
        "geography",
        "url",
        "confidence",
        "method",
        "statistic",
        "license",
    ):
        row[field] = str(row.get(field) or "").strip()

    row["normalized"] = row["normalized"].lower().replace("-", "_").replace(" ", "_")
    if row["normalized"] and row["normalized"] not in NORMALIZED_LEVELS:
        raise ImportValidationError(
            f"{lead}.normalized must be one of "
            f"{', '.join(sorted(NORMALIZED_LEVELS))}"
        )

    for dimension, (low_field, high_field) in RANGE_FIELDS.items():
        low, high = row[low_field], row[high_field]
        if low is not None and high is not None and low > high:
            raise ImportValidationError(
                f"{lead}.{dimension} minimum must not exceed maximum"
            )

    has_compensation = any(
        row[bound] is not None
        for field in COMPENSATION_FIELDS
        for bound in RANGE_FIELDS[field]
    )
    row["currency"] = row["currency"].upper()
    row["period"] = row["period"].lower()
    if has_compensation:
        if not re.fullmatch(r"[A-Z]{3}", row["currency"]):
            raise ImportValidationError(
                f"{lead}.currency must be an explicit 3-letter currency code"
            )
        if row["period"] not in VALID_PERIODS:
            raise ImportValidationError(
                f"{lead}.period must be one of {', '.join(sorted(VALID_PERIODS))}"
            )
        dimensional_limit = 100_000 if row["period"] == "hour" else 100_000_000
        for field in COMPENSATION_FIELDS:
            for bound in RANGE_FIELDS[field]:
                value = row[bound]
                if value is not None and value > dimensional_limit:
                    raise ImportValidationError(
                        f"{lead}.{bound} is dimensionally invalid for period "
                        f"{row['period']}"
                    )
    elif row["currency"] and not re.fullmatch(r"[A-Z]{3}", row["currency"]):
        raise ImportValidationError(
            f"{lead}.currency must be an explicit 3-letter currency code"
        )
    elif row["period"] and row["period"] not in VALID_PERIODS:
        raise ImportValidationError(
            f"{lead}.period must be one of {', '.join(sorted(VALID_PERIODS))}"
        )

    row["confidence"] = row["confidence"].lower() or "unknown"
    if row["confidence"] not in VALID_CONFIDENCE:
        raise ImportValidationError(
            f"{lead}.confidence must be one of "
            f"{', '.join(sorted(VALID_CONFIDENCE))}"
        )

    access = _normalized_access_method(row["access_method"])
    if re.search(r"scrap|crawl", access):
        raise ImportValidationError(
            f"{lead}.access_method must not use scraping or crawling"
        )
    row["access_method"] = access
    if _looks_like_levels_fyi(row["provider"], row["url"]):
        if access not in LEVELS_FYI_ACCESS_METHODS:
            raise ImportValidationError(
                f"{lead}.access_method for Levels.fyi must be one of "
                f"{', '.join(sorted(LEVELS_FYI_ACCESS_METHODS))}"
            )
        if not row["license"]:
            raise ImportValidationError(
                f"{lead}.license is required for Levels.fyi data"
            )
    return row


def _reject_json_constant(value: str) -> None:
    raise ImportValidationError(f"JSON numeric constant {value} is not finite")


def load_records(path: str | Path) -> list[dict[str, Any]]:
    """Load and normalize records from a supported user-supplied file."""
    source = Path(path)
    suffix = source.suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(source.read_text(encoding="utf-8"))
        elif suffix == ".json":
            data = json.loads(
                source.read_text(encoding="utf-8"),
                parse_constant=_reject_json_constant,
            )
        elif suffix == ".csv":
            with source.open(newline="", encoding="utf-8-sig") as handle:
                data = list(csv.DictReader(handle))
        else:
            raise ImportValidationError(
                "input file must use .yaml, .yml, .json, or .csv"
            )
    except OSError as exc:
        raise ImportValidationError(f"could not read input file: {exc}") from exc
    except (yaml.YAMLError, json.JSONDecodeError, csv.Error) as exc:
        raise ImportValidationError(f"could not parse input file: {exc}") from exc

    if isinstance(data, dict):
        if set(data) != {"records"}:
            raise ImportValidationError(
                "input mapping must contain only a records list"
            )
        data = data["records"]
    if not isinstance(data, list):
        raise ImportValidationError("input must be a list or {records: [...]}")
    return [normalize_record(record, index) for index, record in enumerate(data)]


def _provenance(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "tier": "employer_official" if _is_employer_official(row)
        else "market_benchmark",
        "provider": row["provider"],
        "url": row["url"],
        "retrieved_at": row["retrieved_at"],
        "geography": row["geography"],
        "confidence": row["confidence"],
        "sample_size": row["sample_size"],
        "method": row["method"],
        "statistic": row["statistic"],
        "access_method": row["access_method"],
        "license": row["license"],
        "component_coverage": _coverage(row),
    }


def _range_fact(
    row: dict[str, Any],
    low_field: str,
    high_field: str,
    *,
    compensation: bool = False,
) -> dict[str, Any] | None:
    low, high = row[low_field], row[high_field]
    if low is None and high is None:
        return None
    fact: dict[str, Any] = {
        "min": low,
        "max": high,
        "source": SOURCE,
        "provenance": _provenance(row),
    }
    if compensation:
        fact.update({
            "currency": row["currency"],
            "period": row["period"],
        })
        if row["geography"]:
            fact["geography"] = row["geography"]
        if row["location_patterns"]:
            fact["location_patterns"] = list(row["location_patterns"])
    return fact


def record_to_level(row: dict[str, Any]) -> dict[str, Any]:
    """Turn one normalized flat row into a cache level fragment."""
    provenance = _provenance(row)
    level: dict[str, Any] = {
        "name": row["level"],
        "provenance": provenance,
        "source": SOURCE,
    }
    if row["aliases"]:
        level["aliases"] = list(row["aliases"])
    if row["title_patterns"]:
        level["title_patterns"] = list(row["title_patterns"])
    if row["normalized"]:
        level["normalized"] = row["normalized"]

    google = _range_fact(row, "google_min", "google_max")
    required = _range_fact(row, "required_yoe_min", "required_yoe_max")
    if google:
        level["google_equivalent"] = google
    if required:
        level["required_yoe"] = required

    compensation = {}
    for field in COMPENSATION_FIELDS:
        low_field, high_field = RANGE_FIELDS[field]
        fact = _range_fact(
            row, low_field, high_field, compensation=True)
        if fact:
            compensation[field] = _as_scoped_compensation(fact)
    if compensation:
        level["compensation"] = compensation
    return level


def _has_scope(fact: dict[str, Any]) -> bool:
    provenance = fact.get("provenance")
    geography = fact.get("geography") or (
        provenance.get("geography") if isinstance(provenance, dict) else ""
    )
    return bool(geography or fact.get("location_patterns"))


def _as_scoped_compensation(fact: dict[str, Any]) -> dict[str, Any]:
    """Store a geographic fact as a band, even when it is the only band."""
    if not _has_scope(fact):
        return fact
    return {
        "min": None,
        "max": None,
        "bands": [fact],
        "source": fact.get("source", SOURCE),
        "provenance": copy.deepcopy(fact.get("provenance") or {}),
    }


def _winner_without_null_regression(
    winner: dict[str, Any],
    loser: dict[str, Any],
) -> dict[str, Any]:
    """Treat a sourced range as atomic; never mix bounds from two provenances."""
    if _manual_override(winner):
        return copy.deepcopy(winner)
    if any(
        winner.get(key) is None and loser.get(key) is not None
        for key in ("min", "max")
    ):
        return copy.deepcopy(loser)
    return copy.deepcopy(winner)


def _merge_fact(
    existing: Any, imported: dict[str, Any] | None
) -> dict[str, Any] | Any:
    if imported is None:
        return copy.deepcopy(existing)
    if not isinstance(existing, dict):
        return copy.deepcopy(imported)
    winner = pick_candidate(existing, imported)
    if winner is imported:
        return _winner_without_null_regression(imported, existing)
    return _winner_without_null_regression(existing, imported)


def _manual_override(fact: Any) -> bool:
    provenance = fact.get("provenance") if isinstance(fact, dict) else None
    return bool(
        isinstance(provenance, dict)
        and provenance.get("manual_override") is True
    )


def _scope_key(fact: dict[str, Any]) -> tuple[Any, ...]:
    provenance = fact.get("provenance")
    geography = fact.get("geography") or (
        provenance.get("geography") if isinstance(provenance, dict) else ""
    )
    patterns = tuple(sorted(
        _identity(value) for value in (fact.get("location_patterns") or []) if value
    ))
    return (
        _identity(geography),
        patterns,
        str(fact.get("currency") or "").upper(),
        str(fact.get("period") or "").lower(),
    )


def _bands(fact: dict[str, Any]) -> list[dict[str, Any]]:
    raw = fact.get("bands")
    if isinstance(raw, list):
        return [copy.deepcopy(item) for item in raw if isinstance(item, dict)]
    return [copy.deepcopy(fact)]


def _wrapper_provenance(
    existing: dict[str, Any], imported: dict[str, Any]
) -> dict[str, Any]:
    winner = pick_candidate(existing, imported)
    selected = winner if isinstance(winner, dict) else imported
    return copy.deepcopy(selected.get("provenance") or {})


def _merge_compensation(
    existing: Any, imported: dict[str, Any] | None
) -> Any:
    if imported is None:
        return copy.deepcopy(existing)
    if not isinstance(existing, dict):
        return copy.deepcopy(imported)
    if _manual_override(existing):
        return copy.deepcopy(existing)

    existing_has_bands = isinstance(existing.get("bands"), list)
    imported_has_bands = isinstance(imported.get("bands"), list)
    if not existing_has_bands and not imported_has_bands:
        if _scope_key(existing) == _scope_key(imported):
            return _merge_fact(existing, imported)
        existing_has_bands = imported_has_bands = True

    if existing_has_bands or imported_has_bands:
        merged = _bands(existing)
        positions = {_scope_key(band): index for index, band in enumerate(merged)}
        for band in _bands(imported):
            key = _scope_key(band)
            if key in positions:
                merged[positions[key]] = _merge_fact(
                    merged[positions[key]], band)
            else:
                positions[key] = len(merged)
                merged.append(band)
        wrapper = {}
        band_keys = {
            "min",
            "max",
            "bands",
            "currency",
            "period",
            "geography",
            "location_patterns",
            "source",
            "provenance",
        }
        for source_fact in (existing, imported):
            for key, value in source_fact.items():
                if key not in band_keys and key not in wrapper:
                    wrapper[key] = copy.deepcopy(value)
        wrapper.update({
            "min": None,
            "max": None,
            "bands": merged,
            "source": SOURCE,
            "provenance": _wrapper_provenance(existing, imported),
        })
        return wrapper
    return _merge_fact(existing, imported)


def _stable_union(*groups: Iterable[Any]) -> list[Any]:
    result = []
    seen = set()
    for group in groups:
        for value in group:
            marker = _identity(value)
            if marker and marker not in seen:
                result.append(copy.deepcopy(value))
                seen.add(marker)
    return result


def _merge_level(existing: dict[str, Any], imported: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(existing)
    merged.setdefault("name", imported["name"])
    for field in ("aliases", "title_patterns"):
        values = _stable_union(
            merged.get(field) or [], imported.get(field) or [])
        if values:
            merged[field] = values

    structural_winner = pick_candidate(existing, imported)
    if structural_winner is imported:
        for field in ("normalized", "source", "provenance"):
            if imported.get(field) not in (None, "", {}):
                merged[field] = copy.deepcopy(imported[field])
    else:
        for field in ("normalized", "source", "provenance"):
            if merged.get(field) in (None, "", {}) and imported.get(field) not in (
                None, "", {}
            ):
                merged[field] = copy.deepcopy(imported[field])

    for field in ("google_equivalent", "required_yoe"):
        if field in imported:
            merged[field] = _merge_fact(merged.get(field), imported[field])

    imported_compensation = imported.get("compensation") or {}
    if imported_compensation:
        compensation = copy.deepcopy(merged.get("compensation") or {})
        for field, imported_fact in imported_compensation.items():
            compensation[field] = _merge_compensation(
                compensation.get(field), imported_fact)
        merged["compensation"] = compensation
    return merged


def _level_matches(level: dict[str, Any], name: str) -> bool:
    wanted = _identity(name)
    names = [level.get("name"), *(level.get("aliases") or [])]
    return wanted in {_identity(value) for value in names if value}


def _merge_company(
    company: dict[str, Any], row: dict[str, Any], level: dict[str, Any]
) -> dict[str, Any]:
    merged = copy.deepcopy(company)
    merged.setdefault("name", row["company"])
    levels = copy.deepcopy(merged.get("levels") or [])
    for index, current in enumerate(levels):
        if isinstance(current, dict) and _level_matches(current, row["level"]):
            levels[index] = _merge_level(current, level)
            break
    else:
        levels.append(copy.deepcopy(level))
    merged["levels"] = levels

    if row["url"]:
        merged["sources"] = _stable_union(
            merged.get("sources") or [], [row["url"]])
    verified = str(merged.get("last_verified") or "")
    if not verified or row["retrieved_at"] > verified[:10]:
        merged["last_verified"] = row["retrieved_at"]
    return merged


def _company_matches(company: dict[str, Any], name: str) -> bool:
    wanted = _company_identity(name)
    names = [company.get("name"), *(company.get("aliases") or [])]
    return wanted in {_company_identity(value) for value in names if value}


def merge_records(
    cache: dict[str, Any], records: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Merge normalized rows while preserving unrelated cache content."""
    if not isinstance(cache, dict):
        raise ImportValidationError("destination cache must be a mapping")
    merged = copy.deepcopy(cache)
    companies_value = merged.get("companies")
    if companies_value is None:
        companies_value = []
    if not isinstance(companies_value, (list, dict)):
        raise ImportValidationError("destination companies must be a list or mapping")

    for row in records:
        imported_level = record_to_level(row)
        if isinstance(companies_value, list):
            for index, company in enumerate(companies_value):
                if isinstance(company, dict) and _company_matches(
                    company, row["company"]
                ):
                    companies_value[index] = _merge_company(
                        company, row, imported_level)
                    break
            else:
                companies_value.append(_merge_company(
                    {"name": row["company"], "levels": []},
                    row,
                    imported_level,
                ))
        else:
            matching_key = next(
                (
                    key for key, value in companies_value.items()
                    if _company_matches(
                        {"name": key, **(value if isinstance(value, dict) else {})},
                        row["company"],
                    )
                ),
                None,
            )
            key = matching_key or row["company"]
            current = companies_value.get(key)
            if current is not None and not isinstance(current, dict):
                raise ImportValidationError(
                    f"destination company {key!r} must be a mapping"
                )
            had_explicit_name = isinstance(current, dict) and "name" in current
            company = {"name": key, **(current or {})}
            updated = _merge_company(company, row, imported_level)
            if not had_explicit_name:
                updated.pop("name", None)
            companies_value[key] = updated

    merged["companies"] = companies_value
    merged["schema_version"] = 2
    merged.setdefault("tier_precedence", list(SOURCE_TIERS))
    return merged


def _checksum(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ImportValidationError(
            f"could not checksum destination cache: {exc}"
        ) from exc


def _load_cache(path: Path) -> tuple[dict[str, Any], str | None]:
    expected_checksum = _checksum(path)
    if expected_checksum is None:
        return {}, None
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ImportValidationError(
            f"could not parse destination cache: {exc}"
        ) from exc
    if not isinstance(loaded, dict):
        raise ImportValidationError("destination cache must be a mapping")
    return loaded, expected_checksum


def _yaml_bytes(data: dict[str, Any]) -> bytes:
    text = yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    return text.encode("utf-8")


def _atomic_replace(
    path: Path, content: bytes, *, expected_checksum: str | None
) -> bool:
    """Atomically replace path if its checksum is still the expected value."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if _checksum(path) == hashlib.sha256(content).hexdigest():
        return False

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        if _checksum(path) != expected_checksum:
            raise ImportValidationError(
                "destination cache changed during import; refusing to replace it"
            )
        os.replace(temporary, path)
        temporary = None
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # The file itself was fsynced; some filesystems do not permit fsync
            # on a directory descriptor.
            pass
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def import_company_levels(
    input_path: str | Path,
    destination_path: str | Path,
    *,
    write: bool = False,
) -> dict[str, Any]:
    """Load, validate, and merge an import, optionally writing it atomically."""
    records = load_records(input_path)
    destination = Path(destination_path)
    cache, expected_checksum = _load_cache(destination)
    merged = merge_records(cache, records)
    if write:
        _atomic_replace(
            destination,
            _yaml_bytes(merged),
            expected_checksum=expected_checksum,
        )
    return merged


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and merge user-supplied company-level facts. "
            "Dry-run is the default; use --write for atomic replacement."
        )
    )
    parser.add_argument("input", help="normalized .yaml/.yml, .json, or .csv records")
    parser.add_argument("destination", help="company-level YAML cache path")
    parser.add_argument(
        "--write",
        action="store_true",
        help="atomically replace the destination cache",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        records = load_records(args.input)
        destination = Path(args.destination)
        cache, expected_checksum = _load_cache(destination)
        merged = merge_records(cache, records)
        changed = _yaml_bytes(merged) != (
            destination.read_bytes() if destination.exists() else b""
        )
        if args.write:
            wrote = _atomic_replace(
                destination,
                _yaml_bytes(merged),
                expected_checksum=expected_checksum,
            )
            print(
                f"{'Updated' if wrote else 'Unchanged'} {destination} "
                f"from {len(records)} record(s)."
            )
        else:
            print(
                f"Dry run: validated {len(records)} record(s); "
                f"{destination} would be {'updated' if changed else 'unchanged'}."
            )
        return 0
    except ImportValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
