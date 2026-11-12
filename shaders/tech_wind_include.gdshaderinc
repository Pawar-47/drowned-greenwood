// Shared foliage wind for The Drowned Greenwood.
//
// The brief fixes the vertex colour convention, and this file is the single place it is read:
//
//     R = trunk sway   (slow, large amplitude, whole tree)
//     G = branch sway  (medium frequency, follows the trunk with a lag)
//     B = leaf flutter (fast, small amplitude, leaves only)
//
// A mesh with no vertex colours gets no movement, which is deliberate: a tree whose wind
// channels were forgotten stands still and is visible as a bug rather than wobbling wrongly.
//
// Usage, from a spatial shader:
//
//     #include "res://shaders/tech_wind_include.gdshaderinc"
//     ... in vertex():
//     VERTEX += wind_offset(VERTEX, COLOR, MODEL_MATRIX, wind_time);

#ifndef DROWNED_GREENWOOD_WIND
#define DROWNED_GREENWOOD_WIND

// Global wind state, driven by the weather system. gust is the same value filtered over time,
// so a squall arrives smoothly instead of snapping on.
global uniform float wind_time = 0.0;
global uniform float wind_strength : hint_range(0.0, 2.0) = 0.6;
global uniform float wind_gust : hint_range(0.0, 1.0) = 0.0;

// One noise texture, shared by every plant in the world, sampling a flowmap that pushes
// movement across the landscape rather than animating each instance in isolation.
uniform sampler2D wind_noise : hint_black;
uniform sampler2D gust_flowmap : hint_black;

// Amplitude per channel in metres at wind_strength 1.0. A 60 m fir sways further than a fern,
// so these are tuned per material rather than globally.
uniform float sway_amplitude : hint_range(0.0, 0.5) = 0.08;
uniform float branch_amplitude : hint_range(0.0, 0.5) = 0.05;
uniform float flutter_amplitude : hint_range(0.0, 0.1) = 0.012;

// Sample the shared noise at a position and time, giving each plant its own phase from where
// it stands, so a hundred identical trees do not move in lockstep.
float wind_phase(vec2 world_xz, float speed) {
	vec2 uv = world_xz * 0.01 + vec2(wind_time * speed, wind_time * speed * 0.37);
	return texture(wind_noise, uv).r * 2.0 - 1.0;
}

// The displacement applied to a vertex. COLOR is the mesh's vertex colour; a mesh without one
// arrives as opaque white, which would move everything, so guard on the green channel.
vec3 wind_offset(vec3 vertex, vec4 vertex_color, mat4 model, float time_scale) {
	float trunk = vertex_color.r;
	float branch = vertex_color.g;
	float leaf = vertex_color.b;

	// A mesh with no wind channels at all: COLOR is (1,1,1,1) by default in Godot, so treat
	// a fully white vertex colour as "not authored" and leave it alone.
	if (trunk > 0.99 && branch > 0.99 && leaf > 0.99) {
		return vec3(0.0);
	}

	vec2 world_xz = (model * vec4(vertex, 1.0)).xz;
	float strength = wind_strength * (1.0 + wind_gust * 1.5);

	float sway = wind_phase(world_xz, 0.15 * time_scale) * sway_amplitude;
	float branch_move = wind_phase(world_xz + vec2(3.7, 1.9), 0.45 * time_scale) * branch_amplitude;
	float flutter = wind_phase(world_xz + vec2(11.3, 7.1), 2.1 * time_scale) * flutter_amplitude;

	// Gust direction comes from the shared flowmap so the whole forest leans the same way.
	vec2 gust_dir = texture(gust_flowmap, world_xz * 0.001).rg * 2.0 - 1.0;

	vec3 offset = vec3(gust_dir.x, 0.0, gust_dir.y) * (sway * trunk + branch_move * branch);
	// Leaf flutter is perpendicular and vertical, which is what makes leaves shimmer rather
	// than slide sideways.
	offset += vec3(flutter, flutter * 0.6, flutter * 0.4) * leaf * strength;

	return offset * strength;
}

#endif // DROWNED_GREENWOOD_WIND
