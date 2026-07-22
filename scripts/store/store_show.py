"""Resolve an entity key to its derived record and (optionally) its raw blob.

The sanctioned raw-access path for investigations: ``store_show.py <entity-key>``
prints the entity YAML by default; ``--raw`` follows provenance to the payload
blob, decompresses it, and pretty-prints it. When the blob is ``not-synced-here``
(normal on the multi-laptop setup) ``--raw`` refuses informatively, naming the
blob and the manual-sync remedy — it never pretends the bytes are here.

Usage:
    .venv/bin/python scripts/store/store_show.py gh-1234567 --data-root examples/data
    .venv/bin/python scripts/store/store_show.py gh-1234567 --raw --data-root examples/data
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[1] / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import config  # noqa: E402
from store import blobs as _blobs  # noqa: E402
from store import resolver, serialization  # noqa: E402
from store.paths import domain_layout  # noqa: E402


def _resolve_data_root(arg: str | None) -> Path | None:
    if arg:
        return Path(arg).expanduser().resolve()
    return config.data_root()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("entity_key", help="entity key, e.g. gh-1234567")
    parser.add_argument("--domain", default="jobs", help="store domain (default: jobs)")
    parser.add_argument("--data-root", default=None,
                        help="store data root (default: config.data_root())")
    parser.add_argument("--raw", action="store_true",
                        help="decompress and print the raw payload blob")
    args = parser.parse_args(argv)

    data_root = _resolve_data_root(args.data_root)
    if data_root is None:
        print("store not configured (set paths.data_root or JOBHUNT_DATA_ROOT).")
        return 0

    layout = domain_layout(data_root, args.domain)
    found = resolver.load_entity(layout, args.entity_key)
    if found is None:
        print(f"no entity {args.entity_key!r} in domain {args.domain!r} "
              f"under {data_root}", file=sys.stderr)
        return 1
    yaml_path, entity = found

    if not args.raw:
        print(f"# {yaml_path}")
        print(serialization.dumps_yaml(entity), end="")
        return 0

    payload = resolver.resolve_blob(layout, entity)
    if payload is None:
        print(f"entity {args.entity_key!r} records no payload-bearing fetch "
              f"(nothing to show with --raw).", file=sys.stderr)
        return 1

    sha = payload["blob"]
    ext = _blobs.ext_for_content_type(payload.get("content_type"))
    blobstore = _blobs.BlobStore(layout.blobs)
    state = blobstore.state(sha, ext)
    if state != _blobs.PRESENT:
        if state == _blobs.NOT_SYNCED_HERE:
            print(f"blob {sha} is not-synced-here — the manifest is present but the "
                  f"payload has not been synced to this machine.\n"
                  f"Remedy: manually sync raw/_blobs/{sha[:2]}/{sha}.* from the "
                  f"machine that captured it.", file=sys.stderr)
        elif state == _blobs.PRUNED:
            print(f"blob {sha} was pruned by retention (a tombstone exists); the "
                  f"raw bytes are gone.", file=sys.stderr)
        else:
            print(f"blob {sha} is CORRUPT (fails verify-on-read).", file=sys.stderr)
        return 2

    data = blobstore.read(sha, ext)
    ctype = (payload.get("content_type") or "").lower()
    if "json" in ctype:
        try:
            print(json.dumps(json.loads(data), indent=2, sort_keys=True,
                             ensure_ascii=False))
            return 0
        except ValueError:
            pass
    sys.stdout.buffer.write(data)
    if not data.endswith(b"\n"):
        sys.stdout.buffer.write(b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
