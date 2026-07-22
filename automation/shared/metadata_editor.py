"""Formatting-preserving edits for schema-v5 application job metadata."""

from __future__ import annotations

import copy
import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

try:
    from .job_metadata import (
        APPLICATION_SCHEMA_VERSION,
        POSTING_METADATA_FIELDS,
        metadata_field_gaps,
        migrate_job_progress,
        validate_meta,
    )
except ImportError:  # Direct script/shared import used by the existing CLI tools.
    from job_metadata import (
        APPLICATION_SCHEMA_VERSION,
        POSTING_METADATA_FIELDS,
        metadata_field_gaps,
        migrate_job_progress,
        validate_meta,
    )

RecordPath = tuple[str | int, ...]
FieldPath = tuple[str | int, ...]


@dataclass(frozen=True)
class MetadataEditPlan:
    """A checksum-bound, validated metadata edit prepared for an atomic write."""

    before_sha256: str
    output_bytes: bytes
    changed_field_paths: tuple[FieldPath, ...]
    errors: tuple[str, ...]
    changed: bool

    @property
    def before_checksum(self) -> str:
        """Compatibility-friendly name for callers that call the digest a checksum."""
        return self.before_sha256


class MetadataChecksumMismatchError(RuntimeError):
    """Raised when a file changed between planning and writing."""


@dataclass(frozen=True)
class _Edit:
    start: int
    end: int
    replacement: str


def _error_plan(
    raw: bytes,
    before_sha256: str,
    errors: list[str] | tuple[str, ...],
) -> MetadataEditPlan:
    return MetadataEditPlan(
        before_sha256=before_sha256,
        output_bytes=raw,
        changed_field_paths=(),
        errors=tuple(errors),
        changed=False,
    )


def _path_text(path: FieldPath) -> str:
    if not path:
        return "<top-level>"
    rendered = ""
    for part in path:
        if isinstance(part, int):
            rendered += f"[{part}]"
        else:
            rendered += ("." if rendered else "") + part
    return rendered


def _mapping_nodes(
    node: MappingNode,
    *,
    path: FieldPath,
) -> tuple[dict[str, tuple[ScalarNode, Node]], list[str]]:
    items: dict[str, tuple[ScalarNode, Node]] = {}
    errors: list[str] = []
    for key_node, value_node in node.value:
        if not isinstance(key_node, ScalarNode):
            errors.append(
                f"{_path_text(path)} contains a non-scalar YAML key; "
                "manual migration is required"
            )
            continue
        key = key_node.value
        if key in items:
            errors.append(
                f"{_path_text(path + (key,))} is duplicated; "
                "manual migration is required"
            )
            continue
        items[key] = (key_node, value_node)
    return items, errors


def _preferred_newline(text: str) -> str:
    first_lf = text.find("\n")
    if first_lf >= 1 and text[first_lf - 1] == "\r":
        return "\r\n"
    return "\n"


def _line_insertion_index(text: str, node_end: int) -> int:
    """Return the index after the node's physical line, including its comment."""
    newline = text.find("\n", node_end)
    return len(text) if newline < 0 else newline + 1


def _reliable_end_index(node: Node) -> int:
    """End index of ``node``'s own content, safe for edit planning.

    PyYAML's end mark for a BLOCK collection points at the token that follows
    the collection — which may be the next sibling record's line or EOF past
    the trailing newline — so using it as an edit boundary bleeds into text
    that does not belong to the node. Scalars and FLOW collections carry exact
    end marks; for block collections, recurse to the deepest reliable child.
    """
    if isinstance(node, ScalarNode) or getattr(node, "flow_style", False):
        return node.end_mark.index
    end = node.start_mark.index
    if isinstance(node, MappingNode):
        children = [child for pair in node.value for child in pair]
    elif isinstance(node, SequenceNode):
        children = list(node.value)
    else:
        children = []
    for child in children:
        end = max(end, _reliable_end_index(child))
    return end


def _line_suffix(text: str, node_end: int) -> str:
    newline = text.find("\n", node_end)
    if newline < 0:
        return text[node_end:]
    line_end = newline - 1 if newline > 0 and text[newline - 1] == "\r" else newline
    return text[node_end:line_end]


