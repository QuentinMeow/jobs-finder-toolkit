"""Replay the frozen sponsorship verdict matrix against the current classifier.

`assess_sponsorship` has been revised five times, and the first three revisions
each fixed one direction of the same rule by reopening the other. What finally
worked — recorded as method in
`memory/decisions/sponsorship-an-unsettled-denial-is-review-not-a-silent-drop.md`
— was a matrix of readings measured BEFORE and AFTER every change, with "change
nothing" an allowed outcome for any row. It was rebuilt by hand each time and
never tracked. This replays the tracked one, so the before/after comparison is
mechanical rather than a reviewer's memory.

Three commands, and they answer different questions:

    --check   Does the classifier still agree with every asserted reading?
              Exit 1 on the first disagreement. This is the gate.
    --diff    Which rows read differently from the FROZEN baseline, and was
              each move predicted? Always exits 0 — it is a report, not a gate.
    --json    The same content as `--diff`, machine-readable.

A row asserts `expect` when it carries one and `baseline` otherwise, so a
deliberate, reviewed move is recorded in the file rather than argued in a commit
message. `expected-unchanged` rows may never carry an `expect` block: that is
what makes them tripwires, and the lint below refuses the file if one does.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
for _path in (HERE, HERE / "_vendor"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from job_metadata import assess_sponsorship  # noqa: E402

MATRIX_PATH = HERE.parent / "filter_variants" / "sponsorship_verdict_matrix.yaml"

# The fields a move is measured over. `reason` is deliberately excluded: it is
# prose for a human, and pinning it would make every wording edit a matrix move.
FIELDS = ("decision", "verdict", "confidence", "evidence", "rule_ids")
CHANGE_VALUES = {"expected-change", "expected-unchanged"}


def load_matrix(path: Path = MATRIX_PATH) -> dict:
    data = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise ValueError(f"matrix must be a mapping with a `rows` list: {path}")
    return data


def lint_matrix(matrix: dict) -> list[str]:
    """Structural rules that keep the matrix from quietly becoming a rubber stamp."""
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(matrix["rows"]):
        where = row.get("id") or f"row[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{where}: row must be a mapping")
            continue
        if not row.get("id"):
            errors.append(f"{where}: missing id")
        elif row["id"] in seen:
            errors.append(f"{where}: duplicate id")
        else:
            seen.add(row["id"])
        if row.get("change") not in CHANGE_VALUES:
            errors.append(f"{where}: change must be one of {sorted(CHANGE_VALUES)}")
        if not isinstance(row.get("text"), str) or not row["text"].strip():
            errors.append(f"{where}: missing text")
        for block in ("baseline", "expect"):
            value = row.get(block)
            if value is None:
                if block == "baseline":
                    errors.append(f"{where}: missing baseline")
                continue
            missing = [field for field in FIELDS if field not in value]
            if missing:
                errors.append(f"{where}: {block} is missing {missing}")
        # A tripwire that carries an `expect` block has stopped being a tripwire.
        if row.get("change") == "expected-unchanged" and "expect" in row:
            errors.append(
                f"{where}: expected-unchanged rows may not carry an `expect` "
                f"block — flip it to expected-change and say why in `note`")
        # An `expect` identical to `baseline` is noise that hides a real move.
        if "expect" in row and row["expect"] == row["baseline"]:
            errors.append(f"{where}: `expect` equals `baseline`; delete it")
    return errors


def _reading(text: str) -> dict:
    assessment = assess_sponsorship(text)
    return {field: (list(assessment[field]) if isinstance(assessment[field], list)
                    else assessment[field])
            for field in FIELDS}


def replay(matrix: dict) -> list[dict]:
    """One record per row: what it reads now, what it asserts, what it froze."""
    records = []
    for row in matrix["rows"]:
        live = _reading(row["text"])
        asserted = row.get("expect") or row["baseline"]
        asserted = {field: asserted[field] for field in FIELDS}
        baseline = {field: row["baseline"][field] for field in FIELDS}
        records.append({
            "id": row["id"],
            "group": row.get("group", ""),
            "change": row["change"],
            "live": live,
            "asserted": asserted,
            "baseline": baseline,
            "agrees": live == asserted,
            "moved": live != baseline,
        })
    return records


def _summarize(record: dict, block: str) -> str:
    value = record[block]
    return f"{value['decision']}/{value['verdict']}/{value['confidence']}"


def _explain(record: dict, left: str, right: str) -> list[str]:
    lines = []
    for field in FIELDS:
        if record[left][field] != record[right][field]:
            lines.append(f"      {field}: {record[left][field]!r}")
            lines.append(f"      {' ' * len(field)}-> {record[right][field]!r}")
    return lines


def cmd_check(records: list[dict]) -> int:
    disagreeing = [record for record in records if not record["agrees"]]
    for record in disagreeing:
        print(f"MATRIX DISAGREEMENT {record['id']}", file=sys.stderr)
        print(f"    asserted {_summarize(record, 'asserted')} "
              f"but reads {_summarize(record, 'live')}", file=sys.stderr)
        for line in _explain(record, "asserted", "live"):
            print(line, file=sys.stderr)
    if disagreeing:
        print(f"\n{len(disagreeing)} of {len(records)} matrix rows disagree with "
              f"their asserted reading.", file=sys.stderr)
        return 1
    print(f"sponsorship verdict matrix clean: {len(records)} rows agree "
          f"with their asserted reading")
    return 0


def cmd_diff(records: list[dict]) -> int:
    moved = [record for record in records if record["moved"]]
    print(f"sponsorship verdict matrix: {len(records)} rows, "
          f"{len(moved)} moved from the frozen baseline")
    for record in moved:
        flag = ("as predicted" if record["change"] == "expected-change"
                else "*** UNPREDICTED ***")
        print(f"  MOVED  {record['id']}  [{flag}]")
        print(f"    {_summarize(record, 'baseline')} "
              f"-> {_summarize(record, 'live')}")
        for line in _explain(record, "baseline", "live"):
            print(line)
    stationary = [record for record in records
                  if record["change"] == "expected-change" and not record["moved"]]
    for record in stationary:
        print(f"  STILL  {record['id']}  [expected-change, did not move — "
              f"an allowed outcome]")
    unpredicted = [record for record in moved
                   if record["change"] == "expected-unchanged"]
    print(f"\n{len(moved)} moved, {len(unpredicted)} of them unpredicted, "
          f"{len(stationary)} predicted moves did not happen")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--matrix", type=Path, default=MATRIX_PATH)
    parser.add_argument("--check", action="store_true",
                        help="fail when a row disagrees with its asserted reading")
    parser.add_argument("--diff", action="store_true",
                        help="report every row that moved from the frozen baseline")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable form of --diff")
    args = parser.parse_args(argv)

    matrix = load_matrix(args.matrix)
    errors = lint_matrix(matrix)
    if errors:
        for error in errors:
            print(f"MATRIX LINT {error}", file=sys.stderr)
        return 2

    records = replay(matrix)
    if args.json:
        print(json.dumps(records, indent=2, sort_keys=True))
        return 0
    if args.diff:
        return cmd_diff(records)
    return cmd_check(records)


if __name__ == "__main__":
    raise SystemExit(main())
