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
    print("RESULT polyhaven_assets ok=True count=%d" % len(assets))

    wanted = ("forest", "moss", "dirt", "ground", "soil")
    preferred = [name for name in sorted(assets) if any(key in name for key in wanted)]
    pick = (preferred or sorted(assets))[0]
    print("RESULT polyhaven_pick ok=True id=%s" % pick)

    files = get_json(API + "/files/" + pick)
    diffuse = files.get("Diffuse", {}).get("1k", {}).get("jpg", {})
    url = diffuse.get("url")
    if not url:
        print("RESULT polyhaven_diffuse ok=False reason=no 1k jpg diffuse for %s" % pick)
        return 1

    destination = os.path.join(args.out, "polyhaven_sample.jpg")
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=120) as response:
        with open(destination, "wb") as handle:
            handle.write(response.read())
    print(
        "RESULT polyhaven_download ok=True id=%s bytes=%d"
        % (pick, os.path.getsize(destination))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
