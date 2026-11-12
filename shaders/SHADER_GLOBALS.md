# Shader globals

Godot requires every `global uniform` to be registered in **Project Settings → Shader Globals**
before any shader that uses it is compiled. Its documentation is explicit that a default value
written in the shader is ignored, and that compilation fails if the global is missing.

This file is the single list. The probe project registers these in
`tools/phase0/godot_probe/project.godot`; the game project must register the same names.

| Name | Type | Default | Set by |
|---|---|---|---|
| `global_wetness` | float | 0.0 | weather system, from `env_weather_*` presets |
| `puddle_amount` | float | 0.0 | weather system, heavy rain only |
| `wind_time` | float | 0.0 | advanced every frame by the world script |
| `wind_strength` | float | 0.6 | weather system |
| `wind_gust` | float | 0.0 | weather system, smoothed |

## Deliberately per-material, not global

| Uniform | Why it cannot be a global |
|---|---|
| `wetness_darken` | soil and bark darken far more than stone. A global would force one value on every surface in the world. |
| `sway_amplitude`, `branch_amplitude`, `flutter_amplitude` | a 60 m fir moves differently from a fern; these are tuned per material. |
| `wind_noise`, `gust_flowmap` | different foliage classes may use different noise atlases, and Godot does not support texture globals. |

`wetness_darken` was declared `global uniform` for a while while this file described it as set by
material class — a contradiction that would have compiled fine and then behaved wrongly. It is a
per-material uniform now.

## Adding a global

1. Add the row here first, with its type and who sets it.
2. Register it in Project Settings → Shader Globals.
3. Add it to `tools/phase0/godot_probe/project.godot` so CI can compile a shader that uses it.

A global that exists in a shader but not in Project Settings is a compile failure, and CI
should catch it rather than the device.

## Who consumes these

| Shader | Globals it reads |
|---|---|
| `surface_base.gdshader` (ground, rock, wood, buildings) | `global_wetness`, `puddle_amount` — via the wetness include |
| `foliage_base.gdshader` (leaves, ferns, grass, ivy) | `wind_time`, `wind_strength`, `wind_gust` via the wind include; `global_wetness` via the wetness include |
| `tech_wind_include.gdshaderinc` | `wind_time`, `wind_strength`, `wind_gust` |
| `tech_wetness_include.gdshaderinc` | `global_wetness`, `puddle_amount` |

`puddle_amount` is read by `surface_base` only: a leaf does not hold a puddle, and applying the
puddle pass to foliage would flatten a crown's roughness for no visible gain.

Both material shaders are compiled by the Phase 0 gate, so a global that is declared but not
registered fails CI rather than a device.

## Types that are deliberately not globals

`wind_noise` and `gust_flowmap` are per-material samplers, not globals: different foliage classes
may use different noise atlases, and Godot does not support texture globals in the same way.
