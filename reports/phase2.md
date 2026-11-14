# Phase 2 — ground, terrain and hydrology

Phase 2 in progress. This file records what has been built and measured, in the order it was
done. Every number here came from a CI run, not from an estimate.

A number describes the run that produced it, which matters more than it looks: changing a
generator invalidates every measurement below until the publish job has run again. So the figures
are kept as the last recorded run rather than quietly restated, and where a fix is going to move a
figure out from under the prose, the prose names the property the gate checks instead of quoting
the number.

**"Built" here means the file is hashed and recorded, and its bytes are on a release pack.** The 12
terrain products are all recorded in `assets/built.json` at generator 1.3.0, and none of them is
committed: `assets/packs.json` names the release archive, with the archive's SHA-256 and a hash and
size for every file inside it, and `tools/fetch_packs.py` downloads and verifies them into
`assets/terrain/` before any check or build runs. The publish job regenerates the maps on every push
to main, cuts a pack, verifies the upload by downloading it again, and commits the catalogue and the
evidence to `staging` only when the bytes changed — so a rebuilt map cannot silently differ from the
one that passed the gates, and a binary never enters git. See `docs/RELEASES.md`.

## What exists

| Asset | State | Measured |
|---|---|---|
| `terrain_heightmap_master_1km` | **built** | R16, 1025², height 29.1–135.1 m, 1783 KB |
| `terrain_biome_mask` | **built** | R8 bit field, 1025², 16 KB |
| `terrain_surface_id_map` | **built** | R8, 1025², 31 KB |
| `terrain_hydrology_mask` | **built** | RGB8, 1025², depth in R, flow direction as a unit vector in G,B, 117 KB |
| `terrain_shore_mask` | **built** | R8, 1025², 4 m falloff from the waterline, 3 KB |
| `terrain_river_splines` | **built, stale** | every segment descends and at least 90% of its points must lie on water; the committed copy predates the fix below, 42 KB |
| `terrain_water_level_table` | **built** | one row per centreline point, every surface above its bed, 39 KB |
| `terrain_normalmap_master` | **built** | RGB8, 1025², tangent-space normals from the heightmap, 1583 KB |
| `terrain_splat_0` | **present; evidence pending** | RGBA8, weights for grass, moss, rock, gravel, 814 KB |
| `terrain_splat_1` | **present; evidence pending** | RGBA8, weights for mud, sand, clay, reserved, 36 KB |
| `terrain_macro_noise_texture` | **built** | R8, 1024², tiling low-frequency variation, 199 KB |
| `terrain_height_blend_rules` | **built** | the thresholds the weights were built from, 1 KB |

`terrain_splat_1` is 22× smaller than `terrain_splat_0`, which is the expected signature: mud,
sand and clay are rare (1.3 %, 0.6 % and 0.1 % of the map), so those channels are almost entirely
zero and compress hard. A splat map that did not compress that well would mean the sparse surfaces
were being painted everywhere.

## The shape review, and eight fixes

The first published maps were valid files and a wrong place. A hillshade showed a perfect circle, a
disc at bottom-left and a dead-straight trench. Every gate passed, because the gates checked formats,
hashes and value ranges — and a cliff can be perfectly well-formed.

| What the review found | What it was | Fix |
|---|---|---|
| A 14–23 m height jump across the map at row 736 | the river carve was cut off by `if v < 0.72`, so the carving stopped and left a wall across its whole width | the carve runs the length of the river through a `smoothstep` bank, tapering at the ends |
| Hard-edged circles | the rim and bog were discs with threshold edges, and the surface map painted a rock and gravel ring along each | the rim radius and the bog radius are warped by the noise field and blended with a `smoothstep` |
| A 200 m wide, 100 m deep trench with a dry floor | the channel was `0.09` of the map either side and removed 70 % of the local height | 80 m channel in a 140 m bank, blended toward a bed height of 31.4 → 24.0 m, against a 34.0 m water level at the lake |
| Water 1.2 m below the riverbed for 226 of 655 points | a sign error: `bed - depth` instead of `bed + depth` | `max(water_level, bed + depth)` |
| The dominant splat matched the surface map on 46 % of land | slope-and-height weights were computed independently of the ID map | the splats read the ID map and 85 % of each cell's weight goes to its layer; CI gates ≥ 90 % of land — see "The splat seam" below for why that is not 95 % any more |
| Water counted two ways (5.80 % vs 4.53 %) | hydrology also counted high-flow cells as water | water is ground below the waterline, in both generators |
| Mean slope 16°, 10.7 % of land above 30° | mostly the trench and the rings | re-measured by the new gate; nothing else changed |
| Splat weights summed 253–258 | each channel was rounded independently | the residual goes on the dominant channel, so every texel sums to 255 |

