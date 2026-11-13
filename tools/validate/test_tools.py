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
hydrology = load_module("hydrology", os.path.join("tools", "generators", "hydrology.py"))
terrain_surfaces = load_module(
    "terrain_surfaces", os.path.join("tools", "generators", "terrain_surfaces.py")
)


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


def test_png_round_trip_preserves_every_value():
    """The hydrology generator reads back a heightmap another generator wrote.

    A reader that mis-decodes a filter would place water at the wrong height with no error at all,
    so the round trip is checked value for value rather than by eye.
    """
    rows = [[0, 1, 255], [17, 128, 200]]
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.close()
    try:
        generator_common.write_gray_png(handle.name, rows, bit_depth=8)
        width, height, channels, decoded = generator_common.read_png(handle.name)
        assert (width, height, channels) == (3, 2, 1), (width, height, channels)
        assert decoded == rows, "round trip changed the data: %r -> %r" % (rows, decoded)
    finally:
        os.unlink(handle.name)


def test_png_round_trip_sixteen_bit():
    """The heightmap is 16-bit; 8-bit assumptions would truncate it to a tenth of its range."""
    rows = [[0, 65535], [1000, 32768]]
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.close()
    try:
        generator_common.write_gray_png(handle.name, rows, bit_depth=16)
        _w, _h, _c, decoded = generator_common.read_png(handle.name)
        assert decoded == rows, "16-bit round trip changed the data: %r -> %r" % (rows, decoded)
    finally:
        os.unlink(handle.name)


def test_png_round_trip_rgb_and_rgba():
    """The normal map is RGB and the splat weights are RGBA; both go through the same writer.

    A wrong colour type here would produce a file that opens and has the wrong number of channels,
    which is how a normal map ends up being read as a grayscale heightfield.
    """
    three = [[10, 20, 30, 40, 50, 60]]
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.close()
    try:
        generator_common.write_png(handle.name, three, bit_depth=8, channels=3)
        width, height, channels, decoded = generator_common.read_png(handle.name)
        assert (width, height, channels) == (2, 1, 3), (width, height, channels)
        assert decoded == three, "RGB round trip changed the data"

        four = [[1, 2, 3, 4, 5, 6, 7, 8]]
        generator_common.write_png(handle.name, four, bit_depth=8, channels=4)
        width, height, channels, decoded = generator_common.read_png(handle.name)
        assert (width, height, channels) == (2, 1, 4), (width, height, channels)
        assert decoded == four, "RGBA round trip changed the data"
    finally:
        os.unlink(handle.name)


def test_png_rejects_sixteen_bit_colour():
    """PNG has no useful 16-bit RGB path here, and silently writing 8-bit would be worse."""
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.close()
    try:
        try:
            generator_common.write_png(handle.name, [[1, 2, 3]], bit_depth=16, channels=3)
        except ValueError:
            pass
        else:
            raise AssertionError("16-bit RGB was accepted")
    finally:
        os.unlink(handle.name)


def test_smoothstep_is_clamped_and_monotonic():
    """The splat weights are built from smoothstep; an unclamped version gives negative weights."""
    assert terrain_surfaces.smoothstep(0.0, 1.0, -5.0) == 0.0, "below the edge is not 0"
    assert terrain_surfaces.smoothstep(0.0, 1.0, 5.0) == 1.0, "above the edge is not 1"
    previous = -1.0
    for step in range(11):
        value = terrain_surfaces.smoothstep(0.0, 1.0, step / 10.0)
        assert value >= previous, "smoothstep is not monotonic at %r" % (step / 10.0,)
        assert 0.0 <= value <= 1.0, "smoothstep left 0..1 at %r" % value
        previous = value


