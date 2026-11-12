#!/usr/bin/env python3
"""Unit tests for the scripts whose bugs have cost real CI time.

Run:
    python tools/validate/test_tools.py

Why this file exists: `tools/build_manifest.py`, `tools/phase0/make_report.py` and the generators
decide what the pipeline believes — which assets exist, whether a probe passed, and what the world
looks like. All three have silently lied before. The manifest builder once wrote a duplicate name
over another record and reported nothing; the report parser once dropped a whole result line and
reported a passing probe as "produced no result"; and the terrain generator computed a slope in
metres-per-two-samples while its thresholds were written as if it were metres-per-metre.

None of those could be caught by the syntax checks, because all were valid Python that did the
wrong thing.

These are plain asserts with no test framework: the repository has no dependencies, and adding one
to run a dozen checks would be a worse trade than writing them out.

Each test names the bug it would have caught, so a future reader can tell whether it still matters
before deleting it.
"""

import importlib.util
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_module(name, relative_path):
    """Import a script by path; these live in directories that are not packages."""
    path = os.path.join(ROOT, relative_path)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # The generators import `common` by bare name, which needs their own directory on the path.
    directory = os.path.dirname(path)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    spec.loader.exec_module(module)
    return module


build_manifest = load_module("build_manifest", os.path.join("tools", "build_manifest.py"))
make_report = load_module("make_report", os.path.join("tools", "phase0", "make_report.py"))
generator_common = load_module("generator_common", os.path.join("tools", "generators", "common.py"))
terrain = load_module("terrain_maps", os.path.join("tools", "generators", "terrain_maps.py"))


def manifest_with(**categories):
    """A minimal manifest: the builder needs categories, and nothing else is required."""
    return {
        "schema_version": 1,
        "project": "test",
        "field_defaults": {"path": None, "tris": 0, "source_license": None, "status": "pending"},
        "categories": categories,
    }


def category(assets, **overrides):
    group = {"phase": 2, "tier": "C", "priority": "P2", "source_tool": "custom", "assets": assets}
    group.update(overrides)
    return group


# --------------------------------------------------------------------------------------------
# tools/build_manifest.py
# --------------------------------------------------------------------------------------------


def test_variant_name_collision_is_reported():
    """rock_boulder with 2 variants emits rock_boulder_a; a separate rock_boulder_a overwrote it.

    The builder compared base names only, so both entries looked distinct and the second
    silently replaced the first record in the output. Nothing failed.
    """
    manifest = manifest_with(
        **{
            "4.E.a": category(["rock_boulder|C|P2|2"]),
            "4.E.b": category(["rock_boulder_a|C|P2"]),
        }
    )
    records, problems = build_manifest.build(manifest)
    assert len(records) == 3, "expected three records, got %d" % len(records)
    assert any("collides with" in p for p in problems), (
        "a variant name collided with an explicit entry and the builder reported nothing: %r"
        % problems
    )


def test_group_without_phase_is_reported():
    """A group with no phase used to default to 0, putting its assets in a phase that does not exist."""
    manifest = manifest_with(**{"4.E": {"tier": "C", "priority": "P2", "assets": ["rock_small"]}})
    _, problems = build_manifest.build(manifest)
    assert any("no phase" in p for p in problems), (
        "a group without a phase was accepted silently: %r" % problems
    )


def test_group_without_tier_is_reported():
    """Tier used to default to "A", so an unclassified group looked like a deliberate choice."""
    manifest = manifest_with(
        **{"4.E": {"phase": 2, "priority": "P2", "assets": ["rock_small"]}}
    )
    _, problems = build_manifest.build(manifest)
    assert any("no tier" in p for p in problems), (
        "a group without a tier was accepted silently: %r" % problems
    )


def test_licence_is_derived_from_the_source_tool():
    """Every record used to default to CC0, which made an unchecked asset look verified."""
    manifest = manifest_with(**{"4.B": category(["rock_granite"], source_tool="polyhaven")})
    records, problems = build_manifest.build(manifest)
    assert not problems, "unexpected problems: %r" % problems
    assert records[0]["source_license"] == "CC0-1.0", records[0]["source_license"]


