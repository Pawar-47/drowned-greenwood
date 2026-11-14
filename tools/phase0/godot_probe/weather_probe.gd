extends Node
## Load every weather preset and the profiles file that names them.
##
## A .tres is text that Godot parses by property name, so a shader-free static check can prove the
## names are real but not that the file loads as an Environment the renderer accepts. This does the
## second half: every preset must load, be an Environment, carry a sky with a material, draw that
## sky, and have fog and glow on with a fog density in a sane band. The profiles file must name
## exactly the presets that exist, in both directions — a state with no file, or a file no state
## names, is a preset nobody will ever see.
##
## Run:
##   godot --headless --path <project> --quit-after 120 weather_probe.tscn

const ENV_DIR := "res://env"
const PROFILES := "res://env/env_weather_profiles.json"


func _ready() -> void:
	var problems: Array[String] = []
	var presets: Array[String] = []

	var directory := DirAccess.open(ENV_DIR)
	if directory == null:
		problems.append("no %s directory; the copy step did not run" % ENV_DIR)
	else:
		for name in directory.get_files():
			if name.ends_with(".tres"):
				presets.append(name)
	presets.sort()

	for name in presets:
		problems.append_array(_check_preset(name))
	problems.append_array(_check_profiles(presets))

	var payload := {
		"step": "weather_presets",
		"ok": problems.is_empty(),
		"presets": presets.size(),
		"failures": problems.slice(0, 6),
	}
	print("RESULT " + JSON.stringify(payload))
	# quit() on every path, for the reason the shader probe documents: a probe that errors before
	# reaching it leaves the job to its ceiling instead of reporting a failure.
	get_tree().quit(0 if problems.is_empty() else 1)


func _check_preset(name: String) -> Array[String]:
	var problems: Array[String] = []
	var path := "%s/%s" % [ENV_DIR, name]
	if not ResourceLoader.exists(path):
		problems.append("%s does not exist" % path)
		return problems

	var resource := load(path)
	if resource == null:
		problems.append("%s did not load" % name)
		return problems
	if not (resource is Environment):
		problems.append("%s is not an Environment" % name)
		return problems

	var environment := resource as Environment
	if environment.sky == null:
		problems.append("%s has no sky" % name)
	elif environment.sky.sky_material == null:
		problems.append("%s has a sky with no material" % name)
	if environment.background_mode != Environment.BG_SKY:
		problems.append(
			"%s does not draw its sky (background_mode %d)" % [name, environment.background_mode]
		)
	if not environment.fog_enabled:
		problems.append("%s has fog disabled" % name)
	if environment.fog_density <= 0.0 or environment.fog_density > 0.1:
		problems.append(
			"%s has fog_density %f outside 0.0..0.1" % [name, environment.fog_density]
		)
	if not environment.glow_enabled:
		problems.append("%s has glow disabled" % name)
	return problems


func _check_profiles(presets: Array[String]) -> Array[String]:
	var problems: Array[String] = []
	if not FileAccess.file_exists(PROFILES):
		problems.append("%s is missing" % PROFILES)
		return problems
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(PROFILES))
	if not (parsed is Dictionary):
		problems.append("%s is not valid JSON" % PROFILES)
		return problems
	var states: Dictionary = parsed.get("states", {})
	if states.is_empty():
		problems.append("%s declares no states" % PROFILES)
		return problems

	for state in states:
		var expected := "env_weather_%s.tres" % state
		if not presets.has(expected):
			problems.append("%s declares %s but %s is missing" % [PROFILES, state, expected])
	for file in presets:
		var state := file.trim_prefix("env_weather_").trim_suffix(".tres")
		if not states.has(state):
			problems.append("%s exists but the profiles do not declare %s" % [file, state])
	return problems
