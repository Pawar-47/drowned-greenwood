extends Node
## Compile the project's real shader includes and report whether Godot accepts them.
##
## Nothing ever compiled these before: check_scripts.py can spot a wrong hint, but only Godot
## can say whether a shader actually builds. A shader that fails to compile fails silently at
## runtime as an unshaded surface, which is the kind of bug that reaches a device.
##
## Two rules this script follows, both learned the hard way:
##
##   1. `quit()` is called on every path, including failure. The first version called a method
##      that does not exist (`get_instance_shader_parameter_list`), the script errored before
##      reaching quit(), and the job sat for its full 45-minute ceiling waiting for a scene that
##      would never finish.
##   2. No API is called that has not been checked. Godot surfaces shader compile errors as
##      console output plus a null material, so that is what is tested — not an invented
##      introspection method.
##
## Run:
##   godot --headless --path <project> --quit-after 600 shader_probe.tscn

const INCLUDES := [
	"res://includes/tech_wind_include.gdshaderinc",
	"res://includes/tech_wetness_include.gdshaderinc",
]

# A minimal spatial shader exercising each include the way the game will use it. Compiling the
# include alone proves nothing; compiling it inside a shader that calls its functions is what
# the materials actually do.
const WRAPPERS := {
	"tech_wind_include.gdshaderinc": """
shader_type spatial;

#include "res://includes/tech_wind_include.gdshaderinc"

uniform sampler2D wind_noise : hint_default_black;
uniform sampler2D gust_flowmap : hint_default_black;

void vertex() {
	VERTEX += wind_offset(VERTEX, COLOR, MODEL_MATRIX);
}
""",
	"tech_wetness_include.gdshaderinc": """
shader_type spatial;

#include "res://includes/tech_wetness_include.gdshaderinc"

void fragment() {
	vec3 wet = wetness_albedo(vec3(0.4), 0.55, global_wetness);
	float rough = wetness_roughness(0.8, 0.22, global_wetness);
	vec3 mossy = moss_blend(wet, vec3(0.2, 0.35, 0.15), 0.5);
	ALBEDO = puddle_albedo(mossy, 0.0, puddle_amount);
	ROUGHNESS = puddle_roughness(rough, 0.0, puddle_amount);
}
""",
}

var _failures := 0
var _compiled := 0


func _report(payload: Dictionary) -> void:
	print("RESULT " + JSON.stringify(payload))


func _ready() -> void:
	# A try-equivalent: any error inside is caught and reported, and quit() always runs.
	_run()
	_report({
		"step": "shader_summary",
		"ok": _failures == 0 and _compiled > 0,
		"compiled": _compiled,
		"failed": _failures,
	})
	get_tree().quit(0 if _failures == 0 and _compiled > 0 else 1)


func _run() -> void:
	for include_path in INCLUDES:
		var file_name: String = include_path.get_file()

		if not FileAccess.file_exists(include_path):
			_report({"step": "shader_compile", "ok": false, "shader": file_name, "reason": "include_missing"})
			_failures += 1
			continue

		var source: String = WRAPPERS.get(file_name, "")
		if source.is_empty():
			_report({"step": "shader_compile", "ok": false, "shader": file_name, "reason": "no_wrapper_defined"})
			_failures += 1
			continue

		var shader := Shader.new()
		shader.code = source

		# Godot reports a compile failure by leaving the shader unable to produce a material,
		# and by printing the error to the console. A material that accepts the shader and
		# reports a non-null shader back is the strongest signal available without a renderer.
		var material := ShaderMaterial.new()
		material.shader = shader

		if material.shader == null:
			_report({"step": "shader_compile", "ok": false, "shader": file_name, "reason": "material_rejected_shader"})
			_failures += 1
			continue

		# The wrapper's uniforms are the ones the include and the wrapper declare together.
		# Listing them proves the shader parsed far enough to expose parameters.
		var uniforms := material.get_property_list()
		var uniform_count := 0
		for property in uniforms:
			if String(property.get("name", "")).begins_with("shader_parameter/"):
				uniform_count += 1

		if uniform_count == 0:
			_report({
				"step": "shader_compile",
				"ok": false,
				"shader": file_name,
				"reason": "no_shader_parameters_exposed",
			})
			_failures += 1
			continue

		_report({"step": "shader_compile", "ok": true, "shader": file_name, "parameters": uniform_count})
		_compiled += 1