def test_unknown_source_tool_gets_no_licence():
    """An unrecognised tool must produce None so the validator rejects it, not a guessed licence."""
    manifest = manifest_with(**{"4.B": category(["rock_granite"], source_tool="mystery")})
    records, problems = build_manifest.build(manifest)
    assert not problems, "unexpected problems: %r" % problems
    assert records[0]["source_license"] is None, (
        "an unknown tool was given the licence %r" % records[0]["source_license"]
    )


def test_sixth_field_overrides_the_tool_licence():
    """A font is OFL and a music loop may be CC-BY; neither follows from the tool that fetched it."""
    manifest = manifest_with(
        **{
            "4.O": category(
                ["audio_ambience_rain|||||CC-BY-4.0"], phase=9, source_tool="none"
            )
        }
    )
    records, problems = build_manifest.build(manifest)
    assert not problems, "unexpected problems: %r" % problems
    assert records[0]["source_license"] == "CC-BY-4.0", records[0]["source_license"]


def test_too_many_fields_is_rejected():
    """Seven fields is a typo, not an extension; it must be refused rather than truncated."""
    manifest = manifest_with(**{"4.B": category(["rock_granite|C|P2|1|custom|CC0|extra"])})
    _, problems = build_manifest.build(manifest)
    assert any("too many fields" in p for p in problems), problems


# --------------------------------------------------------------------------------------------
# tools/phase0/make_report.py
# --------------------------------------------------------------------------------------------


def parse_log(text):
    handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    try:
        handle.write(text)
        handle.close()
        return make_report.parse(handle.name)
    finally:
        os.unlink(handle.name)


def test_parser_reads_all_three_result_shapes():
    """The key=value shape was dropped, which reported a passing probe as "produced no result"."""
    rows = parse_log(
        'RESULT {"step": "a", "ok": true}\n'
        "RESULT b exit=0\n"
        "RESULT c ok=True version=4.7.2\n"
    )
    by_name = {row["name"]: row for row in rows}
    assert set(by_name) == {"a", "b", "c"}, sorted(by_name)
    assert all(row["ok"] for row in rows), rows


def test_key_value_line_without_a_verdict_is_a_failure():
    """An unrecognised key=value line used to count as a pass: silence was read as success."""
    rows = parse_log("RESULT something reason=whatever\n")
    assert len(rows) == 1, rows
    assert rows[0]["ok"] is False, "a result with no verdict was counted as a pass"
    assert "no ok=" in rows[0]["detail"], rows[0]["detail"]


def test_malformed_json_is_a_failure_not_a_dropped_line():
    """A JSON result that did not parse was skipped, so the probe looked as if it never ran."""
    rows = parse_log('RESULT {"step": "half", "ok": true\n')
    assert len(rows) == 1, rows
    assert rows[0]["ok"] is False, rows[0]
    assert rows[0]["name"] == "malformed_result", rows[0]["name"]


def test_json_without_an_ok_field_is_a_failure():
    """Every JSON emitter in tools/phase0 writes ok; a payload without one has no verdict."""
    rows = parse_log('RESULT {"step": "x", "value": 1}\n')
    assert rows[0]["ok"] is False, rows[0]
    assert "no ok field" in rows[0]["detail"], rows[0]["detail"]


def test_crash_after_result_is_kept_and_named():
    """Dropping the `_exit` row made a probe that crashed after reporting look like a clean pass.

    The row is named after the label run_capture was called with, not after the probe's own
    `step`. run_capture is called with `mtree` while the probe inside reports `mtree_generate`,
    so the crash row is `mtree_crash_after_result`. The first version of this test expected
    `mtree_generate_crash_after_result` and failed against correct code.
    """
    rows = [
        {"name": "mtree_generate", "ok": True, "detail": "tris=1840066"},
        {"name": "mtree_exit", "ok": False, "detail": "exit=139"},
    ]
    converted = make_report.collapse_exit_rows(rows)
    names = [row["name"] for row in converted]
    assert "mtree_exit" not in names, names
    assert "mtree_crash_after_result" in names, names
    crash = [row for row in converted if row["name"].endswith("_crash_after_result")][0]
    assert crash["ok"] is False, crash


