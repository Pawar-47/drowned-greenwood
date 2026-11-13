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
    return write_png(path, rows, bit_depth=bit_depth, channels=1)


def write_png(path, rows, bit_depth=8, channels=1):
    """Write a 1- to 4-channel PNG.

    Colour type carries the channel count: 0 grayscale, 4 grayscale+alpha, 2 RGB, 6 RGBA. The
    two-mask case (hydrology: depth in R, flow direction in G) is packed as LA rather than as two
    textures, and the normal map and splat weights need RGB and RGBA respectively.

    Only 8-bit colour is supported for 3 and 4 channels: PNG has no 16-bit RGB path that is worth
    the decode cost here, and nothing this pipeline emits needs more than 8-bit per channel in
    colour.
    """
    if channels not in (1, 2, 3, 4):
        raise ValueError("channels must be 1..4, got %r" % (channels,))
    if channels > 2 and bit_depth != 8:
        raise ValueError("3 and 4 channel images must be 8-bit, got %r" % (bit_depth,))
    if not rows:
        raise ValueError("no rows to write")
    width = len(rows[0]) // channels
    height = len(rows)
    for index, row in enumerate(rows):
        if len(row) != width * channels:
            raise ValueError(
                "row %d has %d values, expected %d (%d pixels x %d channels)"
                % (index, len(row), width * channels, width, channels)
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

    # IHDR: width, height, bit depth, colour type, deflate, adaptive filter, no interlace.
    colour_type = COLOUR_TYPES[channels]
    header = struct.pack(">IIBBBBB", width, height, bit_depth, colour_type, 0, 0, 0)
    payload = PNG_SIGNATURE
    payload += _chunk(b"IHDR", header)
    payload += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    payload += _chunk(b"IEND", b"")

    with open(path, "wb") as handle:
        handle.write(payload)
    return len(payload)


# PNG colour type by channel count: grayscale, grayscale+alpha, RGB, RGBA.
COLOUR_TYPES = {1: 0, 2: 4, 3: 2, 4: 6}
COLOUR_CHANNELS = {0: 1, 4: 2, 2: 3, 6: 4}


def read_png(path):
    """Read a 1- to 4-channel PNG written by this module.

    Returns (width, height, channels, rows) where rows are flat channel-interleaved ints.

    The writer always emits filter type 0, so this reader only *needs* to handle that — but it
    handles all five, because the heightmap is an intermediate file and someone will eventually
    re-save one in an image editor. A reader that silently mis-decodes a filtered file would
    produce a terrain with no rivers and no error.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("%s is not a PNG" % path)

    width = height = bit_depth = colour_type = None
    idat = bytearray()
    pos = len(PNG_SIGNATURE)
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, bit_depth, colour_type = struct.unpack(">IIBB", payload[:10])
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break

    if width is None:
        raise ValueError("%s has no IHDR" % path)
    if colour_type not in COLOUR_CHANNELS:
        raise ValueError(
            "%s has colour type %r; only grayscale (0) and grayscale+alpha (4) are supported"
            % (path, colour_type)
        )
    if bit_depth not in (8, 16):
        raise ValueError("%s has bit depth %r" % (path, bit_depth))

    channels = COLOUR_CHANNELS[colour_type]
    sample_bytes = 2 if bit_depth == 16 else 1
    bpp = channels * sample_bytes
    stride = width * bpp
    raw = zlib.decompress(bytes(idat))

    rows = []
    previous = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        filter_type = raw[start]
        line = bytearray(raw[start + 1 : start + 1 + stride])
        if filter_type == 0:
            pass
        elif filter_type == 1:  # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                up = previous[i]
                up_left = previous[i - bpp] if i >= bpp else 0
                p = left + up - up_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
                if pa <= pb and pa <= pc:
                    predictor = left
                elif pb <= pc:
                    predictor = up
                else:
                    predictor = up_left
                line[i] = (line[i] + predictor) & 0xFF
        else:
            raise ValueError("%s: unknown filter type %d on row %d" % (path, filter_type, y))
        previous = line

        if bit_depth == 16:
            values = [struct.unpack(">H", line[i : i + 2])[0] for i in range(0, stride, 2)]
        else:
            values = list(line)
        rows.append(values)

    return width, height, channels, rows


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
