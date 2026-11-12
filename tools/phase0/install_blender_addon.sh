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

if [ -n "$blender_root" ] && [ -d "$blender_root" ]; then
  addons_dir="$blender_root/4.2/scripts/addons"
  where="blender_install"
else
  addons_dir="$HOME/.config/blender/4.2/scripts/addons"
  where="user_config"
fi
mkdir -p "$addons_dir"

if [ ! -d "$repo" ]; then
  echo "RESULT addon_install label=${label} ok=False reason=repo_missing path=${repo}"
  exit 0
fi

# A legacy add-on is a directory whose __init__.py has a bl_info block. Prefer the shallowest
# match so a repository's own package wins over anything vendored deeper.
found=""
while IFS= read -r candidate; do
  if grep -q "bl_info" "$candidate" 2>/dev/null; then
    found="$(dirname "$candidate")"
    break
  fi
done < <(find "$repo" -maxdepth 5 -name "__init__.py" -not -path "*/.git/*" | awk -F/ '{print NF" "$0}' | sort -n | cut -d' ' -f2-)

if [ -n "$found" ]; then
  addon_id="$(basename "$found")"
  echo "addon_install ${label}: legacy add-on at ${found} -> ${addons_dir}/${addon_id} (${where})"
  rm -rf "${addons_dir:?}/${addon_id}"
  cp -r "$found" "${addons_dir}/${addon_id}"
  ls "${addons_dir}/${addon_id}" | head -10
  echo "RESULT addon_install label=${label} ok=True kind=legacy_addon addon_id=${addon_id} location=${where}"
  exit 0
fi

# A Blender 4.2+ extension cannot be registered by copying files into scripts/addons. It has
# to be installed as an extension, or run under a Blender version its manifest allows. Report
# the declared minimum so the report can say which, instead of guessing.
manifest="$(find "$repo" -maxdepth 3 -name "blender_manifest.toml" -not -path "*/.git/*" | head -1)"
if [ -n "$manifest" ]; then
  echo "addon_install ${label}: extension manifest at ${manifest}"
  grep -E '^(id|name|version|blender_version_min)' "$manifest" || true
  min_version="$(grep -E '^blender_version_min' "$manifest" | sed -E 's/.*"(.*)".*/\1/')"
  echo "RESULT addon_install label=${label} ok=False kind=extension source=${manifest} blender_version_min=${min_version:-unknown}"
  exit 0
fi

echo "addon_install ${label}: no bl_info and no blender_manifest.toml under ${repo}"
find "$repo" -maxdepth 2 -name "*.py" -not -path "*/.git/*" | head -20
echo "RESULT addon_install label=${label} ok=False kind=unknown reason=no_manifest_and_no_bl_info"
exit 0
