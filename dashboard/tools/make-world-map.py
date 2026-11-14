#!/usr/bin/env python3
"""Shrink Natural Earth's 110 m land outlines to src/assets/world-land.json for the world clock map.

Source (public domain): ne_110m_land.geojson from github.com/nvkelso/natural-earth-vector, geojson/.
Usage: python3 -I mac/make-world-map.py <ne_110m_land.geojson> src/assets/world-land.json

Output: a list of polygons; each polygon is a list of rings (outline first, then holes);
each ring is a flat list [lon, lat, lon, lat, ...] in tenths of a degree.
"""
import json
import sys


def ring(points):
    flat, last = [], None
    for lon, lat in points:
        point = (round(lon * 10), round(lat * 10))
        if point != last:
            flat.extend(point)
            last = point
    return flat if len(flat) >= 8 else None


def main(src, dst):
    with open(src) as fh:
        data = json.load(fh)
    polygons = []
    for feature in data["features"]:
        geometry = feature["geometry"]
        parts = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        for part in parts:
            rings = [r for r in map(ring, part) if r]
            if rings:
                polygons.append(rings)
    with open(dst, "w") as fh:
        json.dump(polygons, fh, separators=(",", ":"))
    print(f"{len(polygons)} polygons, {sum(len(r) for p in polygons for r in p) // 2} points")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
