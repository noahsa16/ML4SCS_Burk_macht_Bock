#!/usr/bin/env python3
"""Trace a line drawing into ordered pen strokes.

The bestiary draws a creature one stroke at a time, so it needs *strokes* —
not the filled outlines an ordinary auto-trace produces. This tool reduces the
ink in an image to its one-pixel centre lines, walks those into polylines, and
writes an SVG with one `<path>` per stroke. That SVG is the input to
`svg_to_marginalia.py`.

    .venv/bin/python tools/trace_to_strokes.py scan.png --out 0-name.svg

Works on line art: a manuscript drollery, a pen sketch, anything where the
subject is dark marks on a lighter ground. It does not work on a photograph or
a shaded painting, and it will say so rather than produce noise.

Needs numpy, scipy and scikit-image, which live in the project's .venv.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from scipy.ndimage import convolve
from skimage.filters import threshold_otsu, threshold_sauvola
from skimage.morphology import (skeletonize, remove_small_objects,
                                opening, closing, disk)

NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def load_ink(path: Path, invert: bool, max_side: int,
             window: int, despeckle: int, bridge: int) -> np.ndarray:
    """Return a boolean mask, True where there is ink."""
    image = Image.open(path).convert("L")
    if max(image.size) > max_side:
        scale = max_side / max(image.size)
        image = image.resize((max(1, int(image.width * scale)),
                              max(1, int(image.height * scale))),
                             Image.LANCZOS)
    # Parchment is warm and uneven, so a global threshold on the raw values
    # tends to swallow the lighter half of the drawing. Autocontrast first,
    # clipping the extremes, gives Otsu a fighting chance.
    image = ImageOps.autocontrast(image, cutoff=2)
    data = np.asarray(image, dtype=float) / 255.0
    if window:
        # Why local and not global: a single threshold works on clean line art
        # but not on parchment, where the ground is blotchy and the pen strokes
        # are pale. Otsu then catches only the darkest part of each line and
        # leaves the rest as gaps, so the trace comes out as fragments rather
        # than strokes. Sauvola compares each pixel with its own neighbourhood,
        # which is what document binarisation is for.
        ink = data < threshold_sauvola(data, window_size=window, k=0.15)
    else:
        ink = data < threshold_otsu(data)
    if invert:
        ink = ~ink
    covered = ink.mean()
    if covered > 0.45:
        raise SystemExit(
            f"{path.name}: {covered:.0%} of the image reads as ink. That is a "
            f"photograph or a shaded painting, not line art — or the tones are "
            f"inverted, in which case pass --invert."
        )
    if covered < 0.002:
        raise SystemExit(f"{path.name}: almost no ink found ({covered:.2%}).")
    # Order matters, and getting it wrong is what made the first attempt at a
    # real manuscript fail. Opening first removes anything narrower than a pen
    # stroke — which is exactly what parchment grain is, and the one property
    # that separates it from the drawing. Closing afterwards rejoins the gaps a
    # skipping nib left. Closing first welds the grain onto the drawing instead,
    # and no later filter can tell them apart again.
    if despeckle:
        ink = opening(ink, disk(despeckle))
    if bridge:
        ink = closing(ink, disk(bridge))
    return ink


def centre_lines(ink: np.ndarray, min_blob: int) -> np.ndarray:
    cleaned = remove_small_objects(ink, min_size=min_blob)
    if not cleaned.any():
        raise SystemExit(f"nothing left after removing blobs under {min_blob} px")
    return skeletonize(cleaned)


def walk(skeleton: np.ndarray) -> list[list[tuple[int, int]]]:
    """Split the skeleton into polylines at its endpoints and junctions.

    A drawing's skeleton is a graph. Cutting it wherever three lines meet, and
    starting from the loose ends, yields runs that each correspond to one
    recognisable stroke of a pen.
    """
    degree = convolve(skeleton.astype(np.uint8),
                      np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.uint8),
                      mode="constant")
    degree = degree * skeleton
    pixels = {(int(r), int(c)) for r, c in np.argwhere(skeleton)}
    nodes = {p for p in pixels if degree[p] != 2}      # ends and junctions

    def around(p):
        r, c = p
        return [(r + dr, c + dc) for dr, dc in NEIGHBOURS if (r + dr, c + dc) in pixels]

    used: set[frozenset] = set()
    runs: list[list[tuple[int, int]]] = []

    def follow(start, step):
        run = [start, step]
        used.add(frozenset((start, step)))
        current, previous = step, start
        while current not in nodes:
            nxt = [q for q in around(current) if q != previous]
            if not nxt:
                break
            previous, current = current, nxt[0]
            used.add(frozenset((previous, current)))
            run.append(current)
        return run

    for node in sorted(nodes):
        for neighbour in around(node):
            if frozenset((node, neighbour)) not in used:
                runs.append(follow(node, neighbour))

    # Closed loops carry no endpoint and no junction, so nothing above reaches
    # them; they have to be picked up separately or every circle disappears.
    seen = {p for run in runs for p in run}
    for start in sorted(pixels - seen):
        if start in seen:
            continue
        run, current, previous = [start], start, None
        while True:
            nxt = [q for q in around(current) if q != previous and q not in seen]
            if not nxt:
                break
            previous, current = current, nxt[0]
            seen.add(current)
            run.append(current)
        seen.add(start)
        if len(run) > 2:
            run.append(start)
            runs.append(run)

    return runs


def simplify(points: list[tuple[int, int]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas-Peucker, so a hand-drawn line stops being a thousand pixels."""
    if len(points) < 3:
        return [(float(c), float(r)) for r, c in points]
    pts = np.array([(c, r) for r, c in points], dtype=float)

    keep = np.zeros(len(pts), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        a, b = pts[lo], pts[hi]
        span = b - a
        length = np.hypot(*span)
        if length == 0:
            d = np.hypot(*(pts[lo + 1:hi] - a).T)
        else:
            rel = pts[lo + 1:hi] - a
            d = np.abs(span[0] * rel[:, 1] - span[1] * rel[:, 0]) / length
        k = int(np.argmax(d))
        if d[k] > tolerance:
            keep[lo + 1 + k] = True
            stack += [(lo, lo + 1 + k), (lo + 1 + k, hi)]
    return [tuple(p) for p in pts[keep]]


def smooth_path(points: list[tuple[float, float]]) -> str:
    """Emit SVG path data, rounding the corners a simplified line leaves behind.

    Catmull-Rom through the kept points, converted to cubics: the result reads
    as a drawn line rather than a chain of segments, which is what the app then
    renders with a round cap.
    """
    if len(points) < 2:
        return ""
    if len(points) == 2:
        (x0, y0), (x1, y1) = points
        return f"M {x0:.1f} {y0:.1f} L {x1:.1f} {y1:.1f}"

    p = [points[0]] + list(points) + [points[-1]]
    out = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        out.append(f"C {c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} "
                   f"{p2[0]:.1f} {p2[1]:.1f}")
    return " ".join(out)


def drawing_order(strokes: list[list[tuple[float, float]]]) -> list:
    """Order the strokes so the creature grows instead of assembling.

    Sorting by length alone looked right finished and wrong in motion: the
    longest strokes are scattered across the figure, so a session showed two
    ears floating in space, then a disconnected leg. A drawing does not appear
    that way. Each stroke here is the one nearest to what is already on the
    page, starting from the longest, so the figure spreads from a first mark
    the way it does under a hand.

    Among strokes that are equally close, the longer wins: contours before the
    details that hang off them.
    """
    if not strokes:
        return strokes
    remaining = sorted(strokes, key=length_of, reverse=True)
    ordered = [remaining.pop(0)]
    # Endpoints are enough: strokes meet at their ends, and comparing every
    # point against every point costs far more for no better an order.
    anchors = [ordered[0][0], ordered[0][-1]]

    while remaining:
        best, best_distance = 0, None
        for i, stroke in enumerate(remaining):
            d = min(np.hypot(p[0] - a[0], p[1] - a[1])
                    for p in (stroke[0], stroke[-1]) for a in anchors)
            if best_distance is None or d < best_distance - 1e-9:
                best, best_distance = i, d
            elif abs(d - best_distance) <= 6.0 and \
                    length_of(stroke) > length_of(remaining[best]):
                best, best_distance = i, d
        stroke = remaining.pop(best)
        ordered.append(stroke)
        anchors += [stroke[0], stroke[-1]]
    return ordered


def length_of(points) -> float:
    return sum(np.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
               for i in range(len(points) - 1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--invert", action="store_true",
                    help="the drawing is light on a dark ground")
    ap.add_argument("--max-side", type=int, default=900,
                    help="downscale before tracing; smaller loses detail, "
                         "larger keeps scanner noise (default 900)")
    ap.add_argument("--window", type=int, default=0,
                    help="local threshold window in pixels (odd, try 31 for a "
                         "manuscript scan); 0 uses a single global threshold, "
                         "which suits clean line art")
    ap.add_argument("--despeckle", type=int, default=0,
                    help="strip marks narrower than this radius before tracing; "
                         "1 clears parchment grain and keeps the pen line")
    ap.add_argument("--bridge", type=int, default=0,
                    help="close gaps up to this radius before tracing; 1 or 2 "
                         "rejoins a skipping nib")
    ap.add_argument("--min-blob", type=int, default=60,
                    help="drop ink specks smaller than this, in pixels")
    ap.add_argument("--min-stroke", type=float, default=14.0,
                    help="drop traced strokes shorter than this, in pixels")
    ap.add_argument("--tolerance", type=float, default=1.6,
                    help="how far a simplified line may stray from the pixels")
    ap.add_argument("--max-strokes", type=int, default=60)
    args = ap.parse_args()

    ink = load_ink(args.image, args.invert, args.max_side,
                   args.window, args.despeckle, args.bridge)
    runs = walk(centre_lines(ink, args.min_blob))

    strokes = []
    for run in runs:
        pts = simplify(run, args.tolerance)
        if len(pts) >= 2 and length_of(pts) >= args.min_stroke:
            strokes.append(pts)

    if not strokes:
        raise SystemExit("no strokes survived; try --min-stroke lower")

    strokes = drawing_order(strokes)
    dropped = max(0, len(strokes) - args.max_strokes)
    strokes = strokes[:args.max_strokes]

    height, width = ink.shape
    body = "\n".join(
        f'  <path id="{i + 1}" fill="none" stroke="black" d="{smooth_path(s)}"/>'
        for i, s in enumerate(strokes))
    args.out.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">\n'
        f'{body}\n</svg>\n')

    print(f"{args.image.name}: {len(strokes)} strokes"
          + (f", {dropped} shorter ones dropped" if dropped else "")
          + f"  ->  {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
