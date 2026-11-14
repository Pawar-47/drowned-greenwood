extends Node
## Compile the project's real shader includes and report whether Godot accepts them.
##
## Nothing compiled these before: check_scripts.py can spot a wrong hint, but only Godot can
## say whether a shader actually builds. A shader that fails to compile fails silently at
## runtime as an unshaded surface, which is the kind of bug that reaches a device.
##
## Four rules here, each learned from a specific failure:
##
##   1. `quit()` runs on every path. The first version called a method that does not exist,
##      errored before reaching quit(), and the job sat until its 45-minute ceiling.
##   2. Only documented APIs. `Shader.get_instance_shader_parameter_list()` does not exist;
##      the real one is `Shader.get_shader_uniform_list()`.
##   3. No duplicate declarations. The include already declares `wind_noise` and
##      `gust_flowmap`; the wrapper used to declare them again, which is a compile error.
##   4. A non-empty uniform list is evidence, not proof. Each include's expected uniforms are
##      named, and the probe fails if they are missing — that is what "compiled" means here.
##
## Run:
##   godot --headless --path <project> --quit-after 120 shader_probe.tscn

const INCLUDES := [
	"res://includes/tech_wind_include.gdshaderinc",
	"res://includes/tech_wetness_include.gdshaderinc",
	# The two material shaders are complete shaders, not includes, so they are compiled as-is
	# rather than wrapped. They are here because they are the ones every opaque surface and every
	# plant in the game will actually use — a material system nothing compiles is a material
	# system whose first real test is on a device.
	"res://includes/surface_base.gdshader",
	"res://includes/foliage_base.gdshader",
	# Water is a complete shader too, and it decodes the hydrology mask — R depth, G/B flow — so it
	# is the one place a channel-order mistake would render plausible-looking water of the wrong
	# depth. Compiling it proves the declarations; check_materials.py checks the scale matches the
	# generator.
	"res://includes/water_base.gdshader",
]

# Each wrapper exercises its include the way the game will: the wind include from vertex(),
# the wetness include from fragment(). The sampler uniforms are declared by the include, so
# the wrapper must not repeat them.
#
# Each wrapper also declares `probe_marker`. The wetness include exposes only *global* uniforms,
# which may not surface in get_shader_uniform_list(); without a regular uniform the probe could
# see an empty list from a shader that compiled perfectly and call it a failure.
const WRAPPERS := {
	"tech_wind_include.gdshaderinc": """
shader_type spatial;

#include "res://includes/tech_wind_include.gdshaderinc"

uniform float probe_marker : hint_range(0.0, 1.0) = 1.0;

void vertex() {
	VERTEX += wind_offset(VERTEX, COLOR, MODEL_MATRIX);
}
""",
	"tech_wetness_include.gdshaderinc": """
shader_type spatial;

#include "res://includes/tech_wetness_include.gdshaderinc"

uniform float probe_marker : hint_range(0.0, 1.0) = 1.0;

void fragment() {
	vec3 wet = wetness_albedo(vec3(0.4), 0.55, global_wetness);
	float rough = wetness_roughness(0.8, 0.22, global_wetness);
	vec3 mossy = moss_blend(wet, vec3(0.2, 0.35, 0.15), 0.5);
	ALBEDO = puddle_albedo(mossy, 0.0, puddle_amount);
	ROUGHNESS = puddle_roughness(rough, 0.0, puddle_amount);
}
""",
}

# The uniform a successfully compiled wrapper must expose. `probe_marker` is the one uniform
# every wrapper declares itself, so its presence proves the shader parsed and built.
const EXPECTED_UNIFORMS := {
	"tech_wind_include.gdshaderinc": ["probe_marker", "wind_noise", "gust_flowmap"],
	"tech_wetness_include.gdshaderinc": ["probe_marker", "wetness_darken"],
	# For the full shaders the expectation is the material's own controls. If an include stops
	# being resolved, these disappear and the probe fails, which is the point.
	"surface_base.gdshader": ["albedo_tex", "normal_tex", "orm_tex", "moss_mask_tex", "puddle_mask_tex", "wetness_darken"],
	"foliage_base.gdshader": ["albedo_tex", "normal_tex", "alpha_cutoff", "translucency", "wind_noise", "wetness_darken"],
	# The globals are deliberately not listed: Godot does not promise to surface them here, and the
	# probe's own comment says so. These are the uniforms that prove the fog/water body parsed.
	"water_base.gdshader": ["hydrology_tex", "shore_tex", "depth_scale_m", "shallow_color", "deep_color", "min_alpha", "max_alpha"],
}

var _failures := 0
var _compiled := 0


func _report(payload: Dictionary) -> void:
	print("RESULT " + JSON.stringify(payload))


func _ready() -> void:
	# Any escaped error inside _run() still leaves _ready() to report and quit.
	var error := _run()
	if error != "":
		_report({"step": "shader_probe_error", "ok": false, "error": error})
		_failures += 1

	_report({
		"step": "shader_summary",
		"ok": _failures == 0 and _compiled > 0,
		"compiled": _compiled,
		"failed": _failures,
	})
	get_tree().quit(0 if _failures == 0 and _compiled > 0 else 1)


func _run() -> String:
	for include_path in INCLUDES:
		var file_name: String = include_path.get_file()
		# One result per include. A shared step name would let the last include overwrite the
		# earlier ones in the report, so a passing shader could mask a failing one.
		var step := "shader_compile_" + file_name.get_basename().replace(".", "_")

		if not FileAccess.file_exists(include_path):
			_report({"step": step, "ok": false, "shader": file_name, "reason": "include_missing"})
			_failures += 1
			continue

		var source: String = WRAPPERS.get(file_name, "")
		if source.is_empty():
			# A complete shader compiles on its own; only an include needs a wrapper to give it
			# a shader_type and a function to be used from.
			if file_name.ends_with(".gdshader"):
				source = FileAccess.get_file_as_string(include_path)
			if source.is_empty():
				_report({"step": step, "ok": false, "shader": file_name, "reason": "no_wrapper_defined"})
				_failures += 1
				continue

		var shader := Shader.new()
		shader.code = source

		# The documented way to read a shader's uniforms. A shader that failed to compile
		# returns an empty list, which is the failure this probe exists to catch.
		var uniforms := shader.get_shader_uniform_list()
		var names := []
		for uniform in uniforms:
			names.append(String(uniform.get("name", "")))

		var expected: Array = EXPECTED_UNIFORMS.get(file_name, [])
		var missing := []
		for wanted in expected:
			if not names.has(wanted):
				missing.append(wanted)

		if missing.size() > 0:
			_report({
				"step": step,
				"ok": false,
				"shader": file_name,
				"reason": "compile_failed_or_uniforms_missing",
				"missing": missing,
				"found": names,
			})
			_failures += 1
			continue

		_report({
			"step": step,
			"ok": true,
			"shader": file_name,
			"uniforms": names.size(),
			"names": names,
		})
		_compiled += 1

	return ""