def test_splat_weights_sum_to_one():
    """Every texel's weights must sum to 1, or the terrain shader darkens or brightens it.

    Reproduces the layer arithmetic the generator uses, for a spread of slopes and heights.
    """
    for gradient in (0.0, 0.1, 0.3, 0.5, 0.7, 0.9):
        for above_water in (-5.0, 0.0, 2.0, 5.0, 20.0):
            rock = terrain_surfaces.smoothstep(terrain_surfaces.SLOPE_SCREE,
                                               terrain_surfaces.SLOPE_ROCK, gradient)
            loose = (terrain_surfaces.smoothstep(terrain_surfaces.SLOPE_MOSS_EDGE,
                                                 terrain_surfaces.SLOPE_SCREE, gradient)
                     * (1.0 - rock))
            soil = (1.0 - rock) * (1.0 - loose)
            bog = (1.0 - terrain_surfaces.smoothstep(0.0, terrain_surfaces.BOG_BAND_M,
                                                     above_water)) * (1.0 - rock)
            shore = (1.0 - terrain_surfaces.smoothstep(0.0, terrain_surfaces.SHORE_BAND_M,
                                                       above_water)) * (1.0 - rock) * soil
            green = soil * (1.0 - bog) * (1.0 - shore)
            moss = green * 0.5
            grass = green * 0.5
            weights = [grass + loose * 0.2, moss, rock, shore * 0.55 + loose * 0.8,
                       bog * 0.75, shore * 0.45, bog * 0.25, 0.0]
            total = sum(weights)
            assert total > 0.0, "all weights are zero at gradient %r height %r" % (
                gradient, above_water)
            normalised = [w / total for w in weights]
            assert abs(sum(normalised) - 1.0) < 1e-9, "weights sum to %r" % sum(normalised)
            assert all(w >= 0.0 for w in normalised), "a negative weight: %r" % normalised



def test_png_round_trip_two_channel():
    """The hydrology mask packs depth and flow direction as grayscale+alpha."""
    rows = [[0, 0, 255, 1], [12, 191, 34, 7]]
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.close()
    try:
        generator_common.write_png(handle.name, rows, bit_depth=8, channels=2)
        width, height, channels, decoded = generator_common.read_png(handle.name)
        assert (width, height, channels) == (2, 2, 2), (width, height, channels)
        assert decoded == rows, "2-channel round trip changed the data: %r -> %r" % (rows, decoded)
    finally:
        os.unlink(handle.name)


def test_wind_uv_leaves_the_unit_range_so_repeat_is_required():
    """The wind UV provably leaves 0..1, so both samplers must repeat.

    A shader can compile perfectly and still freeze: without `repeat_enable` a UV outside 0..1
    clamps to the edge texel, so the foliage stops moving after a few seconds and everything more
    than 100 m from the origin is frozen from the start. Godot cannot warn about this and the
    renderer cannot catch it, because the shader is valid.

    So the maths is checked in Python against the declaration in the shader. If someone removes
    `repeat_enable`, the arithmetic here says the UV still leaves the range and the test fails.
    """
    import re

    # Mirrors wind_phase() in tech_wind_include.gdshaderinc.
    uv_scale_per_metre = 0.01
    sway_frequency = 0.15
    flutter_frequency = 2.1

    # Position alone: 200 m from the origin is already outside 0..1, so the requirement does not
    # depend on time at all.
    assert 200.0 * uv_scale_per_metre > 1.0, (
        "the static UV at 200 m is inside 0..1, so this test proves nothing"
    )
    # Time alone: swing crosses 1.0 after 1/0.15 = 6.7 s, flutter after 0.48 s.
    assert 1.0 / sway_frequency < 7.0, "sway no longer crosses the range quickly"
    assert 1.0 / flutter_frequency < 1.0, "flutter no longer crosses the range within a second"

    source = open(
        os.path.join(ROOT, "shaders", "tech_wind_include.gdshaderinc"), encoding="utf-8"
    ).read()
    for sampler in ("wind_noise", "gust_flowmap"):
        match = re.search(r"uniform\s+sampler2D\s+%s\s*:([^;]*);" % sampler, source)
        assert match, "%s is not declared in the wind include" % sampler
        hints = match.group(1)
        assert "repeat_enable" in hints, (
            "%s does not declare repeat_enable, but the UV leaves 0..1 within a second and at "
            "200 m from the origin, so the foliage would freeze" % sampler
        )