Also fixed: the docstring said 0–600 m while the code has always used 200; the macro-noise texture
is 1024 rather than 1025, so it no longer repeats a texel when tiled; and the hydrology header now
states the axis convention (G is east, B is south, neutral is 128,128).

**Thirteen shape and consistency gates now run**, because the review was right that CI could not see
shape: the largest height step between neighbouring texels (≤ 6 m), at least 80 % of land under 30°,
at least 92 % of the inner valley under 30°, the water surface above its bed at every river point,
the water surface falling at least 2 m from the lake's outlet to the mouth, the centreline's head
reaching that outlet, the river's wet width at least the channel it fills, both water ids existing,
the depression fill raising no more than 25 % of the map, the outlet on the map boundary, at least
90 % of the centreline lying on water, and splat/ID agreement over both all land (≥ 90 %) and the
interior texels whose neighbourhood is one surface (≥ 99.5 %). The inner-valley test lets the ridge
rim stay steep without flattening the floor the player walks; every river gate added since 1.1.0
fails on some earlier version of this terrain.



## Why the splat weights are computed, not blurred

The obvious way to turn a surface-ID map into splat weights is a one-hot pass: one layer per cell,
then a blur to soften the edges. A box blur averages alpha across a cliff edge, which is exactly
where the boundary should stay sharp, and it is what made the splat and ID maps disagree before.

The weights are computed from slope and height as before, then anchored to the surface-ID map: 85 %
of each cell's weight goes to the layer the map names, and the remaining 15 % keeps the boundary
soft. The dominant splat is therefore the surface the map names by construction, and CI checks that
it stays that way rather than trusting the arithmetic.

The older rationale, kept because the first version of this section explained it:

The obvious way to turn a surface-ID map into splat weights is a hard mask per surface followed by
a blur. A blur is expensive at 1025² in pure Python and, worse, it smears weights across a cliff
edge where the transition should be sharp.

The weights are instead continuous functions of the same quantities the classifier used — slope
and height — so they blend smoothly by construction and sharply where the terrain itself is sharp.
A rock face and a meadow meet along a slope threshold, not along a Gaussian.

`terrain_height_blend_rules.json` carries those thresholds so the shader reads them rather than
hardcoding its own copy. A splat map whose thresholds disagree with the shader that reads it is
silently wrong, and it is the kind of wrong that only shows up as "the terrain looks a bit odd".


The first three come from `tools/generators/terrain_maps.py`, from one height field so they cannot
disagree. The last four come from `tools/generators/hydrology.py`, which **reads** that heightmap
rather than being told about it. Deterministic from the seed `drowned-greenwood-v1`; `input_hash`
and `sha256` are recorded in each generator's report.

The hydrology run at 1.1.0: **6.32 % of the map was water**, and 7,980 cells lay within the 4 m shore
band. That run predates the two-body water model, so the figure is history rather than a current
measurement: the 1.2.0 and 1.3.0 water changes move it and nothing here should be read as quoting
them. The centreline's point count is likewise in the CI log rather than here, because the fix
described under "The river was not the river" changes it and a number in this file would then be
wrong in a way nothing checks. What the gate asserts is the property: every segment descends, at
least 90 % of the points lie on water, the head reaches the lake's outlet, and the outlet is on the
map boundary.

## Hydrology: five attempts at the river

The flow accumulation worked first time. Extracting a *centreline* from it did not, and each
failure produced a plausible-looking artefact.

| Attempt | Result | What was wrong |
|---|---|---|
| 1 | 942 points, **477 of 941 segments climb** | Highest-flow cell per row. Where a channel runs across a row, several cells have similar flow and the winner jumps between them. |
| 2 | **1 point** | Start from the highest cell above the flow threshold. That cell is almost always a **pit**, because flow accumulates into sinks. |
| 3 | 655 points in the earlier extractor, **every segment descends** | Find the outlet — the cell collecting the most water — walk upstream taking the neighbour that drains into it with the most flow, then reverse. |
| 4 | 1,356 points, **96 of 1,355 segments climb, 44 % on water** | Following the flow after the water model was fixed. On a 300 m floodplain D8 ties constantly, so the main stem and its tributaries swap places and one step across a bank is a step up. |
| 5 | **the carve, sampled** | The centreline is `river_centre_u(v)` from the lake's outlet to the mouth. The channel is authored, not emergent, so this is the river by construction; the gates still require it to descend, lie on water, reach the lake, leave the map at the boundary and carry a real channel's flow. |

