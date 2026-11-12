#!/usr/bin/env bash
# Install a Blender add-on from a cloned repository into Blender's user addons directory.
#
#   install_blender_addon.sh <repo_dir> <addon_name>
#
# Repositories lay an add-on out differently, so this reports the shape it found rather than
# failing silently:
#   1. a directory whose __init__.py has a bl_info block  -> copied as the add-on
#   2. a blender_manifest.toml                            -> a Blender 4.2+ extension, which is
#                                                            not installed by copying files
#   3. neither                                            -> listed for the report
#
# It always exits 0 and always prints one RESULT line, so a failed install can never abort the
# calling step before the probes run. The probe decides pass or fail, not this script.
set -uo pipefail

repo="${1:?repo dir required}"
name="${2:?addon name required}"

addons_dir="$HOME/.config/blender/4.2/scripts/addons"
mkdir -p "$addons_dir"

if [ ! -d "$repo" ]; then
  echo "RESULT addon_install addon=${name} ok=False reason=repo_missing path=${repo}"
  exit 0
fi

# Case 1: a legacy add-on, found by its bl_info block.
found=""
while IFS= read -r candidate; do
  if grep -q "bl_info" "$candidate" 2>/dev/null; then
    found="$(dirname "$candidate")"
    break
  fi
done < <(find "$repo" -maxdepth 4 -name "__init__.py" -not -path "*/.git/*" | sort)

if [ -n "$found" ]; then
  echo "addon_install ${name}: legacy add-on at ${found}"
  rm -rf "${addons_dir:?}/${name}"
  cp -r "$found" "${addons_dir}/${name}"
  echo "RESULT addon_install addon=${name} ok=True kind=legacy_addon source=${found}"
  exit 0
fi

# Case 2: a Blender 4.2+ extension. Copying it into scripts/addons does not register it.
manifest="$(find "$repo" -maxdepth 3 -name "blender_manifest.toml" -not -path "*/.git/*" | head -1)"
if [ -n "$manifest" ]; then
  echo "addon_install ${name}: extension manifest at ${manifest}"
  grep -E '^(id|name|version|blender_version_min)' "$manifest" || true
  echo "RESULT addon_install addon=${name} ok=False kind=extension source=${manifest} reason=extension_needs_extension_install"
  exit 0
fi

# Case 3: unrecognised layout.
echo "addon_install ${name}: no bl_info and no blender_manifest.toml under ${repo}"
find "$repo" -maxdepth 2 -name "*.py" -not -path "*/.git/*" | head -20
echo "RESULT addon_install addon=${name} ok=False kind=unknown reason=no_manifest_and_no_bl_info"
exit 0
