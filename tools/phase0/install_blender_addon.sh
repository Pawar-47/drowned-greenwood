#!/usr/bin/env bash
# Install a Blender add-on from a cloned repository.
#
#   install_blender_addon.sh <repo_dir> <label> [blender_root]
#
# With blender_root, the add-on goes into that Blender installation's own addons directory,
# which is on sys.path even under `--factory-startup`.
#
# Two things this gets right that an earlier version got wrong:
#   * The installed directory is named after the add-on's own package, not the repository.
#     Blender imports an add-on by package name, so installing `makehumancommunity/mpfb2` as
#     `mpfb2` makes `import mpfb` fail even though every file is present.
#   * It searches to depth 5, because MPFB2's package lives at `src/mpfb`, three levels down.
#
# The script always exits 0 and always prints one RESULT line, so a failed install can never
# abort the calling step before the probes run. The probe decides pass or fail, not this.
set -uo pipefail

repo="${1:?repo dir required}"
label="${2:?label required}"
blender_root="${3:-}"

# RESULT lines are JSON so tools/phase0/make_report.py can read them. A key=value line is
# silently dropped by the report parser, which is why an earlier failure of this script was
# invisible. The step name carries the label: two installs sharing one name meant the report
# kept only the last, so MPFB2's install output was overwritten by MTree's every run.
emit() {
  printf 'RESULT {"step": "addon_install_%s", "label": "%s", %s}\n' "$label" "$label" "$1"
}

if [ -n "$blender_root" ] && [ -d "$blender_root" ]; then
  install_dir="$blender_root/4.2/scripts/addons"
else
  install_dir=""
fi
# The user config addons directory is the one Blender actually scans for a non-bundled
# add-on: its diagnostics reported `.../addons/modules` on sys.path while the Blender
# installation's own addons directory was absent. Installing only into the installation is
# why MPFB2 kept reporting ModuleNotFoundError with all 551 files sitting on disk.
user_dir="$HOME/.config/blender/4.2/scripts/addons"
mkdir -p "$user_dir"
where="user_config"
[ -n "$install_dir" ] && mkdir -p "$install_dir"

if [ ! -d "$repo" ]; then
  emit "\"ok\": false, \"reason\": \"repo_missing\", \"path\": \"$repo\""
  exit 0
fi

# A legacy add-on is a directory whose __init__.py carries a bl_info block (MPFB2 names its
# own copy `fake_bl_info`, which this still matches). Prefer the shallowest match so a
# repository's package wins over anything vendored deeper.
found=""
while IFS= read -r candidate; do
  if grep -q "bl_info" "$candidate" 2>/dev/null; then
    found="$(dirname "$candidate")"
    break
  fi
done < <(find "$repo" -maxdepth 5 -name "__init__.py" -not -path "*/.git/*" | awk -F/ '{print NF" "$0}' | sort -n | cut -d' ' -f2-)

if [ -n "$found" ]; then
  addon_id="$(basename "$found")"
  echo "addon_install ${label}: legacy add-on at ${found} -> ${user_dir}/${addon_id} (${where})"
  rm -rf "${user_dir:?}/${addon_id}"
  cp -r "$found" "${user_dir}/${addon_id}"
  # A second copy in the Blender installation covers the other layout, so whichever path this
  # Blender version scans, the package is there.
  if [ -n "$install_dir" ]; then
    rm -rf "${install_dir:?}/${addon_id}"
    cp -r "$found" "${install_dir}/${addon_id}"
  fi
  count=$(find "${user_dir}/${addon_id}" -name "*.py" | wc -l)
  ls "${user_dir}/${addon_id}" | head -10
  emit "\"ok\": true, \"kind\": \"legacy_addon\", \"addon_id\": \"${addon_id}\", \"location\": \"${where}\", \"py_files\": ${count}, \"addons_dir\": \"${user_dir}\""
  exit 0
fi

# A Blender 4.2+ extension cannot be registered by copying files into scripts/addons. It has
# to be installed as an extension, or run under a Blender version its manifest allows. Report
# the declared minimum so the report says which, instead of guessing.
manifest="$(find "$repo" -maxdepth 3 -name "blender_manifest.toml" -not -path "*/.git/*" | head -1)"
if [ -n "$manifest" ]; then
  echo "addon_install ${label}: extension manifest at ${manifest}"
  grep -E '^(id|name|version|blender_version_min)' "$manifest" || true
  min_version="$(grep -E '^blender_version_min' "$manifest" | sed -E 's/.*"(.*)".*/\1/')"
  emit "\"ok\": false, \"kind\": \"extension\", \"source\": \"${manifest}\", \"blender_version_min\": \"${min_version:-unknown}\""
  exit 0
fi

echo "addon_install ${label}: no bl_info and no blender_manifest.toml under ${repo}"
find "$repo" -maxdepth 2 -name "*.py" -not -path "*/.git/*" | head -20
emit "\"ok\": false, \"kind\": \"unknown\", \"reason\": \"no_manifest_and_no_bl_info\""
exit 0
