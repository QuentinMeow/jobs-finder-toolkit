"""JSON Schema enforcement (stdlib-only) and the zone-aware store validator.

Two pieces:

1. A **minimal-but-honest** JSON Schema validator (no ``jsonschema`` dependency)
   supporting the keywords the store's schemas actually use: ``type``, ``required``,
   ``properties``, ``patternProperties``, ``additionalProperties``, ``enum``,
   ``const``, ``pattern``, ``items``, ``minItems``, ``minimum``, ``maximum`` and
   ``anyOf``. The schema FILES in ``schemas/`` are real JSON Schema documents; this
   validator genuinely enforces required fields / types / patterns.

2. :func:`validate_store` — walks a data root, validates every artifact it
   recognizes against the right schema (dispatching group vs. member manifests),
   reports the four blob availability states (``not-synced-here`` is INFORMATIONAL,
   never a failure; only ``corrupt`` is an error), and tolerates missing raw.

Plus :func:`check_fixture_size` — the soft-threshold size check.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import blobs as _blobs
from . import serialization
from .atomic import read_jsonl
from .constants import (
    FIXTURE_SIZE_OVERRIDE_FILENAME,
    FIXTURE_SIZE_SOFT_LIMIT_BYTES,
    ZONES,
)
from .manifest import is_group_manifest
from .paths import DomainLayout

_SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"

# Artifact -> schema filename.
SCHEMA_FILES = {
    "manifest": "manifest.envelope.v1.json",
    "group": "group-manifest.v1.json",
    "ledger": "ledger-line.v1.json",
    "index-header": "index-header.v1.json",
    "annotation": "annotation.v1.json",
    "key-registry": "key-registry.v1.json",
    "identifiers": "identifiers.v1.json",
    "cursors": "cursors.v1.json",
    "frozen-facts": "frozen-facts.v1.json",
    # Stage 2 — job-postings builder artifacts (derived + index + triage).
    "posting": "posting.v1.json",
    "posting-index-line": "posting-index-line.v1.json",
    "event-line": "event-line.v1.json",
    "suppressed": "suppressed-line.v1.json",
}


def _index_row_schema(idx_path: Path) -> str | None:
    """The data-row schema for an index file, dispatched by its location.

    ``index/postings.jsonl`` rows are posting summary lines; ``index/by-day/*`` and
    per-entity ``events.jsonl`` rows are observed-event lines; ``index/triage/*``
    rows are suppressed-review lines. Unknown index files validate their header only.
    """
    parts = idx_path.parts
    name = idx_path.name
    if "triage" in parts:
        return "suppressed"
    if "by-day" in parts:
        return "event-line"
    if name == "postings.jsonl":
        return "posting-index-line"
    return None


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    path = _SCHEMAS_DIR / SCHEMA_FILES[name]
    return json.loads(path.read_text(encoding="utf-8"))


# ── minimal JSON Schema validator ────────────────────────────
_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _matches_type(value, type_name: str) -> bool:
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    py = _TYPE_MAP.get(type_name)
    if py is None:
        return True  # unknown type name → do not enforce
    if py is dict:
        return isinstance(value, dict)
    if py is list:
        return isinstance(value, list)
    return isinstance(value, py)


def validate(instance, schema: dict, path: str = "") -> list[str]:
    """Return a list of human-readable validation errors (empty == valid)."""
    errors: list[str] = []
    here = path or "<root>"

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{here}: expected const {schema['const']!r}, got {instance!r}")

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{here}: {instance!r} not in enum {schema['enum']}")

    if "type" in schema:
        types = schema["type"]
        types = [types] if isinstance(types, str) else types
        if not any(_matches_type(instance, t) for t in types):
            errors.append(f"{here}: expected type {schema['type']}, "
                          f"got {type(instance).__name__}")
            return errors  # further checks assume the type held

    if "anyOf" in schema:
        if not any(not validate(instance, sub, here) for sub in schema["anyOf"]):
            errors.append(f"{here}: does not match any of anyOf")

    if isinstance(instance, str) and "pattern" in schema:
        if not re.search(schema["pattern"], instance):
            errors.append(f"{here}: {instance!r} does not match pattern "
                          f"{schema['pattern']!r}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{here}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{here}: {instance} > maximum {schema['maximum']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{here}: {len(instance)} items < minItems "
                          f"{schema['minItems']}")
        if "items" in schema:
            for i, item in enumerate(instance):
                errors += validate(item, schema["items"], f"{here}[{i}]")

    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{here}: missing required property {req!r}")
        props = schema.get("properties", {})
        pattern_props = schema.get("patternProperties", {})
        addl = schema.get("additionalProperties", True)
        for key, value in instance.items():
            handled = False
            if key in props:
                errors += validate(value, props[key], f"{here}.{key}")
                handled = True
            for pat, sub in pattern_props.items():
                if re.search(pat, key):
                    errors += validate(value, sub, f"{here}.{key}")
                    handled = True
            if not handled:
                if addl is False:
                    errors.append(f"{here}: additional property {key!r} not allowed")
                elif isinstance(addl, dict):
                    errors += validate(value, addl, f"{here}.{key}")
    return errors


# ── zone-aware store walk ────────────────────────────────────
@dataclass
class StoreReport:
    root: str
    errors: list[str] = field(default_factory=list)
    blob_states: dict[str, int] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    infos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and self.blob_states.get(_blobs.CORRUPT, 0) == 0


def _find_domains(root: Path) -> list[Path]:
    domains = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and any((child / z).is_dir() for z in ZONES):
            domains.append(child)
    return domains


def _validate_yaml_file(path: Path, schema_name: str, report: StoreReport) -> None:
    if not path.exists():
        return
    data = serialization.loads_yaml(path.read_text(encoding="utf-8"))
    for err in validate(data, load_schema(schema_name), path.name):
        report.errors.append(f"{path}: {err}")
    report.counts[schema_name] = report.counts.get(schema_name, 0) + 1


def _validate_derived_postings(layout: DomainLayout, report: StoreReport) -> None:
    """Validate derived posting entities: ``posting.yaml`` + ``events.jsonl`` rows."""
    postings_root = layout.derived / "postings"
    if not postings_root.is_dir():
        return
    for pyaml in sorted(postings_root.rglob("posting.yaml")):
        data = serialization.loads_yaml(pyaml.read_text(encoding="utf-8"))
        for err in validate(data, load_schema("posting"), pyaml.name):
            report.errors.append(f"{pyaml}: {err}")
        report.counts["posting"] = report.counts.get("posting", 0) + 1
        events = pyaml.parent / "events.jsonl"
        if events.exists():
            for i, ev in enumerate(read_jsonl(events)):
                for err in validate(ev, load_schema("event-line"), f"event[{i}]"):
                    report.errors.append(f"{events}: {err}")
            report.counts["event-line"] = report.counts.get("event-line", 0) + 1


def _validate_domain(domain_root: Path, report: StoreReport) -> None:
    layout = DomainLayout(root=domain_root, domain=domain_root.name)

    # raw manifests + blob states
    blobstore = _blobs.BlobStore(layout.blobs)
    from .manifest import iter_manifests

    for path, env in iter_manifests(layout):
        schema_name = "group" if is_group_manifest(env) else "manifest"
        for err in validate(env, load_schema(schema_name), path.name):
            report.errors.append(f"{path}: {err}")
        report.counts[schema_name] = report.counts.get(schema_name, 0) + 1
        payload = env.get("payload")
        if isinstance(payload, dict) and payload.get("blob"):
            ext = _blobs.ext_for_content_type(payload.get("content_type"))
            state = blobstore.state(payload["blob"], ext)
            report.blob_states[state] = report.blob_states.get(state, 0) + 1
            if state == _blobs.NOT_SYNCED_HERE:
                report.infos.append(
                    f"{path}: blob {payload['blob'][:12]}… not-synced-here "
                    f"(informational; manual raw sync remedy)")
            elif state == _blobs.CORRUPT:
                report.errors.append(
                    f"{path}: blob {payload['blob'][:12]}… is CORRUPT "
                    f"(fails verify-on-read)")

    # ledger lines
    ledger = layout.build_ledger
    if ledger.exists():
        for i, line in enumerate(read_jsonl(ledger)):
            for err in validate(line, load_schema("ledger"), f"{ledger.name}[{i}]"):
                report.errors.append(f"{ledger}: {err}")
        report.counts["ledger"] = report.counts.get("ledger", 0) + 1

    # derived posting entities (Stage 2) — entity YAML + event lines
    _validate_derived_postings(layout, report)

    # index headers + data rows (dispatched by location)
    if layout.index.is_dir():
        for idx in sorted(layout.index.rglob("*.jsonl")):
            lines = read_jsonl(idx)
            if not lines:
                report.errors.append(f"{idx}: index file has no header line")
                continue
            for err in validate(lines[0], load_schema("index-header"), "header"):
                report.errors.append(f"{idx}: {err}")
            report.counts["index-header"] = report.counts.get("index-header", 0) + 1
            row_schema = _index_row_schema(idx)
            if row_schema is not None:
                for i, row in enumerate(lines[1:], start=1):
                    for err in validate(row, load_schema(row_schema), f"row[{i}]"):
                        report.errors.append(f"{idx}: {err}")
                report.counts[row_schema] = report.counts.get(row_schema, 0) + len(lines) - 1

    # annotations
    if layout.annotations.is_dir():
        from .annotations import annotation_key

        for ann in sorted(layout.annotations.glob("*.yaml")):
            data = serialization.loads_yaml(ann.read_text(encoding="utf-8"))
            for err in validate(data, load_schema("annotation"), ann.name):
                report.errors.append(f"{ann}: {err}")
            if isinstance(data, dict) and data.get("key") not in (
                    None, annotation_key(ann)):
                report.errors.append(
                    f"{ann}: key {data.get('key')!r} != filename stem "
                    f"{annotation_key(ann)!r}")
            report.counts["annotation"] = report.counts.get("annotation", 0) + 1

    # state single-file artifacts
    _validate_yaml_file(layout.key_registry, "key-registry", report)
    _validate_yaml_file(layout.identifiers, "identifiers", report)
    _validate_yaml_file(layout.cursors, "cursors", report)

    # frozen-facts snapshots (retention GC) — state, informational, schema-checked
    frozen_dir = layout.state / "frozen-facts"
    if frozen_dir.is_dir():
        for fpath in sorted(frozen_dir.glob("*.yaml")):
            _validate_yaml_file(fpath, "frozen-facts", report)

    # retention.yaml (the GC config) — parse it so a malformed rule is a loud error.
    retention_yaml = domain_root / "retention.yaml"
    if retention_yaml.exists():
        from . import retention as _retention
        try:
            _retention.parse_config(
                serialization.loads_yaml(retention_yaml.read_text(encoding="utf-8")))
            report.counts["retention"] = report.counts.get("retention", 0) + 1
        except _retention.RetentionError as exc:
            report.errors.append(f"{retention_yaml}: {exc}")


def validate_store(root: Path) -> StoreReport:
    """Walk a data root and validate every recognized artifact, zone-aware."""
    root = Path(root)
    report = StoreReport(root=str(root))
    if not root.is_dir():
        report.errors.append(f"data root does not exist: {root}")
        return report
    domains = _find_domains(root)
    if not domains:
        report.infos.append(f"no domains found under {root}")
    for domain_root in domains:
        _validate_domain(domain_root, report)
    return report


# ── fixture-size soft threshold ──────────────────────────────
@dataclass
class SizeCheck:
    total_bytes: int
    limit_bytes: int
    over: bool
    limit_source: str


def _dir_size(root: Path) -> int:
    total = 0
    for p in root.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def check_fixture_size(root: Path) -> SizeCheck:
    """Compute the fixture store size vs. the soft threshold.

    The default limit is the single-source-of-truth constant; a deliberate,
    visible ``<root>/FIXTURE_SIZE_LIMIT_KB`` file (an integer in KB) raises it —
    the human-approved path. Never a hard block: the CLI warns and exits 0.
    """
    root = Path(root)
    limit = FIXTURE_SIZE_SOFT_LIMIT_BYTES
    source = "default constant"
    override = root / FIXTURE_SIZE_OVERRIDE_FILENAME
    if override.exists():
        try:
            limit = int(override.read_text(encoding="utf-8").strip()) * 1024
            source = f"{override.name} override"
        except ValueError:
            pass
    total = _dir_size(root) if root.is_dir() else 0
    return SizeCheck(total_bytes=total, limit_bytes=limit, over=total > limit,
                     limit_source=source)
