# Shader globals

Godot requires every `global uniform` to be registered in **Project Settings → Shader Globals**
before any shader that uses it is compiled. Its documentation is explicit that a default value
written in the shader is ignored, and that compilation fails if the global is missing.

This file is the single list. The probe project registers these in
`tools/phase0/godot_probe/project.godot`; the game project must register the same names.

| Name | Type | Default | Set by |
|---|---|---|---|
| `global_wetness` | float | 0.0 | weather system, from `env_weather_*` presets |
| `wetness_darken` | float | 0.45 | material class (soil and bark darken more than stone) |
| `puddle_amount` | float | 0.0 | weather system, heavy rain only |
| `wind_time` | float | 0.0 | advanced every frame by the world script |
| `wind_strength` | float | 0.6 | weather system |
| `wind_gust` | float | 0.0 | weather system, smoothed |

## Adding a global

1. Add the row here first, with its type and who sets it.
2. Register it in Project Settings → Shader Globals.
3. Add it to `tools/phase0/godot_probe/project.godot` so CI can compile a shader that uses it.

A global that exists in a shader but not in Project Settings is a compile failure, and CI
should catch it rather than the device.

## Types that are deliberately not globals

`wind_noise` and `gust_flowmap` are per-material samplers, not globals: different foliage classes
may use different noise atlases, and Godot does not support texture globals in the same way.
