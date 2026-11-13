// The shared opaque surface shader. Every opaque material in the game that is not foliage,
// water, skin or cloth is an instance of this shader with different textures and parameters.
//
// Why one shader rather than one per material: the Mobile renderer on Android charges for shader
// *variants*, and a project with forty near-identical shaders spends its compile budget and its
// draw-call batching on differences that are all parameter values. One shader with per-material
// uniforms batches, compiles once, and cannot drift from its siblings.
//
// Usage, from tools/config/materials.json: a material names this shader plus an albedo, normal
// and ORM map, a tiling in metres, and its wetness behaviour. Nothing else is per-material code.
//
// The wetness include is not optional. Every surface in this world can be rained on, so the
// wetness path is in the base shader rather than bolted onto some materials and forgotten on
// others — which is exactly how a wet-looking rock ends up next to a bone-dry one.
shader_type spatial;
render_mode blend_mix, depth_draw_opaque, cull_back, diffuse_burley, specular_schlick_ggx;

#include "res://shaders/tech_wetness_include.gdshaderinc"

// Texture set. The three maps are the glTF convention, so a downloaded Poly Haven set maps
// straight on: albedo is sRGB, normal is tangent-space, and the ORM map packs ambient occlusion
// in R, roughness in G and metallic in B — which is what glTF's metallicRoughness texture does,
// with AO added in the unused channel.
uniform sampler2D albedo_tex : source_color, hint_default_white, repeat_enable, filter_linear_mipmap;
uniform sampler2D normal_tex : hint_normal, repeat_enable, filter_linear_mipmap;
uniform sampler2D orm_tex : hint_default_white, repeat_enable, filter_linear_mipmap;
// Moss grows where the mask says it does, never where the shader guesses. An unassigned mask
// returns black, so moss is off unless a material both assigns a mask and raises moss_strength.
uniform sampler2D moss_mask_tex : hint_default_black, repeat_enable, filter_linear_mipmap;
// Where water pools. A puddle needs a shape, and a shape needs a mask — passing a constant here
// would compile, render, and never produce a puddle, which is the quietest possible failure.
uniform sampler2D puddle_mask_tex : hint_default_black, repeat_enable, filter_linear_mipmap;

// How many times the texture set repeats across the surface. The material's `tiling_m` is metres
// per tile, and the importer converts that to this scale using the mesh's UV area — the shader
// takes the finished number so it never has to know how big the object is.
uniform vec2 uv_scale = vec2(1.0, 1.0);

uniform vec3 moss_color : source_color = vec3(0.16, 0.28, 0.12);
uniform float moss_strength : hint_range(0.0, 1.0) = 0.0;
uniform float normal_strength : hint_range(0.0, 2.0) = 1.0;

// wetness_darken, global_wetness and puddle_amount come from the include. Do not declare them
// again: a duplicate uniform is a compile error, and this shader's whole purpose is to compile.
void fragment() {
	vec2 uv = UV * uv_scale;
	vec4 albedo_sample = texture(albedo_tex, uv);
	vec3 orm = texture(orm_tex, uv).rgb;

	float wet = clamp(global_wetness, 0.0, 1.0);
	float puddle_mask = texture(puddle_mask_tex, uv).r;

	// Wetness darkens by the material's own amount. The 1.0 scale factor is deliberate: the
	// per-material weight lives in `wetness_darken`, so passing a second multiplier here would
	// multiply two per-material numbers and make the tuned values meaningless.
	vec3 albedo = wetness_albedo(albedo_sample.rgb, 1.0, wet);

	// Moss is applied before the puddle pass so a puddle darkens the moss too, rather than the
	// moss sitting on top of standing water.
	if (moss_strength > 0.0) {
		float moss = texture(moss_mask_tex, uv).r * moss_strength;
		albedo = moss_blend(albedo, moss_color, moss);
	}

	ALBEDO = puddle_albedo(albedo, puddle_mask, puddle_amount);
	// No ALPHA write here, deliberately. In Godot 4, writing ALPHA at all — even the constant
	// 1.0 — moves the material to the transparent pipeline (spatial shader reference: "If read
	// from or written to, the material will go to the transparent pipeline"), where it is
	// blended, depth-sorted and cannot cast shadows. An opaque surface is one that leaves ALPHA
	// unwritten. test_tools.py asserts this, because `ALPHA = 1.0` compiles and looks right
	// until you notice the rocks have stopped casting shadows.

	NORMAL_MAP = texture(normal_tex, uv).rgb;
	NORMAL_MAP_DEPTH = normal_strength;

	// AO_LIGHT_AFFECT stays at 0 so ambient occlusion only affects ambient light. At 1 it would
	// darken direct light too, which reads as dirt rather than as occlusion.
	AO = orm.r;
	AO_LIGHT_AFFECT = 0.0;

	// Roughness is driven into the wet band by the include, then flattened where puddles pool.
	ROUGHNESS = puddle_roughness(wetness_roughness(orm.g, 0.22, wet), puddle_mask, puddle_amount);
	METALLIC = orm.b;
	SPECULAR = 0.5;
}
