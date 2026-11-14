#!/usr/bin/env python3
"""Record built assets: turn generator reports plus committed files into assets/built.json.

Run:
    python tools/record_built.py \
        --report artifacts/terrain/report.json \
        --report artifacts/terrain/hydrology.json \
        --report artifacts/terrain/surfaces.json \
        --dir assets/terrain --out assets/built.json \
        --gate composition=pass --gate determinism=pass

Why this exists: "built" used to be an assertion. A record needs a path, a SHA-256, an input hash,
a tool version and gate results, but nothing wrote them, so every record stayed `pending` and the
evidence for the Phase 2 maps — an artifact that expires — was the only evidence there was.

This writes that evidence down. It refuses to record anything it has not checked:

  * the committed file must exist in `--dir`
  * its SHA-256 must equal the one the generator reported, so a file that changed after the
    generator measured it is not signed off
  * at least one `--gate` must be given, because a built record with no measured result is the
    assertion the manifest validator exists to refuse

Existing entries for other assets are preserved; rerunning only rewrites the ones named.
"""

import argparse
import hashlib
import json
import os
import sys

EXTENSIONS = (".png", ".json", ".tres", ".glb", ".ogg", ".ttf")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def find_file(directory, name):
    for extension in EXTENSIONS:
        candidate = os.path.join(directory, name + extension)
        if os.path.exists(candidate):
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="append", default=[], required=True)
    parser.add_argument("--dir", required=True, help="where the built files were committed")
    parser.add_argument("--out", default="assets/built.json")
    parser.add_argument(
        "--manifest",
        default="",
        help="the authored manifest; when given, an asset it does not declare is reported and "
        "not recorded, because built evidence for a name the plan does not have is a failure",
    )
    parser.add_argument(
        "--gate",
        action="append",
        default=[],
        metavar="NAME=RESULT",
        help="a measured result for this build, e.g. composition=pass; at least one is required",
    )
    args = parser.parse_args()

    declared = None
    if args.manifest:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import build_manifest  # noqa: E402 - same directory, imported only when needed

        with open(args.manifest, encoding="utf-8") as handle:
            authored = json.load(handle)
        records, problems = build_manifest.build(authored)
        if problems:
            print(
                "refusing: the manifest does not build (%s), so there is nothing to record against"
                % problems[0],
                file=sys.stderr,
            )
            return 1
        declared = {record["name"] for record in records}

    gate_results = {}
    for item in args.gate:
        key, _, value = item.partition("=")
        if not key or not value:
            print("--gate needs NAME=VALUE, got %r" % item, file=sys.stderr)
            return 1
        gate_results[key] = value
    if not gate_results:
        print(
            "refusing: no --gate given, so this build measured nothing. A record marked built "
            "without a gate result is an assertion, not evidence.",
            file=sys.stderr,
        )
        return 1

    entries = {}
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as handle:
            entries = json.load(handle).get("built", {})

    problems = []
    recorded = 0
    for report_path in args.report:
        with open(report_path, encoding="utf-8") as handle:
            report = json.load(handle)
        for asset in report.get("assets", []):
            name = asset["name"]
            if declared is not None and name not in declared:
                problems.append(
                    "%s: generator report names an asset the manifest does not declare" % name
                )
                continue
            path = find_file(args.dir, name)
            if path is None:
                problems.append("%s: no committed file in %s" % (name, args.dir))
                continue
            measured = sha256_file(path)
            if measured != asset.get("sha256"):
                problems.append(
                    "%s: the committed file hashes to %s but the generator recorded %s — the file "
                    "changed after it was measured" % (name, measured[:16], str(asset.get("sha256"))[:16])
                )
                continue
            entries[name] = {
                "status": "built",
                "path": path,
                "sha256": measured,
                "input_hash": asset.get("input_hash", ""),
                "tool_version": asset.get("tool_version", ""),
                "size_kb": asset.get("size_kb") or os.path.getsize(path) // 1024,
                "gate_results": dict(gate_results),
            }
            recorded += 1

    if problems:
        print("refusing to record built evidence:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1

    if recorded == 0:
        print(
            "refusing: the reports named no assets, so this wrote nothing and verified nothing",
            file=sys.stderr,
        )
        return 1

    payload = {
        "schema_version": 1,
        "name": "built",
        "description": "Evidence for assets that exist in the repository: path, SHA-256, input hash, tool version and the gates that ran. Written by tools/record_built.py; read by tools/build_manifest.py. A name here that the manifest does not declare is a failure, so deleting an asset means deleting its evidence too.",
        "built": entries,
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")

    print("recorded %d built asset(s) in %s (%d total)" % (recorded, args.out, len(entries)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
