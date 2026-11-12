"""Turn the Phase 0 probe logs into reports/tool_evaluation.md.

Run:
    python tools/phase0/make_report.py --logs "a/phase0_log.txt b/phase0_log.txt" \
        --out reports/tool_evaluation.md

The logs contain two kinds of RESULT lines:
    RESULT <name> exit=<code>                  (shell probes)
    RESULT {"step": "...", ...}                (Python probes, JSON)
Both are normalised into rows so the report reads the same either way.
"""

import argparse
import json
import os
import re
import sys

SHELL_RESULT = re.compile(r"^RESULT (\S+) exit=(\d+)\s*$")
PY_RESULT = re.compile(r"^RESULT (\{.*\})\s*$")

# What each probe means for the pipeline, keyed by the probe's name.
DECISIONS = {
    "blender_checksum": ("Blender download", "verified against the vendor's published SHA-256"),
    "blender_env": ("Blender headless", "conversion hub; every other 3D tool routes through it"),
    "gltf_export": ("Blender glTF 2.0 exporter", "the only way assets leave Blender"),
    "render_cycles": ("Cycles CPU render", "preview renderer with no GPU and no display"),
    "render_workbench": ("Workbench via Xvfb + llvmpipe", "fast preview renderer if it works"),
    "render_eevee": ("EEVEE Next via Xvfb + llvmpipe", "material preview renderer if it works"),
    "gltfpack_help": ("gltfpack", "LOD simplification; -cc and -tc stay off until Godot accepts them"),
    "gltfpack_simplify": ("gltfpack -si", "LOD generation"),
    "godot_version": ("Godot", "import gate and later the game runtime"),
    "godot_import": ("Godot headless import", "proves Godot accepts Blender's GLB output"),
    "godot_load": ("Godot headless load", "proves the imported mesh survives to a scene node"),
    "godot_import_gltfpack": ("Godot import of gltfpack output", "decides whether gltfpack is safe in the LOD step"),
    "godot_load_gltfpack": ("Godot load of gltfpack output", "same decision, one step further"),
    "mpfb2": ("MPFB2 human", "all human bodies, heads and base clothing"),
    "mtree_register": ("Modular Tree", "procedural trees for the rainforest species"),
    "gltf_transform_install": ("glTF-Transform CLI", "dedup, prune, animation resample, texture resize"),
    "gltf_transform_version": ("glTF-Transform version", "pin recorded for tools/TOOLS.md"),
    "polyhaven": ("Poly Haven API", "CC0 PBR textures, HDRIs and scanned models"),
    "infinigen_install": ("Infinigen install", "rocks, plants, fungi, clouds, materials"),
    "infinigen_import": ("Infinigen import", "same decision, checked after install"),
    "infinigen_cli": ("Infinigen asset generator CLI", "individual-asset generation on CPU"),
}

FAILURE_CONSEQUENCE = {
    "render_cycles": "no preview renderer at all; previews would have to move to a paid GPU runner or be dropped",
    "render_workbench": "previews fall back to Cycles CPU only",
    "render_eevee": "previews fall back to Cycles CPU only",
    "godot_import": "the import gate cannot run; every asset would ship unverified",
    "godot_import_gltfpack": "gltfpack is dropped and LODs come from Blender's Decimate modifier",
    "mpfb2": "humans fall back to a custom generator, with the fidelity loss the brief already expects",
    "mtree_register": "trees fall back to custom generators plus Infinigen bush/plant factories",
    "infinigen_install": "rocks and plants fall back to custom generators plus Poly Haven scans",
    "polyhaven": "no CC0 texture source; materials fall back to procedural baking only",
}


def parse(path):
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            match = SHELL_RESULT.match(line)
            if match:
                rows.append(
                    {
                        "name": match.group(1),
                        "ok": match.group(2) == "0",
                        "detail": "exit=%s" % match.group(2),
                    }
                )
                continue
            match = PY_RESULT.match(line)
            if match:
                try:
                    payload = json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
                name = payload.pop("step", "unknown")
                ok = bool(payload.pop("ok", True))
                rows.append(
                    {
                        "name": name,
                        "ok": ok,
                        "detail": ", ".join("%s=%s" % (k, v) for k, v in sorted(payload.items())),
                    }
                )
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", default="")
    parser.add_argument("--out", default="reports/tool_evaluation.md")
    args = parser.parse_args()

    paths = [p for p in args.logs.split() if p and os.path.exists(p)]
    rows = []
    for path in paths:
        rows.extend(parse(path))

    # A probe run more than once keeps its last result, which is the run that counted.
    latest = {}
    for row in rows:
        latest[row["name"]] = row
    ordered = list(latest.values())

    lines = []
    lines.append("# Tool evaluation (Phase 0)")
    lines.append("")
    lines.append(
        "Generated by `tools/phase0/make_report.py` from the Phase 0 workflow logs. "
        "Every entry below is a probe that ran on a GitHub-hosted runner; nothing here is "
        "estimated or assumed."
    )
    lines.append("")
    if not paths:
        lines.append("**No probe logs were found.** The Phase 0 workflow did not produce output.")
        lines.append("")
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        print("\n".join(lines))
        return 1

    lines.append("## Probes")
    lines.append("")
    lines.append("| Probe | Result | Detail | Consequence if it failed |")
    lines.append("|---|---|---|---|")
    for row in ordered:
        label, purpose = DECISIONS.get(row["name"], (row["name"], ""))
        status = "PASS" if row["ok"] else "FAIL"
        consequence = FAILURE_CONSEQUENCE.get(row["name"], "")
        if row["ok"]:
            consequence = purpose
        lines.append(
            "| %s | %s | %s | %s |" % (label, status, row["detail"], consequence)
        )
    lines.append("")

    failed = [r for r in ordered if not r["ok"]]
    lines.append("## Outcome")
    lines.append("")
    lines.append("- Probes run: **%d**" % len(ordered))
    lines.append("- Passed: **%d**" % (len(ordered) - len(failed)))
    lines.append("- Failed: **%d**" % len(failed))
    if failed:
        lines.append("")
        lines.append("Failed probes, and the fallback the brief already defines for each:")
        lines.append("")
        for row in failed:
            label, _ = DECISIONS.get(row["name"], (row["name"], ""))
            consequence = FAILURE_CONSEQUENCE.get(row["name"], "see the probe detail")
            lines.append("- **%s** — %s" % (label, consequence))
    lines.append("")

    text = "\n".join(lines)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
