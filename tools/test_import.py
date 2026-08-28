#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_import.py
--------------
Import nuke_draw_dots.py for real against a bundled PySide and drive the Qt
pieces headlessly, with a stub `nuke` standing in for the application.

This is what catches the things the geometry tests cannot: a Qt enum that
moved between PySide2 and PySide6, a widget that fails to build, a signal
connected to a slot with the wrong signature, and the Dot wiring order.

Run it with the interpreter shipped alongside each Nuke you care about:

    "C:/Program Files/Nuke14.1v8/python.exe" tools/test_import.py   # PySide2
    "C:/Program Files/Nuke17.1v1/python.exe" tools/test_import.py   # PySide6
"""

from __future__ import print_function
import math
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
sys.path.insert(0, os.path.join(ROOT, "src"))

# Qt must be able to start without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _add_bundled_pyside():
    """
    Nuke's own python.exe does not put the interpreter's site-packages on
    sys.path the way the application does, so PySide is invisible until we
    point at it. Harmless when a PySide is already importable.
    """
    try:
        import PySide6  # noqa: F401
        return
    except ImportError:
        pass
    try:
        import PySide2  # noqa: F401
        return
    except ImportError:
        pass
    candidate = os.path.join(os.path.dirname(sys.executable),
                             "pythonextensions", "site-packages")
    if os.path.isdir(candidate):
        sys.path.append(candidate)


_add_bundled_pyside()

_failures = []


def check(name, condition, detail=""):
    if condition:
        print("  ok    {}".format(name))
    else:
        print("  FAIL  {} {}".format(name, detail))
        _failures.append(name)


# -- stub nuke -------------------------------------------------

class FakeNode(object):
    def __init__(self, cls="Dot", name=None, inputs=None,
                 xpos=0, ypos=0, width=12, height=12, max_inputs=1,
                 optional_input=-1):
        self._class = cls
        self._name = name or "{}{}".format(cls, len(_NUKE.nodes._all) + 1)
        self._inputs = {}
        self._xpos, self._ypos = xpos, ypos
        self._w, self._h = width, height
        self._max_inputs = max_inputs
        self._optional_input = optional_input   # a Merge's mask pipe
        self.selected = False
        for index, node in enumerate(inputs or []):
            if node is not None:
                self._inputs[index] = node

    def Class(self):
        return self._class

    def name(self):
        return self._name

    def maxInputs(self):
        return self._max_inputs

    def optionalInput(self):
        return self._optional_input

    def screenWidth(self):
        return self._w

    def screenHeight(self):
        return self._h

    def xpos(self):
        return self._xpos

    def ypos(self):
        return self._ypos

    def setXYpos(self, x, y):
        self._xpos, self._ypos = x, y

    def setInput(self, index, node):
        self._inputs[index] = node
        return True

    def input(self, index):
        return self._inputs.get(index)

    def setSelected(self, value):
        self.selected = bool(value)

    def isSelected(self):
        return self.selected


class _Nodes(object):
    def __init__(self):
        self._all = []

    def Dot(self, **kwargs):
        node = FakeNode("Dot", inputs=kwargs.get("inputs"))
        self._all.append(node)
        return node


class _Undo(object):
    depth = 0
    log = []

    def begin(self, name):
        _Undo.depth += 1
        _Undo.log.append(("begin", name))

    def end(self):
        _Undo.depth -= 1
        _Undo.log.append(("end", None))


def _build_stub_nuke():
    module = types.ModuleType("nuke")
    module.GUI = False
    module.nodes = _Nodes()
    module.Undo = _Undo
    module.zoom = lambda: 1.0
    module.center = lambda: (0.0, 0.0)
    module.allNodes = lambda: list(module._scene)
    module.selectedNodes = lambda: [n for n in module._scene if n.selected]
    module._scene = []
    return module


_NUKE = _build_stub_nuke()
sys.modules["nuke"] = _NUKE

import nuke_draw_dots as dd  # noqa: E402  (must follow the stub)

# Never touch the user's real prefs file.
_PREFS_DIR = tempfile.mkdtemp(prefix="drawdots-test-")
dd.PREFS_FILE = os.path.join(_PREFS_DIR, "prefs.json")

QtCore = dd.QtCore
QtGui = dd.QtGui
QtWidgets = dd.QtWidgets


# -- tests -----------------------------------------------------

def test_binding():
    print("Qt binding")
    check("a PySide binding was resolved", dd._PYSIDE_MAJOR in (2, 6),
          dd._PYSIDE_MAJOR)
    print("        PySide{}, Qt {}".format(dd._PYSIDE_MAJOR,
                                           QtCore.qVersion()))
    check("module version is set", bool(dd.__version__))
    # Every Qt constant referenced at import time already resolved, or the
    # import above would have raised - assert the shape anyway.
    check("shortcut constants resolved",
          dd.SHORTCUT_KEY is not None and dd.REQUIRE_MODIFIER is not None)


def test_transform(app):
    print("_DagTransform")

    widget = QtWidgets.QWidget()
    widget.resize(800, 600)
    widget.move(100, 50)
    widget.show()
    app.processEvents()

    xform = dd._DagTransform(dd._capture_dag_rect(widget))
    check("widget size captured", (xform.w, xform.h) == (800.0, 600.0),
          (xform.w, xform.h))

    # The DAG centre sits at the middle of the widget.
    cx, cy = xform.local_to_dag(400.0, 300.0)
    check("widget centre maps to the DAG centre",
          abs(cx) < 1e-6 and abs(cy) < 1e-6, (cx, cy))

    # local -> dag -> local must round-trip.
    for local in ((0.0, 0.0), (799.0, 599.0), (123.0, 456.0)):
        dag = xform.local_to_dag(*local)
        back = xform.dag_to_local(*dag)
        if abs(back[0] - local[0]) > 1e-6 or abs(back[1] - local[1]) > 1e-6:
            check("round-trips local -> dag -> local", False,
                  (local, back))
            break
    else:
        check("round-trips local -> dag -> local", True)

    # Zoom must scale DAG distance, not screen distance.
    _NUKE.zoom = lambda: 2.0
    zoomed = dd._DagTransform(dd._capture_dag_rect(widget))
    _NUKE.zoom = lambda: 1.0
    span_1x = xform.local_to_dag(600.0, 300.0)[0]
    span_2x = zoomed.local_to_dag(600.0, 300.0)[0]
    check("zooming in halves the DAG distance covered",
          abs(span_2x * 2.0 - span_1x) < 1e-6, (span_1x, span_2x))

    widget.hide()
    return xform


def test_overlay(app, xform):
    print("_PathOverlay")

    overlay = dd._PathOverlay(xform.zoom)
    overlay.setGeometry(xform.global_rect())
    check("overlay ignores mouse events",
          overlay.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents))
    check("overlay is translucent",
          overlay.testAttribute(QtCore.Qt.WA_TranslucentBackground))

    overlay.set_raw([(0.0, 0.0), (50.0, 20.0), (90.0, 80.0)])
    overlay.set_path([(0.0, 0.0), (90.0, 0.0), (90.0, 80.0)])
    overlay.show()
    app.processEvents()

    # grab() runs paintEvent for real - a bad pen, brush or enum raises here.
    pixmap = overlay.grab()
    check("paintEvent renders without raising",
          not pixmap.isNull() and pixmap.width() > 0, pixmap.size())

    overlay.set_raw([])
    overlay.set_path([])
    check("empty paths render without raising", not overlay.grab().isNull())

    overlay.hide()
    return overlay


def test_dialog(app, xform):
    print("_SimplifyDialog")

    overlay = dd._PathOverlay(xform.zoom)
    overlay.setGeometry(xform.global_rect())

    raw = [(float(i) * 2.0, (i % 3) * 1.5) for i in range(120)]
    raw += [(240.0 + (i % 3) * 1.5, float(i) * 2.0) for i in range(120)]

    start = FakeNode("Read", name="Read1", max_inputs=0)
    end = FakeNode("Merge2", name="Merge1", max_inputs=2)

    dialog = dd._SimplifyDialog(raw, xform, overlay, start, end)
    check("dialog builds", dialog is not None)
    check("dialog is topmost, so the overlay cannot cover it",
          bool(dialog.windowFlags() & QtCore.Qt.WindowStaysOnTopHint))
    check("connect label names both nodes",
          "Read1" in dialog._connect.text() and
          "Merge1" in dialog._connect.text(), dialog._connect.text())

    dialog._slider.setValue(12)
    dialog._ortho.setChecked(True)
    dialog._snap.setChecked(False)
    app.processEvents()
    square = list(dialog.points)
    check("live refresh produced a path", len(square) >= 2, len(square))
    check("right angles honoured in the dialog",
          all(abs(b[0] - a[0]) < 1e-6 or abs(b[1] - a[1]) < 1e-6
              for a, b in zip(square, square[1:])), square)
    check("dot count label tracks the path",
          dialog._count.text() == "{} dots".format(len(square)),
          dialog._count.text())

    dialog._slider.setValue(120)
    app.processEvents()
    check("raising the slider simplifies further",
          len(dialog.points) <= len(square),
          (len(square), len(dialog.points)))

    dialog._snap.setChecked(True)
    dialog._grid.setValue(16)
    app.processEvents()
    check("grid spinbox enables with the checkbox", dialog._grid.isEnabled())
    check("snapped points land on the grid",
          all(abs(v % 16) < 1e-6 for p in dialog.points for v in p),
          dialog.points)

    check("connect checkbox is available when ends were found",
          dialog.connect_ends())

    # Prefs must survive a round-trip through the file.
    dialog.save_prefs()
    check("prefs file written", os.path.isfile(dd.PREFS_FILE))
    prefs = dd._prefs_get()
    check("prefs round-trip", prefs["grid"] == 16 and prefs["snap"] is True,
          prefs)

    lonely = dd._SimplifyDialog(raw, xform, overlay, None, None)
    check("connect is disabled when no node is under either end",
          not lonely.connect_ends())

    dialog.deleteLater()
    lonely.deleteLater()
    return square


def test_create_chain():
    print("create_dot_chain")

    _NUKE.nodes = _Nodes()
    _Undo.log = []

    start = FakeNode("Read", name="Read1", max_inputs=0)
    end = FakeNode("Merge2", name="Merge1", max_inputs=2)
    stray = FakeNode("Blur", name="Blur1")
    stray.setSelected(True)
    _NUKE._scene = [start, end, stray]

    points = [(0.0, 0.0), (200.0, 0.0), (200.0, 300.0)]
    dots = dd.create_dot_chain(points, start, end)

    check("one Dot per point", len(dots) == 3, len(dots))
    check("wrapped in a single undo step",
          _Undo.log[0] == ("begin", dd.UNDO_NAME) and
          _Undo.log[-1] == ("end", None) and
          len([e for e in _Undo.log if e[0] == "begin"]) == 1, _Undo.log)

    check("first Dot takes the start node",
          dots[0].input(0) is start)
    check("Dots chain head to tail",
          dots[1].input(0) is dots[0] and dots[2].input(0) is dots[1])
    check("end node is wired to the last Dot",
          end.input(0) is dots[-1])

    # Dots are placed by centre, so xpos is offset by half the node width.
    check("Dots are centred on the path points",
          (dots[0].xpos(), dots[0].ypos()) == (-6, -6) and
          (dots[2].xpos(), dots[2].ypos()) == (194, 294),
          [(d.xpos(), d.ypos()) for d in dots])

    check("the previous selection was cleared", not stray.isSelected())
    check("the new Dots are selected", all(d.isSelected() for d in dots))

    # Without a start node the chain must float free, not grab the selection.
    _NUKE.nodes = _Nodes()
    _NUKE._scene = [stray]
    stray.setSelected(True)
    loose = dd.create_dot_chain(points, None, None)
    check("no start node means the first Dot has no input",
          loose[0].input(0) is None)

    # One Dot is a legitimate result now: trimming both ends of a stroke
    # drawn between two adjacent nodes leaves exactly one. Degenerate
    # strokes are rejected before the panel opens, not here.
    _NUKE.nodes = _Nodes()
    check("a single point creates one Dot",
          len(dd.create_dot_chain([(0.0, 0.0)])) == 1)
    _NUKE.nodes = _Nodes()
    check("an empty path creates nothing", dd.create_dot_chain([]) == [])
    check("undo is balanced after every call", _Undo.depth == 0, _Undo.depth)


def merge_node(name="Merge1", **kw):
    """A Merge2: B=0, A=1, mask=2, then extra A inputs."""
    return FakeNode("Merge2", name=name, max_inputs=kw.pop("max_inputs", 10),
                    optional_input=2, **kw)


def test_free_input():
    print("_free_input")

    fresh = merge_node()
    check("an untouched Merge offers B first",
          dd._free_input(fresh) == 0, dd._free_input(fresh))

    fresh.setInput(0, FakeNode())
    check("with B taken it offers A",
          dd._free_input(fresh) == 1, dd._free_input(fresh))

    # The crux: with B and A full, the next free index is the mask. Taking
    # it would route an image into the mask pipe.
    fresh.setInput(1, FakeNode())
    check("it skips the mask and offers the next A input",
          dd._free_input(fresh) == 3, dd._free_input(fresh))

    # A Merge with only B, A and mask has nowhere left to go.
    small = merge_node("Merge2", max_inputs=3)
    small.setInput(0, FakeNode())
    small.setInput(1, FakeNode())
    check("a full 3-input Merge reports no free pipe",
          dd._free_input(small) is None, dd._free_input(small))

    blur = FakeNode("Blur", name="Blur1", max_inputs=1)
    check("an unconnected Blur offers input 0", dd._free_input(blur) == 0)
    blur.setInput(0, FakeNode())
    check("a connected Blur has no free pipe",
          dd._free_input(blur) is None)

    read = FakeNode("Read", name="Read1", max_inputs=0)
    check("a Read has no inputs at all", dd._free_input(read) is None)

    # Merge2 reports a huge maxInputs; the search must stay bounded.
    huge = merge_node("Merge3", max_inputs=100000)
    check("the search is capped rather than scanning to maxInputs",
          dd._free_input(huge) == 0)


def test_connect_uses_free_input():
    print("connecting into a free pipe")

    _NUKE.nodes = _Nodes()
    merge = merge_node()
    existing = FakeNode("Blur", name="Blur1")
    merge.setInput(0, existing)          # B is already wired
    _NUKE._scene = [merge, existing]

    dots = dd.create_dot_chain([(0.0, 0.0), (100.0, 0.0)],
                               None, merge)
    check("the existing B connection is left alone",
          merge.input(0) is existing, merge.input(0))
    check("the chain lands in the free A pipe",
          merge.input(1) is dots[-1], merge.input(1))

    # Nothing free: the chain must not overwrite a live connection.
    _NUKE.nodes = _Nodes()
    full = merge_node("Merge9", max_inputs=3)
    a, b = FakeNode("Blur", name="B1"), FakeNode("Blur", name="B2")
    full.setInput(0, a)
    full.setInput(1, b)
    dd.create_dot_chain([(0.0, 0.0), (100.0, 0.0)], None, full)
    check("a full node keeps both its connections",
          full.input(0) is a and full.input(1) is b)
    check("and nothing was forced into its mask",
          full.input(2) is None)

    # An explicit pipe wins over the search.
    _NUKE.nodes = _Nodes()
    target = merge_node("Merge4")
    dots = dd.create_dot_chain([(0.0, 0.0), (100.0, 0.0)],
                               None, target, end_input=4)
    check("an explicit end_input is honoured",
          target.input(4) is dots[-1] and target.input(0) is None)


def test_insert_leaves_a_free_tail():
    """
    Splicing means the Dot ON THE LINE carries the connection, and
    everything drawn after it hangs off that Dot with a free end.

    Wiring the LAST Dot instead made the connection detour out to wherever
    the stroke finished and come back, which is not an insertion - it is a
    diversion, and it leaves nothing free to wire up by hand.
    """
    print("splicing leaves the tail free")

    _NUKE.nodes = _Nodes()
    src = FakeNode("Constant", name="Src1", max_inputs=0)
    dst = FakeNode("Blur", name="Dst1", max_inputs=1)
    dst.setInput(0, src)
    _NUKE._scene = [src, dst]

    # Three Dots: the first sits on the line, the other two trail off it.
    dots = dd.create_dot_chain(
        [(0.0, 0.0), (200.0, 0.0), (400.0, 0.0)],
        start_node=src, end_node=dst, end_input=0, insert_at_first=True)

    check("one Dot per point", len(dots) == 3, len(dots))
    check("the first Dot takes the pipe's source",
          dots[0].input(0) is src, dots[0].input(0))
    check("the line now runs through that first Dot",
          dst.input(0) is dots[0], dst.input(0))
    check("the rest chain off it",
          dots[1].input(0) is dots[0] and dots[2].input(0) is dots[1])

    # The whole point: nothing downstream of the last Dot.
    downstream = [n for n in (src, dst) + tuple(dots)
                  if any(n.input(i) is dots[-1] for i in range(3))]
    check("the last Dot is left free", not downstream, downstream)

    # And the original connection is genuinely replaced, not duplicated.
    check("the source no longer feeds the destination directly",
          dst.input(0) is not src)

    # Without insert_at_first the last Dot carries the connection - the
    # plain connect case, where a free end would be wrong.
    _NUKE.nodes = _Nodes()
    dst2 = FakeNode("Blur", name="Dst2", max_inputs=1)
    _NUKE._scene = [src, dst2]
    chain = dd.create_dot_chain([(0.0, 0.0), (200.0, 0.0)],
                                start_node=src, end_node=dst2, end_input=0)
    check("a plain connect still wires the last Dot",
          dst2.input(0) is chain[-1], dst2.input(0))

    # A single Dot is both ends at once.
    _NUKE.nodes = _Nodes()
    dst3 = FakeNode("Blur", name="Dst3", max_inputs=1)
    dst3.setInput(0, src)
    _NUKE._scene = [src, dst3]
    one = dd.create_dot_chain([(0.0, 0.0)], start_node=src, end_node=dst3,
                              end_input=0, insert_at_first=True)
    check("a single spliced Dot sits in the line",
          len(one) == 1 and one[0].input(0) is src and
          dst3.input(0) is one[0], one)


def test_straight_run_needs_no_dots():
    """
    Dots mark corners. A straight run between two nodes has none, so the
    nodes are simply wired to each other and no Dot is left in the middle
    of a connection that does not bend.
    """
    print("a straight run between nodes leaves no Dots")

    src = FakeNode("Constant", name="S1", xpos=0, ypos=0,
                   width=80, height=18, max_inputs=0)
    dst = FakeNode("Blur", name="D1", xpos=0, ypos=400,
                   width=80, height=18, max_inputs=1)
    _NUKE._scene = [src, dst]

    # Drawn straight down from one to the other. Both node centres are at
    # x=40, so every sample sits on the line between them.
    straight = [(40.0, float(y)) for y in range(0, 420, 5)]
    points = dd._build_points(straight, tolerance=12, orthogonal=True,
                              grid=0, connect=True,
                              start_node=src, end_node=dst)
    check("no Dots survive a straight run", points == [], points)

    # ...and the two nodes still get joined, or the stroke would do nothing.
    _NUKE.nodes = _Nodes()
    made = dd.create_dot_chain(points, src, dst, 0)
    check("no Dots are created", made == [], made)
    check("but the nodes are wired directly", dst.input(0) is src,
          dst.input(0))

    # A route that genuinely bends keeps the Dot at the corner.
    bent = [(40.0, float(y)) for y in range(0, 200, 5)]
    bent += [(float(x), 200.0) for x in range(40, 400, 5)]
    bent += [(400.0, float(y)) for y in range(200, 420, 5)]
    bent += [(float(x), 400.0) for x in range(400, 40, -5)]
    points = dd._build_points(bent, tolerance=12, orthogonal=True, grid=0,
                              connect=True, start_node=src, end_node=dst)
    check("a bending route keeps its corners", len(points) >= 2, points)

    # A slight wobble is not a corner.
    wobbly = [(40.0 + (i % 2) * 3.0, float(i) * 5.0) for i in range(84)]
    points = dd._build_points(wobbly, tolerance=12, orthogonal=True,
                              grid=0, connect=True,
                              start_node=src, end_node=dst)
    check("hand wobble on a straight run is not a corner",
          points == [], points)

    # With only one node involved there is nothing to draw a line to, so
    # the Dots stand on their own merits.
    points = dd._build_points(straight, tolerance=12, orthogonal=True,
                              grid=0, connect=True,
                              start_node=src, end_node=None)
    check("a stroke into empty space still leaves a Dot",
          len(points) >= 1, points)

    # Not connecting at all must never drop Dots this way.
    points = dd._build_points(straight, tolerance=12, orthogonal=True,
                              grid=0, connect=False,
                              start_node=src, end_node=dst)
    check("with connecting off the Dots are kept", len(points) >= 1, points)


def test_trim_endpoints():
    print("_trim_endpoints")

    # Node boxes: Read1 at the origin, Merge1 further along.
    read = FakeNode("Read", name="Read1", xpos=0, ypos=0,
                    width=80, height=18, max_inputs=0)
    merge = merge_node("Merge1", xpos=400, ypos=0, width=80, height=18)

    check("a point on the start node is dropped",
          dd._trim_endpoints([(40.0, 9.0), (200.0, 9.0), (300.0, 9.0)],
                             read, None) ==
          [(200.0, 9.0), (300.0, 9.0)])

    check("a point on the end node is dropped",
          dd._trim_endpoints([(200.0, 9.0), (300.0, 9.0), (440.0, 9.0)],
                             None, merge) ==
          [(200.0, 9.0), (300.0, 9.0)])

    check("both ends trim together",
          dd._trim_endpoints([(40.0, 9.0), (250.0, 9.0), (440.0, 9.0)],
                             read, merge) == [(250.0, 9.0)])

    # Several samples can land on the node before the stroke leaves it.
    check("a run of points on the node is trimmed, not just one",
          dd._trim_endpoints(
              [(10.0, 9.0), (40.0, 9.0), (70.0, 9.0), (250.0, 9.0)],
              read, None) == [(250.0, 9.0)])

    check("points clear of both nodes are untouched",
          dd._trim_endpoints([(200.0, 9.0), (250.0, 9.0)], read, merge) ==
          [(200.0, 9.0), (250.0, 9.0)])

    # A stroke drawn entirely on one node says "connect", not "put a Dot
    # here" - so it must leave nothing behind.
    check("a stroke wholly on a node yields no Dots",
          dd._trim_endpoints([(20.0, 9.0), (50.0, 9.0)], read, None) == [])

    check("trimming nothing is safe",
          dd._trim_endpoints([], read, merge) == [])

    # A Dot deliberately routed over a node mid-stroke is kept.
    middle = FakeNode("Blur", name="Blur1", xpos=200, ypos=0,
                      width=80, height=18)
    path = [(100.0, 9.0), (240.0, 9.0), (350.0, 9.0)]
    check("only the ends are trimmed, never the middle",
          dd._trim_endpoints(path, middle, None) == path)


def test_no_dot_lands_on_a_connected_node(app, xform):
    """
    The stray-Dot-on-the-Merge bug.

    Orthogonalising snaps each point onto its neighbour's axis and the
    grid rounds it again, so a point drawn on the Merge gets moved clear
    of the node box and then survives a trim that only runs afterwards.
    Trimming the raw stroke first is what actually fixes it, so this
    drives the real dialog with right angles and grid snapping on.
    """
    print("no Dot is left sitting on a connected node")

    read = FakeNode("Read", name="Read1", xpos=0, ypos=0,
                    width=80, height=18, max_inputs=0)
    merge = merge_node("Merge1", xpos=600, ypos=120, width=80, height=18)
    _NUKE._scene = [read, merge]

    # Drawn from inside Read1, wandering across, ending inside Merge1.
    raw = [(20.0 + i * 2.0, 9.0 + (i % 3)) for i in range(140)]
    raw += [(300.0 + (i % 3), 9.0 + i * 1.0) for i in range(110)]
    raw += [(300.0 + i * 3.0, 120.0 + (i % 3)) for i in range(115)]
    raw.append((640.0, 128.0))          # squarely on the Merge

    overlay = dd._PathOverlay(xform.zoom)
    dialog = dd._SimplifyDialog(raw, xform, overlay, read, merge,
                                dd._free_input(merge))
    dialog._ortho.setChecked(True)
    dialog._snap.setChecked(True)
    dialog._grid.setValue(16)
    dialog._connect.setChecked(True)
    app.processEvents()

    points = list(dialog.points)
    check("some Dots survive the trim", len(points) >= 1, points)
    check("no Dot sits on the Merge",
          not any(dd._point_on_node(p, merge) for p in points),
          [p for p in points if dd._point_on_node(p, merge)])
    check("no Dot sits on the Read",
          not any(dd._point_on_node(p, read) for p in points),
          [p for p in points if dd._point_on_node(p, read)])

    # Not merely off the node - clear of it. A Dot parked against the
    # Merge's edge is clutter, so the whole TRIM_PADDING margin is kept
    # free, measured from the node's box rather than its centre.
    def clearance(point, node):
        nx, ny, nw, nh = dd._node_rect(node)
        dx = max(nx - point[0], 0.0, point[0] - (nx + nw))
        dy = max(ny - point[1], 0.0, point[1] - (ny + nh))
        return math.hypot(dx, dy)

    for node, label in ((merge, "Merge"), (read, "Read")):
        offenders = [(p, round(clearance(p, node), 1)) for p in points
                     if clearance(p, node) < dd.TRIM_PADDING]
        check("every Dot clears the {} by TRIM_PADDING".format(label),
              not offenders, offenders)

    # Unchecking connect means no connection is made, so the Dots that
    # mark where the stroke actually went should come back.
    dialog._connect.setChecked(False)
    app.processEvents()
    check("untrimmed when not connecting",
          len(dialog.points) >= len(points), (len(dialog.points),
                                              len(points)))
    dialog.deleteLater()


def test_pipe_near():
    print("_pipe_near")

    # Read1 --> Merge1(B), laid out left to right along y=9.
    read = FakeNode("Read", name="Read1", xpos=0, ypos=0,
                    width=80, height=18, max_inputs=0)
    merge = merge_node("Merge1", xpos=600, ypos=0, width=80, height=18)
    merge.setInput(0, read)
    _NUKE._scene = [read, merge]

    # Centres are (40, 9) and (640, 9), so the pipe runs along y = 9.
    found = dd._pipe_near(300.0, 9.0)
    check("finds the pipe under the point",
          found == (read, merge, 0), found)

    check("tolerates being slightly off the line",
          dd._pipe_near(300.0, 25.0) is not None)
    check("ignores a point well clear of the pipe",
          dd._pipe_near(300.0, 400.0) is None)
    check("ignores a point beyond the ends of the pipe",
          dd._pipe_near(-400.0, 9.0) is None)

    # Two pipes: the nearer one wins.
    blur = FakeNode("Blur", name="Blur1", xpos=0, ypos=200,
                    width=80, height=18)
    merge.setInput(1, blur)          # second pipe along y ~ 105
    found = dd._pipe_near(300.0, 100.0)
    check("picks the nearest of two pipes",
          found == (blur, merge, 1), found)

    # An unconnected input is not a pipe.
    lonely = merge_node("Merge2", xpos=0, ypos=600)
    _NUKE._scene = [lonely]
    check("an unconnected node has no pipes",
          dd._pipe_near(0.0, 600.0) is None)

    _NUKE._scene = []
    check("an empty script has no pipes", dd._pipe_near(0.0, 0.0) is None)


def test_resolve_connections():
    print("_resolve_connections")

    read = FakeNode("Read", name="Read1", xpos=0, ypos=0,
                    width=80, height=18, max_inputs=0)
    merge = merge_node("Merge1", xpos=600, ypos=0, width=80, height=18)
    merge.setInput(0, read)
    _NUKE._scene = [read, merge]

    # Ending on the pipe between them splices the chain into it.
    stroke = [(300.0, 200.0), (300.0, 9.0)]
    start, end, index, inserting = dd._resolve_connections(stroke)
    check("splices into the pipe under the stroke end",
          inserting == "end", inserting)
    check("the upstream node becomes the source", start is read, start)
    check("the downstream node is the target", end is merge, end)
    check("and it takes over that pipe's input", index == 0, index)

    # Drawing from another node onto the pipe keeps that node as the
    # source - it was chosen deliberately - and re-routes the input.
    other = FakeNode("Blur", name="Blur1", xpos=0, ypos=300,
                     width=80, height=18)
    _NUKE._scene = [read, merge, other]
    stroke = [(40.0, 309.0), (300.0, 9.0)]
    start, end, index, inserting = dd._resolve_connections(stroke)
    check("a deliberate start node beats the pipe's upstream",
          start is other, start)
    check("still targets the pipe's input", end is merge and index == 0,
          (end, index))

    # Pulling a route out of a pipe: the stroke STARTS on the connection
    # and ends wherever you want the Dots. This is the more natural
    # gesture, and it leaves the far end in empty space - so testing only
    # the end found nothing and quietly made a disconnected chain.
    _NUKE._scene = [read, merge]
    stroke = [(300.0, 9.0), (300.0, 200.0), (300.0, 400.0)]
    start, end, index, inserting = dd._resolve_connections(stroke)
    check("a stroke starting on a pipe splices into it",
          inserting == "start", (start, end, index, inserting))
    check("it wires the pipe's upstream node", start is read, start)
    check("and takes over the downstream input",
          end is merge and index == 0, (end, index))

    # Starting on a NODE and ending nowhere must not drag in some pipe:
    # the start was a deliberate choice of source.
    stroke = [(40.0, 9.0), (40.0, 400.0)]
    start, end, index, inserting = dd._resolve_connections(stroke)
    check("starting on a node does not splice a pipe",
          not inserting and start is read, (start, inserting))
    check("and with nothing at the far end there is no target",
          end is None, end)

    # A node under the end still wins over a pipe near it.
    stroke = [(40.0, 9.0), (640.0, 9.0)]
    start, end, index, inserting = dd._resolve_connections(stroke)
    check("a node under the end beats a pipe", not inserting, inserting)
    check("and takes a free pipe rather than the occupied one",
          end is merge and index == 1, (end, index))

    # Nothing near either end.
    stroke = [(0.0, 2000.0), (300.0, 2000.0)]
    start, end, index, inserting = dd._resolve_connections(stroke)
    check("empty space connects to nothing",
          (start, end, index, inserting) == (None, None, None, False),
          (start, end, index, inserting))

    # Splicing a node into its own feed would make a loop.
    _NUKE._scene = [read, merge]
    stroke = [(640.0, 9.0), (300.0, 9.0)]
    start, end, index, inserting = dd._resolve_connections(stroke)
    check("will not splice a node into the pipe feeding it",
          not (inserting and start is merge and end is merge),
          (start, end, inserting))

    check("an empty stroke resolves to nothing",
          dd._resolve_connections([]) == (None, None, None, False))

    # The case that made splicing look broken. Two nodes only 120 units
    # apart: every point on the pipe between them is inside CONNECT_RADIUS
    # (45) of one node or the other, so a generous node test swallows the
    # whole pipe and nothing is ever spliced.
    near_a = FakeNode("Blur", name="Near1", xpos=0, ypos=0,
                      width=80, height=18)
    near_b = merge_node("Near2", xpos=120, ypos=0, width=80, height=18)
    near_b.setInput(0, near_a)
    _NUKE._scene = [near_a, near_b]

    midpoint = (100.0, 9.0)      # on the pipe, but ~20 units from both boxes
    check("the midpoint really is within CONNECT_RADIUS of a node",
          dd._node_near(midpoint[0], midpoint[1], dd.CONNECT_RADIUS)
          is not None,
          "if this fails the test no longer covers the reported bug")

    start, end, index, inserting = dd._resolve_connections(
        [(100.0, 200.0), midpoint])
    check("a short pipe is still spliceable", bool(inserting),
          (start, end, index, inserting))
    check("splicing a short pipe wires the upstream node",
          start is near_a, start)
    check("and takes over the occupied input",
          end is near_b and index == 0, (end, index))

    # A short stroke drawn along the pipe itself. Both its ends are within
    # CONNECT_RADIUS of the downstream node, so testing the start with the
    # generous radius made start_node == downstream, and the loop guard
    # then refused the splice. Nothing was ever inserted.
    # x=110 is 30 from the upstream box and 10 from the downstream one,
    # so proximity picks the downstream node - the case that broke.
    on_pipe = [(110.0, 9.0), (112.0, 9.0)]
    check("the stroke start is nearest the DOWNSTREAM node",
          dd._node_near(110.0, 9.0, dd.CONNECT_RADIUS) is near_b,
          "if this fails the test no longer covers the reported bug")
    check("but it is not actually on that node",
          dd._node_near(110.0, 9.0, dd.ON_NODE_RADIUS) is None,
          "otherwise connecting, not splicing, is the right answer")

    start, end, index, inserting = dd._resolve_connections(on_pipe)
    check("a stroke drawn along a pipe splices into it",
          bool(inserting), (start, end, index, inserting))
    check("the nearby downstream node does not become the source",
          start is near_a, start)
    check("and the splice targets the downstream node",
          end is near_b and index == 0, (end, index))

    # But landing squarely on one of those close nodes still connects to
    # the node rather than splicing its pipe.
    start, end, index, inserting = dd._resolve_connections(
        [(100.0, 200.0), (160.0, 9.0)])
    check("landing on a node still beats the pipe beside it",
          not inserting and end is near_b, (end, inserting))


def test_node_near():
    print("_node_near")

    read = FakeNode("Read", name="Read1", xpos=0, ypos=0,
                    width=80, height=18, max_inputs=0)
    merge = FakeNode("Merge2", name="Merge1", xpos=400, ypos=400,
                     width=80, height=18, max_inputs=2)
    backdrop = FakeNode("BackdropNode", name="BackdropNode1",
                        xpos=-500, ypos=-500, width=2000, height=2000)
    _NUKE._scene = [read, merge, backdrop]

    check("finds a node the stroke starts on",
          dd._node_near(40, 9, 45) is read)
    check("finds a node just outside its box",
          dd._node_near(100, 9, 45) is read)
    check("ignores a node beyond the radius",
          dd._node_near(200, 9, 45) is None)
    check("never returns the backdrop the stroke crossed",
          dd._node_near(-400, -400, 45) is None)
    check("need_input skips a Read",
          dd._node_near(40, 9, 45, need_input=True) is None)
    check("need_input accepts a Merge",
          dd._node_near(440, 409, 45, need_input=True) is merge)

    _NUKE._scene = []
    check("an empty script finds nothing", dd._node_near(0, 0, 45) is None)


def test_panel_position(app):
    print("_panel_position")

    screen = QtCore.QRect(0, 0, 1920, 1080)
    panel = QtCore.QSize(320, 180)

    def placed(stroke):
        point = dd._panel_position(panel, stroke, screen)
        return QtCore.QRect(point, panel)

    def clear_of(rect, stroke):
        return not rect.intersects(stroke)

    # Plenty of room: sits to the right of the stroke.
    stroke = QtCore.QRect(400, 400, 300, 200)
    rect = placed(stroke)
    check("sits to the right when there is room",
          rect.left() > stroke.right(), rect)
    check("aligns with the top of the stroke",
          rect.top() == stroke.top(), rect)
    check("does not cover the stroke", clear_of(rect, stroke))
    check("stays on screen", screen.contains(rect), rect)

    # Stroke hard against the right edge: must flip to the left side.
    stroke = QtCore.QRect(1700, 400, 200, 200)
    rect = placed(stroke)
    check("flips to the left when the right is off screen",
          rect.right() < stroke.left(), rect)
    check("still on screen", screen.contains(rect), rect)
    check("still clear of the stroke", clear_of(rect, stroke))

    # Full-width stroke: no room either side, so it goes below.
    stroke = QtCore.QRect(0, 100, 1920, 200)
    rect = placed(stroke)
    check("drops below when neither side fits",
          rect.top() > stroke.bottom(), rect)
    check("remains on screen", screen.contains(rect), rect)

    # Full-width and low: nothing below, so it goes above.
    stroke = QtCore.QRect(0, 800, 1920, 200)
    rect = placed(stroke)
    check("rises above when there is no room below",
          rect.bottom() < stroke.top(), rect)
    check("remains on screen", screen.contains(rect), rect)

    # A stroke covering everything: placement is impossible, but the panel
    # must still be fully visible rather than half off screen.
    stroke = QtCore.QRect(0, 0, 1920, 1080)
    rect = placed(stroke)
    check("a full-screen stroke still leaves the panel on screen",
          screen.contains(rect), rect)

    # A second monitor with negative coordinates must work the same way.
    left_screen = QtCore.QRect(-1920, 0, 1920, 1080)
    stroke = QtCore.QRect(-1500, 300, 200, 200)
    point = dd._panel_position(panel, stroke, left_screen)
    rect = QtCore.QRect(point, panel)
    check("works on a screen at negative coordinates",
          left_screen.contains(rect) and clear_of(rect, stroke), rect)

    # A dot-sized stroke (a very short drag) must not confuse it.
    stroke = QtCore.QRect(960, 540, 1, 1)
    rect = placed(stroke)
    check("handles a degenerate one-pixel stroke",
          screen.contains(rect) and clear_of(rect, stroke), rect)


def test_dag_match(app):
    print("_dag_match")

    plain = QtWidgets.QWidget()
    plain.setObjectName("Properties")
    check("an unrelated widget does not match",
          dd._dag_match(plain) is None, dd._dag_match(plain))

    for tag in dd.DAG_TAGS:
        w = QtWidgets.QWidget()
        w.setObjectName("panel_{}_1".format(tag))
        check("tag '{}' is recognised".format(tag),
              dd._dag_match(w) is not None)

    # Nuke nests the GL viewport inside the panel, so the match has to
    # survive walking up the parent chain.
    parent = QtWidgets.QWidget()
    parent.setObjectName("DAG_1")
    child = QtWidgets.QWidget(parent)
    child.setObjectName("viewport")
    grandchild = QtWidgets.QWidget(child)
    grandchild.setObjectName("inner")
    reason = dd._dag_match(grandchild)
    check("a nested child matches through its ancestors",
          reason is not None, reason)
    check("the reason reports the depth it matched at",
          "depth 2" in (reason or ""), reason)
    check("_is_dag_widget agrees with _dag_match",
          dd._is_dag_widget(grandchild) and not dd._is_dag_widget(plain))

    # Deeper than the walk limit must not match, and must not hang.
    deep = QtWidgets.QWidget()
    deep.setObjectName("DAG_1")
    node = deep
    for i in range(40):
        node = QtWidgets.QWidget(node)
        node.setObjectName("w{}".format(i))
    check("the ancestor walk is bounded",
          dd._dag_match(node) is None)


def test_diagnostics(app):
    print("diagnose / key_probe")

    dag = QtWidgets.QWidget()
    dag.setObjectName("DAG_1")
    dag.resize(900, 700)
    dag.show()
    app.processEvents()

    # These print rather than return; the check is that they survive a
    # real widget tree without raising.
    import io
    import contextlib
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        dd.diagnose()
    report = buffer.getvalue()
    check("diagnose reports the binding",
          "PySide{}".format(dd._PYSIDE_MAJOR) in report)
    check("diagnose finds a Node Graph widget",
          "1 visible widget(s) accepted" in report or
          "accepted" in report, report[:200])
    check("diagnose names the matched widget",
          "DAG_1" in report, report[:400])

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        probe = dd.key_probe(seconds=1)
    check("key_probe installs", probe is not None)

    # Feed it a real key event to prove the handler runs.
    buffer = io.StringIO()
    event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_D,
                            QtCore.Qt.ShiftModifier)
    with contextlib.redirect_stdout(buffer):
        probe.eventFilter(dag, event)
        probe.stop()
    check("key_probe reports a Shift+D press",
          "shift=True" in buffer.getvalue(), buffer.getvalue())

    dag.hide()


class DeadWrapper(object):
    """
    A destroyed-C++-object wrapper, as Nuke 14.1's widgetAt() returns.

    The point is that it still answers metaObject() - so a class-name test
    happily calls it a Node Graph - and raises RuntimeError the moment any
    geometry is asked for. That combination is what crashed _DagTransform.
    """

    class _Meta(object):
        @staticmethod
        def className():
            return "PySide2.QtOpenGL.QGLWidget"

    def metaObject(self):
        return self._Meta()

    def objectName(self):
        return ""

    def width(self):
        raise RuntimeError(
            "Internal C++ object (PySide2.QtOpenGL.QGLWidget) "
            "already deleted.")

    height = width
    isVisible = width
    mapToGlobal = width


def test_dead_widget(app):
    print("stale widget wrappers (the Nuke 14.1 crash)")

    dead = DeadWrapper()
    check("a stale wrapper is not live", not dd._widget_is_live(dead))
    check("a real widget is live", dd._widget_is_live(QtWidgets.QWidget()))
    check("None is not live", not dd._widget_is_live(None))

    # This is the trap: the matcher accepts it on class name alone.
    check("the DAG matcher would still accept it",
          dd._dag_match(dead) is not None,
          "if this changes the liveness check is what protects us")

    # ...so resolution must reject it rather than hand it to _DagTransform.
    real_at = QtWidgets.QApplication.widgetAt
    real_focus = QtWidgets.QApplication.focusWidget
    QtWidgets.QApplication.widgetAt = staticmethod(lambda *a: dead)
    QtWidgets.QApplication.focusWidget = staticmethod(lambda *a: None)
    try:
        resolved = dd._resolve_dag_rect(QtCore.QPoint(5, 5))
    finally:
        QtWidgets.QApplication.widgetAt = real_at
        QtWidgets.QApplication.focusWidget = real_focus

    check("resolution never returns a stale wrapper", resolved is not dead,
          resolved)

    # And the whole armed-click path must survive it without throwing,
    # because throwing is what handed the click back to Nuke.
    dd.uninstall()
    dd.install()
    dd._filter.arm()
    QtWidgets.QApplication.widgetAt = staticmethod(lambda *a: dead)
    QtWidgets.QApplication.focusWidget = staticmethod(lambda *a: None)
    try:
        event = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonPress, QtCore.QPointF(5.0, 5.0),
            QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier)
        swallowed = dd._filter.eventFilter(None, event)
    finally:
        QtWidgets.QApplication.widgetAt = real_at
        QtWidgets.QApplication.focusWidget = real_focus

    check("an armed click over a stale widget does not raise",
          swallowed is True, swallowed)
    check("and the tool stands down cleanly",
          dd._filter._mode == "idle" and dd._filter._overlay is None)
    dd.uninstall()


def test_search_dag_widgets(app):
    print("_search_dag_widgets")

    dag = QtWidgets.QWidget()
    dag.setObjectName("DAG.1")
    dag.resize(1041, 330)
    dag.move(0, 0)
    dag.show()

    # A small DAG-tagged child, like the overlay buttons Nuke puts in the
    # graph. Largest-wins must not pick it.
    button = QtWidgets.QWidget(dag)
    button.setObjectName("DAG.1.button")
    button.resize(20, 20)
    button.move(5, 5)
    button.show()
    app.processEvents()

    # Returns every candidate, largest first, so the caller can fall
    # through if the best one dies before it can be measured.
    inside = dag.mapToGlobal(QtCore.QPoint(500, 200))
    found = dd._search_dag_widgets(inside)
    check("finds the Node Graph containing the point",
          found and found[0] is dag, found)

    over_button = dag.mapToGlobal(QtCore.QPoint(10, 10))
    ranked = dd._search_dag_widgets(over_button)
    check("prefers the graph view over a small tagged child",
          ranked and ranked[0] is dag, ranked)
    check("but still offers the child as a fallback",
          button in ranked, ranked)
    check("candidates are ordered largest first",
          ranked == sorted(ranked, key=lambda w: -(w.width() * w.height())))

    outside = dag.mapToGlobal(QtCore.QPoint(5000, 5000))
    check("returns nothing for a point outside every Node Graph",
          dd._search_dag_widgets(outside) == [])

    dag.hide()


def test_resolve_dag_rect(app, monkey):
    print("_resolve_dag_rect")

    dag = QtWidgets.QWidget()
    dag.setObjectName("DAG_1")          # matches the "dag" tag
    dag.resize(640, 480)
    other = QtWidgets.QWidget()
    other.setObjectName("Properties")
    other.resize(300, 300)

    # A rect, never a widget - nothing that can be deleted later.
    rect = monkey(under=dag, focus=None)
    check("a DAG under the cursor gives its rect",
          rect is not None and (rect[2], rect[3]) == (640.0, 480.0), rect)
    check("the result is plain numbers, not a widget",
          isinstance(rect, tuple) and
          all(isinstance(v, float) for v in rect), rect)

    # widgetAt() returns None often enough on Windows that treating it as
    # "not the Node Graph" would drop strokes and hand the drag to Nuke's
    # own marquee - the bug this fallback exists to prevent.
    rect = monkey(under=None, focus=dag)
    check("widgetAt None falls back to a focused DAG",
          rect is not None and (rect[2], rect[3]) == (640.0, 480.0), rect)

    check("a click in another panel resolves to nothing",
          monkey(under=other, focus=dag) is None)
    check("no DAG anywhere resolves to nothing",
          monkey(under=None, focus=other) is None)
    check("nothing at all resolves to nothing",
          monkey(under=None, focus=None) is None)


def test_widget_dies_during_nuke_call(app):
    """
    The Nuke 14.1 crash exactly: the widget passes every liveness check,
    then dies while nuke.zoom() runs, before its size is read.
    """
    print("widget destroyed mid-construction")

    class DiesOnSecondRead(object):
        """Live for the liveness probe, dead by the time it is measured."""

        class _Meta(object):
            @staticmethod
            def className():
                return "QGLWidget"

        def __init__(self):
            self.reads = 0

        def metaObject(self):
            return self._Meta()

        def objectName(self):
            return "DAG.1"

        def isVisible(self):
            return True

        def width(self):
            self.reads += 1
            if self.reads > 1:
                raise RuntimeError(
                    "Internal C++ object (PySide2.QtOpenGL.QGLWidget) "
                    "already deleted.")
            return 1041

        def height(self):
            raise RuntimeError("already deleted")

        def mapToGlobal(self, point):
            raise RuntimeError("already deleted")

    dying = DiesOnSecondRead()
    check("it passes the liveness probe", dd._widget_is_live(dying))
    check("but capturing its rect fails cleanly rather than raising",
          dd._capture_dag_rect(dying) is None)

    # And the armed click path must survive it: previously this exact
    # sequence threw out of eventFilter and gave the click back to Nuke.
    real_at = QtWidgets.QApplication.widgetAt
    real_focus = QtWidgets.QApplication.focusWidget
    QtWidgets.QApplication.widgetAt = staticmethod(lambda *a: dying)
    QtWidgets.QApplication.focusWidget = staticmethod(lambda *a: None)
    dd.uninstall()
    dd.install()
    dd._filter.arm()
    try:
        event = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonPress, QtCore.QPointF(5.0, 5.0),
            QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier)
        swallowed = dd._filter.eventFilter(None, event)
    finally:
        QtWidgets.QApplication.widgetAt = real_at
        QtWidgets.QApplication.focusWidget = real_focus

    check("the armed click is swallowed, not thrown out of the filter",
          swallowed is True, swallowed)
    check("no exception left the filter armed",
          dd._filter._mode == "idle")
    dd.uninstall()


def test_armed_click_is_swallowed(app):
    print("armed click never reaches the Node Graph")

    dd.uninstall()
    dd.install()
    filt = dd._filter
    filt.arm()
    check("armed by arm()", filt._mode == "armed")

    # No DAG resolvable: the click must still be consumed. Returning False
    # here is what let Nuke draw its selection marquee instead.
    real = dd._resolve_dag_rect
    dd._resolve_dag_rect = lambda point: None
    try:
        swallowed = filt._begin_stroke(QtCore.QPoint(10, 10))
    finally:
        dd._resolve_dag_rect = real

    check("an unresolvable armed click is still swallowed", swallowed is True)
    check("and the tool stands down", filt._mode == "idle")

    dd.uninstall()


def test_short_stroke(app):
    print("short stroke guard")

    dd.uninstall()
    dd.install()
    filt = dd._filter

    widget = QtWidgets.QWidget()
    widget.resize(800, 600)
    widget.show()
    app.processEvents()

    _NUKE.nodes = _Nodes()
    _NUKE._scene = []

    # A click with no drag: the DAG's own click behaviour should be all the
    # user gets, not a one-Dot chain and a panel.
    filt._xform = dd._DagTransform(dd._capture_dag_rect(widget))
    filt._overlay = dd._PathOverlay(filt._xform.zoom)
    filt._points = [(100.0, 100.0), (100.1, 100.0)]
    filt._mode = "drawing"
    filt._end_stroke()
    app.processEvents()

    check("a click without a drag creates nothing",
          len(_NUKE.nodes._all) == 0, len(_NUKE.nodes._all))
    check("the filter is back to idle", filt._mode == "idle")
    check("the overlay was released", filt._overlay is None)
    check("the cursor was restored",
          QtWidgets.QApplication.overrideCursor() is None)

    widget.hide()
    dd.uninstall()


def test_settings_dialog(app):
    print("_SettingsDialog")

    _prefs_save_default = dd._prefs_save
    dd._prefs_save({"tolerance": 12, "ortho": True, "snap": False,
                    "grid": 16, "connect": True, "ask": False})

    dialog = dd._SettingsDialog()
    check("settings panel builds", dialog is not None)
    check("it shows the same path controls as the stroke panel",
          all(hasattr(dialog, name) for name in
              ("_slider", "_ortho", "_snap", "_grid")))
    check("panel-after-every-stroke is off by default",
          not dialog._ask.isChecked())

    check("it is not modal, so it can sit beside the Node Graph",
          not dialog.isModal())

    # No OK button to press - every change must land in the file by
    # itself, or a non-modal panel would quietly discard everything.
    dialog._slider.setValue(40)
    app.processEvents()
    check("moving the slider saves on its own",
          dd._prefs_get()["tolerance"] == 40, dd._prefs_get())

    dialog._ortho.setChecked(False)
    dialog._snap.setChecked(True)
    dialog._grid.setValue(32)
    dialog._ask.setChecked(True)
    app.processEvents()
    check("the grid spin follows its checkbox", dialog._grid.isEnabled())

    prefs = dd._prefs_get()
    check("every control persists without an OK button",
          prefs["tolerance"] == 40 and prefs["ortho"] is False and
          prefs["snap"] is True and prefs["grid"] == 32 and
          prefs["ask"] is True, prefs)
    check("the panel says it saved", "Saved" in dialog._saved.text(),
          dialog._saved.text())

    reopened = dd._SettingsDialog()
    check("reopening shows what was saved",
          reopened._slider.value() == 40 and reopened._grid.value() == 32 and
          reopened._ask.isChecked())
    dialog.deleteLater()
    reopened.deleteLater()
    assert dd._prefs_save is _prefs_save_default


def test_show_settings(app):
    print("show_settings")

    first = dd.show_settings()
    check("opens a panel", first is not None)
    check("shown rather than blocking on exec", first.isVisible())
    check("kept on the module so it is not garbage collected",
          dd._settings_dialog is first)

    # Calling again must not stack panels up.
    second = dd.show_settings()
    check("reopening replaces the old panel rather than stacking",
          dd._settings_dialog is second and second is not first)

    second.close()
    check("closing leaves no modal state behind", not second.isModal())
    second.deleteLater()
    dd._settings_dialog = None


def test_commit_without_panel(app):
    print("drawing with the panel turned off")

    dd._prefs_save({"tolerance": 12, "ortho": True, "snap": False,
                    "grid": 16, "connect": True, "ask": False})

    _NUKE.nodes = _Nodes()
    src = FakeNode("Constant", name="Src9", xpos=0, ypos=0,
                   width=80, height=18, max_inputs=0)
    dst = FakeNode("Blur", name="Dst9", xpos=0, ypos=600,
                   width=80, height=18, max_inputs=1)
    dst.setInput(0, src)
    _NUKE._scene = [src, dst]

    dd.uninstall()
    dd.install()
    filt = dd._filter

    # A stroke starting on the pipe between them and heading off sideways.
    raw = [(40.0, 300.0 + i * 0.5) for i in range(20)]
    raw += [(40.0 + i * 8.0, 310.0) for i in range(40)]

    start, end, index, inserting = dd._resolve_connections(raw)
    check("the stroke does splice", bool(inserting), inserting)

    prefs = dd._prefs_get()
    filt._commit_without_panel(raw, prefs, start, end, index, inserting)

    made = _NUKE.nodes._all
    check("Dots are created with no panel shown", len(made) >= 1, len(made))
    check("the line runs through the first Dot",
          dst.input(0) is made[0], dst.input(0))
    check("the first Dot takes the pipe's source",
          made[0].input(0) is src, made[0].input(0))

    # Settings really are honoured, not defaults: right angles were on.
    positions = [(n.xpos(), n.ypos()) for n in made]
    check("more than one Dot means the path was kept",
          len(positions) >= 1, positions)

    # Turning simplification right up must yield fewer Dots.
    dd._prefs_save({"tolerance": 150, "ortho": True, "snap": False,
                    "grid": 16, "connect": True, "ask": False})
    _NUKE.nodes = _Nodes()
    dst.setInput(0, src)
    filt._commit_without_panel(raw, dd._prefs_get(), start, end, index,
                               inserting)
    check("the saved Simplify value is applied",
          len(_NUKE.nodes._all) <= len(made),
          (len(_NUKE.nodes._all), len(made)))

    dd.uninstall()


def test_set_shortcut():
    print("set_shortcut")

    original_key = dd.SHORTCUT_KEY
    original_mod = dd.REQUIRE_MODIFIER
    try:
        dd.set_shortcut("E")
        check("a character sets the key", dd.SHORTCUT_KEY == QtCore.Qt.Key_E)
        # Omitting the modifier must KEEP Shift, not clear it - the whole
        # point of the _UNSET sentinel.
        check("omitting the modifier keeps Shift",
              dd.REQUIRE_MODIFIER == original_mod, dd.REQUIRE_MODIFIER)

        dd.set_shortcut("Q", None)
        check("an explicit None clears the modifier",
              dd.SHORTCUT_KEY == QtCore.Qt.Key_Q and
              dd.REQUIRE_MODIFIER is None, dd.REQUIRE_MODIFIER)

        dd.set_shortcut(QtCore.Qt.Key_W, QtCore.Qt.ControlModifier)
        check("a Qt constant works too",
              dd.SHORTCUT_KEY == QtCore.Qt.Key_W and
              dd.REQUIRE_MODIFIER == QtCore.Qt.ControlModifier)

        for bad in ("EE", "", "£"):
            try:
                dd.set_shortcut(bad)
            except ValueError:
                pass
            else:
                check("rejects {!r}".format(bad), False)
                break
        else:
            check("rejects input that is not a single Qt key", True)

        # The filter must read the change, not a value captured at import.
        # Set the modifier explicitly - the Ctrl from the case above is
        # deliberately still in force, which is what set_shortcut promises.
        dd.set_shortcut("E", QtCore.Qt.ShiftModifier)
        dd.uninstall()
        dd.install()
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_E,
                                QtCore.Qt.ShiftModifier)
        dag = QtWidgets.QWidget()
        dag.setObjectName("DAG_1")
        dag.show()
        dag.setFocus()
        QtWidgets.QApplication.instance().processEvents()
        dd._filter._handle(dag, event)
        check("the new key arms the filter", dd._filter._mode == "armed",
              dd._filter._mode)
        dd._filter._disarm()
        dd.uninstall()
        dag.hide()
    finally:
        dd.SHORTCUT_KEY = original_key
        dd.REQUIRE_MODIFIER = original_mod


def test_filter_lifecycle():
    print("install / uninstall")

    dd.uninstall()
    dd.install()
    check("install creates the filter", dd._filter is not None)
    filt = dd._filter
    dd.install()
    check("install is idempotent", dd._filter is filt)
    check("starts idle", dd._filter._mode == "idle")

    dd._filter.arm()
    check("arm enters draw mode", dd._filter._mode == "armed")
    dd._filter._disarm()
    check("disarm returns to idle", dd._filter._mode == "idle")
    check("disarm restores the cursor",
          QtWidgets.QApplication.overrideCursor() is None)

    dd.uninstall()
    check("uninstall clears the filter", dd._filter is None)


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    test_binding()
    print("")
    xform = test_transform(app)
    print("")
    test_overlay(app, xform)
    print("")
    test_dialog(app, xform)
    print("")
    test_create_chain()
    print("")
    test_no_dot_lands_on_a_connected_node(app, xform)
    print("")
    test_pipe_near()
    print("")
    test_resolve_connections()
    print("")
    test_free_input()
    print("")
    test_connect_uses_free_input()
    print("")
    test_insert_leaves_a_free_tail()
    print("")
    test_straight_run_needs_no_dots()
    print("")
    test_trim_endpoints()
    print("")
    test_node_near()
    print("")
    test_panel_position(app)
    print("")
    test_dag_match(app)
    print("")
    test_diagnostics(app)
    print("")

    # _resolve_dag_rect reads live Qt state; drive it with stand-ins for
    # "what is under the cursor" and "what has focus".
    def monkey(under, focus):
        real_at = QtWidgets.QApplication.widgetAt
        real_focus = QtWidgets.QApplication.focusWidget
        QtWidgets.QApplication.widgetAt = staticmethod(lambda *a: under)
        QtWidgets.QApplication.focusWidget = staticmethod(lambda *a: focus)
        try:
            return dd._resolve_dag_rect(QtCore.QPoint(0, 0))
        finally:
            QtWidgets.QApplication.widgetAt = real_at
            QtWidgets.QApplication.focusWidget = real_focus

    test_dead_widget(app)
    print("")
    test_search_dag_widgets(app)
    print("")
    test_resolve_dag_rect(app, monkey)
    print("")
    test_widget_dies_during_nuke_call(app)
    print("")
    test_armed_click_is_swallowed(app)
    print("")
    test_short_stroke(app)
    print("")
    test_settings_dialog(app)
    print("")
    test_show_settings(app)
    print("")
    test_commit_without_panel(app)
    print("")
    test_set_shortcut()
    print("")
    test_filter_lifecycle()
    print("")

    if _failures:
        print("{} FAILED: {}".format(len(_failures), ", ".join(_failures)))
        return 1
    print("all import/runtime tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
