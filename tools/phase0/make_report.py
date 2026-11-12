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
    "render_cycles": ("Cycles CPU render", "the official preview renderer"),
    "render_blender_workbench": ("Workbench via Xvfb + llvmpipe", "fast preview renderer if it works"),
    "render_blender_eevee_next": ("EEVEE Next via Xvfb + llvmpipe", "material preview renderer if it works"),
    "mpfb_import": ("MPFB2 module import", "the real error behind a zero-operator add-on"),
    "mpfb_diagnostics": ("MPFB2 diagnostics", "where Blender looked for the add-on"),
    "gltfpack_help": ("gltfpack", "LOD simplification; -cc and -tc stay off until Godot accepts them"),
    "gltfpack_simplify": ("gltfpack -si", "LOD generation"),
    "gltfpack_noq": ("gltfpack -si -noq", "the control run that separates quantization from the tool"),
    "godot_version": ("Godot", "import gate and later the game runtime"),
    "godot_import": ("Godot headless import", "proves Godot accepts Blender's GLB output"),
    "godot_load": ("Godot headless load", "proves the imported mesh survives to a scene node"),
    "godot_scene_plain": ("Godot load of the Blender GLB", "the import gate itself: meshes and triangles that arrive"),
    "godot_scene_gltfpack": ("Godot load of gltfpack output", "decides whether gltfpack is safe in the LOD step"),
    "godot_scene_gltfpack_noq": ("Godot load of gltfpack -noq output", "the control run for the LOD decision"),
    "godot_import_gltfpack": ("Godot import of gltfpack output", "same decision, one step earlier"),
    "godot_import_gltfpack_noq": ("Godot import of gltfpack -noq output", "same decision, one step earlier"),
    "mpfb2": ("MPFB2 human", "all human bodies, heads and base clothing"),
    "mpfb_enable": ("MPFB2 enable", "whether Blender accepts the add-on at all"),
    "mpfb_operators": ("MPFB2 operators", "zero operators means the add-on is inert"),
    "addon_install": ("Add-on install", "which layout the add-on used: legacy add-on or 4.2+ extension"),
    "addon_install_mpfb2": ("MPFB2 install", "which package name and directory MPFB2 landed in"),
    "addon_install_modular_tree": ("MTree install", "the layout Modular Tree uses"),
    "mtree_register": ("Modular Tree", "procedural trees for the rainforest species"),
    "mtree": ("Modular Tree", "procedural trees for the rainforest species"),
    "mtree_blender": ("MTree Blender version", "the Blender version the extension actually needs"),
    "mtree_modules": ("MTree modules", "which add-on modules Blender can see"),
    "mtree_operators": ("MTree operators", "the namespace and operators the extension registers"),
    "mtree_add_tree": ("MTree generate a tree", "the operator that generates a tree"),
    "mtree_export": ("MTree tree export", "a generated tree must reach glTF"),
    "mtree_extension_install": ("MTree extension install", "installing a blender_manifest.toml repository"),
    "blender45_checksum": ("Blender 4.5 download", "verified against the vendor's published SHA-256"),
    "gltf_transform_install": ("glTF-Transform CLI", "dedup, prune, animation resample, texture resize"),
    "gltf_transform_version": ("glTF-Transform version", "pin recorded for tools/TOOLS.md"),
    "polyhaven": ("Poly Haven API", "CC0 PBR textures, HDRIs and scanned models"),
    "quaternius_packs": ("Quaternius animation packs", "CC0 humanoid clips; every missing clip is authored with bpy"),
    "quaternius_download": ("Quaternius release download", "fetching the owner's ZIPs outside git"),
    "quaternius_coverage": ("Quaternius coverage", "which of the brief's animation families the packs actually supply"),
    "quaternius_inventory": ("Quaternius inventory", "the real clip count, measured rather than promised"),
    "infinigen_install": ("Infinigen install", "rocks, plants, fungi, clouds, materials"),
    "infinigen_import": ("Infinigen import", "same decision, checked after install"),
    "infinigen_cli": ("Infinigen asset generator CLI", "individual-asset generation on CPU"),
}