def test_exit_zero_row_is_still_dropped():
    """An exit=0 row beside a probe's own result genuinely says nothing new."""
    rows = [
        {"name": "a", "ok": True, "detail": ""},
        {"name": "a_exit", "ok": True, "detail": "exit=0"},
    ]
    assert [row["name"] for row in make_report.collapse_exit_rows(rows)] == ["a"]


def test_retarget_probe_is_required():
    """The retarget map was written from a naming convention and never diffed against the pack."""
    assert "retarget_bones" in make_report.REQUIRED_PROBES, (
        "retarget_bones is not required, so a retarget map that names no real bone stays green"
    )


def test_crash_rows_are_listed_among_defects():
    """A crash row must survive as a defect even when its label is not a required probe name."""
    rows = make_report.collapse_exit_rows(
        [
            {"name": "mtree_generate", "ok": True, "detail": ""},
            {"name": "mtree_exit", "ok": False, "detail": "exit=139"},
        ]
    )
    crash = [row for row in rows if row["name"].endswith("_crash_after_result")]
    assert crash, "the crash row was dropped"
    # `mtree` is not in REQUIRED_PROBES — only mtree_generate and friends are — so this is the
    # case that a name-matching rule would have silently let through.
    assert "mtree" not in make_report.REQUIRED_PROBES, (
        "this test only proves something if the label is not a required probe name"
    )


# --------------------------------------------------------------------------------------------
# tools/generators
# --------------------------------------------------------------------------------------------


def test_png_writer_emits_a_readable_png():
    """The heightmap is written by hand, so the writer itself has to be right.

    A PNG with a wrong CRC or a missing IEND is not a PNG; Godot would fail to import it and the
    terrain would be missing rather than wrong, which is a confusing way to find out.
    """
    import struct

    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.close()
    try:
        size = generator_common.write_gray_png(handle.name, [[0, 128], [255, 7]], bit_depth=8)
        with open(handle.name, "rb") as reader:
            data = reader.read()
        assert data.startswith(b"\x89PNG\r\n\x1a\n"), "no PNG signature"
        assert len(data) == size, "reported size %d but wrote %d" % (size, len(data))
        assert b"IHDR" in data and b"IDAT" in data and b"IEND" in data, "missing a required chunk"
        # The IHDR payload starts 8 (signature) + 4 (length) + 4 (tag) bytes in.
        width, height, depth, colour = struct.unpack(">IIBB", data[16:26])
        assert (width, height, depth, colour) == (2, 2, 8, 0), (
            "IHDR says %dx%d depth %d colour %d" % (width, height, depth, colour)
        )
    finally:
        os.unlink(handle.name)


def test_png_writer_rejects_a_ragged_image():
    """A short row would silently shift every following row; refuse instead."""
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.close()
    try:
        try:
            generator_common.write_gray_png(handle.name, [[0, 1, 2], [3, 4]])
        except ValueError:
            pass
        else:
            raise AssertionError("a ragged image was accepted")
    finally:
        os.unlink(handle.name)


def test_noise_is_deterministic_from_the_seed():
    """The whole reproducibility story rests on this: same seed, same bytes."""
    a = generator_common.fbm_field(16, "seed-a", octaves=3)
    b = generator_common.fbm_field(16, "seed-a", octaves=3)
    c = generator_common.fbm_field(16, "seed-b", octaves=3)
    assert a == b, "the same seed produced different noise"
    assert a != c, "two different seeds produced identical noise"


def test_input_hash_ignores_key_order():
    """A config reordered by an editor is the same asset, not a different one."""
    first = generator_common.input_hash({"a": 1, "b": 2})
    second = generator_common.input_hash({"b": 2, "a": 1})
    assert first == second, "the input hash depends on key order"
    assert first != generator_common.input_hash({"a": 1, "b": 3}), "the hash ignores a value change"


