# Assets added beyond the final list

The brief's asset list is final and named. The additions below are **approved additions**
(review section 4) and are exceptions to the rule that additions wait for P1 and P2 to be
built: all are **P1** and all are scheduled into the phases shown. They are in
`assets/manifest.json` like any other asset.

**Six additions, in six table rows.** The four from the review, plus two animal skeleton families
found while writing the validator. Those two were not in the review; they are listed separately
because they are separate assets, and they are recorded here rather than slipped into the
manifest unannounced. This is the count the README uses.

| Asset | Category | Tier | Priority | Phase | Why it is needed |
|---|---|---|---|---|---|
| `env_weather_<state>` — drizzle, steady_rain, heavy_rain, storm, fog, clearing, dusk, night, ridge_snow (9 `.tres`) | 4.A.env | C | P1 | 2 | The brief has sky panoramas but nothing that makes a weather state actually run. Each preset sets fog depth and height, ambient light, tonemap, sun colour and energy, sky reference, rain intensity, wetness target and wind strength, with LOW/MEDIUM/HIGH flags (glow off on LOW) and `env_transition_curves.json`. |
| `terrain_hydrology_mask`, `terrain_water_level_table`, `terrain_river_splines`, `terrain_shore_mask` | 4.B.hydro | C | P1 | 2 | Nothing tied the 1 km terrain to where water sits. The mask is 1025² with R = water depth and G = flow direction, derived from the heightmap by a flow-accumulation script. Waterfall steps and the bog basin must match the heightmap. |
| `terrain_surface_id_map`, `surface_ids`, `surface_fx_table` | 4.B.surface | C | P1 | 2 | Footsteps, impact VFX, decals and surface audio all need to know the surface at a point. Lossless R8 1024² (about 1 m per texel), IDs for mud, wet leaves, moss, wet stone, gravel, sand, wood, shallow and deep water, snow, dirt path, grass, clay, cobble and ash. Props and buildings carry a `surface:<id>` tag in the GLB extras; `surface_fx_table.json` links each ID to its footstep VFX, impact VFX, decal and audio ID. |
| `char_skeleton_definition`, `char_retarget_map`, `animal_skeleton_<family>`, `anim_retarget_report` | 4.G.rig | C | P1 | 1 | The brief mandates one shared humanoid skeleton (≤ 65 bones) and per-family animal skeletons (≤ 50), but no artifact defined them. Written in Phase 1, before any human or animation work: bones, hierarchy, rest pose, naming, the mapping to Godot `SkeletonProfileHumanoid`, the Quaternius → MPFB2/Rigify → shared-skeleton retarget map, per-family animal definitions, and root-speed metadata recorded in the retarget report. |
| `animal_skeleton_amphibian` | 4.G.rig | C | P1 | 1 | Found while writing the coverage check: frogs, toads and salamanders were in the manifest with no skeleton family of their own. A frog's hind limbs fold in two planes for the crouch and the jump, which a small-mammal leg chain cannot express, so they get a **23-bone** family rather than being forced into one that cannot animate them. |
| `animal_skeleton_bat` | 4.G.rig | C | P1 | 1 | Found the same way: `animal_bat_pipistrelle` was covered by no family. A bat's wing is a membrane over elongated fingers, so the bird skeleton's beak, crest and three-segment wing cannot express it; 14 bones. |

Six additions in total, not four: the two skeleton families above were found while writing the
validator, and each is recorded here rather than being slipped into the manifest unannounced.

## Naming decisions (not new assets)

Three parts of the brief's list are written as prose rather than names. They are built as
written, and only given names so the manifest can address them. Nothing is added, renamed in
substance or skipped:

| Brief wording | How it is named | Note |
|---|---|---|
| Clan identity kits (×4 clans): banner, tabard, shield face, face-paint set, camp flag, fort emblem, totem pole, war standard | `kit_<clan>_<item>` — 32 entries | The brief names the eight items and the four clans, not the 32 names. |
| Icon set: one icon per item in 4.F loot, 4.H, 4.J | `ui_icon_<asset>` | Derived by `tools/build_manifest.py` from the matching assets rather than hand-written, so the icon set cannot drift from the item list. `ui_icon_set` remains the atlas that packs them. |
| Common building kit, damage states, HUD/menu/audio groups | `bld_kit_*`, `bld_damagestate_*`, `ui_*`, `audio_*` | The brief lists these as groups; each member of every group is a separate manifest entry. |

## Deliberately not added

Nothing else. If the built world turns out to need more, it is recorded here first with the
reason, then reported.

