extends Node
## Load the hydrology mask in Godot and assert the channel contract it was written to.
##
## Why this exists: `validate.yml` checks the PNG header — colour type 2, 8-bit, 1025² — which
## proves what the generator wrote, not what the engine reads. Those are different claims. The
## original bug was exactly that gap: a 2-channel PNG is grey-plus-alpha, so Godot would have put
## the flow direction in A and mirrored the depth into G, and every header check would still have
## passed. Only loading it here settles it.
##
## Run:
##   godot --headless --path <project> --quit-after 120 hydrology_probe.tscn
##
## The mask is generated in the same job and copied beside this scene, so a missing file is a
## mis-wired workflow rather than a broken generator, and it says so.

const MASK := "res://terrain_hydrology_mask.png"
const EXPECTED_SIZE := 1025
# G and B encode (cos, sin) as value * 0.5 + 0.5, so a direction texel must decode to unit length.
# 8-bit rounding plus the odd filtered edge means the tolerance is not zero.
const UNIT_MIN := 0.95
const UNIT_MAX := 1.05


func _finish(payload: Dictionary) -> void:
	payload["step"] = "godot_hydrology_mask"
	print("RESULT " + JSON.stringify(payload))
	get_tree().quit(0 if payload.get("ok", false) else 1)


func _ready() -> void:
	if not FileAccess.file_exists(MASK):
		_finish({"ok": false, "reason": "mask_missing", "path": MASK})
		return

	var image := Image.new()
	var error := image.load(MASK)
	if error != OK:
		_finish({"ok": false, "reason": "load_failed", "error": error})
		return

	var width := image.get_width()
	var height := image.get_height()
	var format := image.get_format()
	if width != EXPECTED_SIZE or height != EXPECTED_SIZE:
		_finish({
			"ok": false,
			"reason": "wrong_size",
			"width": width,
			"height": height,
			"expected": EXPECTED_SIZE,
		})
		return
	if format != Image.FORMAT_RGB8:
		# The precise failure this guards: grey+alpha decodes to FORMAT_LA8 and moves the
		# direction into the alpha channel.
		_finish({
			"ok": false,
			"reason": "wrong_format",
			"format": format,
			"expected_format": Image.FORMAT_RGB8,
		})
		return

	var sampled := 0
	var water := 0
	var directions := 0
	var neutral := 0
	var off_unit := 0
	var mirrored := 0
	var worst := 0.0

	# Every fifth texel: about 42k samples over the 1025² grid, enough to see a wrong encoding
	# without spending the probe's time budget on a million get_pixel calls.
	for y in range(0, height, 5):
		for x in range(0, width, 5):
			var texel := image.get_pixel(x, y)
			sampled += 1
			if texel.r <= 0.0:
				continue
			water += 1
			var dx := texel.g * 2.0 - 1.0
			var dy := texel.b * 2.0 - 1.0
			var length := sqrt(dx * dx + dy * dy)
			if length < 0.01:
				# No flow at this cell: the neutral vector, which is also what a filtered edge
				# blends toward. Legal inside standing water.
				neutral += 1
				continue
			directions += 1
			worst = maxf(worst, absf(length - 1.0))
			if length < UNIT_MIN or length > UNIT_MAX:
				off_unit += 1
			if absf(texel.g - texel.r) < 0.004:
				# G mirroring R is the signature of depth in luminance and direction in alpha.
				mirrored += 1

	var ok := (
		water >= 20
		and directions >= 20
		and off_unit == 0
		and mirrored < directions / 2
	)

	_finish({
		"ok": ok,
		"format": format,
		"width": width,
		"height": height,
		"sampled": sampled,
		"water_texels": water,
		"direction_texels": directions,
		"neutral_texels": neutral,
		"off_unit_texels": off_unit,
		"worst_unit_error": snappedf(worst, 0.001),
		"mirrored_texels": mirrored,
		"reason": "" if ok else "channel_contract_broken",
	})