def test_slope_is_metres_per_metre():
    """The first version returned metres per two samples, so its thresholds were meaningless.

    A ramp that rises 10 m over one cell must report a gradient of about 10/CELL_SPACING_M, not
    10. This test is what would have caught the unit error.
    """
    rows = 3
    rise = 10.0
    field = [
        [0.0, rise / terrain.MAX_HEIGHT_M, 2 * rise / terrain.MAX_HEIGHT_M] for _ in range(rows)
    ]
    gradient = terrain.slope(field, 1, 1)
    expected = rise / terrain.CELL_SPACING_M
    assert abs(gradient - expected) < 1e-6, (
        "slope at the middle of a %g m/cell ramp is %g, expected %g (metres per metre)"
        % (rise, gradient, expected)
    )


def test_slope_is_zero_on_flat_ground():
    flat = [[0.5] * 5 for _ in range(5)]
    assert terrain.slope(flat, 2, 2) == 0.0, "flat ground reported a gradient"


def test_surface_ids_are_still_the_numbers_the_generator_writes():
    """The generator hardcodes ids; surface_ids.json is the contract. A renumbering must fail."""
    terrain.check_surface_ids()


# --------------------------------------------------------------------------------------------


TESTS = [
    ("build_manifest: variant name collision", test_variant_name_collision_is_reported),
    ("build_manifest: group without phase", test_group_without_phase_is_reported),
    ("build_manifest: group without tier", test_group_without_tier_is_reported),
    ("build_manifest: licence from the tool", test_licence_is_derived_from_the_source_tool),
    ("build_manifest: unknown tool gets no licence", test_unknown_source_tool_gets_no_licence),
    ("build_manifest: sixth field overrides", test_sixth_field_overrides_the_tool_licence),
    ("build_manifest: too many fields", test_too_many_fields_is_rejected),
    ("make_report: three result shapes", test_parser_reads_all_three_result_shapes),
    ("make_report: key=value with no verdict", test_key_value_line_without_a_verdict_is_a_failure),
    ("make_report: malformed JSON", test_malformed_json_is_a_failure_not_a_dropped_line),
    ("make_report: JSON with no ok", test_json_without_an_ok_field_is_a_failure),
    ("make_report: crash after result", test_crash_after_result_is_kept_and_named),
    ("make_report: exit=0 row dropped", test_exit_zero_row_is_still_dropped),
    ("make_report: retarget probe required", test_retarget_probe_is_required),
    ("make_report: crash rows survive as defects", test_crash_rows_are_listed_among_defects),
    ("generators: PNG writer", test_png_writer_emits_a_readable_png),
    ("generators: PNG rejects ragged rows", test_png_writer_rejects_a_ragged_image),
    ("generators: noise is deterministic", test_noise_is_deterministic_from_the_seed),
    ("generators: input hash ignores key order", test_input_hash_ignores_key_order),
    ("generators: slope is metres per metre", test_slope_is_metres_per_metre),
    ("generators: slope is zero on flat ground", test_slope_is_zero_on_flat_ground),
    ("generators: surface ids match the contract", test_surface_ids_are_still_the_numbers_the_generator_writes),
]


def main():
    failures = []
    for label, test in TESTS:
        # Any exception, not just AssertionError: a test that crashes on a TypeError is a
        # failing test, and an uncaught traceback would abort the remaining tests and report
        # one cause instead of all of them.
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - a test failure of any kind is a failure
            detail = "%s: %s" % (type(exc).__name__, exc)
            failures.append((label, detail))
            print("FAIL " + label + ": " + detail)
        else:
            print("ok   " + label)

    if failures:
        print("\n%d of %d tool tests failed:" % (len(failures), len(TESTS)), file=sys.stderr)
        for label, detail in failures:
            print("  - " + label + ": " + detail, file=sys.stderr)
        return 1
    print("\nall %d tool tests passed" % len(TESTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
