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

**Human faces and heads (4.G).** MPFB2 is under repair, not verified. If its `register()` call
does not succeed, heads come from a custom generator with no skin/hair library: expect the
`[TARGET-VISUAL]` detail-band score on skin to be the first thing to miss, because procedural
skin at 1024 px has no pores, no subsurface variation and no hair strands. The fallback is
stylisation, which is an honest answer for this tier but is a visible step below the reference
quality in section 2A.

**Animals (4.F).** The brief already grades this category Medium–Low. The specific risk is
animation, not shape: a rigged quadruped with the right silhouette but a walk cycle that slides
will read worse than a simpler mesh that moves correctly. Foot-sliding is measurable through the
root-speed metadata in `char_retarget_map.json`, so it should be caught by a number rather than
by eye.

**Grass and ground cover (4.E).** Alpha-scissor cards at `[HARD-TECH]` are easy; making 5,000 of
them per 100 m² look like a wet meadow rather than a field of identical tufts is the hard part.
The first thing to miss is likely the "not flat" judgement, which is why the scatter presets in
`tech_scatter_presets` carry per-tier density tables from the start.