def test_alpha_writes_match_the_pipeline_they_ask_for():
    """An opaque shader must not write ALPHA; a cut-out shader must write the texture's alpha.

    Both rules come from the spatial shader reference, and both were nearly broken in the same
    audit round, in opposite directions:

      * "ALPHA ... If read from or written to, the material will go to the transparent pipeline."
        So `ALPHA = 1.0` in the opaque shader does not mean "fully opaque": it means every rock,
        wall and terrain surface in the game is drawn in the blended, depth-sorted pass and
        stops casting shadows.
      * "ALPHA_SCISSOR_THRESHOLD ... values below a certain amount of alpha are discarded." The
        value compared is the ALPHA the shader writes, so setting ALPHA to the constant 1.0 in
        the foliage shader makes the threshold discard nothing and every leaf card draws as a
        full rectangle.

    Neither mistake fails to compile and neither looks obviously wrong in a still frame, which
    is why they are checked here rather than left to a device.
    """
    import re

    def code_of(name):
        with open(os.path.join(ROOT, "shaders", name), encoding="utf-8") as handle:
            source = handle.read()
        # Comments are stripped first: a comment quoting the rule must not trip it, and the
        # comment that documents this very rule mentions both patterns.
        return re.sub(r"//[^\n]*", "", source)

    opaque = code_of("surface_base.gdshader")
    assert not re.search(r"\bALPHA\s*=", opaque), (
        "surface_base.gdshader writes ALPHA. Godot puts any shader that writes ALPHA on the "
        "transparent pipeline, even if the value is a constant 1.0, so every opaque surface "
        "would be blended, depth-sorted and unable to cast shadows. Opaque means leaving "
        "ALPHA unwritten"
    )

    foliage = code_of("foliage_base.gdshader")
    assert "ALPHA_SCISSOR_THRESHOLD" in foliage, (
        "foliage_base.gdshader no longer sets an alpha scissor threshold, so leaf cards are "
        "drawn as full quads"
    )
    match = re.search(r"\bALPHA\s*=\s*([^;]+);", foliage)
    assert match, (
        "foliage_base.gdshader sets ALPHA_SCISSOR_THRESHOLD but never writes ALPHA, so the "
        "threshold is compared against the default and nothing is discarded"
    )
    written = match.group(1).strip()
    assert ".a" in written, (
        "foliage_base.gdshader writes ALPHA = %s. The scissor compares exactly that value, so a "
        "constant passes every fragment and the cut-out disappears; it must be the albedo "
        "texture's alpha" % written
    )


def test_flow_accumulation_counts_upstream_area():
    """Each cell in a downhill chain adds the one before it: 1, 2, 3, 4, 5.

    `downhill` is supplied explicitly rather than derived, because the point under test is the
    accumulation order, not the neighbour search. Deriving it drags in D8's diagonal tie-breaking,
    and the first version of this test assumed a chain that the tie-breaking did not actually
    produce — which is a good illustration of how easy it is to believe the wrong thing about this
    algorithm.

    Heights decrease by index, so the counting sort visits cell 0 first: exactly the order a
    correct accumulation needs.
    """
    samples = 5
    heights = [65535 - i * 100 for i in range(samples * samples)]
    downhill = [-1] * (samples * samples)
    for i in range(4):
        downhill[i] = i + 1

    flow = hydrology.accumulate(heights, downhill, samples)

    assert [flow[i] for i in range(5)] == [1.0, 2.0, 3.0, 4.0, 5.0], (
        "accumulation along the chain is %r, expected [1, 2, 3, 4, 5]"
        % [flow[i] for i in range(5)]
    )
    # Everything off the chain is a single cell with no upstream.
    assert all(flow[i] == 1.0 for i in range(5, 25)), "a cell off the chain accumulated flow"


