// The shared foliage shader: leaves, ferns, grass cards, ivy. Wind and wetness, one shader.
//
// This is a separate shader from surface_base for two reasons that are both real:
//
//   1. Foliage moves. The wind include displaces vertices, and doing that in a shader that also
//      renders rocks would mean every rock pays for a vertex transform it never uses.
//   2. Foliage is alpha-cut, double-sided and backlit. `cull_disabled` and `depth_prepass_alpha`
//      change how the surface is drawn, and those are render modes — they cannot be a uniform.
//
// Authoring rule, inherited from the wind include: a vertex moves only when its vertex-colour
// ALPHA is below 1. A mesh with no vertex colours arrives as (1,1,1,1), so an unauthored mesh
// stands still and is visible as a bug rather than wobbling wrongly.
shader_type spatial;
render_mode blend_mix, depth_prepass_alpha, cull_disabled, diffuse_burley, specular_schlick_ggx;

#include "res://shaders/tech_wind_include.gdshaderinc"
#include "res://shaders/tech_wetness_include.gdshaderinc"

uniform sampler2D albedo_tex : source_color, hint_default_white, repeat_enable, filter_linear_mipmap;
uniform sampler2D normal_tex : hint_normal, repeat_enable, filter_linear_mipmap;

uniform vec2 uv_scale = vec2(1.0, 1.0);

// Cut-out threshold. Leaves are cards with alpha, so anything below this is discarded rather
// than blended: blending would sort wrongly against every other leaf in the crown.
uniform float alpha_cutoff : hint_range(0.0, 1.0) = 0.5;

// How much light passes through a leaf from behind. This is what stops a backlit crown looking
// like a solid black mass, which is the single most common way stylised foliage reads as fake.
uniform float translucency : hint_range(0.0, 1.0) = 0.35;

// sway_amplitude, branch_amplitude, flutter_amplitude, wind_noise and gust_flowmap come from the
// wind include. wetness_darken, global_wetness and puddle_amount come from the wetness include.
// Declaring any of them again here is a duplicate-uniform compile error.

void vertex() {
	// COLOR is the vertex colour. The include reads R/G/B as sway/branch/flutter and ALPHA as
	// the "has wind data" flag, so the whole convention lives in one place.
	VERTEX += wind_offset(VERTEX, COLOR, MODEL_MATRIX);
}

void fragment() {
	vec2 uv = UV * uv_scale;
	vec4 tex = texture(albedo_tex, uv);

	float wet = clamp(global_wetness, 0.0, 1.0);

	// Leaves darken less than soil when wet — water beads on a waxy surface rather than soaking
	// in — so this passes a smaller scale than surface_base does, on top of the material's own
	// wetness_darken.
	ALBEDO = wetness_albedo(tex.rgb, 0.55, wet);
	ALPHA = tex.a;
	ALPHA_SCISSOR_THRESHOLD = alpha_cutoff;

	NORMAL_MAP = texture(normal_tex, uv).rgb;
	NORMAL_MAP_DEPTH = 1.0;

	// BACKLIGHT is the light transmitted through the surface. Scaling the albedo keeps a leaf
	// the colour of the leaf, so an autumn crown glows amber rather than white.
	BACKLIGHT = ALBEDO * translucency;

	ROUGHNESS = wetness_roughness(0.75, 0.35, wet);
	SPECULAR = 0.3;
}
