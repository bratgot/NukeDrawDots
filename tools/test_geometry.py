#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_geometry.py
----------------
Exercise the path maths in nuke_draw_dots.py with plain CPython - no Nuke,
no Qt. The functions under test are read straight out of the shipped module
between its "geometry - BEGIN" and "geometry - END" markers, so this tests
the real code rather than a copy of it.

    python tools/test_geometry.py
"""

from __future__ import print_function
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, os.pardir, "src", "nuke_draw_dots.py")

BEGIN = "# -- geometry - BEGIN"
END = "# -- geometry - END"


def load_geometry():
    """exec() the marked region of the module into a bare namespace."""
    with open(SOURCE) as fh:
        text = fh.read()
    try:
        after = text.split(BEGIN, 1)[1]
        # Drop the rest of the marker's own line - the trailing rule would
        # otherwise arrive as an indented first line and fail to compile.
        body = after.split("\n", 1)[1].split(END, 1)[0]
    except IndexError:
        raise SystemExit("geometry markers not found in {}".format(SOURCE))
    namespace = {"math": math}
    exec(compile(body, SOURCE, "exec"), namespace)
    return namespace


G = load_geometry()

_failures = []


def check(name, condition, detail=""):
    if condition:
        print("  ok    {}".format(name))
    else:
        print("  FAIL  {} {}".format(name, detail))
        _failures.append(name)


def is_orthogonal(points, tol=1e-6):
    """Every segment is purely horizontal or purely vertical."""
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if abs(x1 - x0) > tol and abs(y1 - y0) > tol:
            return False
    return True


# -- _rdp ------------------------------------------------------

def test_rdp():
    print("_rdp")

    line = [(float(i), 0.0) for i in range(0, 101)]
    check("collapses a straight line to its ends",
          G["_rdp"](line, 1.0) == [(0.0, 0.0), (100.0, 0.0)])

    check("epsilon 0 is a no-op",
          G["_rdp"](line, 0.0) == line)

    spike = [(0.0, 0.0), (50.0, 40.0), (100.0, 0.0)]
    check("keeps a corner taller than epsilon",
          G["_rdp"](spike, 5.0) == spike)
    check("drops a corner shorter than epsilon",
          G["_rdp"](spike, 50.0) == [(0.0, 0.0), (100.0, 0.0)])

    check("endpoints always survive",
          G["_rdp"](line, 1e9)[0] == line[0] and
          G["_rdp"](line, 1e9)[-1] == line[-1])

    check("fewer than 3 points passes through",
          G["_rdp"]([(0.0, 0.0), (1.0, 1.0)], 10.0) ==
          [(0.0, 0.0), (1.0, 1.0)])

    # The iterative form must survive a stroke far longer than Python's
    # default recursion limit - a recursive RDP blows up here.
    zigzag = [(float(i), float(i % 2) * 30.0) for i in range(6000)]
    result = G["_rdp"](zigzag, 2.0)
    check("handles a 6000-sample stroke without recursing",
          len(result) > 2 and result[0] == zigzag[0] and
          result[-1] == zigzag[-1])

    check("output is a subsequence of the input, in order",
          all(p in zigzag for p in result) and
          [zigzag.index(p) for p in result] ==
          sorted(zigzag.index(p) for p in result))


# -- _orthogonalise --------------------------------------------

def test_orthogonalise():
    print("_orthogonalise")

    diagonal = [(0.0, 0.0), (100.0, 40.0)]
    out = G["_orthogonalise"](diagonal)
    check("a shallow diagonal becomes horizontal",
          out == [(0.0, 0.0), (100.0, 0.0)], out)

    steep = [(0.0, 0.0), (40.0, 100.0)]
    check("a steep diagonal becomes vertical",
          G["_orthogonalise"](steep) == [(0.0, 0.0), (0.0, 100.0)])

    stroke = [(0.0, 0.0), (90.0, 20.0), (110.0, 120.0), (250.0, 140.0)]
    out = G["_orthogonalise"](stroke)
    check("every segment is axis-aligned", is_orthogonal(out), out)
    # Each point takes one axis from the stroke and the other from the
    # point already placed - that is what keeps the staircase connected.
    check("each point inherits one axis from the previous point",
          all(out[i] == (stroke[i][0], out[i - 1][1]) or
              out[i] == (out[i - 1][0], stroke[i][1])
              for i in range(1, len(out))), out)
    check("the start point is untouched", out[0] == stroke[0])

    check("a single point passes through",
          G["_orthogonalise"]([(5.0, 5.0)]) == [(5.0, 5.0)])
    check("an empty path passes through", G["_orthogonalise"]([]) == [])

    check("point count is preserved", len(out) == len(stroke))


# -- _snap_to_grid ---------------------------------------------

def test_snap_to_grid():
    print("_snap_to_grid")

    check("rounds to the nearest multiple",
          G["_snap_to_grid"]([(17.0, 31.0)], 16) == [(16.0, 32.0)])
    check("grid 0 is a no-op",
          G["_snap_to_grid"]([(17.0, 31.0)], 0) == [(17.0, 31.0)])
    check("negative coordinates round correctly",
          G["_snap_to_grid"]([(-17.0, -31.0)], 16) == [(-16.0, -32.0)])

    # This is why snapping runs after orthogonalising: a horizontal segment
    # has one y for both ends, so both snap to the same row and the right
    # angle survives.
    ortho = G["_orthogonalise"](
        [(0.0, 0.0), (93.0, 17.0), (101.0, 122.0), (263.0, 131.0)])
    snapped = G["_snap_to_grid"](ortho, 16)
    check("snapping preserves right angles", is_orthogonal(snapped), snapped)


# -- _dedupe / _drop_collinear ---------------------------------

def test_dedupe():
    print("_dedupe")

    check("removes a repeated point",
          G["_dedupe"]([(0.0, 0.0), (0.0, 0.0), (10.0, 0.0)], 0.5) ==
          [(0.0, 0.0), (10.0, 0.0)])
    check("keeps points beyond min_dist",
          len(G["_dedupe"]([(0.0, 0.0), (1.0, 0.0)], 0.5)) == 2)
    check("an empty path passes through", G["_dedupe"]([], 0.5) == [])


def test_drop_collinear():
    print("_drop_collinear")

    check("drops a midpoint on the line",
          G["_drop_collinear"](
              [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)], 0.5) ==
          [(0.0, 0.0), (100.0, 0.0)])
    check("keeps a real corner",
          len(G["_drop_collinear"](
              [(0.0, 0.0), (50.0, 50.0), (100.0, 0.0)], 0.5)) == 3)
    check("endpoints always survive",
          G["_drop_collinear"](
              [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)], 0.5)[0] == (0.0, 0.0))


# -- simplify_path ---------------------------------------------

def _hand_drawn_L(jitter=1.7):
    """A wobbly L, the shape someone actually draws with a mouse."""
    points = []
    for i in range(160):
        points.append((float(i) * 2.0,
                       math.sin(i * 0.7) * jitter))
    for i in range(160):
        points.append((320.0 + math.sin(i * 0.9) * jitter,
                       float(i) * 2.0))
    return points


def test_simplify_path():
    print("simplify_path")

    raw = _hand_drawn_L()

    loose = G["simplify_path"](raw, tolerance=0.0, orthogonal=False)
    check("tolerance 0 keeps the stroke detailed", len(loose) > 50,
          len(loose))

    tight = G["simplify_path"](raw, tolerance=12.0, orthogonal=False)
    check("simplifying cuts the point count hard", len(tight) < 12,
          len(tight))
    check("more tolerance never means more points",
          len(G["simplify_path"](raw, tolerance=60.0)) <=
          len(G["simplify_path"](raw, tolerance=12.0)))

    square = G["simplify_path"](raw, tolerance=12.0, orthogonal=True)
    check("right angles produce an axis-aligned path",
          is_orthogonal(square), square)
    check("an L simplifies to 3 dots", len(square) == 3, square)

    gridded = G["simplify_path"](raw, tolerance=12.0, orthogonal=True,
                                 grid=16)
    check("gridded output is still axis-aligned",
          is_orthogonal(gridded), gridded)
    check("every gridded coordinate is on the grid",
          all(abs(v % 16) < 1e-6 for p in gridded for v in p), gridded)

    check("endpoints are near where the stroke started and ended",
          math.hypot(gridded[0][0] - raw[0][0],
                     gridded[0][1] - raw[0][1]) < 32)

    # Degenerate input must not raise or invent points.
    check("a single point yields no chain",
          len(G["simplify_path"]([(0.0, 0.0)], 12.0, True, 16)) < 2)
    check("an empty stroke yields nothing",
          G["simplify_path"]([], 12.0, True, 16) == [])
    check("a stroke that never moved collapses to one point",
          len(G["simplify_path"]([(5.0, 5.0)] * 40, 12.0, True, 16)) < 2)

    # A dead-straight drag is the common "just route two dots" case.
    straight = [(float(i), 0.0) for i in range(200)]
    check("a straight drag becomes exactly 2 dots",
          len(G["simplify_path"](straight, 12.0, True, 0)) == 2)


def main():
    for test in (test_rdp, test_orthogonalise, test_snap_to_grid,
                 test_dedupe, test_drop_collinear, test_simplify_path):
        test()
        print("")

    if _failures:
        print("{} FAILED: {}".format(len(_failures), ", ".join(_failures)))
        return 1
    print("all geometry tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
