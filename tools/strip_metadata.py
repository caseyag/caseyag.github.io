#!/usr/bin/env python3
"""Remove EXIF/XMP metadata (including GPS location) from JPEG files.

Keeps image data, the JFIF header, ICC color profiles (APP2) and Adobe APP14.
Drops APP1 (EXIF, XMP), APP3-APP13, APP15 and comments, and drops any bytes
after the first EOI marker. Bake rotation in before running this, because the
EXIF orientation tag is removed too.

Usage: python3 tools/strip_metadata.py IN.jpg OUT.jpg
"""
import sys

KEEP_APP = {0xE0, 0xE2, 0xEE}  # APP0 (JFIF), APP2 (ICC profile), APP14 (Adobe)


def walk_segments(data):
    """Yield (marker, start, end) for each piece of the primary image, in order.

    Marker 0 means entropy-coded scan data. The walk stops at the first EOI
    (marker 0xD9), so anything appended after the image is never visited.
    Raises ValueError on a malformed or truncated file.
    """
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    yield 0xD8, 0, 2
    n = len(data)
    i = 2
    while True:
        if i >= n:
            raise ValueError("truncated JPEG")
        if data[i] != 0xFF:
            raise ValueError(f"bad marker at byte {i}")
        while i < n and data[i] == 0xFF:  # skip fill bytes
            i += 1
        if i >= n:
            raise ValueError("truncated JPEG")
        marker = data[i]
        i += 1
        start = i - 2
        if marker == 0xD9:
            yield marker, start, i
            return
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # standalone markers
            yield marker, start, i
            continue
        if i + 2 > n:
            raise ValueError("truncated JPEG")
        length = int.from_bytes(data[i:i + 2], "big")
        end = i + length
        if length < 2 or end > n:
            raise ValueError("truncated JPEG")
        yield marker, start, end
        i = end
        if marker == 0xDA:  # entropy-coded data runs to the next real marker
            j = i
            while True:
                j = data.find(b"\xff", j)
                if j == -1 or j + 1 >= n:
                    raise ValueError("truncated JPEG")
                nxt = data[j + 1]
                if nxt == 0x00 or 0xD0 <= nxt <= 0xD7:
                    j += 2
                elif nxt == 0xFF:
                    j += 1
                else:
                    break
            yield 0, i, j
            i = j


def is_metadata(marker):
    return (0xE1 <= marker <= 0xEF and marker not in KEEP_APP) or marker == 0xFE


def primary_end(data):
    """Index just past the first EOI, i.e. the end of the primary image."""
    end = 0
    for _, _, end in walk_segments(data):
        pass
    return end


def strip(data):
    out = bytearray()
    for marker, start, end in walk_segments(data):
        if not is_metadata(marker):
            out += data[start:end]
    return bytes(out)


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, "rb") as f:
        cleaned = strip(f.read())
    with open(dst, "wb") as f:
        f.write(cleaned)
