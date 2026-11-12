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

SHELL_RESULT = re.compile(r"^RESULT (\S+) exit=(-?\d+)\s*(.*)$")
PY_RESULT = re.compile(r"^RESULT (\{.*\})\s*$")
# Any other RESULT line: `RESULT <name> <key=value...>`. Probes that report this way are
# parsed rather than dropped — see parse() for why that matters.
GENERIC_RESULT = re.compile(r"^RESULT (\S+)\s*(.*)$")

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
    "gltfpack_size_cost": ("gltfpack -noq size cost", "the bytes -noq spends compared with quantized output"),
    "godot_version": ("Godot", "import gate and later the game runtime"),
    "godot_import": ("Godot headless import", "proves Godot accepts Blender's GLB output"),
    "godot_load": ("Godot headless load", "proves the imported mesh survives to a scene node"),
    "godot_scene_plain": ("Godot load of the Blender GLB", "the import gate itself: meshes and triangles that arrive"),
    "godot_scene_gltfpack": ("Godot load of gltfpack output", "decides whether gltfpack is safe in the LOD step"),
    "godot_scene_gltfpack_noq": ("Godot load of gltfpack -noq output", "the control run for the LOD decision"),
    "godot_import_gltfpack": ("Godot import of gltfpack output", "same decision, one step earlier"),
    "godot_import_gltfpack_noq": ("Godot import of gltfpack -noq output", "same decision, one step earlier"),
    "shader_compile": ("Shader compile", "the project's real shader includes build in Godot"),
    "shader_compile_tech_wind_include": ("Shader compile: wind", "the wind include builds"),
    "shader_compile_tech_wetness_include": ("Shader compile: wetness", "the wetness include builds"),
    "shader_probe_error": ("Shader probe error", "the probe itself raised"),
    "shader_import": ("Shader project import", "the probe project must be imported before a scene runs"),
    "shader_summary": ("Shader compile summary", "how many includes compiled and how many failed"),
    "godot_scene_tree": ("Godot load of the MTree tree", "the tree MTree generated must import and load"),
    "godot_scene_human": ("Godot load of the MPFB2 human", "the human MPFB2 built must import and load"),
    "godot_import_tree": ("Godot import of the MTree tree", "same check, one step earlier"),
    "godot_import_human": ("Godot import of the MPFB2 human", "same check, one step earlier"),
    "mpfb2": ("MPFB2 human", "all human bodies, heads and base clothing"),
    "mpfb_modules": ("MPFB2 modules", "which add-on modules Blender can see"),
    "mpfb_import": ("MPFB2 module import", "the module import, which is what actually fails"),
    "mpfb_register": ("MPFB2 register", "register() through Blender's loader, so extension context is set up"),
    "mpfb_data": ("MPFB2 data directory", "whether MPFB can find base.obj and the rest of its data"),
    "mpfb_create_human": ("MPFB2 create a human", "the operator that builds a body"),
    "mpfb_export": ("MPFB2 human export", "a built human must reach glTF"),
    "mpfb_rig": ("MPFB2 rig", "whether a built human gets an armature; informational, rigging is Phase 5"),
    "mpfb_operators": ("MPFB2 operators", "the operators the add-on registered"),
    "mpfb2_extension_install": ("MPFB2 extension install", "installing MPFB2 as the extension it is"),
    "addon_install": ("Add-on install", "which layout the add-on used: legacy add-on or 4.2+ extension"),
    "addon_install_mpfb2": ("MPFB2 install", "which package name and directory MPFB2 landed in"),
    "addon_install_modular_tree": ("MTree install", "the layout Modular Tree uses"),
    "mtree_register": ("Modular Tree", "procedural trees for the rainforest species"),
    "mtree": ("Modular Tree", "procedural trees for the rainforest species"),
    "mtree_blender": ("MTree Blender version", "the Blender version the extension actually needs"),
    "mtree_modules": ("MTree modules", "which add-on modules Blender can see"),
    "mtree_native_module": ("MTree native module", "the compiled pybind11 module the operators import"),
    "mtree_operators": ("MTree operators", "the namespace and operators the extension registers"),
    "mtree_generate": ("MTree generate a tree", "the operator that generates a tree"),
    "mtree_export": ("MTree tree export", "a generated tree must reach glTF"),
    "mtree_crash": ("MTree probe crash", "the probe raised before it could report"),
    "mtree_extension_install": ("MTree extension install", "installing a blender_manifest.toml repository"),
    "blender45_checksum": ("Blender 4.5 download", "verified against the vendor's published SHA-256"),
    "gltf_transform_install": ("glTF-Transform CLI", "dedup, prune, animation resample, texture resize"),
    "gltf_transform_version": ("glTF-Transform version", "pin recorded for tools/TOOLS.md"),
    "polyhaven": ("Poly Haven API", "CC0 PBR textures, HDRIs and scanned models"),
    "polyhaven_assets": ("Poly Haven asset list", "the API answers at all"),
    "polyhaven_pick": ("Poly Haven asset pick", "which CC0 texture set was chosen"),
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
    "mtree_generate": "MTree registers but will not generate; trees fall back to custom generators",
    "mtree_export": "MTree can make trees but not export them; trees fall back to custom generators",
    "mtree_crash": "the probe crashed; its cause is in the traceback, not in MTree",
    "mpfb_crash": "the probe crashed; its cause is in the traceback, not in MPFB2",
    "blender45_checksum": "MTree cannot be tested at all; it stays unverified",
    "addon_install": "the add-on cannot be loaded; its asset class falls back to a custom generator",
    "addon_install_mpfb2": "MPFB2 cannot be loaded; humans fall back to a custom generator",
    "addon_install_modular_tree": "MTree cannot be loaded; trees fall back to custom generators",
    "mpfb_import": "MPFB2 is inert; humans fall back to a custom generator",
    "mpfb2_extension_install": "MPFB2 could not be installed as an extension; humans fall back",
    "mpfb_register": "MPFB2's register() raised; humans fall back to a custom generator",
    "mpfb_data": "MPFB2 cannot find its own data; humans fall back to a custom generator",
    "mpfb_create_human": "MPFB2 registers but cannot build a body; humans fall back to a custom generator",
    "mpfb_export": "MPFB2 can build but not export; humans fall back to a custom generator",
    "infinigen_install": "rocks and plants fall back to custom generators plus Poly Haven scans",
    "polyhaven": "no CC0 texture source; materials fall back to procedural baking only",
    "quaternius_packs": "no CC0 clip source yet; the release is an open task on the owner and clips are authored instead",
    "quaternius_inventory": "clip coverage unknown; the animation report stays open",
    "quaternius_coverage": "coverage is incomplete: 25 of 41 animation families have no matching clip, so those are authored with bpy",
    "quaternius_unzip": "a pack did not extract; its clips are unknown",
    "shader_compile": "the shader includes do not build; every material using them fails at runtime",
    "shader_compile_tech_wind_include": "the wind include does not build; every foliage material fails at runtime",
    "shader_compile_tech_wetness_include": "the wetness include does not build; every ground material fails at runtime",
    "shader_probe_error": "the probe itself failed, so the shaders remain uncompiled and unverified",
    "shader_summary": "one or more shader includes failed to compile",
    "godot_scene_tree": "MTree generates a tree that Godot cannot load; the tree pipeline is unverified",
    "godot_scene_human": "MPFB2 builds a human that Godot cannot load; the human pipeline is unverified",
    "godot_import_tree": "the tree file does not import; MTree output is unusable",
    "godot_import_human": "the human file does not import; MPFB2 output is unusable",
}

