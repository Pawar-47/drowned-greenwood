"""Phase 0 probe: the Poly Haven public API is reachable and a CC0 1k PBR map downloads.

Run:
    python3 tools/phase0/polyhaven_probe.py --out artifacts/phase0

Uses only the standard library. The asset id it picks is recorded so it can be entered in
assets/LICENSES.md if the asset is used in the pipeline.
"""

import argparse
import json
import os
import sys
import urllib.request

API = "https://api.polyhaven.com"
HEADERS = {"User-Agent": "drowned-greenwood-asset-pipeline/phase0"}


def result(**fields):
    """Emit one machine-readable line, in the shape the report parser reads."""
    print("RESULT " + json.dumps(fields, sort_keys=True))


def get_json(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="artifacts/phase0")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    assets = get_json(API + "/assets?t=textures")
    result(step="polyhaven_assets", ok=True, count=len(assets))

    wanted = ("forest", "moss", "dirt", "ground", "soil")
    preferred = [name for name in sorted(assets) if any(key in name for key in wanted)]
    pick = (preferred or sorted(assets))[0]
    result(step="polyhaven_pick", ok=True, asset_id=pick)

    files = get_json(API + "/files/" + pick)
    diffuse = files.get("Diffuse", {}).get("1k", {}).get("jpg", {})
    url = diffuse.get("url")
    if not url:
        result(step="polyhaven", ok=False, reason="no 1k jpg diffuse for %s" % pick)
        return 1

    destination = os.path.join(args.out, "polyhaven_sample.jpg")
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=120) as response:
        with open(destination, "wb") as handle:
            handle.write(response.read())
    size = os.path.getsize(destination)
    # The single summary row the report gates on.
    result(step="polyhaven", ok=size > 0, asset_id=pick, bytes=size)
    return 0 if size > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