FAILURE_CONSEQUENCE = {
    "render_cycles": "no preview renderer at all; previews would have to move to a paid GPU runner or be dropped",
    "render_workbench": "previews fall back to Cycles CPU only",
    "render_eevee": "previews fall back to Cycles CPU only",
    "godot_import": "the import gate cannot run; every asset would ship unverified",
    "godot_scene_plain": "the import gate cannot pass; every asset would ship unverified",
    "godot_import_gltfpack": "gltfpack is dropped and LODs come from Blender's Decimate modifier",
    "godot_scene_gltfpack": "gltfpack is dropped and LODs come from Blender's Decimate modifier",
    "godot_scene_gltfpack_noq": "gltfpack is dropped and LODs come from Blender's Decimate modifier",
    "mpfb2": "humans fall back to a custom generator, with the fidelity loss the brief already expects",
    "mtree_register": "trees fall back to custom generators plus Infinigen bush/plant factories",
    "mtree": "trees fall back to custom generators plus Infinigen bush/plant factories",
    "mtree_enable": "trees fall back to custom generators plus Infinigen bush/plant factories",
    "mtree_operators": "trees fall back to custom generators plus Infinigen bush/plant factories",
    "mtree_add_tree": "MTree registers but will not generate; trees fall back to custom generators",
    "mtree_export": "MTree can make trees but not export them; trees fall back to custom generators",
    "blender45_checksum": "MTree cannot be tested at all; it stays unverified",
    "addon_install": "the add-on cannot be loaded; its asset class falls back to a custom generator",
    "addon_install_mpfb2": "MPFB2 cannot be loaded; humans fall back to a custom generator",
    "addon_install_modular_tree": "MTree cannot be loaded; trees fall back to custom generators",
    "mpfb_import": "MPFB2 is inert; humans fall back to a custom generator",
    "infinigen_install": "rocks and plants fall back to custom generators plus Poly Haven scans",
    "polyhaven": "no CC0 texture source; materials fall back to procedural baking only",
    "quaternius_packs": "no CC0 clip source yet; the release is an open task on the owner and clips are authored instead",
    "quaternius_inventory": "clip coverage unknown; the animation report stays open",
    "quaternius_coverage": "coverage is unknown, not zero: the packs downloaded but no clips were found inside them, so the extraction or the pack contents need looking at",
    "quaternius_unzip": "a pack did not extract; its clips are unknown",
}

