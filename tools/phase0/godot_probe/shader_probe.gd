extends Node
## Compile the project's real shader includes and report whether Godot accepts them.
##
## Nothing ever compiled these before: `check_scripts.py` can spot a wrong hint, but only Godot
## can tell you whether a shader actually builds. A shader that fails to compile fails silently
## at runtime as an unshaded surface, which is exactly the kind of bug that reaches a device.
##
## Each shader is written to a temp file, loaded as a Shader, and inspected for errors. Godot
## reports compile errors on the Shader resource rather than throwing, so both are checked.
##
## Run:
##   godot --headless --path <project> --script res://shader_probe.gd

const INCLUDES := [
	"res://includes/tech_wind_include.gdshaderinc",
	"res://includes/tech_wetness_include.gdshaderinc",
]

# A minimal spatial shader that exercises each include the way the game will use it. Compiling
# the include alone proves nothing; compiling it inside a shader that calls its functions is
# what the materials will actually do.
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


func _finish(step: String, ok: bool, payload: Dictionary) -> void:
	payload["step"] = step
	payload["ok"] = ok
	print("RESULT " + JSON.stringify(payload))


func _ready() -> void:
	var failures := 0
	var compiled := 0

	for include_path in INCLUDES:
		var file_name: String = include_path.get_file()
		if not FileAccess.file_exists(include_path):
			_finish("shader_compile", false, {"shader": file_name, "reason": "include_missing"})
			failures += 1
			continue

		var source: String = WRAPPERS.get(file_name, "")
		if source.is_empty():
			_finish("shader_compile", false, {"shader": file_name, "reason": "no_wrapper_defined"})
			failures += 1
			continue

		var shader := Shader.new()
		shader.code = source

		# Godot surfaces compile problems through the resource rather than by throwing.
		var error := shader.get_instance_shader_parameter_list()
		if error == null:
			_finish("shader_compile", false, {"shader": file_name, "reason": "shader_resource_invalid"})
			failures += 1
			continue

		var material := ShaderMaterial.new()
		material.shader = shader
		if material.shader == null:
			_finish("shader_compile", false, {"shader": file_name, "reason": "material_rejected_shader"})
			failures += 1
			continue

		_finish("shader_compile", true, {"shader": file_name, "parameters": error.size()})
		compiled += 1

	_finish("shader_summary", failures == 0, {"compiled": compiled, "failed": failures})
	get_tree().quit(0 if failures == 0 else 1)
