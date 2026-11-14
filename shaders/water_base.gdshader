// The water surface shader. One shader for the lake, the river and every pocket of standing water,
// with per-material depth and colour — the same decision the opaque and foliage shaders make, for
// the same reason: the Mobile renderer charges for variants, not for parameter values.
//
// It reads the hydrology mask the terrain generator writes, so the water surface and the terrain it
// sits in cannot disagree. The mask's channels are a contract, and it is the terrain's own:
//
//   R    depth, 0..1 mapped over depth_scale_m metres — which is MAX_MASK_DEPTH_M in
//        tools/generators/hydrology.py, and check_materials.py fails if the two drift apart
//   G    flow direction, east component, (value / 255) * 2 - 1
//   B    flow direction, south component, (value / 255) * 2 - 1
//        A neutral texel is (128, 128) — no flow, or a cell whose neighbours are all higher.
//
// A vector rather than an angle is why the mask can be sampled with ordinary bilinear filtering:
// 10 degrees and 350 degrees average to 180, which is the opposite direction, while their vectors
// average to roughly zero length — which the shader reads as "no flow" rather than as "flow south".
//
// What this shader deliberately does not do: refraction, depth-based caustics, or a reflection
// probe. Each costs a pass the Mobile renderer cannot spare at 60 fps on a phone, and the mask
// already carries the one thing a water surface cannot fake — how deep it is.
shader_type spatial;
render_mode blend_mix, cull_disabled, depth_draw_opaque, diffuse_burley, specular_schlick_ggx;

// The weather globals. Declared here rather than included from the wind file because the water does
// not lean: it ripples, and the wind include's helpers expect a vertex colour mask that a water
// plane does not have. SHADER_GLOBALS.md lists this shader against those three globals.
global uniform float wind_time = 0.0;
global uniform float wind_strength : hint_range(0.0, 1.0) = 0.6;
global uniform float wind_gust : hint_range(0.0, 1.0) = 0.0;

// The hydrology mask, sampled with the water mesh's UVs, which span the terrain once. Repeat is
// declared because check_scripts.py requires it of every sampler and the UVs never leave 0..1, so
// it cannot wrap in practice.
uniform sampler2D hydrology_tex : hint_default_black, repeat_enable, filter_linear;
// The shore mask: 255 at the waterline, falling to 0 over 4 m. Foam uses it so the edge of the
// water is a band rather than a cut line.
uniform sampler2D shore_tex : hint_default_black, repeat_enable, filter_linear;

// Must equal MAX_MASK_DEPTH_M in tools/generators/hydrology.py. The gate is in check_materials.py,
// because a shader that decodes the mask at the wrong scale renders water of the wrong depth with no
// error anywhere — the same class of fault the terrain's own sidecar exists to prevent.
uniform float depth_scale_m : hint_range(0.5, 16.0) = 8.0;

uniform vec3 shallow_color : source_color = vec3(0.22, 0.3, 0.25);
uniform vec3 deep_color : source_color = vec3(0.04, 0.12, 0.13);
uniform float flow_strength : hint_range(0.0, 1.0) = 0.35;
uniform float ripple_strength : hint_range(0.0, 1.0) = 0.5;
uniform float wave_height_m : hint_range(0.0, 0.5) = 0.06;
uniform float min_alpha : hint_range(0.0, 1.0) = 0.35;
uniform float max_alpha : hint_range(0.0, 1.0) = 0.92;

void vertex() {
	// A small swell, not a simulation. The amplitude is in metres and stays under ten centimetres:
	// a water plane that lifts its own shoreline by half a metre reads as a wobbling sheet, and a
	// river a hunter can see through is worth more than a convincing ocean.
	float phase = wind_time * (0.8 + wind_strength * 1.6) + VERTEX.x * 0.35 + VERTEX.z * 0.22;
	VERTEX.y += sin(phase) * wave_height_m * (0.35 + wind_strength * 0.5 + wind_gust * 0.3);
}

void fragment() {
	vec4 hydro = texture(hydrology_tex, UV);
	float depth_m = hydro.r * depth_scale_m;

	// A neutral flow texel decodes to a near-zero vector. Normalising that would amplify rounding
	// into a random direction, so a short vector is treated as no flow — which is what the mask
	// means by neutral.
	vec2 flow_raw = hydro.gb * 2.0 - 1.0;
	float flow_len = length(flow_raw);
	vec2 flow = flow_len > 0.05 ? flow_raw / flow_len : vec2(0.0);

	// Depth is the whole visual: metres of water, not a distance to the camera. The band stops at
	// 2.5 m because below that the colour is already the deep colour and more range only flattens it.
	float depth_band = smoothstep(0.0, 2.5, depth_m);
	vec3 water = mix(shallow_color, deep_color, depth_band);

	// Ripples travel along the flow, which is where a river's surface reads as moving water rather
	// than as a still one. Two rates, so the pattern does not look like a single sine wave.
	float ripple_phase = dot(UV, vec2(210.0, 150.0))
		+ wind_time * (1.4 + wind_strength * 3.2)
		+ flow.x * 4.0 + flow.y * 2.5;
	float ripple = sin(ripple_phase) * 0.5 + 0.5;
	float ripple_fine = sin(ripple_phase * 2.7 + 1.3) * 0.5 + 0.5;
	water += vec3((ripple * 0.6 + ripple_fine * 0.4 - 0.5) * 0.06 * ripple_strength * (0.4 + flow_len));

	// Foam where the water is shallow AND the shore mask says this is an edge. Both conditions,
	// because either one alone puts foam in the middle of a lake.
	float shore = texture(shore_tex, UV).r;
	float foam = (1.0 - smoothstep(0.0, 0.25, depth_m)) * shore;
	water = mix(water, vec3(0.72, 0.76, 0.73), foam * 0.35);

	// Grazing angles show more sky through water, which is what makes a flat surface read as a
	// surface at all.
	float fresnel = pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), 3.0);

	ALBEDO = water;
	ALPHA = clamp(
		mix(min_alpha, max_alpha, smoothstep(0.0, 1.2, depth_m)) + fresnel * 0.15 + foam * 0.2,
		min_alpha,
		1.0
	);
	ROUGHNESS = mix(0.12, 0.04, fresnel);
	SPECULAR = 0.6;
	METALLIC = 0.0;
	// Water is the one surface that writes ALPHA on purpose: it is transparent, so it belongs on the
	// transparent pipeline. surface_base.gdshader must not write it, and the two rules are asserted
	// separately in test_tools.py so one cannot be "fixed" into the other.
}