The gate is absolute now: any climbing segment fails the build, and so does a channel shorter
than 50 points.

## The D8 bug the tests found

`compute_downhill` compared raw height **drops**. A diagonal neighbour is √2 cells away, so an
equal drop across it is a gentler slope — comparing drops made the diagonal tie with the cardinal
neighbour, and because the neighbour list is scanned in a fixed order, the diagonal won. On a
uniform slope that sends flow zig-zagging diagonally instead of down the fall line, which appears
as spurious diagonal channels in the river network.

It compares `drop / distance` now, which is what "steepest" means. Two of my own tests were wrong
first: one assumed the cardinal neighbour won a tie it did not, and one asserted that the sum of
all flow values equals the cell count, which is false — the correct invariant is that the outlets
collect exactly one unit per cell.

The map composition the last run produced, after the shape fixes:

| Surface | Share |
|---|---|
| grass | 43.8 % |
| moss | 21.3 % |
| bare rock | 17.3 % |
| gravel | 9.2 % |
| water (shallow + deep) | 6.3 % |
| mud, sand, clay | 2.1 % |

The height range is 29.1–135.1 m and the largest step between neighbouring texels is under 6 m.
The splat agreement figure is now reported twice, over all land cells and over the interior cells
whose whole 3x3 neighbourhood carries one surface; the second is the one that cannot move when the
anchor is softened, so it is the one held at 99.5 %.

That is a temperate rainforest valley: 65 % moss and grass, rock and gravel on the rim and the
scree, and water where the bog and the river hold it. The water share rose from 4.5 % to 6.3 % when
the bog floor was put below the waterline; before that it was a damp lawn with a dry channel
through it.

## Four attempts, and what each one got wrong

The generator produced a well-formed map on its first run and every structural check passed. It
was also wrong, and only a quality gate caught it. The rounds are recorded because the failure
mode — "the format is right, so it must be fine" — is the one this repository keeps meeting.

| Round | Change | Measured rock | What was actually wrong |
|---|---|---|---|
| 1 | 600 m relief, noise blended 40/60 with the rim | **82 %** | 600 m over 1 km is a 27° average slope. A mountain, not a valley. |
| 2 | 200 m relief, additive floor + noise + rim | **40 %** | Still too steep, and the quality floor was set at 40 %, so it passed while doing nothing. |
| 3 | rim 0.50, power 2.6 | **30 %** | Chasing the number instead of the cause. |
| 4 | **rock threshold 29° → 35°**, rim 0.45 | **16.6 %** | The threshold was the error. Vegetation holds on steeper ground than 29°. |

The lesson is in round 4: three attempts to fix a number by moving the terrain, when the
threshold defining the number was the thing that was wrong. A threshold is a claim about the
world and deserves the same scrutiny as the code that reads it.

## The quality gates this produced

`validate.yml` runs the generator and checks the output, because a generator is worth what it
produces rather than what it imports:

- the three PNGs exist, are PNGs, and are 1025² at the right bit depth
- bare rock under 30 %, moss and grass over 30 %
- water present, and under 60 %
- at least three surfaces used
- every asset carries a `sha256` and an `input_hash`
- the river's outlet is on the map boundary, at least 90 % of the centreline lies on water, and
  the outlet carries at least the flow the channel threshold calls a stream
- the dominant splat agrees with the surface-ID map on at least 90 % of land and 99.5 % of the
  interior texels whose neighbourhood is one surface

The floors are deliberately not set at the observed values. Round 2's floor was 40 % against a
measured 40 %, which is decoration rather than a check.

## The visual review, and three defects every gate passed

The second review of these maps started from the pictures rather than from the jobs. The jobs were
green; the pictures were not. Three findings, each of which no existing check could have caught
because each one is a property of what the image *means* rather than of how it is encoded.

### The river was not the river

`terrain_river_splines` began at (957, 502) — the eastern rim, 104.91 m — and ended at (639, 513),
the middle of the map, 52.29 m. The water level table therefore described a river surface 1.2 m
above its bed at 53.49 m, which is 21 m above the lake. Neither of those points is anywhere near
the channel `terrain_maps.py` carves, which runs north from the bog at u ≈ 0.30 with its bed at
29–30 m. **Not one of the points lay on water.**