def _dump_entries(
    entries: list[tuple[str, Any]],
    *,
    indent: int,
    newline: str,
    terminate: bool,
) -> str:
    mapping = {key: value for key, value in entries}
    dumped = yaml.safe_dump(
        mapping,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=4096,
    ).rstrip("\n")
    rendered = newline.join(
        (" " * indent) + line if line else line
        for line in dumped.splitlines()
    )
    return rendered + (newline if terminate else "")


def _dump_replacement_value(
    value: Any,
    *,
    parent_indent: int,
    newline: str,
    suffix: str,
) -> str:
    """Render just a mapping value without rewriting its existing YAML key."""
    dumped = yaml.safe_dump(
        {"field": value},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=4096,
    ).rstrip("\n")
    lines = dumped.splitlines()
    first = lines[0]
    inline = first[len("field:"):].lstrip()
    if inline:
        return inline

    nested = newline.join((" " * parent_indent) + line for line in lines[1:])
    replacement = newline + nested
    if suffix:
        # Keep an inline comment or trailing spaces byte-for-byte, but move them
        # onto their own line so a newly block-styled value remains valid YAML.
        replacement += newline + (" " * parent_indent)
    return replacement


def _record_at(document: dict, path: RecordPath) -> dict:
    return document["jobs"][path[1]]


def _posting_records(
    document: dict,
    root_node: MappingNode,
    root_items: dict[str, tuple[ScalarNode, Node]],
) -> tuple[dict[RecordPath, tuple[dict, MappingNode]], list[str]]:
    jobs = document.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        return {}, [
            "schema v4 requires a non-empty jobs list; manual migration is required"
        ]

    jobs_pair = root_items.get("jobs")
    if jobs_pair is None or not isinstance(jobs_pair[1], SequenceNode):
        return {}, [
            "jobs is not represented by a YAML sequence; manual migration is required"
        ]
    jobs_node = jobs_pair[1]
    records: dict[RecordPath, tuple[dict, MappingNode]] = {}
    errors: list[str] = []
    for index, record in enumerate(jobs):
        path: RecordPath = ("jobs", index)
        if index >= len(jobs_node.value) or not isinstance(
            jobs_node.value[index], MappingNode
        ):
            errors.append(
                f"{_path_text(path)} is not a YAML mapping; "
                "manual migration is required"
            )
            continue
        if not isinstance(record, dict):
            errors.append(
                f"{_path_text(path)} is not a mapping; manual migration is required"
            )
            continue
        records[path] = (record, jobs_node.value[index])
    return records, errors


def _apply_edits(raw: bytes, text: str, edits: list[_Edit]) -> bytes:
    byte_offsets = [0]
    offset = 0
    for character in text:
        offset += len(character.encode("utf-8"))
        byte_offsets.append(offset)

    byte_edits = [
        (
            byte_offsets[edit.start],
            byte_offsets[edit.end],
            edit.replacement.encode("utf-8"),
        )
        for edit in edits
    ]
    ordered = sorted(byte_edits, key=lambda edit: (edit[0], edit[1]))
    previous_end = 0
    for start, end, _replacement in ordered:
        if start < previous_end:
            raise ValueError("planned YAML edits overlap")
        previous_end = max(previous_end, end)

    output = raw
    for start, end, replacement in reversed(ordered):
        output = output[:start] + replacement + output[end:]
    return output


