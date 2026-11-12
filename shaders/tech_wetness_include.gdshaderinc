// Shared wetness for The Drowned Greenwood.
//
// The whole world is wet. Every opaque material that can be rained on includes this file and
// gets one global control plus a moss blend, so a single uniform drives the look of the entire
// scene instead of each material guessing at its own wetness.
//
// Usage, from any spatial shader:
//
//     #include "res://shaders/tech_wetness_include.gdshaderinc"
//     ... in fragment():
//     vec3 wet_albedo = wetness_albedo(albedo, 0.55, global_wetness);
//     float wet_rough = wetness_roughness(roughness, 0.22, global_wetness);
//
// The ranges come from the quality standard: wet surfaces sit at roughness 0.20-0.50, dry
// stone and wood at 0.65-0.90. Interpolating between those two bands is what makes rain
// readable without a second texture set.

#ifndef DROWNED_GREENWOOD_WETNESS
#define DROWNED_GREENWOOD_WETNESS

// Global rain state, 0 = dry, 1 = soaked. Driven by the weather system.
global uniform float global_wetness : hint_range(0.0, 1.0) = 0.0;

// How much darker this material goes when fully wet. Soil and bark darken hard; stone less so.
global uniform float wetness_darken : hint_range(0.0, 0.8) = 0.45;

// Puddle coverage, driven separately from wetness so a heavy storm can pool water without
// every surface needing its own puddle texture.
global uniform float puddle_amount : hint_range(0.0, 1.0) = 0.0;

// Darken an albedo toward its wet value. Wet surfaces read darker because a water film
// refracts light away rather than scattering it back.
vec3 wetness_albedo(vec3 albedo, float darken_scale, float wetness) {
	float amount = clamp(wetness * darken_scale * wetness_darken, 0.0, 0.85);
	return albedo * (1.0 - amount);
}

// Drive roughness into the wet band (0.20-0.50) from the dry band (0.65-0.90).
float wetness_roughness(float dry_roughness, float wet_roughness_value, float wetness) {
	float wet = clamp(wet_roughness_value, 0.20, 0.50);
	return mix(dry_roughness, wet, clamp(wetness, 0.0, 1.0));
}

// Blend a moss colour into a surface by its mask. The mask is authored per material; this
// only applies it, so the shader never invents moss where the artist did not put any.
vec3 moss_blend(vec3 albedo, vec3 moss_color, float moss_mask) {
	return mix(albedo, moss_color, clamp(moss_mask, 0.0, 1.0));
}

// A cheap puddle darkening for surfaces that cannot afford a separate puddle pass. Puddles
// read as near-mirror: very dark albedo, roughness around 0.05.
vec3 puddle_albedo(vec3 albedo, float puddle_mask, float amount) {
	float p = clamp(puddle_mask * amount, 0.0, 1.0);
	return mix(albedo, albedo * 0.35, p);
}

float puddle_roughness(float roughness, float puddle_mask, float amount) {
	float p = clamp(puddle_mask * amount, 0.0, 1.0);
	return mix(roughness, 0.05, p);
}

#endif // DROWNED_GREENWOOD_WETNESS
