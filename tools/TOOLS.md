# Pinned toolchain

Third-party tool source code is never copied in; it is fetched at a pinned version and recorded
here. **Not every pin is enforced yet** — the outstanding ones are listed below rather than
implied to be done.

## Pin policy

A build must not change because upstream changed. Every entry states how the workflow enforces
the pin; where it does not yet, it says so rather than implying otherwise.

This is the **only** pin table. An earlier version had two — one under "Pin policy" and one under
"Verified pins" — and they disagreed about glTF-Transform (`4.2.1` in one, `@4` in the other),
which is exactly the drift a pin table exists to prevent. Merged, because two tables of the same
facts is a guarantee that one of them is wrong.

| Tool | Pin | Enforced / verified how | State |
|---|---|---|---|
| Blender 4.2 | `4.2.23` LTS, linux-x64, sha256 `bea0eb31…` | **SHA-256 verified on every run**, in both jobs, cache hit or miss | working |
| Blender 4.5 | `4.5.16` LTS, linux-x64, sha256 `23432b06…` | **SHA-256 verified on every run** | working |
| Godot | `4.7.2-stable`, linux.x86_64 | `--version` confirmed; **archive hash computed and reported, not pinned** | working, pin outstanding |
| gltfpack | `v1.3`, `gltfpack-ubuntu.zip` | `-si` verified end to end; **archive hash computed and reported, not pinned** | working — `-noq` mandatory |
| glTF-Transform | `4.2.1` exact | exact version in CI | working |
| git-filter-repo | `2.45.0` | exact version in `pip install` | working |
| Python | `3.11` | `actions/setup-python` | working |
| Infinigen | commit `53033dd55c7191cbc436be6ffbb63c026935a509` | exact commit fetched in CI | working |
| Poly Haven API | live, asset IDs recorded per download | `api.polyhaven.com` | working |
| Quaternius | release `third-party-quaternius`, sha256 `cc73fc4e…` | **SHA-256 verified in CI** on every downloaded archive | measured: 43 clips |
| Modular Tree | release `5.6.0`, `modular_tree-5.6.0-linux_x64.zip`, sha256 `698cf57c…` | **SHA-256 verified in CI**; the release zip carries the compiled `m_tree` module | working — generates a tree Godot loads (1,840,066 tris, needs decimation) |
| MPFB2 | commit `d0a32e57a7f915cb2f2b95410e2117648c7bbb7e` (tag `v2.0.18`) | **commit fetched and verified in CI**; a tag is movable, so the commit is the pin | working — 36,972 tris / 137 bones, both over budget |
| GitHub Actions | `@v4` / `@v5` | **major tags, not commit SHAs** | pin outstanding |

## Outstanding pins

An unpinned dependency can change a generated asset without the repository changing.

| Item | State | Why it is not done |
|---|---|---|
| Godot archive checksum | hash computed and **reported as UNPINNED** each run | Godot publishes no checksum file with its GitHub release assets (no `SHA256-SUMS.txt` at that tag — it 404s), so there is no vendor value to check against. The run prints the measured hash in the job summary; pasting it into `GODOT_SHA256` makes the pin real. Until then the probe reports `ok=False reason=unpinned` rather than claiming verification. |
| gltfpack archive checksum | same mechanism | meshoptimizer publishes no release-asset checksums either. |
| GitHub Actions | major tags | 14 pins across three workflows; needs each action's commit SHA resolved. No behavioural change, so it is queued behind the asset pipeline. |

**The rule these follow:** an unverified pin must never read as a verified one. That is why the
Godot and gltfpack probes report `ok=False reason=unpinned` and write a warning into the job
summary, instead of silently passing as they did before.

## Why Blender 4.2 LTS and not a newer major

MPFB2 2.x requires Blender >= 4.2 (stated in its README). 4.2 is the oldest LTS that satisfies
it, and its glTF exporter is the one the rest of the pipeline is written against. A second
Blender version is pinned per job where a tool demands it — MTree needs 4.5.16.

**4.2 is an old LTS and its support window is closing.** It is kept because MPFB2's requirement
is the binding constraint, not because it is preferred. The moment MPFB2 works on 4.5, 4.2
should be dropped and one Blender pinned for every job: two pinned Blenders is two toolchains to
keep correct, and the tools job has already been the place where the checksum check went
missing. Tracked in `docs/POLICY.md`.

## Modular Tree must come from the release, not the source

MTree's operators do `from m_tree import m_tree`. `m_tree` is a **compiled pybind11 extension**
built with scikit-build-core (`m_tree/pyproject.toml`, `m_tree/CMakeLists.txt`). A source clone
contains a *directory* called `m_tree` holding C++ sources and no built module, so Python
resolves it as an empty namespace package and the import fails with:

```
cannot import name 'm_tree' from 'm_tree' (unknown location)
```

That is not a bug in the tool and not something a `sys.path` tweak fixes. The project's CD
workflow compiles the extension and packages it with the addon; `modular_tree-5.6.0-linux_x64.zip`
is that package, and it is what CI installs, checksum-verified.

Building it ourselves would mean cmake, a C++20 toolchain and a vcpkg build of Eigen on every
run. Downloading the 3.8 MB release is faster, pinned and verifiable.

## Decisions taken on the Phase 0 evidence (owner-approved)

| Question | Decision |
|---|---|
| Preview rendering | **Cycles CPU is the official preview renderer.** Low samples with denoise, contact sheets at roughly 640×360. Each report states which engine actually produced the pixels. Workbench and EEVEE under Xvfb + llvmpipe are probed but are not depended on. |
| Godot visual checks | Not in CI. The Godot headless **import and load** check stays; anything that needs pixels happens on a real device. |
| Infinigen | Approved as planned: `generate_individual_assets` only, CPU, small shards, never full scenes. |
| Modular Tree | Approved, and it runs under **Blender 4.5.16** (its manifest requires 4.5.0). Installed from the **prebuilt release zip**, because the source ships only C++. If generation still fails, trees come from the Infinigen plant factories plus custom generators and the loss is recorded in `reports/tool_evaluation.md`. |
| Quaternius animations | The release supplies `UAL1_Standard.glb` and `UAL1_Standard_RM.glb`: whole animation libraries in single containers. **Measured: 43 clips.** Family coverage is a keyword match on clip-name tokens, so it is a lower bound on what is missing and an upper bound on what is usable: a clip named for a different weapon can still satisfy a family. The retarget map is now diffed against the pack's real skin joints on every run, and that diff is a required probe. |
| fps | Not measured in CI. Static budgets only (triangles, draw calls, materials, texture memory); `tech_perf_overlay_stub` is P1 so real-device measurement is possible. |

## Release packs

A category that overflows its size budget moves to a GitHub Release, **one tag per
category** (`pack-4e-flora`, and so on). Every asset in a pack records `pack` and its
`sha256` in the manifest, so the build can verify what it downloads. The APK workflow fetches
packs with `GITHUB_TOKEN` and `contents: write`.

## History

`main` stays under 800 MB, the absolute cap. The plan's declared category budgets total 790 MB
against a 700 MB target; `check_manifest.py` warns above the target and fails above the cap.
Binaries reach `main` only by merging the staging branch after the gates pass, never by direct
push. Purging is prevention-first; if it is ever needed, `docs/HISTORY_PURGE.md` has the manual
steps and `.github/workflows/history-purge.yml` is the manual-only, force-pushing equivalent that
must not be run without the owner's explicit approval.

