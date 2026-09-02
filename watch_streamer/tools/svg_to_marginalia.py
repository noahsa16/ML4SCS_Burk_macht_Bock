#!/usr/bin/env python3
"""Turn hand-drawn SVG strokes into the Swift the bestiary expects.

The creatures are drawn one stroke at a time as a focus session accumulates
writing time, so the source has to be a list of *stroked* paths in drawing
order — not a filled silhouette. That is what a vector app produces when each
stroke is its own path, and it is why an auto-traced outline cannot be used
directly.

Usage:

    python3 tools/svg_to_marginalia.py drawings/*.svg \\
        --out WatchStreamer/Scrybe/Components/Marginalia.swift

One SVG per creature. The file's stem becomes the species name, so name them
in roster order:

    0-trompeten-hase.svg  1-panzerschnecke.svg  …

Stroke order is the order the paths appear in the file, which is the order the
layers sit in the drawing app. If every path carries an id or label beginning
with a number, that number wins instead — useful when you reorder layers for
tidiness but want the drawing order preserved.

Only stdlib. No SVG library is installed on this machine and none is needed:
the input is a handful of hand-drawn strokes, not arbitrary artwork.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

# The box every creature is normalised into, matching Marginalia's contract.
BOX = 100.0
# Kept clear on every side so a stroke's round cap is never clipped by the
# frame that draws it.
MARGIN = 4.0

NUMBER = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
COMMAND = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")


class Unsupported(Exception):
    """Raised with a message aimed at the person who drew the file."""


# --------------------------------------------------------------------------
# SVG path data → absolute segments
# --------------------------------------------------------------------------

def _tokenize(d: str):
    pos, out = 0, []
    while pos < len(d):
        ch = d[pos]
        if ch in " ,\t\r\n":
            pos += 1
        elif COMMAND.match(ch):
            out.append(ch)
            pos += 1
        else:
            m = NUMBER.match(d, pos)
            if not m:
                raise Unsupported(f"cannot read path data near {d[pos:pos + 12]!r}")
            out.append(float(m.group()))
            pos = m.end()
    return out


def parse_path(d: str) -> list[tuple]:
    """Return segments as ('L', x, y) or ('C', x1, y1, x2, y2, x, y).

    Every command is resolved to absolute coordinates and every curve to a
    cubic, so the emitter downstream has exactly two shapes to handle.
    """
    tokens = _tokenize(d)
    segments: list[tuple] = []
    i = 0
    cx = cy = 0.0          # current point
    sx = sy = 0.0          # subpath start, for Z
    last_c2 = None         # previous cubic's second control, for S
    last_q = None          # previous quadratic's control, for T
    command = None

    def take(n):
        nonlocal i
        values = tokens[i:i + n]
        if len(values) < n or any(isinstance(v, str) for v in values):
            raise Unsupported(f"command {command!r} is missing coordinates")
        i += n
        return values

    while i < len(tokens):
        if isinstance(tokens[i], str):
            command = tokens[i]
            i += 1
            if command in "Zz":
                segments.append(("L", sx, sy))
                cx, cy = sx, sy
                last_c2 = last_q = None
                continue
        elif command is None:
            raise Unsupported("path data starts with a number, not a command")
        elif command in "Mm":
            # A repeated coordinate pair after M is an implicit lineto.
            command = "L" if command == "M" else "l"

        rel = command.islower()
        up = command.upper()

        if up == "M":
            x, y = take(2)
            cx, cy = (cx + x, cy + y) if rel else (x, y)
            sx, sy = cx, cy
            segments.append(("M", cx, cy))
            last_c2 = last_q = None
        elif up == "L":
            x, y = take(2)
            cx, cy = (cx + x, cy + y) if rel else (x, y)
            segments.append(("L", cx, cy))
            last_c2 = last_q = None
        elif up == "H":
            (x,) = take(1)
            cx = cx + x if rel else x
            segments.append(("L", cx, cy))
            last_c2 = last_q = None
        elif up == "V":
            (y,) = take(1)
            cy = cy + y if rel else y
            segments.append(("L", cx, cy))
            last_c2 = last_q = None
        elif up == "C":
            x1, y1, x2, y2, x, y = take(6)
            if rel:
                x1, y1, x2, y2, x, y = (cx + x1, cy + y1, cx + x2, cy + y2,
                                        cx + x, cy + y)
            segments.append(("C", x1, y1, x2, y2, x, y))
            last_c2, last_q = (x2, y2), None
            cx, cy = x, y
        elif up == "S":
            x2, y2, x, y = take(4)
            if rel:
                x2, y2, x, y = cx + x2, cy + y2, cx + x, cy + y
            x1, y1 = (2 * cx - last_c2[0], 2 * cy - last_c2[1]) if last_c2 else (cx, cy)
            segments.append(("C", x1, y1, x2, y2, x, y))
            last_c2, last_q = (x2, y2), None
            cx, cy = x, y
        elif up in "QT":
            if up == "Q":
                qx, qy, x, y = take(4)
                if rel:
                    qx, qy, x, y = cx + qx, cy + qy, cx + x, cy + y
            else:
                x, y = take(2)
                if rel:
                    x, y = cx + x, cy + y
                qx, qy = (2 * cx - last_q[0], 2 * cy - last_q[1]) if last_q else (cx, cy)
            # Quadratic to cubic: control points sit two thirds of the way out.
            segments.append(("C",
                             cx + 2 / 3 * (qx - cx), cy + 2 / 3 * (qy - cy),
                             x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y),
                             x, y))
            last_q, last_c2 = (qx, qy), None
            cx, cy = x, y
        elif up == "A":
            raise Unsupported(
                "the drawing contains an elliptical arc (A command). Most vector "
                "apps only emit these for shapes drawn with the ellipse tool — "
                "convert those to curves before exporting, or redraw them with "
                "the pen."
            )
        else:
            raise Unsupported(f"unsupported command {command!r}")

    return segments


# --------------------------------------------------------------------------
# Transforms
# --------------------------------------------------------------------------

def parse_transform(text: str) -> tuple[float, ...]:
    """Return an affine matrix (a, b, c, d, e, f); identity when absent."""
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not text:
        return matrix
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", text):
        v = [float(n) for n in NUMBER.findall(args)]
        if name == "translate":
            m = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale":
            m = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "matrix":
            m = tuple(v[:6])
        elif name == "rotate":
            r = math.radians(v[0])
            m = (math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0)
            if len(v) == 3:
                matrix = _compose(matrix, (1, 0, 0, 1, v[1], v[2]))
                matrix = _compose(matrix, m)
                matrix = _compose(matrix, (1, 0, 0, 1, -v[1], -v[2]))
                continue
        else:
            raise Unsupported(f"unsupported transform {name!r}")
        matrix = _compose(matrix, m)
    return matrix


def _compose(outer, inner):
    a, b, c, d, e, f = outer
    A, B, C, D, E, F = inner
    return (a * A + c * B, b * A + d * B,
            a * C + c * D, b * C + d * D,
            a * E + c * F + e, b * E + d * F + f)


def apply(matrix, x, y):
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


# --------------------------------------------------------------------------
# Reading one creature
# --------------------------------------------------------------------------

def strokes_from_svg(path: Path) -> list[list[tuple]]:
    # Why this check rather than defusedxml: the stdlib parser does not fetch
    # external entities, but it does expand internal ones, so a crafted file
    # can exhaust memory. This tool must stay dependency-free, and a drawing
    # export has no legitimate reason to declare entities at all — so refusing
    # one is both a complete mitigation here and a sign the file is not what it
    # claims to be.
    head = path.read_text(errors="replace")[:4096]
    if "<!DOCTYPE" in head or "<!ENTITY" in head:
        raise Unsupported(
            f"{path.name} declares XML entities. A drawing export should not; "
            f"open it and check where it came from."
        )
    tree = ET.parse(path)
    found: list[tuple[float | None, list[tuple]]] = []

    def walk(node, matrix):
        matrix = _compose(matrix, parse_transform(node.get("transform", "")))
        tag = node.tag.split("}")[-1]
        if tag == "path" and node.get("d"):
            segments = [
                (kind,) + tuple(
                    coord
                    for i in range(0, len(rest), 2)
                    for coord in apply(matrix, rest[i], rest[i + 1])
                )
                for kind, *rest in parse_path(node.get("d"))
            ]
            label = node.get("id") or node.get("{http://www.inkscape.org/namespaces/inkscape}label") or ""
            m = re.match(r"\s*(\d+)", label)
            found.append((float(m.group(1)) if m else None, segments))
        elif tag in {"rect", "circle", "ellipse", "line", "polyline", "polygon"}:
            raise Unsupported(
                f"{path.name} contains a <{tag}>. Convert every shape to a path "
                f"before exporting — a shape has no stroke order."
            )
        for child in node:
            walk(child, matrix)

    walk(tree.getroot(), (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
    if not found:
        raise Unsupported(f"{path.name} contains no paths")

    # Explicit numbering wins over document order, but only if every stroke
    # carries one — a half-numbered file is a mistake, not an instruction.
    if all(order is not None for order, _ in found):
        found.sort(key=lambda pair: pair[0])
    return [segments for _, segments in found]


def normalise(strokes: list[list[tuple]]) -> list[list[tuple]]:
    """Scale and centre a creature into the 100×100 box, aspect preserved."""
    points = [(seg[i], seg[i + 1])
              for stroke in strokes for seg in stroke
              for i in range(1, len(seg), 2)]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    span = max(width, height)
    if span <= 0:
        raise Unsupported("the drawing has no extent")
    scale = (BOX - 2 * MARGIN) / span
    # Centre the shorter axis so the creature does not sit against an edge.
    ox = MARGIN + (BOX - 2 * MARGIN - width * scale) / 2 - min(xs) * scale
    oy = MARGIN + (BOX - 2 * MARGIN - height * scale) / 2 - min(ys) * scale
    return [
        [(seg[0],) + tuple(
            (seg[i] * scale + ox) if i % 2 == 1 else (seg[i] * scale + oy)
            for i in range(1, len(seg))
        ) for seg in stroke]
        for stroke in strokes
    ]


# --------------------------------------------------------------------------
# Emitting Swift
# --------------------------------------------------------------------------

def identifier(stem: str) -> str:
    name = re.sub(r"^\d+[-_ ]*", "", stem)
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", ascii_name) if p]
    if not parts:
        raise Unsupported(f"cannot derive a Swift name from {stem!r}")
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])


# The names a reader sees, keyed by the file stem with its roster number
# stripped. They are proper names in English — the collection reads like a
# bestiary's roster, and the names are not translated — so they are spelled
# out here rather than derived from the German file stems. VoiceOver reads
# them aloud ("The Inkspine Bookworm, im Entstehen"). A short German epithet
# under each name lives in the app's `CreatureLore`, which is localized.
DISPLAY_NAMES = {
    "trompeten-hase": "The Brass Harebugle",
    "panzerschnecke": "Ironshell Dawdler",
    "dreibein-vogel": "Threefoot Wren of Vellum",
    "lesender-greif": "Gryphon of the Quiet Folio",
    "buecherwurm": "The Inkspine Bookworm",
    "mondhund": "Moonhound Sable",
    "federfisch": "Quillfin Carp",
    "zwei-kopf-kranich": "Twinbill Crane Solene",
}


def display_name(stem: str) -> str:
    """The creature's name, from DISPLAY_NAMES or capitalised from the stem.

    The fallback keeps a newly added drawing usable before anyone has named
    it, but a name it produces is a placeholder: add the real one above.
    """
    slug = re.sub(r"^\d+[-_ ]*", "", stem).replace("_", "-").strip("- ")
    if slug in DISPLAY_NAMES:
        return DISPLAY_NAMES[slug]
    return " ".join(w[:1].upper() + w[1:] for w in slug.split("-") if w)


def emit(creatures: list[tuple[str, str, list[list[tuple]]]]) -> str:
    def n(v: float) -> str:
        return f"{v:.1f}"

    lines = [
        "import SwiftUI",
        "",
        "// GENERATED by tools/svg_to_marginalia.py — do not edit by hand.",
        "// Redraw the SVG and run the tool again instead.",
        "//",
        "// The creatures a focus session draws in the margin of its page:",
        "// drolleries, traced from public-domain manuscript scans. Each path is",
        "// one stroke of the pen, in drawing order, normalised into a 100×100 box",
        "// using SwiftUI's convention that y counts downward.",
        "enum Marginalia {",
        "",
        "    static let names = [",
    ]
    lines += [f'        "{name}",' for _, name, _ in creatures]
    lines += [
        "    ]",
        "",
        "    static func strokeCount(forSpecies id: Int) -> Int {",
        "        strokes(forSpecies: id).count",
        "    }",
        "",
        "    static func strokes(forSpecies id: Int) -> [Path] {",
        "        switch id {",
    ]
    lines += [f"        case {i}: return {ident}"
              for i, (ident, _, _) in enumerate(creatures)]
    lines += [
        "        default: return []",
        "        }",
        "    }",
    ]

    for ident, name, strokes in creatures:
        lines += ["", f"    // MARK: - {name}", "",
                  f"    private static let {ident}: [Path] = ["]
        for stroke in strokes:
            lines.append("            Path { p in")
            for seg in stroke:
                if seg[0] == "M":
                    lines.append(f"                p.move(to: CGPoint(x: {n(seg[1])}, y: {n(seg[2])}))")
                elif seg[0] == "L":
                    lines.append(f"                p.addLine(to: CGPoint(x: {n(seg[1])}, y: {n(seg[2])}))")
                else:
                    lines.append(
                        f"                p.addCurve(to: CGPoint(x: {n(seg[5])}, y: {n(seg[6])}),")
                    lines.append(
                        f"                           control1: CGPoint(x: {n(seg[1])}, y: {n(seg[2])}),")
                    lines.append(
                        f"                           control2: CGPoint(x: {n(seg[3])}, y: {n(seg[4])}))")
            lines.append("            },")
        lines += ["    ]"]

    lines += ["}", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("svg", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    creatures = []
    for svg in sorted(args.svg, key=lambda p: p.name):
        try:
            strokes = normalise(strokes_from_svg(svg))
        except Unsupported as exc:
            print(f"{svg.name}: {exc}", file=sys.stderr)
            return 1
        count = len(strokes)
        note = "" if 6 <= count <= 60 else "   <-- unusual stroke count"
        print(f"  {svg.name:<34} {count:>3} strokes{note}")
        creatures.append((identifier(svg.stem), display_name(svg.stem), strokes))

    args.out.write_text(emit(creatures))
    print(f"\nwrote {args.out} — {len(creatures)} creatures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