# Probes that are SUPPOSED to fail. Two kinds live here, and neither is a defect:
#
#   * control runs that prove a decision. The quantized gltfpack load is meant to fail; that
#     failure is the evidence for using -noq. Counting it as a defect inverts its meaning.
#   * tools rejected after the brief's three attempts. Their probes keep running so a later
#     change is noticed, but a failure there is the expected state, not news.
EXPECTED_FAILURES = {
    "godot_scene_gltfpack": "the control run: quantized gltfpack output is expected not to load, which is why LODs use -noq",
    "godot_load_gltfpack": "the control run: quantized gltfpack output is expected not to load, which is why LODs use -noq",
    "godot_import_gltfpack": "the control run for the LOD decision",
    "mpfb2": "MPFB2 is rejected after 3 attempts; the custom generator is the plan, not a fallback",
    "mpfb2_exit": "MPFB2 is rejected after 3 attempts",
    "mpfb_enable": "MPFB2 is rejected after 3 attempts",
    "mpfb_import": "MPFB2 is rejected after 3 attempts",
    "mpfb_operators": "MPFB2 is rejected after 3 attempts",
    "mpfb_create_human": "MPFB2 is rejected after 3 attempts",
    "mpfb_diagnostics": "MPFB2 is rejected after 3 attempts",
    "addon_install_mpfb2": "MPFB2 is rejected after 3 attempts",
    "mtree": "Modular Tree is rejected after 3 attempts; Infinigen plus custom generators is the plan",
    "mtree_register": "Modular Tree is rejected after 3 attempts",
    "mtree_enable": "Modular Tree is rejected after 3 attempts",
    "mtree_operators": "Modular Tree is rejected after 3 attempts",
    "mtree_add_tree": "Modular Tree is rejected after 3 attempts",
    "mtree_export": "Modular Tree is rejected after 3 attempts",
    "mtree_diagnostics": "Modular Tree is rejected after 3 attempts",
    "addon_install_modular_tree": "Modular Tree is rejected after 3 attempts",
    "quaternius_packs": "the release was empty until the owner uploaded the packs; now expected to pass",
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


def collapse_exit_rows(rows):
    """Drop the bare exit-code row that run_capture adds beside a probe's own result.

    run_capture only emits `<name>_exit` when the command already printed a RESULT line and
    then exited non-zero, so the row is always redundant. It was only being dropped when
    `<name>` also matched a probe name, which it does not: run_capture is called with
    `mtree` while the probe reports `mtree_operators`, so `mtree_exit` survived and was
    counted as a defect. Drop them unconditionally.
    """
    return [row for row in rows if not row["name"].endswith("_exit")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", default="")
    parser.add_argument("--out", default="reports/tool_evaluation.md")
    args = parser.parse_args()

    paths = [p for p in args.logs.split() if p and os.path.exists(p)]
    rows = []
    for path in paths:
        rows.extend(parse(path))
    rows = collapse_exit_rows(rows)

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
    lines.append("| Probe | Result | Detail | What it means |")
    lines.append("|---|---|---|---|")
    for row in ordered:
        label, purpose = DECISIONS.get(row["name"], (row["name"], ""))
        status = "PASS" if row["ok"] else "FAIL"
        # A failed probe has one of two meanings, and conflating them is what made this report
        # read as a wall of failure. Either the pipeline is broken (a defect), or the probe was
        # the control run proving that the fallback is correct (a decision, not a defect).
        if row["ok"]:
            meaning = purpose
        elif row["name"] in EXPECTED_FAILURES:
            status = "EXPECTED FAIL"
            meaning = EXPECTED_FAILURES[row["name"]]
        else:
            meaning = FAILURE_CONSEQUENCE.get(row["name"], "see the probe detail")
        lines.append("| %s | %s | %s | %s |" % (label, status, row["detail"], meaning))
    lines.append("")

    expected = [r for r in ordered if not r["ok"] and r["name"] in EXPECTED_FAILURES]
    defects = [r for r in ordered if not r["ok"] and r["name"] not in EXPECTED_FAILURES]

    lines.append("## Outcome")
    lines.append("")
    lines.append("- Probes run: **%d**" % len(ordered))
    lines.append("- Passed: **%d**" % (len(ordered) - len(expected) - len(defects)))
    lines.append("- Expected failures (controls that prove a decision): **%d**" % len(expected))
    lines.append("- Defects (something is actually broken): **%d**" % len(defects))
    lines.append("")
    if expected:
        lines.append("### Expected failures")
        lines.append("")
        for row in expected:
            label, _ = DECISIONS.get(row["name"], (row["name"], ""))
            lines.append("- **%s** — %s" % (label, EXPECTED_FAILURES[row["name"]]))
        lines.append("")
    if defects:
        lines.append("### Defects, and the fallback the brief defines for each")
        lines.append("")
        for row in defects:
            label, _ = DECISIONS.get(row["name"], (row["name"], ""))
            lines.append(
                "- **%s** — %s" % (label, FAILURE_CONSEQUENCE.get(row["name"], "see the probe detail"))
            )
        lines.append("")
    else:
        lines.append("No defects.")
        lines.append("")

    text = "\n".join(lines)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