def plan_metadata_edit(
    raw: bytes,
    generated_by_path: dict[tuple, dict],
    *,
    verify_idempotence: bool = True,
) -> MetadataEditPlan:
    """Plan a formatting-preserving schema-v4 metadata edit.

    Record paths are ``("jobs", index)`` for entries in the uniform ``jobs``
    sequence (schema v4 always uses a jobs list). The planner fails closed: any
    path, migration, parse, validation, semantic, or idempotence error returns
    the original bytes and no changed field paths.
    """
    before_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return _error_plan(
            raw,
            before_sha256,
            [f"metadata is not valid UTF-8: {exc}"],
        )

    try:
        document = yaml.safe_load(text)
        root_node = yaml.compose(text)
    except yaml.YAMLError as exc:
        return _error_plan(raw, before_sha256, [f"invalid YAML: {exc}"])

    if not isinstance(document, dict) or not isinstance(root_node, MappingNode):
        return _error_plan(
            raw,
            before_sha256,
            ["metadata document must be a top-level YAML mapping"],
        )

    root_items, errors = _mapping_nodes(root_node, path=())
    records, record_errors = _posting_records(document, root_node, root_items)
    errors.extend(record_errors)

    supplied_paths = set(generated_by_path)
    expected_paths = set(records)
    for path in sorted(supplied_paths - expected_paths, key=repr):
        errors.append(
            f"generated metadata record path {_path_text(path)} does not exist "
            "in this document"
        )
    for path in sorted(expected_paths - supplied_paths, key=repr):
        errors.append(
            f"generated metadata is missing exact record path {_path_text(path)}"
        )

    for path in sorted(supplied_paths & expected_paths, key=repr):
        if not isinstance(generated_by_path[path], dict):
            errors.append(
                f"generated metadata for {_path_text(path)} must be a mapping"
            )
            continue
        missing_generated = [
            field for field in POSTING_METADATA_FIELDS
            if field not in generated_by_path[path]
        ]
        if missing_generated:
            errors.append(
                f"generated metadata for {_path_text(path)} is missing fields: "
                f"{', '.join(missing_generated)}"
            )

    record_items: dict[RecordPath, dict[str, tuple[ScalarNode, Node]]] = {}
    for path, (_record, node) in records.items():
        items, item_errors = _mapping_nodes(node, path=path)
        record_items[path] = items
        errors.extend(item_errors)

    replacement_fields: set[FieldPath] = set()
    fields_to_change: dict[RecordPath, list[str]] = {}
    for path in sorted(supplied_paths & expected_paths, key=repr):
        generated = generated_by_path[path]
        if not isinstance(generated, dict):
            continue
        record, _node = records[path]
        changes: list[str] = []
        gaps = metadata_field_gaps(record, generated)
        for field in POSTING_METADATA_FIELDS:
            if field not in generated:
                continue
            if field not in record:
                changes.append(field)
                continue
            current = record[field]
            if (
                current == {}
                or current == ""
                or (current is None and generated[field] is not None)
            ):
                changes.append(field)
                replacement_fields.add(path + (field,))
                continue
            if current is not None and field in gaps:
                errors.append(
                    f"{_path_text(path + (field,))} is populated but has nested "
                    "metadata gaps; manual migration is required"
                )
        fields_to_change[path] = changes

    if errors:
        return _error_plan(raw, before_sha256, errors)

    newline = _preferred_newline(text)
    edits: list[_Edit] = []
    changed_paths: list[FieldPath] = []

    if "job_metadata_schema_version" not in document:
        if root_node.flow_style or not root_node.value:
            return _error_plan(
                raw,
                before_sha256,
                [
                    "top-level YAML mapping cannot accept a block-style schema "
                    "version insertion; manual migration is required"
                ],
            )
        first_key_node = root_node.value[0][0]
        schema_fragment = _dump_entries(
            [("job_metadata_schema_version", APPLICATION_SCHEMA_VERSION)],
            indent=first_key_node.start_mark.column,
            newline=newline,
            terminate=True,
        )
        edits.append(
            _Edit(
                first_key_node.start_mark.index,
                first_key_node.start_mark.index,
                schema_fragment,
            )
        )
        changed_paths.append(("job_metadata_schema_version",))

    expected_document = copy.deepcopy(document)
    if "job_metadata_schema_version" not in expected_document:
        expected_document["job_metadata_schema_version"] = APPLICATION_SCHEMA_VERSION

    for path in sorted(expected_paths, key=repr):
        record, record_node = records[path]
        items = record_items[path]
        generated = generated_by_path[path]
        missing_entries: list[tuple[str, Any]] = []

        for field in POSTING_METADATA_FIELDS:
            if field not in fields_to_change[path]:
                continue
            field_path = path + (field,)
            changed_paths.append(field_path)
            _record_at(expected_document, path)[field] = copy.deepcopy(
                generated[field]
            )
            if field_path not in replacement_fields:
                missing_entries.append((field, generated[field]))
                continue

            key_node, value_node = items[field]
            if value_node.start_mark.index < key_node.end_mark.index:
                return _error_plan(
                    raw,
                    before_sha256,
                    [
                        f"{_path_text(field_path)} uses an aliased placeholder; "
                        "manual migration is required"
                    ],
                )
            parent_indent = key_node.start_mark.column
            value_end = _reliable_end_index(value_node)
            replacement = _dump_replacement_value(
                generated[field],
                parent_indent=parent_indent,
                newline=newline,
                suffix=_line_suffix(text, value_end),
            )
            edits.append(
                _Edit(
                    value_node.start_mark.index,
                    value_end,
                    replacement,
                )
            )

        if missing_entries:
            if record_node.flow_style or not record_node.value:
                return _error_plan(
                    raw,
                    before_sha256,
                    [
                        f"{_path_text(path)} cannot accept block-style metadata "
                        "insertions; manual migration is required"
                    ],
                )
            insertion_index = _line_insertion_index(
                text, _reliable_end_index(record_node)
            )
            indent = record_node.value[0][0].start_mark.column
            at_eof_without_newline = (
                insertion_index == len(text)
                and not text.endswith(("\n", "\r"))
            )
            fragment = _dump_entries(
                missing_entries,
                indent=indent,
                newline=newline,
                terminate=not at_eof_without_newline,
            )
            if at_eof_without_newline:
                fragment = newline + fragment
            edits.append(_Edit(insertion_index, insertion_index, fragment))

    try:
        output_bytes = _apply_edits(raw, text, edits)
    except (IndexError, ValueError) as exc:
        return _error_plan(
            raw,
            before_sha256,
            [f"could not apply planned YAML edits: {exc}"],
        )

    try:
        output_document = yaml.safe_load(output_bytes.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        return _error_plan(
            raw,
            before_sha256,
            [f"planned output is not valid YAML: {exc}"],
        )
    if output_document != expected_document:
        return _error_plan(
            raw,
            before_sha256,
            [
                "planned output changed preexisting semantic values outside "
                "replaceable empty metadata placeholders"
            ],
        )

    validation_errors = validate_meta(output_document)
    if validation_errors:
        return _error_plan(
            raw,
            before_sha256,
            [f"planned output validation failed: {error}" for error in validation_errors],
        )

    changed = output_bytes != raw
    plan = MetadataEditPlan(
        before_sha256=before_sha256,
        output_bytes=output_bytes,
        changed_field_paths=tuple(changed_paths),
        errors=(),
        changed=changed,
    )
    if verify_idempotence:
        second_plan = plan_metadata_edit(
            output_bytes,
            generated_by_path,
            verify_idempotence=False,
        )
        if (
            second_plan.errors
            or second_plan.changed
            or second_plan.output_bytes != output_bytes
        ):
            details = "; ".join(second_plan.errors) or "second plan produced edits"
            return _error_plan(
                raw,
                before_sha256,
                [f"idempotence verification failed: {details}"],
            )
    return plan


def plan_field_updates(
    raw: bytes,
    updates_by_path: dict[RecordPath, dict[str, Any]],
) -> MetadataEditPlan:
    """Plan a formatting-preserving SET of per-job scalar fields.

    ``updates_by_path`` maps a record path ``("jobs", index)`` to a mapping of
    field name -> new value. Unlike ``plan_metadata_edit`` (which only fills
    empty/absent metadata placeholders and refuses to touch populated values), this
    OVERWRITES the named field when present and INSERTS it when absent — the
    machinery ``status.py`` uses to stamp per-job ``status`` / ``status_date`` /
    ``progress`` on a transition. Values are YAML scalars, or a mapping for a
    TOOL-OWNED nested block (``progress``): a mapping value rewrites the whole
    ``key: block`` region, so comments inside that one block do not survive —
    every neighboring line still does.

    It shares every safety property of ``plan_metadata_edit``: it fails closed
    (any parse/path/semantic/validation error returns the original bytes with no
    edits), preserves comments/quoting/blank lines/newline style on untouched text,
    compares the reparsed output to an expected document so nothing outside the
    requested fields changes, and gates on ``validate_meta``. The gate runs WITHOUT
    ``app_dir`` so the folder-consistency rule is not applied here — callers move
    the folder AFTER stamping the new statuses, so the on-disk folder is expected to
    lag the rollup at edit time.
    """
    before_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return _error_plan(raw, before_sha256, [f"metadata is not valid UTF-8: {exc}"])

    try:
        document = yaml.safe_load(text)
        root_node = yaml.compose(text)
    except yaml.YAMLError as exc:
        return _error_plan(raw, before_sha256, [f"invalid YAML: {exc}"])

    if not isinstance(document, dict) or not isinstance(root_node, MappingNode):
        return _error_plan(
            raw, before_sha256,
            ["metadata document must be a top-level YAML mapping"])

    root_items, errors = _mapping_nodes(root_node, path=())
    records, record_errors = _posting_records(document, root_node, root_items)
    errors.extend(record_errors)

    supplied_paths = set(updates_by_path)
    expected_paths = set(records)
    for path in sorted(supplied_paths - expected_paths, key=repr):
        errors.append(
            f"update record path {_path_text(path)} does not exist in this document")
    if errors:
        return _error_plan(raw, before_sha256, errors)

    newline = _preferred_newline(text)
    edits: list[_Edit] = []
    changed_paths: list[FieldPath] = []
    expected_document = copy.deepcopy(document)

    for path in sorted(supplied_paths, key=repr):
        record, record_node = records[path]
        items, item_errors = _mapping_nodes(record_node, path=path)
        errors.extend(item_errors)
        updates = updates_by_path[path]
        if not isinstance(updates, dict):
            errors.append(f"updates for {_path_text(path)} must be a mapping")
            continue

        insert_entries: list[tuple[str, Any]] = []
        for field, value in updates.items():
            field_path = path + (field,)
            _record_at(expected_document, path)[field] = copy.deepcopy(value)
            changed_paths.append(field_path)
            if field in items:
                key_node, value_node = items[field]
                if value_node.start_mark.index < key_node.end_mark.index:
                    errors.append(
                        f"{_path_text(field_path)} uses an aliased placeholder; "
                        "manual migration is required")
                    continue
                parent_indent = key_node.start_mark.column
                suffix = _line_suffix(text, value_node.end_mark.index)
                if isinstance(value_node, ScalarNode):
                    replacement = _dump_replacement_value(
                        value,
                        parent_indent=parent_indent,
                        newline=newline,
                        suffix=suffix,
                    )
                    edits.append(
                        _Edit(
                            value_node.start_mark.index,
                            value_node.end_mark.index,
                            replacement,
                        )
                    )
                elif isinstance(value_node, MappingNode) and isinstance(value, dict):
                    # Tool-owned nested block (e.g. jobs[].progress): rewrite the
                    # whole `key: block` region from the key onward. Clamp the
                    # region to the block's own content — its end mark overshoots.
                    value_end = _reliable_end_index(value_node)
                    rendered = _dump_replacement_value(
                        value,
                        parent_indent=parent_indent,
                        newline=newline,
                        suffix=_line_suffix(text, value_end),
                    )
                    joiner = "" if rendered.startswith(newline) else " "
                    edits.append(
                        _Edit(
                            key_node.start_mark.index,
                            value_end,
                            f"{key_node.value}:{joiner}{rendered}",
                        )
                    )
                else:
                    errors.append(
                        f"{_path_text(field_path)} is not a scalar or tool-owned "
                        "mapping value; manual migration is required")
                    continue
            else:
                insert_entries.append((field, value))

        if insert_entries:
            if record_node.flow_style or not record_node.value:
                errors.append(
                    f"{_path_text(path)} cannot accept block-style field "
                    "insertions; manual migration is required")
                continue
            insertion_index = _line_insertion_index(
                text, _reliable_end_index(record_node)
            )
            indent = record_node.value[0][0].start_mark.column
            at_eof_without_newline = (
                insertion_index == len(text) and not text.endswith(("\n", "\r"))
            )
            fragment = _dump_entries(
                insert_entries,
                indent=indent,
                newline=newline,
                terminate=not at_eof_without_newline,
            )
            if at_eof_without_newline:
                fragment = newline + fragment
            edits.append(_Edit(insertion_index, insertion_index, fragment))

    if errors:
        return _error_plan(raw, before_sha256, errors)

    try:
        output_bytes = _apply_edits(raw, text, edits)
    except (IndexError, ValueError) as exc:
        return _error_plan(
            raw, before_sha256, [f"could not apply planned YAML edits: {exc}"])

    try:
        output_document = yaml.safe_load(output_bytes.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        return _error_plan(
            raw, before_sha256, [f"planned output is not valid YAML: {exc}"])
    if output_document != expected_document:
        return _error_plan(
            raw, before_sha256,
            ["planned output changed values outside the requested field updates"])

    validation_errors = validate_meta(output_document)
    if validation_errors:
        return _error_plan(
            raw, before_sha256,
            [f"planned output validation failed: {error}" for error in validation_errors])

    return MetadataEditPlan(
        before_sha256=before_sha256,
        output_bytes=output_bytes,
        changed_field_paths=tuple(changed_paths),
        errors=(),
        changed=output_bytes != raw,
    )


def plan_v4_to_v5_migration(raw: bytes) -> MetadataEditPlan:
    """Plan the formatting-preserving, deterministic v4 -> v5 migration.

    Three minimal edits per file: the ``job_metadata_schema_version`` scalar is
    rewritten ``4`` -> ``5`` in place, every per-job ``stage`` line is removed,
    and a structured ``progress`` block (``migrate_job_progress``) is appended
    to each job. Everything else — comments, quoting, blank lines, newline
    style, field order — is preserved byte-for-byte.

    Fails closed (original bytes, no edits) on: a non-v4 document (including an
    already-migrated v5 one), YAML/shape problems, a preexisting ``progress``
    key, a job whose facts cannot be retained, or any verification failure
    (reparse mismatch or v5 validation errors on the planned output). No
    migration invents a calendar time, timezone, email source, or completion
    event.
    """
    before_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return _error_plan(raw, before_sha256, [f"metadata is not valid UTF-8: {exc}"])

    try:
        document = yaml.safe_load(text)
        root_node = yaml.compose(text)
    except yaml.YAMLError as exc:
        return _error_plan(raw, before_sha256, [f"invalid YAML: {exc}"])

    if not isinstance(document, dict) or not isinstance(root_node, MappingNode):
        return _error_plan(
            raw, before_sha256,
            ["metadata document must be a top-level YAML mapping"])

    version = document.get("job_metadata_schema_version")
    if version == APPLICATION_SCHEMA_VERSION:
        return _error_plan(
            raw, before_sha256,
            [f"already schema v{APPLICATION_SCHEMA_VERSION}; nothing to migrate"])
    if isinstance(version, bool) or version != 4:
        return _error_plan(
            raw, before_sha256,
            [f"only schema v4 can be migrated to v5; found {version!r}"])

    root_items, errors = _mapping_nodes(root_node, path=())
    records, record_errors = _posting_records(document, root_node, root_items)
    errors.extend(record_errors)
    if errors:
        return _error_plan(raw, before_sha256, errors)

    newline = _preferred_newline(text)
    edits: list[_Edit] = []
    changed_paths: list[FieldPath] = [("job_metadata_schema_version",)]
    expected_document = copy.deepcopy(document)
    expected_document["job_metadata_schema_version"] = APPLICATION_SCHEMA_VERSION

    version_key_node, version_value_node = root_items["job_metadata_schema_version"]
    if not isinstance(version_value_node, ScalarNode) or (
        version_value_node.start_mark.index < version_key_node.end_mark.index
    ):
        return _error_plan(
            raw, before_sha256,
            ["job_metadata_schema_version is not a plain scalar; "
             "manual migration is required"])
    edits.append(
        _Edit(
            version_value_node.start_mark.index,
            version_value_node.end_mark.index,
            str(APPLICATION_SCHEMA_VERSION),
        )
    )

    for path in sorted(records, key=repr):
        record, record_node = records[path]
        items, item_errors = _mapping_nodes(record_node, path=path)
        errors.extend(item_errors)
        if "progress" in record:
            errors.append(
                f"{_path_text(path)}.progress already exists in a v4 document; "
                "manual migration is required")
            continue
        try:
            progress = migrate_job_progress(record.get("status"), record.get("stage"))
        except ValueError as exc:
            errors.append(f"{_path_text(path)}: {exc}")
            continue

        expected_record = _record_at(expected_document, path)
        expected_record.pop("stage", None)
        expected_record["progress"] = copy.deepcopy(progress)
        changed_paths.append(path + ("progress",))

        if "stage" in items:
            stage_key_node, stage_value_node = items["stage"]
            if not isinstance(stage_value_node, ScalarNode):
                errors.append(
                    f"{_path_text(path + ('stage',))} is not a scalar; "
                    "manual migration is required")
                continue
            if record_node.value and record_node.value[0][0] is stage_key_node:
                errors.append(
                    f"{_path_text(path + ('stage',))} is the first key of its "
                    "entry; manual migration is required")
                continue
            line_start = (
                stage_key_node.start_mark.index - stage_key_node.start_mark.column
            )
            line_end = _line_insertion_index(text, stage_value_node.end_mark.index)
            edits.append(_Edit(line_start, line_end, ""))
            changed_paths.append(path + ("stage",))

        if record_node.flow_style or not record_node.value:
            errors.append(
                f"{_path_text(path)} cannot accept a block-style progress "
                "insertion; manual migration is required")
            continue
        insertion_index = _line_insertion_index(
            text, _reliable_end_index(record_node)
        )
        indent = record_node.value[0][0].start_mark.column
        at_eof_without_newline = (
            insertion_index == len(text) and not text.endswith(("\n", "\r"))
        )
        fragment = _dump_entries(
            [("progress", progress)],
            indent=indent,
            newline=newline,
            terminate=not at_eof_without_newline,
        )
        if at_eof_without_newline:
            fragment = newline + fragment
        edits.append(_Edit(insertion_index, insertion_index, fragment))

    if errors:
        return _error_plan(raw, before_sha256, errors)

    try:
        output_bytes = _apply_edits(raw, text, edits)
    except (IndexError, ValueError) as exc:
        return _error_plan(
            raw, before_sha256, [f"could not apply planned YAML edits: {exc}"])

    try:
        output_document = yaml.safe_load(output_bytes.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        return _error_plan(
            raw, before_sha256, [f"planned output is not valid YAML: {exc}"])
    if output_document != expected_document:
        return _error_plan(
            raw, before_sha256,
            ["planned migration changed values outside the version, stage, and "
             "progress fields"])

    validation_errors = validate_meta(output_document)
    if validation_errors:
        return _error_plan(
            raw, before_sha256,
            [f"planned output validation failed: {error}"
             for error in validation_errors])

    return MetadataEditPlan(
        before_sha256=before_sha256,
        output_bytes=output_bytes,
        changed_field_paths=tuple(changed_paths),
        errors=(),
        changed=output_bytes != raw,
    )


def atomic_write_bytes(
    path: str | os.PathLike[str],
    data: bytes,
    expected_sha256: str,
) -> None:
    """Atomically replace *path* only when its current SHA-256 still matches."""
    destination = Path(path)
    def assert_checksum() -> None:
        actual_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise MetadataChecksumMismatchError(
                f"checksum mismatch for {destination}: expected {expected_sha256}, "
                f"found {actual_sha256}"
            )

    assert_checksum()

    file_stat = destination.stat()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    try:
        os.fchmod(descriptor, stat.S_IMODE(file_stat.st_mode))
        with os.fdopen(descriptor, "wb") as temporary:
            descriptor = -1
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        # Recheck after preparing and syncing the replacement. This catches edits
        # made during the write window before the atomic rename.
        assert_checksum()
        os.replace(temporary_name, destination)

        directory_flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        directory_descriptor = os.open(destination.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