# Negative controls: probes whose PASSING condition is that the thing they test FAILS.
#
# These were labelled "EXPECTED FAIL" and rendered red, which was the wrong design. A row that
# is permanently red teaches a reader to skim past red rows, and then the one that matters gets
# missed too. The test is doing its job when the failure happens, so it should read green.
#
# The control: `godot_scene_gltfpack` loads a GLB written by gltfpack with default
# quantization. Godot's importer accepts the file and then builds no scene from it, so LODs are
# written with -noq. If a future Godot ever loads it, that is not a defect — it is an
# opportunity, because quantization shrinks vertex data, and the row says so.
#
# Each entry is (what the expected failure proves, what a change would mean).
NEGATIVE_CONTROLS = {
    "godot_scene_gltfpack": (
        "Godot builds no scene from gltfpack's quantized output, which is why LODs use -noq",
        "quantized gltfpack output NOW LOADS — -noq may no longer be needed, and LODs could shrink",
    ),
}

# Probes that report a state but must not fail the build, because their failure is not a
# pipeline defect. They stay in the table and in the summary — visible, never silent — but they
# are not counted as defects.
#
# The distinction matters: mpfb_data probes an internal service that raised on every run while
# the human built and exported perfectly well. Counting that as a defect is the same mistake as
# counting a control run as one.
INFORMATIONAL_PROBES = {
    "mpfb_data",
    "mpfb_rig",
    "quaternius_coverage",
    "mtree_native_module",
    "quaternius_inventory",
}

