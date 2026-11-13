extends Node
## Phase 0 probe: load the GLB beside this scene, count what actually arrived, and exit.
##
## Prints one JSON RESULT line so the workflow log carries the detail, not just an exit code.
## The label distinguishes the runs (plain, gltfpack, gltfpack_noq) so their rows cannot
## overwrite each other in the report.
##
## Run:
##   godot --headless --path <project> -- label=plain

const GLB := "res://probe_sphere.glb"


func _label() -> String:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("label="):
			return arg.substr("label=".length())
	return "unlabelled"


func _finish(label: String, payload: Dictionary) -> void:
	payload["step"] = "godot_scene_%s" % label
	print("RESULT " + JSON.stringify(payload))
	get_tree().quit(0 if payload.get("ok", false) else 1)


func _ready() -> void:
	var label := _label()

	if not ResourceLoader.exists(GLB):
		_finish(label, {"ok": false, "reason": "glb_missing"})
		return

	var packed: Resource = load(GLB)
	if packed == null:
		_finish(label, {"ok": false, "reason": "load_returned_null"})
		return

	var root: Node = packed.instantiate()
	add_child(root)

	var meshes := 0
	var surfaces := 0
	var triangles := 0
	var empty_meshes := 0
	var materials := 0
	var vertex_colours := 0
	var wind_mask_vertices := 0

	var stack: Array[Node] = [root]
	while stack.size() > 0:
		var node: Node = stack.pop_back()
		for child in node.get_children():
			stack.append(child)
		if node is MeshInstance3D:
			meshes += 1
			var mesh: Mesh = (node as MeshInstance3D).mesh
			if mesh == null:
				empty_meshes += 1
				continue
			for surface in range(mesh.get_surface_count()):
				surfaces += 1
				if mesh.surface_get_material(surface) != null:
					materials += 1
				var arrays := mesh.surface_get_arrays(surface)
				var indices = arrays[Mesh.ARRAY_INDEX]
				if indices != null:
					triangles += int(indices.size() / 3)
				else:
					var vertices = arrays[Mesh.ARRAY_VERTEX]
					if vertices != null:
						triangles += int(vertices.size() / 3)
				# The wind mask is the ALPHA of COLOR_0, so its survival is the thing this probe
				# exists to prove. gltfpack is free to drop an attribute nothing uses, and the
				# sphere in the Blender probe is authored with it precisely so that loss is
				# visible here rather than as motionless trees in Phase 3.
				var colours = arrays[Mesh.ARRAY_COLOR]
				if colours != null:
					vertex_colours += int(colours.size())
					for colour in colours:
						if colour.a < 1.0:
							wind_mask_vertices += 1

	# A mesh node whose mesh failed to decode is the failure worth naming: it means Godot
	# accepted the file but could not build geometry from it. Vertex colours are part of `ok` for
	# the same reason triangles are: a mesh that arrives without them is not the mesh that was
	# exported, and nothing downstream would notice until the foliage stopped moving.
	_finish(label, {
		"ok": meshes > 0 and triangles > 0 and vertex_colours > 0,
		"meshes": meshes,
		"empty_meshes": empty_meshes,
		"surfaces": surfaces,
		"materials": materials,
		"tris": triangles,
		"vertex_colours": vertex_colours,
		"wind_mask_vertices": wind_mask_vertices,
	})
