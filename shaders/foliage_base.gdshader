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
	ALPHA_SCISSOR_THRESHOLD = alpha_cutoff;
	// ALPHA must be the texture's alpha. This pairing is not a mistake to be "tidied" later, and
	// it was nearly removed on the theory that a surviving fragment must not be blended:
	//
	//   * Godot's material documentation describes exactly this path — alpha scissor: "Semi-
	//     transparent areas whose opacity is below Alpha Scissor Threshold are not drawn (above
	//     this opacity, these are drawn as opaque) ... this doesn't exhibit transparency sorting
	//     issues ... Materials using alpha scissor can cast shadows." That is the comment above,
	//     stated by the engine and not by me.
	//   * The threshold is compared against the ALPHA *this shader writes*, so ALPHA has to be the
	//     value being cut on. `ALPHA = 1.0` passes every fragment, the scissor discards nothing,
	//     and every leaf card draws as a full rectangle. It fails silently: it compiles, and the
	//     trees just look wrong from a distance.
	//   * Not writing ALPHA at all is not the alternative either. The spatial shader reference says
	//     a material "will go to the transparent pipeline" if ALPHA is read from or written to, so
	//     transparency here is unavoidable and the scissor is what makes it behave as a cut-out.
	//
	// test_tools.py asserts ALPHA is a texture channel, because both wrong versions compile.
	ALPHA = tex.a;

	NORMAL_MAP = texture(normal_tex, uv).rgb;
	NORMAL_MAP_DEPTH = 1.0;

	// BACKLIGHT is the light transmitted through the surface. Scaling the albedo keeps a leaf
	// the colour of the leaf, so an autumn crown glows amber rather than white.
	BACKLIGHT = ALBEDO * translucency;

	ROUGHNESS = wetness_roughness(0.75, 0.35, wet);
	SPECULAR = 0.3;
}
