extends Node
## Phase 0 probe: load the GLB written by Blender, count what actually arrived, and exit.
## Prints one RESULT line so the workflow log shows the import gate's outcome.

func _ready() -> void:
	const PATH := "res://probe_sphere.glb"
	if not ResourceLoader.exists(PATH):
		print("RESULT godot_load ok=False reason=glb_missing")
		get_tree().quit(1)
		return

	var packed: Resource = load(PATH)
	if packed == null:
		print("RESULT godot_load ok=False reason=load_returned_null")
		get_tree().quit(1)
		return

	var root: Node = packed.instantiate()
	add_child(root)

	var meshes := 0
	var triangles := 0
	var surfaces := 0
	var stack: Array[Node] = [root]
	while stack.size() > 0:
		var node: Node = stack.pop_back()
		for child in node.get_children():
			stack.append(child)
		if node is MeshInstance3D:
			meshes += 1
			var mesh: Mesh = (node as MeshInstance3D).mesh
			if mesh != null:
				for surface in range(mesh.get_surface_count()):
					surfaces += 1
					var arrays := mesh.surface_get_arrays(surface)
					var indices = arrays[Mesh.ARRAY_INDEX]
					if indices != null:
						triangles += int(indices.size() / 3)
					else:
						var vertices = arrays[Mesh.ARRAY_VERTEX]
						if vertices != null:
							triangles += int(vertices.size() / 3)

	print("RESULT godot_load ok=True meshes=%d surfaces=%d tris=%d" % [meshes, surfaces, triangles])
	get_tree().quit(0 if meshes > 0 and triangles > 0 else 1)