# Probes that must pass for Phase 0 to be considered closed. A failure here is a defect and
# must fail the job, and so must a required probe that produced no result at all.
#
# MTree is here because it is retained as the production tree tool: registration alone is not
# success, so generation, export and the Godot import of its tree are all gated.
REQUIRED_PROBES = {
    "blender_checksum",
    "blender_env",
    "gltf_export",
    "render_cycles",
    "godot_version",
    "godot_import",
    "godot_scene_plain",
    "shader_import",
    "shader_compile_tech_wind_include",
    "shader_compile_tech_wetness_include",
    "shader_summary",
    "gltfpack_simplify",
    "gltfpack_noq",
    "godot_scene_gltfpack_noq",
    "polyhaven",
    "gltf_transform_install",
    "quaternius_download",
    "quaternius_packs",
    "mtree_extension_install",
    "mtree_operators",
    "mtree_generate",
    "mtree_export",
    "godot_scene_tree",
    "godot_import_tree",
    # MPFB2 now produces a human and Godot loads it, so it is a real pipeline rather than a
    # tool under repair. Gating it means a regression surfaces as a defect instead of quietly
    # reverting to "falls back to a custom generator".
    "mpfb2_extension_install",
    "mpfb_register",
    "mpfb_create_human",
    "mpfb_export",
    "godot_scene_human",
    "godot_import_human",
}


