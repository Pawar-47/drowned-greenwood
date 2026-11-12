#!/usr/bin/env python3
"""Shared machinery for the asset generators.

Every generator in this directory follows the same contract, and this file is where that contract
lives so it cannot drift between them:

  * **Deterministic.** Given the same seed and the same config, a generator produces byte-identical
    output. That is what makes `input_hash` meaningful and what lets a rebuild be compared rather
    than trusted.
  * **Reproducible provenance.** Each run reports the seed, the config hash and the tool version,
    so `check_manifest.py` can require them before a record is allowed to claim `built`.
  * **No third-party Python.** These run on a bare `setup-python` runner. A heightmap needs a PNG
    writer and a hash, and both are in the standard library, so there is no numpy and no Pillow to
    pin, break or audit.

The PNG writer exists because writing a 1,050,625-pixel grayscale image should not require a
dependency. It emits the smallest valid form: one IDAT, filter type 0 on every scanline, no
ancillary chunks.
"""

import hashlib
import json
import struct
import zlib

# Bumped when a generator's output changes for the same inputs. It is recorded in every asset's
# tool_version, so a rebuild that produces different bytes is visible as a version change rather
# than as an unexplained difference in the hash.
GENERATOR_VERSION = "1.0.0"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(tag, data):
    """One PNG chunk: length, tag, data, CRC over tag+data."""
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_gray_png(path, rows, bit_depth=8):
    """Write a single-channel PNG.

    `rows` is a sequence of equal-length sequences of ints. bit_depth is 8 (surface ids, masks)
    or 16 (heightmaps). Colour type 0 is grayscale, so there is no palette to keep in sync and no
    sRGB profile to strip.
    """
    if not rows:
        raise ValueError("no rows to write")
    width = len(rows[0])
    height = len(rows)
    for index, row in enumerate(rows):
        if len(row) != width:
            raise ValueError(
                "row %d has %d values, expected %d" % (index, len(row), width)
            )

    limit = (1 << bit_depth) - 1
    raw = bytearray()
    for row in rows:
        raw.append(0)  # filter type 0: None
        if bit_depth == 16:
            for value in row:
                if not 0 <= value <= limit:
                    raise ValueError("value %r outside 16-bit range" % (value,))
                raw += struct.pack(">H", value)
        elif bit_depth == 8:
            for value in row:
                if not 0 <= value <= limit:
                    raise ValueError("value %r outside 8-bit range" % (value,))
                raw.append(value)
        else:
            raise ValueError("bit_depth must be 8 or 16, got %r" % (bit_depth,))

    # IHDR: width, height, bit depth, colour type 0 (grayscale), deflate, adaptive filter, no
    # interlace.
    header = struct.pack(">IIBBBBB", width, height, bit_depth, 0, 0, 0, 0)
    payload = PNG_SIGNATURE
    payload += _chunk(b"IHDR", header)
    payload += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    payload += _chunk(b"IEND", b"")

    with open(path, "wb") as handle:
        handle.write(payload)
    return len(payload)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def input_hash(payload):
    """The hash of what was fed to a generator: seed, config, resolution, everything.

    Sorted keys and no whitespace, so two runs that mean the same thing hash the same and a
    cosmetic edit to the config does not look like a different asset.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def value_lattice(size, rng):
    """A size×size grid of random values in 0..1, sampled with wraparound.

    Wrapping rather than clamping means the noise tiles, which matters because the 1 km terrain is
    one tile of a larger world and a visible seam at its border would be a bug nobody looks for.
    """
    lattice = [[rng.random() for _ in range(size)] for _ in range(size)]
    return lattice


def smoothstep(t):
    """The standard 3t²-2t³ ease, so lattice interpolation has no visible grid creases."""
    return t * t * (3.0 - 2.0 * t)


def sample_lattice(lattice, u, v):
    """Bilinear, smoothed sample of a wrapping lattice at fractional coordinates in 0..1."""
    size = len(lattice)
    x = u * size
    y = v * size
    x0 = int(x) % size
    y0 = int(y) % size
    x1 = (x0 + 1) % size
    y1 = (y0 + 1) % size
    fx = smoothstep(x - int(x))
    fy = smoothstep(y - int(y))
    a = lattice[y0][x0] * (1.0 - fx) + lattice[y0][x1] * fx
    b = lattice[y1][x0] * (1.0 - fx) + lattice[y1][x1] * fx
    return a * (1.0 - fy) + b * fy


def fbm_field(cells, seed, octaves=4, base_size=4, persistence=0.5, lacunarity=2.0):
    """A `cells`×`cells` fractal noise field in 0..1, deterministic from the seed.

    The noise is generated at the requested resolution directly: each octave samples a lattice of
    `base_size`-ish cells, so cost is O(cells² · octaves) with no interpolation pass to get wrong.
    """
    import random

    field = [[0.0] * cells for _ in range(cells)]
    amplitude = 1.0
    total = 0.0
    size = base_size
    for octave in range(octaves):
        # A separate stream per octave: reusing one rng would make the octaves correlated, which
        # shows up as repeating structure at a fixed offset.
        rng = random.Random("%s:%d" % (seed, octave))
        lattice = value_lattice(size, rng)
        for y in range(cells):
            v = y / (cells - 1)
            row = field[y]
            for x in range(cells):
                u = x / (cells - 1)
                row[x] += amplitude * sample_lattice(lattice, u, v)
        total += amplitude
        amplitude *= persistence
        size = max(2, int(size * lacunarity))
    for y in range(cells):
        row = field[y]
        for x in range(cells):
            row[x] /= total
    return field


def bilinear_upsample(field, target):
    """Resample a square field to `target`×`target` by bilinear interpolation."""
    source = len(field)
    if source == target:
        return [row[:] for row in field]
    scale = (source - 1) / float(target - 1)
    out = []
    for y in range(target):
        sy = y * scale
        y0 = int(sy)
        y1 = min(y0 + 1, source - 1)
        fy = sy - y0
        row0 = field[y0]
        row1 = field[y1]
        row = [0.0] * target
        for x in range(target):
            sx = x * scale
            x0 = int(sx)
            x1 = min(x0 + 1, source - 1)
            fx = sx - x0
            a = row0[x0] * (1.0 - fx) + row0[x1] * fx
            b = row1[x0] * (1.0 - fx) + row1[x1] * fx
            row[x] = a * (1.0 - fy) + b * fy
        out.append(row)
    return out


def record(name, path, sha, in_hash, tool_version, **extra):
    """A manifest-shaped record for an asset this generator just wrote.

    Only fields the generator actually knows are set. `tris`, `bones` and `gate_results` are left
    for the step that measures the built file — a generator claiming a triangle count it never
    counted is the kind of assertion `check_manifest.py` exists to refuse.
    """
    out = {
        "name": name,
        "path": path,
        "sha256": sha,
        "input_hash": in_hash,
        "tool_version": tool_version,
    }
    out.update(extra)
    return out
