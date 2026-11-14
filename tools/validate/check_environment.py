#!/usr/bin/env python3
"""Check the weather presets against the manifest, Godot's property list and each other.

Run:
    python tools/validate/check_environment.py

Why this exists: a `.tres` is a text file Godot parses by property name, and Godot's failure mode for
a name it does not know is quiet — the line is ignored, or the resource loads with a default where a
value was meant. A preset that sets `fog_height_density` as `fog_heightdensity` looks correct in
review, loads without complaint, and puts the fog at the wrong height on a device. Nothing else in
this repository reads these files, so the name list is checked here against the Godot 4.2 class
reference rather than trusted.

The other half is consistency. `assets/env/env_weather_profiles.json` holds the drivers an
Environment cannot express and `env_transition_curves.json` says how each one moves; a driver in one
and not the other is either a value that jumps or a curve nothing reads. Both directions fail.

What this does not check: that Godot renders the preset the way it was designed to look. That is a
device question, and the Phase 0 shader gate compiles under Compatibility rather than Mobile.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_DIR = os.path.join("assets", "env")
PROFILES = os.path.join(ENV_DIR, "env_weather_profiles.json")
CURVES = os.path.join(ENV_DIR, "env_transition_curves.json")

# Every property of Environment, Sky and ProceduralSkyMaterial in Godot 4.2. A name outside this set
# is not a value Godot will read, whatever it looks like.
ENVIRONMENT_PROPERTIES = {
    "adjustment_brightness", "adjustment_color_correction", "adjustment_contrast",
    "adjustment_enabled", "adjustment_saturation",
    "ambient_light_color", "ambient_light_energy", "ambient_light_sky_contribution",
    "ambient_light_source",
    "background_camera_feed_id", "background_canvas_max_layer", "background_color",
    "background_energy_multiplier", "background_intensity", "background_mode",
    "fog_aerial_perspective", "fog_density", "fog_enabled", "fog_height", "fog_height_density",
    "fog_light_color", "fog_light_energy", "fog_sky_affect", "fog_sun_scatter",
    "glow_blend_mode", "glow_bloom", "glow_enabled", "glow_hdr_luminance_cap", "glow_hdr_scale",
    "glow_hdr_threshold", "glow_intensity", "glow_map", "glow_map_strength", "glow_mix",
    "glow_normalized", "glow_strength",
    "reflected_light_source", "sky", "sky_custom_fov", "sky_rotation",
    "ssao_ao_channel_affect", "ssao_detail", "ssao_enabled", "ssao_horizon", "ssao_intensity",
    "ssao_light_affect", "ssao_power", "ssao_radius", "ssao_sharpness",
    "ssil_enabled", "ssil_intensity", "ssil_normal_rejection", "ssil_radius", "ssil_sharpness",
    "ssr_depth_tolerance", "ssr_enabled", "ssr_fade_in", "ssr_fade_out", "ssr_max_steps",
    "sdfgi_bounce_feedback", "sdfgi_cascade0_distance", "sdfgi_cascades", "sdfgi_enabled",
    "sdfgi_energy", "sdfgi_max_distance", "sdfgi_min_cell_size", "sdfgi_normal_bias",
    "sdfgi_probe_bias", "sdfgi_read_sky_light", "sdfgi_use_occlusion", "sdfgi_y_scale",
    "tonemap_exposure", "tonemap_mode", "tonemap_white",
}
ENVIRONMENT_PROPERTIES |= {"glow_levels/%d" % level for level in range(1, 8)}
ENVIRONMENT_PROPERTIES |= {"volumetric_fog_%s" % suffix for suffix in (
    "albedo", "ambient_inject", "anisotropy", "density", "detail_spread", "emission",
    "emission_energy", "enabled", "gi_inject", "length", "sky_affect",
    "temporal_reprojection_amount", "temporal_reprojection_enabled",
)}

SKY_PROPERTIES = {"process_mode", "radiance_size", "sky_material"}

PROCEDURAL_SKY_PROPERTIES = {
    "ground_bottom_color", "ground_curve", "ground_energy_multiplier", "ground_horizon_color",
    "sky_cover", "sky_cover_modulate", "sky_curve", "sky_energy_multiplier",
    "sky_horizon_color", "sky_top_color", "sun_angle_max", "sun_curve", "use_debanding",
}

ALLOWED = {
    "Environment": ENVIRONMENT_PROPERTIES,
    "Sky": SKY_PROPERTIES,
    "ProceduralSkyMaterial": PROCEDURAL_SKY_PROPERTIES,
}

# Enumerations, as integers: the value must be one the class defines or Godot clamps it.
ENUMS = {
    "background_mode": 6,
    "ambient_light_source": 4,
    "reflected_light_source": 3,
    "tonemap_mode": 4,
    "glow_blend_mode": 5,
    "radiance_size": 8,
    "process_mode": 4,
}

# Properties the presets must set. A preset without fog or glow is not a weather state; it is the
# default environment with a name.
REQUIRED = ("background_mode", "sky", "ambient_light_source", "tonemap_mode", "fog_enabled",
            "fog_density", "glow_enabled", "glow_intensity")

# The drivers the weather system interpolates. `rain_intensity` is not a shader global; the other
# four are, and SHADER_GLOBALS.md names them.
DRIVERS = ("rain_intensity", "global_wetness", "puddle_amount", "wind_strength", "wind_gust")
CURVE_NAMES = ("linear", "ease_in", "ease_out", "ease_in_out")

COLOUR = re.compile(r"^Color\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)$")
NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
RESOURCE_REF = re.compile(r"^(?:SubResource\(\"[^\"]+\"\)|null|ExtResource\(\"[^\"]+\"\))$")
SECTION = re.compile(r"^\[(gd_resource|sub_resource|resource)\b(.*)\]$")
TYPE = re.compile(r'type="([^"]+)"')


def read_json(relative):
    path = os.path.join(ROOT, relative)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def read_lines(relative):
    with open(os.path.join(ROOT, relative), "r", encoding="utf-8") as handle:
        return handle.read().splitlines()


def parse_tres(relative, problems):
    """The properties of a .tres, by section: {'resource': {...}, 'sub:-N:Type': {...}}."""
    sections = {}
    current = None
    current_type = None
    for number, raw in enumerate(read_lines(relative), start=1):
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        match = SECTION.match(line)
        if match:
            kind = match.group(1)
            declared = TYPE.search(match.group(2))
            current_type = declared.group(1) if declared else ("Environment" if kind == "gd_resource" else "")
            if kind == "resource":
                current = "resource"
            else:
                current = "sub:%d:%s" % (number, current_type)
            sections.setdefault(current, {})
            continue
        if current is None or "=" not in line:
            continue
        key, _sep, value = line.partition("=")
        key = key.strip()
        sections[current][key] = (value.strip(), number, current_type)
    return sections


def check_value(where, key, value, number, problems):
    enums = ENUMS.get(key)
    if enums is not None:
        if not NUMBER.match(value) or not 0 <= int(float(value)) < enums:
            problems.append("%s:%d: %s is %r, which is not one of Godot's %d values" % (where, number, key, value, enums))
        return
    colour = COLOUR.match(value)
    if colour:
        for channel in colour.groups():
            if not 0.0 <= float(channel) <= 1.0:
                problems.append("%s:%d: %s has a channel outside 0..1 (%s)" % (where, number, key, channel))
        return
    if value in ("true", "false"):
        return
    if RESOURCE_REF.match(value):
        return
    if NUMBER.match(value):
        number_value = float(value)
        if key in ("fog_density", "fog_aerial_perspective", "fog_sky_affect", "fog_sun_scatter",
                   "ambient_light_sky_contribution", "sky_curve", "ground_curve", "sun_curve"):
            if not 0.0 <= number_value <= 1.0:
                problems.append("%s:%d: %s is %s, outside 0..1" % (where, number, key, value))
        if number_value < 0.0:
            problems.append("%s:%d: %s is negative (%s)" % (where, number, key, value))
        return
    problems.append("%s:%d: %s = %r is not a value this checker understands" % (where, number, key, value))


def check_preset(relative, problems):
    sections = parse_tres(relative, problems)
    environment = sections.get("resource")
    if environment is None:
        problems.append("%s has no [resource] section, so it declares no Environment" % relative)
        return

    for key, (value, number, resource_type) in sorted(environment.items()):
        allowed = ALLOWED.get(resource_type or "Environment", ENVIRONMENT_PROPERTIES)
        if key not in allowed:
            problems.append(
                "%s:%d: %r is not a property of %s in Godot 4.2, so Godot will ignore it"
                % (relative, number, key, resource_type or "Environment")
            )
            continue
        check_value(relative, key, value, number, problems)

    for key in REQUIRED:
        if key not in environment:
            problems.append("%s does not set %s, so it is not a complete weather state" % (relative, key))
    if environment.get("background_mode", ("", 0, ""))[0] != "2":
        problems.append("%s does not use the sky as its background (background_mode = 2)" % relative)
    if "sky" not in environment:
        problems.append("%s has no sky reference" % relative)

    sky_sections = [s for s in sections.values() if "sky_material" in s]
    if not sky_sections:
        problems.append("%s declares no Sky sub-resource" % relative)
    for section in sections.values():
        for key, (value, number, resource_type) in sorted(section.items()):
            if resource_type in ("Sky", "ProceduralSkyMaterial"):
                if key not in ALLOWED[resource_type]:
                    problems.append(
                        "%s:%d: %r is not a property of %s in Godot 4.2"
                        % (relative, number, key, resource_type)
                    )
                else:
                    check_value(relative, key, value, number, problems)


def check_profiles(manifest_states, problems):
    if not os.path.exists(os.path.join(ROOT, PROFILES)):
        problems.append("%s is missing: nothing supplies the weather drivers" % PROFILES)
        return None
    profiles = read_json(PROFILES)

    drivers = profiles.get("drivers")
    if list(drivers or []) != list(DRIVERS):
        problems.append(
            "%s: drivers are %r, expected %r — the transition curves and the shader globals are "
            "written against this list" % (PROFILES, drivers, list(DRIVERS))
        )

    states = profiles.get("states") or {}
    if sorted(states) != sorted(manifest_states):
        problems.append(
            "%s: states are %s; the manifest declares %s"
            % (PROFILES, sorted(states), sorted(manifest_states))
        )
    for name, row in sorted(states.items()):
        where = "%s:%s" % (PROFILES, name)
        if row.get("assets") != "env_weather_" + name:
            problems.append("%s: assets is %r, expected %r" % (where, row.get("assets"), "env_weather_" + name))
        expected_tres = "res://assets/env/env_weather_%s.tres" % name
        if row.get("tres") != expected_tres:
            problems.append("%s: tres is %r, expected %r" % (where, row.get("tres"), expected_tres))
        for driver in DRIVERS:
            value = row.get(driver)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append("%s: %s is %r, not a number" % (where, driver, value))
            elif not 0.0 <= float(value) <= 1.0:
                problems.append("%s: %s is %s, outside 0..1" % (where, driver, value))

    tiers = profiles.get("quality_tiers") or {}
    for tier in ("low", "medium", "high"):
        if tier not in tiers:
            problems.append("%s: no %r quality tier" % (PROFILES, tier))
            continue
        if not isinstance(tiers[tier].get("glow"), bool):
            problems.append("%s: tier %r does not say whether glow is on" % (PROFILES, tier))
        scale = tiers[tier].get("rain_particles_scale")
        if not isinstance(scale, (int, float)) or not 0.0 < float(scale) <= 1.0:
            problems.append("%s: tier %r has no rain_particles_scale in 0..1" % (PROFILES, tier))
    if tiers.get("low", {}).get("glow") is not False:
        problems.append("%s: the low tier must turn glow off (approved addition 1)" % PROFILES)

    maximum = profiles.get("rain_particles_max")
    if not isinstance(maximum, int) or maximum <= 0:
        problems.append("%s: rain_particles_max is %r" % (PROFILES, maximum))
    default = profiles.get("default_state")
    if default not in states:
        problems.append("%s: default_state %r is not one of the states" % (PROFILES, default))
    return profiles


def check_curves(profiles, problems):
    if not os.path.exists(os.path.join(ROOT, CURVES)):
        problems.append("%s is missing: nothing says how the weather moves between states" % CURVES)
        return
    curves = read_json(CURVES)

    named = curves.get("curves") or {}
    for name in CURVE_NAMES:
        if name not in named:
            problems.append("%s: curve %r is not described" % (CURVES, name))

    drivers = curves.get("drivers") or {}
    if profiles is not None:
        expected = set(profiles.get("drivers") or [])
        if set(drivers) != expected:
            problems.append(
                "%s: drivers are %s; the profiles declare %s — a driver with no curve jumps, and a "
                "curve with no driver is dead" % (CURVES, sorted(drivers), sorted(expected))
            )
    for name, row in sorted(drivers.items()):
        where = "%s:%s" % (CURVES, name)
        if row.get("curve") not in CURVE_NAMES:
            problems.append("%s: curve %r is not one of %s" % (where, row.get("curve"), ", ".join(CURVE_NAMES)))
        for key in ("rise_seconds", "fall_seconds"):
            value = row.get(key)
            if not isinstance(value, (int, float)) or value <= 0.0:
                problems.append("%s: %s is %r, and a transition takes time" % (where, key, value))

    default = curves.get("default") or {}
    if default.get("curve") not in CURVE_NAMES:
        problems.append("%s: the default curve is %r" % (CURVES, default.get("curve")))
    if not isinstance(default.get("seconds"), (int, float)) or default.get("seconds") <= 0.0:
        problems.append("%s: the default duration is %r" % (CURVES, default.get("seconds")))

    for pair, row in sorted((curves.get("pairs") or {}).items()):
        where = "%s:%s" % (CURVES, pair)
        if "->" not in pair:
            problems.append("%s: an ordered pair is written from->to" % where)
            continue
        source, target = pair.split("->", 1)
        if profiles is not None:
            for state in (source, target):
                if state not in (profiles.get("states") or {}):
                    problems.append("%s names %r, which is not a weather state" % (where, state))
        if row.get("curve") not in CURVE_NAMES:
            problems.append("%s: curve %r is not one of %s" % (where, row.get("curve"), ", ".join(CURVE_NAMES)))
        if not isinstance(row.get("seconds"), (int, float)) or row.get("seconds") <= 0.0:
            problems.append("%s: seconds is %r" % (where, row.get("seconds")))


def main():
    problems = []
    manifest = read_json(os.path.join("assets", "manifest.json"))
    group = manifest.get("categories", {}).get("4.A.env", {})
    declared = list(group.get("assets") or [])
    if not declared:
        problems.append("assets/manifest.json no longer declares the 4.A.env weather group")

    presets = [name for name in declared if name.startswith("env_weather_")]
    for name in presets:
        relative = os.path.join("assets", "env", name + ".tres")
        if not os.path.exists(os.path.join(ROOT, relative)):
            problems.append("%s is declared in the manifest but %s does not exist" % (name, relative))
            continue
        check_preset(relative.replace(os.sep, "/"), problems)

    states = [name[len("env_weather_"):] for name in presets]
    profiles = check_profiles(states, problems)
    check_curves(profiles, problems)

    if "env_transition_curves" in declared:
        for state in states:
            if "env_weather_" + state not in declared:
                problems.append("the manifest declares a state %r with no preset" % state)
    else:
        problems.append("assets/manifest.json no longer declares env_transition_curves")

    if problems:
        print("environment preset checks failed:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1

    print(
        "environment: %d presets, every property a Godot 4.2 Environment/Sky/ProceduralSkyMaterial "
        "property, %d drivers with a curve in both directions, low tier glow off"
        % (len(presets), len(DRIVERS))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
