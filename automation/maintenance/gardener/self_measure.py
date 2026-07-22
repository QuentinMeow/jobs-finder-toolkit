"""gardener routine: recompute the pipeline funnel + memory-health metrics.

Self-measurement: derive the application funnel
from the status folders (matching status.py) plus the discovered count from the
derived applications-log, LESSONS staleness counts, and the instruction-budget
summary. Prints YAML to stdout.

``--apply`` writes ``metrics.yaml`` NEXT TO the applications-log (inside the
overlay via config paths, i.e. ``<applications_root>/0_profile/metrics.yaml``) —
never into the toolkit tree.

Usage:
    .venv/bin/python automation/maintenance/gardener/self_measure.py
    .venv/bin/python automation/maintenance/gardener/self_measure.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

try:
    import config  # noqa: E402
except ImportError:  # pragma: no cover
    config = C.config

# Status label -> on-disk numbered folder. _common bootstraps automation/shared onto
# sys.path, so this imports the canonical mapping (the same one status.py uses)
# instead of hand-maintaining a copy.
from layout import STATUS_DIRS  # noqa: E402


def _count_apps(status_dir: Path) -> int:
    if not status_dir.is_dir():
        return 0
    return sum(1 for c in status_dir.iterdir() if c.is_dir() and not c.name.startswith("."))


def _discovered_count(profile_dir: Path) -> int | None:
    log = profile_dir / "applications-log.yaml"
    if not log.is_file():
        return None
    try:
        import yaml
        data = yaml.safe_load(log.read_text()) or {}
        if isinstance(data.get("count"), int):
            return data["count"]
        return len(data.get("postings") or [])
    except Exception:
        return None


def _lessons_metrics() -> dict:
    policy = C.retention()
    confirm_days = policy["lesson_confirm_days"]
    ref = C.today()
    sections = stale = untagged = 0
    for lessons in C.lessons_files():
        for sec in C.parse_lessons(lessons):
            sections += 1
            if sec["status"] is None:
                untagged += 1
                continue
            d = C.parse_iso(sec["confirmed"])
            if d and (ref - d).days > confirm_days:
                stale += 1
    return {"tagged_sections": sections, "stale_over_confirm_days": stale,
            "untagged_sections": untagged, "confirm_days": confirm_days}


def _budget_metrics() -> dict:
    metrics_root = C.REPO_ROOT / "automation" / "metrics"
    if str(metrics_root) not in sys.path:
        sys.path.insert(0, str(metrics_root))
    try:
        import instruction_budget as ib
        rows, violations = ib.build_report(C.REPO_ROOT)
    except Exception as exc:  # pragma: no cover
        return {"error": f"instruction_budget unavailable: {exc}"}
    agents = next((r for r in rows if r["path"] == "AGENTS.md"), None)
    return {
        "instruction_files": len(rows),
        "over_budget": len(violations),
        "agents_md_lines": agents["lines"] if agents else None,
        "agents_md_budget": agents["budget"] if agents else None,
    }


def collect() -> dict:
    apps_root = config.applications_root()
    profile_dir = apps_root / "0_profile"
    funnel = {label: _count_apps(apps_root / folder)
              for label, folder in STATUS_DIRS.items()}
    total = sum(funnel.values())
    return {
        "generated": C.today().isoformat(),
        "applications_root": C.rel(apps_root),
        "funnel": {
            "discovered": _discovered_count(profile_dir),
            **funnel,
            "total_tracked": total,
        },
        "lessons": _lessons_metrics(),
        "instruction_budget": _budget_metrics(),
        "policy_doc": C.DESIGN_DOC,
    }


def _to_yaml(data: dict) -> str:
    try:
        import yaml
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    except Exception:  # pragma: no cover — trivial fallback
        import json
        return json.dumps(data, indent=2)


def run(apply: bool = False) -> int:
    C.print_header("self-measure", apply)
    metrics = collect()
    text = _to_yaml(metrics)
    print()
    print(text, end="" if text.endswith("\n") else "\n")
    if apply:
        out = config.applications_root() / "0_profile" / "metrics.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        header = (f"# gardener self-measure snapshot ({metrics['generated']}). "
                  f"Regenerable; do not hand-edit.\n"
                  f"# Funnel counts the derived-rollup status folders (each folder "
                  f"reflects its applications' per-job status rollup) + the "
                  f"applications-log ({C.DESIGN_DOC}).\n")
        out.write_text(header + text, encoding="utf-8")
        print(f"  APPLY: wrote {C.rel(out)}")
    else:
        print("  DRY-RUN: printed only. --apply writes "
              "<applications_root>/0_profile/metrics.yaml.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write metrics.yaml beside the applications-log")
    return run(ap.parse_args(argv).apply)


if __name__ == "__main__":
    raise SystemExit(main())
