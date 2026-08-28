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
                 xpos=0, ypos=0, width=12, height=12, max_inputs=1):
        self._class = cls
        self._name = name or "{}{}".format(cls, len(_NUKE.nodes._all) + 1)
        self._inputs = {}
        self._xpos, self._ypos = xpos, ypos
        self._w, self._h = width, height
        self._max_inputs = max_inputs
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

    _NUKE.nodes = _Nodes()
    check("a single point creates nothing",
          dd.create_dot_chain([(0.0, 0.0)]) == [])
    check("an empty path creates nothing", dd.create_dot_chain([]) == [])
    check("undo is balanced after every call", _Undo.depth == 0, _Undo.depth)


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
    test_node_near()
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