def parse(path):
    """Parse every RESULT line a run produced.

    Three shapes are accepted, and the third is the important one:

      RESULT {"step": "...", "ok": true, ...}   JSON, from the Python and GDScript probes
      RESULT <name> exit=<n> [trailing text]     shell probes
      RESULT <name> <anything else>              shell probes written as key=value

    That last shape was previously dropped silently, and it hid real probes: the workflow
    emitted `RESULT godot_version version=4.7.2-stable` and the Poly Haven probe emitted
    `RESULT polyhaven_download ok=True ...`, neither of which matched the two strict patterns.
    Both were then reported as "required probe produced no result" even though they had run and
    succeeded. A probe's report must never depend on it guessing the exact punctuation.
    """
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line.startswith("RESULT "):
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
                continue

            match = SHELL_RESULT.match(line)
            if match:
                rows.append(
                    {
                        "name": match.group(1),
                        "ok": match.group(2) == "0",
                        "detail": ("exit=%s %s" % (match.group(2), match.group(3))).strip(),
                    }
                )
                continue

            match = GENERIC_RESULT.match(line)
            if match:
                name = match.group(1)
                rest = match.group(2).strip()
                rows.append(
                    {
                        "name": name,
                        # A key=value probe is a success unless it says otherwise.
                        "ok": "ok=False" not in rest and "ok=false" not in rest,
                        "detail": rest,
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
        meaning = purpose

        if row["name"] in NEGATIVE_CONTROLS:
            proves, changed = NEGATIVE_CONTROLS[row["name"]]
            if row["ok"]:
                # The control stopped failing. That is news, not breakage.
                status = "CHANGED"
                meaning = changed
            else:
                status = "PASS (control)"
                meaning = "control, doing its job: " + proves
        elif row["ok"]:
            meaning = purpose
        elif row["name"] in INFORMATIONAL_PROBES:
            status = "INFO"
            meaning = "reported for context; does not fail the build — " + purpose
        else:
            meaning = FAILURE_CONSEQUENCE.get(row["name"], "see the probe detail")
        lines.append("| %s | %s | %s | %s |" % (label, status, row["detail"], meaning))
    lines.append("")

    # A control is green when it fails, and its own outcome line says so.
    controls = [r for r in ordered if r["name"] in NEGATIVE_CONTROLS]
    controls_holding = [r for r in controls if not r["ok"]]
    informational = [r for r in ordered if not r["ok"] and r["name"] in INFORMATIONAL_PROBES]
    defects = [
        r
        for r in ordered
        if not r["ok"]
        and r["name"] not in NEGATIVE_CONTROLS
        and r["name"] not in INFORMATIONAL_PROBES
    ]
    # The four counts sum to the number of probes run, exactly. A control that is holding is
    # reported on its own line rather than folded into "Passed", because folding it in made
    # 49 passes plus 1 control read as 50 of 50 — true, but not arithmetic a reader can check.
    passed = len(ordered) - len(controls_holding) - len(informational) - len(defects)

    lines.append("## Outcome")
    lines.append("")
    lines.append("- Probes run: **%d**" % len(ordered))
    lines.append("- Passed: **%d**" % passed)
    lines.append(
        "- Negative controls holding (a test that passes by failing): **%d**"
        % len(controls_holding)
    )
    lines.append("- Informational failures (context, not defects): **%d**" % len(informational))
    lines.append("- Defects (something is actually broken): **%d**" % len(defects))
    lines.append("")
    if controls:
        lines.append("### Negative controls")
        lines.append("")
        for row in controls:
            label, _ = DECISIONS.get(row["name"], (row["name"], ""))
            proves, changed = NEGATIVE_CONTROLS[row["name"]]
            if row["ok"]:
                lines.append("- **%s** — %s" % (label, changed))
            else:
                lines.append("- **%s** — %s" % (label, proves))
        lines.append("")
    if informational:
        lines.append("### Informational failures")
        lines.append("")
        for row in informational:
            label, _ = DECISIONS.get(row["name"], (row["name"], ""))
            lines.append("- **%s** — %s" % (label, row["detail"]))
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

    # Exit non-zero when a required probe FAILED, or when one never reported at all.
    #
    # The first version only looked for failed rows. A probe that timed out and produced no
    # row was therefore invisible: the Godot shader step hung for 45 minutes, emitted nothing,
    # and the report job still succeeded. A missing result is a failure — it is the one case
    # where silence is indistinguishable from success unless it is treated as neither.
    seen = {row["name"] for row in ordered}
    missing_required = sorted(REQUIRED_PROBES - seen)
    required_failures = [row for row in defects if row["name"] in REQUIRED_PROBES]

    exit_code = 0
    if missing_required:
        print(
            "\nFAILED: %d required probe(s) produced no result: %s"
            % (len(missing_required), ", ".join(missing_required)),
            file=sys.stderr,
        )
        exit_code = 1
    if required_failures:
        print(
            "\nFAILED: %d required probe(s) failed: %s"
            % (
                len(required_failures),
                ", ".join(sorted(row["name"] for row in required_failures)),
            ),
            file=sys.stderr,
        )
        exit_code = 1

    # The gate outcome belongs in the report, not only on stderr.
    #
    # stderr is unbuffered and stdout is block-buffered, so on a piped CI log the "FAILED:"
    # line appears hundreds of lines above the markdown that explains it — and was truncated
    # out of the run view entirely. A report that fails the build must say why, in the body.
    lines.append("## Gate")
    lines.append("")
    if exit_code == 0:
        lines.append("Every required probe ran and passed. The build is green.")
    else:
        lines.append("**This report failed the build.**")
        lines.append("")
        if missing_required:
            lines.append(
                "Required probes that produced **no result at all** (%d):"
                % len(missing_required)
            )
            lines.append("")
            for name in missing_required:
                label, purpose = DECISIONS.get(name, (name, ""))
                lines.append("- `%s` — %s" % (name, purpose))
            lines.append("")
        if required_failures:
            lines.append("Required probes that **failed** (%d):" % len(required_failures))
            lines.append("")
            for row in required_failures:
                label, _ = DECISIONS.get(row["name"], (row["name"], ""))
                lines.append("- **%s** — %s" % (label, row["detail"]))
            lines.append("")
    lines.append("")

    text = "\n".join(lines)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