def test_compute_downhill_picks_the_steepest_lower_neighbour():
    """On a plane tilted only in x, every non-edge cell drains to its +x neighbour.

    The +x and the diagonal +x±1 neighbours have the SAME drop, so this only holds if the
    comparison is by gradient: the diagonal is sqrt(2) further away and therefore gentler. The
    first version compared raw drops and sent the flow diagonally.
    """
    samples = 5
    heights = [65535 - x * 1000 for _y in range(samples) for x in range(samples)]
    downhill = hydrology.compute_downhill(heights, samples)
    middle = 2 * samples + 2
    assert downhill[middle] == middle + 1, (
        "the steepest lower neighbour of cell (2,2) is %r, expected %r — a diagonal won a tie it "
        "should have lost" % (downhill[middle], middle + 1)
    )
    # The last column has nothing lower: it is the outlet.
    for y in range(samples):
        assert downhill[y * samples + samples - 1] == -1


def test_flow_accumulation_conserves_cells():
    """Every cell drains to exactly one outlet, so the outlets' flow sums to the cell count.

    Not the sum of ALL flow values — a cell's value is 1 plus everything upstream of it, so the
    total of the array is much larger than the number of cells. The first version of this test
    asserted the wrong invariant and failed against correct code.
    """
    samples = 6
    heights = [65535 - ((x * 37 + y * 91) % 5000) for y in range(samples) for x in range(samples)]
    downhill = hydrology.compute_downhill(heights, samples)
    flow = hydrology.accumulate(heights, downhill, samples)

    outlets = [flow[i] for i, target in enumerate(downhill) if target < 0]
    assert outlets, "the grid has no outlet, which means it has a cycle"
    assert sum(outlets) == float(samples * samples), (
        "the outlets collect %r units, expected %d — flow is being lost or double counted"
        % (sum(outlets), samples * samples)
    )


def test_flow_direction_reserves_zero_for_no_flow():
    """0 means "no flow", so a flowing cell must never encode as 0.

    The first encoding masked the angle with & 0xFF, which mapped a due-west flow — and the -pi
    that atan2 returns on a negative zero — to 0: a flowing cell reporting that it flows nowhere.
    """
    import math

    for step in range(-8, 9):
        for dy in (-1, 0, 1):
            dx = step
            if dx == 0 and dy == 0:
                continue
            angle = math.atan2(dy, dx)
            encoded = 1 + int(round((angle + math.pi) / (2 * math.pi) * 254))
            assert 1 <= encoded <= 255, "direction %r encodes to %d" % ((dx, dy), encoded)


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
    ("shaders: wind UV requires repeat", test_wind_uv_leaves_the_unit_range_so_repeat_is_required),
    ("shaders: alpha writes match the pipeline", test_alpha_writes_match_the_pipeline_they_ask_for),
    ("generators: PNG round trip 8-bit", test_png_round_trip_preserves_every_value),
    ("generators: PNG round trip 16-bit", test_png_round_trip_sixteen_bit),
    ("generators: PNG round trip 2-channel", test_png_round_trip_two_channel),
    ("generators: PNG round trip RGB and RGBA", test_png_round_trip_rgb_and_rgba),
    ("generators: PNG rejects 16-bit colour", test_png_rejects_sixteen_bit_colour),
    ("terrain surfaces: smoothstep is clamped", test_smoothstep_is_clamped_and_monotonic),
    ("terrain surfaces: splat weights sum to one", test_splat_weights_sum_to_one),
    ("hydrology: flow accumulates upstream", test_flow_accumulation_counts_upstream_area),
    ("hydrology: downhill picks the steepest", test_compute_downhill_picks_the_steepest_lower_neighbour),
    ("hydrology: flow conserves cells", test_flow_accumulation_conserves_cells),
    ("hydrology: direction reserves zero", test_flow_direction_reserves_zero_for_no_flow),
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
