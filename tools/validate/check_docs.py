#!/usr/bin/env python3
"""Check that the numbers and contracts quoted in the docs match the code.

Run:
    python tools/validate/check_docs.py

Why this exists: every stale figure in this repository was a number written once in prose and then
changed in the code. The README said "15 unit tests" while the suite had 35. `ADDITIONS.md` said
the surface-ID map was 1024² while every generator wrote 1025² — twice, in two different files, and
both times the contradiction was found by a human reading, not by a check. Then `reports/phase2.md`
described a 24 m river bank while the generator carved an 80 m one, and that file had never been
checked at all.

A number in prose is a claim about the code. This makes it one that can fail.
"""

import importlib.util
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_module(name, relative_path):
    """Import a script by path; these live in directories that are not packages."""
    path = os.path.join(ROOT, relative_path)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    directory = os.path.dirname(path)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    spec.loader.exec_module(module)
    return module


def read(relative):
    with open(os.path.join(ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


def check_markdown_tables(relative, text, problems):
    """Every row in a markdown table must have the same shape as the table it sits in.

    A row appended to the line above it — which is what happens when an edit replaces a line and
    its trailing newline — produces two rows fused into one. Markdown renders that as a single
    malformed row, and it reads as a typo rather than as lost content. This happened to
    reports/phase2.md and had to be found by eye.

    Fenced code blocks are skipped: a shell fragment with pipes in it is not a table.
    """
    first_row_pipes = None
    first_row_line = 0
    in_fence = False

    def close_table():
        nonlocal first_row_pipes, first_row_line
        first_row_pipes = None
        first_row_line = 0

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            close_table()
            continue
        if in_fence:
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            pipes = stripped.count("|")
            if first_row_pipes is None:
                first_row_pipes = pipes
                first_row_line = number
            elif pipes != first_row_pipes:
                problems.append(
                    "%s:%d: this table row has %d pipes; the table at line %d has %d — a row was "
                    "probably merged into the one above it"
                    % (relative, number, pipes, first_row_line, first_row_pipes)
                )
                return
        else:
            close_table()


def main():
    problems = []

    readme = read("README.md")
    manifest = json.loads(read(os.path.join("assets", "manifest.json")))
    records, manifest_problems = build_manifest.build(manifest)
    if manifest_problems:
        # The builder's own failures are check_manifest.py's to report. Stacking a doc failure on
        # top of them would bury the cause.
        print(
            "skipping doc checks: the manifest does not build (%s)"
            % manifest_problems[0],
            file=sys.stderr,
        )
        return 1

    expected_assets = len(records)
    match = re.search(r"([\d,]+)-asset manifest", readme)
    if not match:
        problems.append("README.md no longer states the asset count")
    elif int(match.group(1).replace(",", "")) != expected_assets:
        problems.append(
            "README.md says the manifest holds %s assets; it holds %d"
            % (match.group(1), expected_assets)
        )

    materials = json.loads(read(os.path.join("tools", "config", "materials.json")))
    expected_materials = len(materials.get("materials", []))
    match = re.search(r"(\d+) materials\b", readme)
    if not match:
        problems.append("README.md no longer states the material count")
    elif int(match.group(1)) != expected_materials:
        problems.append(
            "README.md says there are %s materials; materials.json has %d"
            % (match.group(1), expected_materials)
        )

    expected_tests = len(test_tools.TESTS)
    match = re.search(r"(\d+) unit tests", readme)
    if not match:
        problems.append("README.md no longer states the unit test count")
    elif int(match.group(1)) != expected_tests:
        problems.append(
            "README.md says %s unit tests; test_tools.py registers %d"
            % (match.group(1), expected_tests)
        )

    # The number of validator scripts is a claim in prose as well, and it drifts the moment one is
    # added: this line said "eight" while tools/validate held nine, and only a person reading would
    # have caught it. Counting the files is the one version of the check that cannot go stale.
    validator_scripts = sorted(
        name
        for name in os.listdir(os.path.join(ROOT, "tools", "validate"))
        if name.startswith("check_") and name.endswith(".py")
    )
    match = re.search(r"(\d+) validator scripts", readme)
    if not match:
        problems.append("README.md no longer states the validator script count")
    elif int(match.group(1)) != len(validator_scripts):
        problems.append(
            "README.md says %s validator scripts; tools/validate holds %d (%s)"
            % (match.group(1), len(validator_scripts), ", ".join(validator_scripts))
        )

    # The 1025 contract. This is the exact number that drifted twice: the generator has always
    # written 1025 samples and two documents said 1024.
    samples = terrain_maps.SAMPLES
    surface_ids = json.loads(read(os.path.join("assets", "surface_ids.json")))
    encoding = surface_ids.get("encoding", {})
    quoted = "%dx%d" % (samples, samples)
    if quoted not in encoding.get("map", ""):
        problems.append(
            "assets/surface_ids.json encoding.map does not say %s, but the generator writes %d "
            "samples" % (quoted, samples)
        )
    if "why_1025" not in encoding:
        problems.append(
            "assets/surface_ids.json no longer explains why the grid is %s" % quoted
        )

    # The river's shape is described in prose in reports/phase2.md and implemented as constants in
    # terrain_maps.py, and the two had drifted: the report described a 24 m bank and a bed falling
    # from 33.5 to 30.5 m while the generator carved an 80 m bank toward 30.0 then 29.0 m. The
    # numbers were checked by nobody, because "a number in prose is a claim about the code" was a
    # rule this file applied to the README only. Deriving the sentence from the constants is the
    # one version of the check that cannot go stale.
    phase2 = read(os.path.join("reports", "phase2.md"))
    for phrase in (
        "%.0f m bank" % terrain_maps.RIVER_BANK_M,
        "%.0f m channel" % (2.0 * terrain_maps.RIVER_HALF_WIDTH_M),
        "%.1f → %.1f m" % (terrain_maps.RIVER_BED_SOURCE_M, terrain_maps.RIVER_BED_OUTLET_M),
        "%.1f m water level" % terrain_maps.WATER_LEVEL_M,
    ):
        if phrase not in phase2:
            problems.append(
                "reports/phase2.md no longer states %r, which is what terrain_maps.py carves — "
                "either the prose drifted from the constants or the constants moved" % phrase
            )

    # The exact wrong figure, caught by name. If this string ever comes back, it is the same
    # contradiction a reader has had to find by hand twice.
    additions = read(os.path.join("assets", "ADDITIONS.md"))
    if "1024²" in additions:
        problems.append(
            "assets/ADDITIONS.md says 1024², but every terrain map is %s" % quoted
        )

    # Release packs keep binaries out of history, which only works while the documents say what the
    # mechanism is. A policy with no entry point is how a rule quietly stops being followed.
    if not os.path.exists(os.path.join(ROOT, "docs", "RELEASES.md")):
        problems.append("docs/RELEASES.md is missing: nothing describes the release-pack policy")
    for phrase in ("assets/packs.json", "tools/fetch_packs.py", "tools/pack_release.py"):
        if phrase not in readme:
            problems.append(
                "README.md no longer mentions %s, which is the release-pack mechanism" % phrase
            )

    for directory, _dirs, files in os.walk(ROOT):
        if ".git" in directory:
            continue
        for name in sorted(files):
            if not name.endswith(".md"):
                continue
            relative = os.path.relpath(os.path.join(directory, name), ROOT)
            check_markdown_tables(relative, read(relative), problems)

    if problems:
        print("documentation checks failed:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1

    print(
        "docs: %d assets, %d materials, %d validator scripts, %d unit tests, %s grid all match "
        "their documents, the river constants match reports/phase2.md, and every markdown table is "
        "rectangular"
        % (
            expected_assets,
            expected_materials,
            len(validator_scripts),
            expected_tests,
            quoted,
        )
    )
    return 0


build_manifest = load_module("build_manifest", os.path.join("tools", "build_manifest.py"))
test_tools = load_module(
    "test_tools", os.path.join("tools", "validate", "test_tools.py")
)
terrain_maps = load_module(
    "terrain_maps", os.path.join("tools", "generators", "terrain_maps.py")
)


if __name__ == "__main__":
    sys.exit(main())
