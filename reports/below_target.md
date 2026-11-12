# Below-target assets

The brief allows up to three improvement attempts per asset class on `[TARGET-VISUAL]` rules.
When an asset still misses after that, it is marked `status: BELOW_TARGET` in the manifest and
listed here with the measured numbers and the reason. **Nothing is listed yet because no asset
has been built** — Phase 0 was tooling and Phase 1 is definitions.

`[HARD-TECH]` failures are never listed here: those are rebuilt until they pass.

| Asset | Rule missed | Measured | Target | Attempts | Proposed fix |
|---|---|---|---|---|---|
| _(none: no assets built yet)_ | | | | | |

## Known risks carried into production

These are not yet failures, but they are the places the brief itself expects trouble, recorded
now so the eventual numbers are not a surprise.

**Human faces and heads (4.G).** MPFB2 now exports a human mesh **with an armature**
(36,972 triangles, 137 bones), so heads need not come from a scratch generator — but three
measured problems are already known before any asset is graded. The triangle count is roughly
double the 12k–18k character budget before clothing, so decimation is mandatory and will cost
silhouette detail. The 137 bones exceed the 65-bone shared skeleton, so the rig must be reduced
and remapped or replaced. And skin at 1024 px has no pores, no subsurface variation and no hair
strands, so the `[TARGET-VISUAL]` detail-band score on skin is the first thing expected to miss.
Stylisation is an honest answer for this tier and is a visible step below the reference quality
in section 2A.

**Trees (4.E).** MTree generates a tree and Godot loads it, but at **1,840,066 triangles and
60 MB** against a 10k–16k hero-tree budget and a 1.5 MB per-species cap. That is the largest
single gap between "the tool works" and "the asset ships" in the project. Closing it means leaf
cards rather than individual leaf geometry, decimation, LODs and impostors — the Phase 3 core,
not a Phase 0 concern.

**Animals (4.F).** The brief already grades this category Medium–Low. The specific risk is
animation, not shape: a rigged quadruped with the right silhouette but a walk cycle that slides
will read worse than a simpler mesh that moves correctly. Foot-sliding is measurable through the
root-speed metadata in `char_retarget_map.json`, so it should be caught by a number rather than
by eye.

**Grass and ground cover (4.E).** Alpha-scissor cards at `[HARD-TECH]` are easy; making 5,000 of
them per 100 m² look like a wet meadow rather than a field of identical tufts is the hard part.
The first thing to miss is likely the "not flat" judgement, which is why the scatter presets in
`tech_scatter_presets` carry per-tier density tables from the start.