The cause is not the trace. It is that D8 follows only a strictly lower neighbour, so a level
surface drains nowhere — and this terrain contains two by construction. The bog basin is
deliberately level so it can hold water, and the carved channel descends about a metre over the
whole valley, which is well under one 16-bit step every other row and nothing at all after the 3×3
smoothing pass. Both were pit fields. With every flat area a pit, the cell collecting the most
water is a *sink*: 55,733 cells drained into a hole in the middle of the map, and the trace walked
upstream from the sink.

Two changes, both in `hydrology.py`. Depressions are filled by priority-flood from the boundary
before anything is routed, so flow can cross the bog and the channel; and the outlet is chosen
among boundary cells only, because a river that ends inland has not left the valley. The three
gates this produces are the ones that were missing: the outlet must be on the boundary, at least
90 % of the centreline must lie on water, and the outlet must carry at least the flow the channel
threshold calls a stream — a constant that had been written, documented as the definition of a
channel, and never read by anything.

**The committed `terrain_river_splines` and `terrain_water_level_table` are still the pre-fix
output.** `assets/built.json` will not change until the publish job regenerates them, so this is
stale by exactly one publish run and the report says so rather than implying the file is right.

### The splat seam

The weights were anchored by adding 0.85 of every texel's weight to whichever layer the surface-ID
map named for that single texel. Two adjacent texels with different ids therefore held 0.85 against
0.15 of the same layer: a **one-texel seam along every material boundary in the world**, with the
moss-to-grass gradient the classifier builds over twenty metres collapsing into a hard edge. And
the gate read *better* the sharper it got — 100 % agreement over 984,212 land cells was never
evidence of a good blend, it was evidence that the blend had been replaced by a mask.

The anchor is now that layer averaged over the 3×3 neighbourhood, so it ramps across a boundary. An
interior texel is surrounded by its own layer, so its anchor is unchanged at exactly 1.0 and the
arithmetic it gets is the arithmetic it always got; only the boundary band moves. The gate is split
in two to say that precisely: ≥ 90 % over all land, and ≥ 99.5 % over the interior texels the anchor
cannot soften.

### The generator and the prose disagreed about the river

`reports/phase2.md` described a "24 m bank" and a bed falling from 33.5 to 30.5 m. `terrain_maps.py`
carves an 80 m bank toward 30.0 then 29.0 m. Nothing checked it, because `check_docs.py` applied its
"a number in prose is a claim about the code" rule to the README and to one string in ADDITIONS.md,
and to no other document. It now derives that sentence from the generator's constants.

Also found by reading: `terrain_maps.py` divided sample coordinates by `CELLS - 1` while hydrology
and terrain_surfaces divide the same index by `CELLS`, so two generators described one texel with
two different coordinates; `check_manifest.py` carried a comment asserting `tools/generators/` was
"planned, not present" and a warning guarded on precisely that, so it had never fired; and
`check_assets.py` had a mojibake token (`vfспx_step_soft`, Cyrillic с and п) in its own docstring.

Three checks were added to `check_assets.py` at that revision, so they cost nothing now and catch
the drift later: the surface-ID map and the hydrology mask must name exactly the same water texels,
every value must be an id `surface_ids.json` still declares, and every normal-map texel must decode
to a unit vector — the contract the flow vectors have met since the mask was made RGB, and which the
normal map had never been held to. The first of the three later turned out to contain an impossible
half, recorded as S12.14 in the audit ledger: it also demanded a water texel whose ground stood above
the lake level, which no water body can produce.

## The river is a river now

Making the centreline follow the flow was not enough: the maps still showed a flooded trench. The
reason is a sampling question as much as a design one, and the CI run on `1baa3aa` measured it.

| What that run reported | What it means |
|---|---|
| 1.4 % of 971 centreline points on water | the traced line was not on the river |
| the river climbs at 361 of 970 segments | it followed a filled plateau, not a channel |
| 696,054 cells filled — 66 % of the map | D8 found no lower neighbour anywhere in the valley |

The bed fell 1 m across the whole valley: **1.4 mm per texel, against the heightmap's 3 mm 16-bit
step.** The channel's slope did not exist in the stored file. D8 follows only a strictly lower
neighbour, so a channel that is flat once quantised drains nowhere; the priority-flood then raised
the interior to the rim's spill level and the trace wandered across that plateau.

Two changes, and for the player they are one:

- **The bed falls 7.4 m** — 31.4 m at the lake's outlet to 24.0 m at the mouth, 22 mm per texel
  and seven stored steps over the river's 340 m. The channel drains, the fill has almost nothing to
  do, and the trace follows it.
- **Water is two bodies, not one waterline.** The river's surface is its bed plus its depth, so it
  descends from 34.0 m at the outlet to 26.6 m at the mouth, while the lake stays level at 34.0 m.
  A single level could not express both: because the channel floor must lie below the lake for the
  lake to drain at all, "ground below the level" flooded the channel to one flat sheet.

### What the next run found in that model

The 1.2.0 model made the river flow, and the CI run on `87e6c60` still failed it: **5 of 591
centreline segments climbed.** The cause was not the trace.

The bed was anchored at the bowl's centre (v = 0.68), so along the reach where the channel lies
inside the lake the river's surface was **2 m below the lake's**. That is three defects at once: a
2 m water step where the two bodies meet, a groove cut through the lake, and a climb the moment the
trace walked out of the bowl.

The bed now **holds** at `WATER_LEVEL_M - RIVER_DEPTH_M` from `RIVER_HEAD_V` upwards, so
`river_surface_m(RIVER_HEAD_V)` **is** the lake's level and the seam is continuous by construction.
The centreline stops at that outlet, and at the first row whose ground does not stand above the one
before it, so it cannot climb: monotonicity is a property of the model rather than a threshold.

Two more findings from the same review, both visual rather than structural:

- **The river was all shallow water.** `RIVER_DEPTH_M` was 1.6 m against the 2.0 m `water_deep`
  threshold, so every texel of the channel classified as `water_shallow` and the deep id existed
  only in the lake — a river the data says is never deep. The channel is 2.6 m now, and the gate
  requires both ids to exist.
- **The river was 44 m wide.** At a kilometre across that reads as a creek. The channel is 80 m wide
  in a 140 m floodplain, the meander is three bends rather than a gentle curve, and the gate
  requires the river's wet width to be at least the channel it fills.

None of that has been measured yet: 1.3.0 is the version the next publish run exercises, and the
gates above are what will say whether the numbers are right.

The first 1.3.0 publish run got further than any before it. The generators ran, the river gates
passed, the manifest and the docs passed, and it failed on the last pair check instead: **113 texels
of 1,050,625** were water in the surface-ID map and dry in the depth mask, first at x=306 y=11. Both
files obeyed their own rule. Zero in the depth channel means "no water" to every reader, and over
255 counts of an 8 m range one count is 3 cm — so a shoreline texel 4 mm deep rounded to dry. The
encoder now guarantees a wet texel takes at least one count, so the two files agree by construction,
and a unit test holds it. It is worth saying plainly what this run did and did not prove: it proved
the river model and the gates work, and it did not prove the maps are committed yet, because the job
stopped before the push to `staging`.

`hydrology.py` and `terrain_surfaces.py` import the water rule from `terrain_maps.py` rather than
restating it, so the depth mask, the surface-ID map and the splat shore band cannot disagree — the
same argument `terrain_meta.json` makes for the heightmap's scale.

Five gates were added for the properties that were missing: the surface must fall at least 2 m from
the lake to the mouth, the depression fill must not have to raise more than 25 % of the map, the
centreline's head must reach the lake's outlet, the wet width must be at least the carved channel,
and both water ids must exist. Each one fails on some earlier version of this terrain, which is the
point of adding them after the fact rather than at the value the generator happens to produce.

## Not yet done in Phase 2

- `env_weather_<state>` presets and `env_transition_curves.json`
- rocks, water surfaces, sky panoramas
- the terrain mesh itself: the heightmap is data, and nothing yet turns it into geometry. This is
  the first asset that needs Blender, and would be the first binary committed.
- **regenerate and re-record the terrain maps.** Every generator changed again this round —
  `terrain_maps.py` (the river's bed, depth, width and meander, and the two water bodies meeting at
  one height), and `hydrology.py`, which now stops the centreline at the outlet — so all twelve
  products' bytes will change and `GENERATOR_VERSION` is 1.3.0 to say so. The 1.1.0 plumbing was
  measured and it failed (`1baa3aa`: 1.4 % of the centreline on water, 66 % of the map filled).
  1.2.0 was measured too and it failed differently (`87e6c60`: 5 of 591 segments climbed at the
  bowl's edge). 1.3.0 has not been run at all; the publish job's own gates are what will say whether
  it worked.
