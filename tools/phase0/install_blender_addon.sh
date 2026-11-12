#!/usr/bin/env bash
# Install a Blender add-on from a cloned repository into Blender's user addons directory.
#
#   install_blender_addon.sh <repo_dir> <addon_name>
#
# Repositories lay their add-on out differently (a package folder, a src/ directory, or the
# repository root itself), so this finds the directory that actually contains a bl_info
# block and links that under the requested name. It prints what it decided, so a failure in
# the Phase 0 report says which shape was expected and which was found.
set -uo pipefail

repo="${1:?repo dir required}"
name="${2:?addon name required}"

addons_dir="$HOME/.config/blender/4.2/scripts/addons"
mkdir -p "$addons_dir"

if [ ! -d "$repo" ]; then
  echo "addon_install ${name}: repo missing at ${repo}"
  exit 1
fi

found=""
while IFS= read -r candidate; do
  dir="$(dirname "$candidate")"
  if grep -q "bl_info" "$candidate" 2>/dev/null; then
    found="$dir"
    break
  fi
done < <(find "$repo" -maxdepth 3 -name "__init__.py" -not -path "*/.git/*" | sort)

if [ -z "$found" ]; then
  echo "addon_install ${name}: no __init__.py containing bl_info under ${repo}"
  find "$repo" -maxdepth 2 -name "*.py" -not -path "*/.git/*" | head -20
  exit 1
fi

echo "addon_install ${name}: using ${found}"
rm -rf "${addons_dir:?}/${name}"
cp -r "$found" "${addons_dir}/${name}"
echo "addon_install ${name}: copied to ${addons_dir}/${name}"
ls -la "${addons_dir}/${name}" | head -20
