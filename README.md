# The Drowned Greenwood — asset pipeline

Open-world hunting + clan-war game. Dark-age tribal world in a permanently damp temperate
rainforest. Android, Godot 4 (Mobile renderer).

**This repository is in the ASSETS phase.** It contains the tooling, generators, validators,
reports and (once built) the 3D/2D assets. There is no gameplay, AI, networking, input or UI
logic here, by design.

Source of truth = scripts + configs + seeds + pinned tool versions. Binaries are build
products, rebuilt in GitHub Actions and committed per category per milestone only after the
gates pass.

## Layout

```
assets/          manifest.json, LICENSES.md, ADDITIONS.md, and the built asset tree
tools/           generators/ config/ validate/ phase0/ TOOLS.md
reports/         tool_evaluation.md, quality_report.md, below_target.md, scene_tests/, previews/
.github/workflows/  Phase 0 tool evaluation (more workflows arrive in Phase 1)
```

## Phases (stop and report after each)

| Phase | Content | Status |
|---|---|---|
| 0 | Tool smoke tests: Blender headless render, glTF export, Godot import, gltfpack, glTF-Transform, MPFB2, MTree, Infinigen, Poly Haven API | in progress |
| 1 | Repo structure, `assets/manifest.json` for every asset in the brief, workflows, validators, shared PBR material system | pending |
| 2 | Ground/terrain, rocks, water, sky/atmosphere/weather | pending |
| 3 | Flora: trees, dead wood, shrubs, ferns, ground cover, fungi, crops | pending |
| 4 | Fauna, hunting loot, animal sign | pending |
| 5 | Humans, clothing, armor, clan kits, animations | pending |
| 6 | Weapons, hunting gear, traps, siege | pending |
| 7 | Settlements, forts, props, vehicles | pending |
| 8 | VFX, shaders, UI | pending |
| 9 | Biome scatter, audio, final 1 km test world, debug APK | pending |

## CI

All building happens on GitHub-hosted runners (CPU only, no GPU, no display). Nothing is
generated on a workstation. Pinned versions and the resolve-then-pin policy: `tools/TOOLS.md`.

Phase 0 workflow: `.github/workflows/phase0-tool-evaluation.yml` — runs on push to
`tools/phase0/**` or manually from the Actions tab.
